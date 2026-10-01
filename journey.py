"""Journey clock after a destination stop is confirmed.

Python owns the ride label, the arrive-by comparison, and the leave-by
clock. This module does not notify, reroute, or call LTA, OneMap, or OpenAI.
"""

import math
from datetime import datetime, timedelta, timezone

from catch_heuristic import (
    BOARDING_BUFFER_S,
    MISSED_AFTER_S,
    SLOW_WALK_M_S,
    headway_seconds,
)
from destination_stops import WALK_SPEED_M_S, _service_record, list_destination_stops
from lta_static import StopAndRouteCache
from nearby import haversine_m

SGT = timezone(timedelta(hours=8))
ON_TRACK_LABEL = "Arrive-by check: On track"
ON_TRACK_MESSAGE = "Estimated arrival is at or before your requested time."
LATE_LABEL = "Arrive-by check: Risk of delay"
LATE_MESSAGE = "Rough check: may miss arrive-by time."
RIDE_UNAVAILABLE = "Ride time: Unavailable"
COMPARISON_UNAVAILABLE = "Arrive-by check: N/A"
COMPARISON_NOTE = (
    "Destination ride duration unavailable; cannot verify target arrival time."
)


def build_journey(
    cache: StopAndRouteCache,
    dest_lat: float,
    dest_lon: float,
    user_lat: float,
    user_lon: float,
    destination_stop_code: str,
    boarding_stop_code: str | None = None,
    service_no: str | None = None,
    arrive_by: datetime | None = None,
    eta: datetime | None = None,
    arrival_status: str = "ok",
    now: datetime | None = None,
    transfer: bool = False,
    leg1_ride_minutes: float | None = None,
    leg2_ride_minutes: float | None = None,
    leg1_service_no: str | None = None,
    leg1_direction: int | None = None,
) -> dict:
    """Ride label, arrive-by comparison, and leave-by for one confirmed stop."""
    moment = _as_sgt(now if now is not None else datetime.now(SGT))
    listed = list_destination_stops(
        cache,
        dest_lat,
        dest_lon,
        user_lat,
        user_lon,
        boarding_stop_code=boarding_stop_code,
        service_no=service_no,
        now=moment,
    )
    stop = _find_stop(listed, destination_stop_code)
    if transfer:
        ride_minutes = transfer_arrive_minutes(
            cache,
            boarding_stop_code=boarding_stop_code,
            destination_stop_code=destination_stop_code,
            user_lat=user_lat,
            user_lon=user_lon,
            dest_lat=dest_lat,
            dest_lon=dest_lon,
            leg1_service_no=leg1_service_no,
            leg1_direction=leg1_direction,
            leg1_ride_minutes=leg1_ride_minutes,
            leg2_ride_minutes=leg2_ride_minutes,
            now=moment,
        )
    else:
        ride_minutes = None if stop is None else stop.get("rough_journey_minutes")
        if not isinstance(ride_minutes, int) or isinstance(ride_minutes, bool):
            ride_minutes = None
    services = [] if stop is None else list(stop.get("connecting_services") or [])
    comparison = _comparison(moment, ride_minutes, arrive_by)
    distance_m = _boarding_distance_m(cache, boarding_stop_code, user_lat, user_lon)
    leave_by = resolve_leave_by(
        eta=eta,
        distance_m=distance_m,
        arrival_status=arrival_status,
        now=moment,
    )
    return {
        "status": "ok",
        "destination_stop_code": destination_stop_code,
        "ride_minutes": ride_minutes,
        "connecting_services": services,
        "ride_label": comparison["ride_label"],
        "comparison_label": comparison["comparison_label"],
        "comparison_note": comparison["comparison_note"],
        "estimated_arrival": comparison["estimated_arrival"],
        "leave_by": _as_sgt_iso(leave_by) if leave_by is not None else None,
    }


def resolve_leave_by(
    *,
    eta: datetime | None,
    distance_m: float | None,
    arrival_status: str,
    now: datetime,
) -> datetime | None:
    """Leave-by from a fresh ETA. Stale, missed, and missing ETAs have no clock."""
    if arrival_status != "ok" or eta is None or distance_m is None:
        return None
    if not math.isfinite(distance_m) or distance_m < 0:
        return None
    moment = _as_sgt(now)
    arrival = _as_sgt(eta)
    if (arrival - moment).total_seconds() < -MISSED_AFTER_S:
        return None
    return leave_by_time(arrival, distance_m)


def leave_by_time(eta: datetime, distance_m: float) -> datetime:
    """leave_by = ETA - slow_walk - 45s, with slow_walk = distance / 1.1."""
    slow_walk_s = distance_m / SLOW_WALK_M_S
    return eta - timedelta(seconds=slow_walk_s + BOARDING_BUFFER_S)


def leave_by_for_buses(
    buses: list[dict],
    *,
    stop_code: str,
    user_lat: float | None,
    user_lon: float | None,
    cache: StopAndRouteCache | None,
    now: datetime,
) -> str | None:
    """Leave-by for the primary bus on a fresh arrival poll."""
    if (
        cache is None
        or user_lat is None
        or user_lon is None
        or not math.isfinite(user_lat)
        or not math.isfinite(user_lon)
    ):
        return None
    distance_m = _boarding_distance_m(cache, stop_code, user_lat, user_lon)
    eta = _primary_eta(buses)
    leave_by = resolve_leave_by(
        eta=eta,
        distance_m=distance_m,
        arrival_status="ok",
        now=now,
    )
    if leave_by is None:
        return None
    return _as_sgt_iso(leave_by)


def parse_journey_time(value: str) -> datetime:
    """Parse an ISO time. A clock with no offset is Singapore local time."""
    text = value.strip()
    if not text:
        raise ValueError("A journey time must be a non-empty timestamp.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("A journey time must be an ISO timestamp.") from exc
    if parsed.utcoffset() is None and parsed.tzinfo is not None:
        raise ValueError("A journey time must be an ISO timestamp.")
    return _as_sgt(parsed)


def transfer_arrive_minutes(
    cache: StopAndRouteCache,
    *,
    boarding_stop_code: str | None,
    destination_stop_code: str,
    user_lat: float,
    user_lon: float,
    dest_lat: float,
    dest_lon: float,
    leg1_service_no: str | None,
    leg1_direction: int | None,
    leg1_ride_minutes: float | None,
    leg2_ride_minutes: float | None,
    now: datetime,
) -> int | None:
    """Door-to-door minutes for a transfer: both rides, one walk pair, one half-headway."""
    ride_1 = _usable_ride(leg1_ride_minutes)
    ride_2 = _usable_ride(leg2_ride_minutes)
    if ride_1 is None or ride_2 is None:
        return None
    walk_origin = _walk_minutes(cache, boarding_stop_code, user_lat, user_lon)
    walk_place = _walk_minutes(cache, destination_stop_code, dest_lat, dest_lon)
    if walk_origin is None or walk_place is None:
        return None
    headway = _leg1_headway_seconds(
        cache, leg1_service_no, leg1_direction, boarding_stop_code, now
    )
    total = walk_origin + (headway / 2) / 60 + ride_1 + ride_2 + walk_place
    return math.ceil(total)


def _usable_ride(value: float | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _walk_minutes(
    cache: StopAndRouteCache | None,
    stop_code: str | None,
    lat: float,
    lon: float,
) -> float | None:
    if cache is None or not stop_code:
        return None
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    stop = cache.stop_by_code(stop_code)
    if stop is None:
        return None
    stop_lat = stop.get("Latitude")
    stop_lon = stop.get("Longitude")
    if isinstance(stop_lat, bool) or not isinstance(stop_lat, (int, float)):
        return None
    if isinstance(stop_lon, bool) or not isinstance(stop_lon, (int, float)):
        return None
    if not math.isfinite(stop_lat) or not math.isfinite(stop_lon):
        return None
    return haversine_m(lat, lon, float(stop_lat), float(stop_lon)) / WALK_SPEED_M_S / 60


def _leg1_headway_seconds(
    cache: StopAndRouteCache,
    service_no: str | None,
    direction: int | None,
    boarding_stop_code: str | None,
    now: datetime,
) -> int:
    service = service_no.strip() if isinstance(service_no, str) else ""
    record = None
    if service and isinstance(direction, int) and not isinstance(direction, bool):
        record = _service_record(cache.services, service, direction)
    origin_code = record.get("OriginCode") if record else None
    destination_code = record.get("DestinationCode") if record else None
    return headway_seconds(
        cache.services,
        cache.routes,
        service,
        boarding_stop_code or "",
        origin_code if isinstance(origin_code, str) else None,
        destination_code if isinstance(destination_code, str) else None,
        now,
    )


def _comparison(
    now: datetime,
    ride_minutes: int | None,
    arrive_by: datetime | None,
) -> dict:
    if ride_minutes is None:
        return {
            "ride_label": RIDE_UNAVAILABLE,
            "comparison_label": COMPARISON_UNAVAILABLE,
            "comparison_note": COMPARISON_NOTE,
            "estimated_arrival": None,
        }
    ride_label = f"Ride time: ~{ride_minutes} min"
    if arrive_by is None:
        return {
            "ride_label": ride_label,
            "comparison_label": "",
            "comparison_note": "",
            "estimated_arrival": None,
        }
    estimated = now + timedelta(minutes=ride_minutes)
    late = estimated > _as_sgt(arrive_by)
    return {
        "ride_label": ride_label,
        "comparison_label": LATE_LABEL if late else ON_TRACK_LABEL,
        "comparison_note": LATE_MESSAGE if late else ON_TRACK_MESSAGE,
        "estimated_arrival": _as_sgt_iso(estimated),
    }


def _find_stop(listed: dict, stop_code: str) -> dict | None:
    for key in ("reachable_stops", "unreachable_stops"):
        for stop in listed.get(key, []):
            if stop.get("stop_code") == stop_code:
                return stop
    return None


def _boarding_distance_m(
    cache: StopAndRouteCache | None,
    boarding_stop_code: str | None,
    user_lat: float,
    user_lon: float,
) -> float | None:
    if cache is None or not boarding_stop_code:
        return None
    stop = cache.stop_by_code(boarding_stop_code)
    if stop is None:
        return None
    stop_lat = stop.get("Latitude")
    stop_lon = stop.get("Longitude")
    if not isinstance(stop_lat, (int, float)) or not isinstance(stop_lon, (int, float)):
        return None
    if isinstance(stop_lat, bool) or isinstance(stop_lon, bool):
        return None
    return haversine_m(user_lat, user_lon, float(stop_lat), float(stop_lon))


def _primary_eta(buses: list[dict]) -> datetime | None:
    for bus in buses:
        if not bus.get("is_primary") or bus.get("is_missed"):
            continue
        arrival = bus.get("arrival_time")
        if not isinstance(arrival, str) or not arrival.strip():
            continue
        try:
            return parse_journey_time(arrival)
        except ValueError:
            return None
    return None


def _as_sgt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SGT)
    return value.astimezone(SGT)


def _as_sgt_iso(value: datetime) -> str:
    return _as_sgt(value).replace(microsecond=0).isoformat()

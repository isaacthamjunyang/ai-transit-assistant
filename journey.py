"""Journey clock after a destination stop is confirmed.

Python owns the ride label, the arrive-by comparison, and the leave-by
clock. This module does not notify, reroute, or call LTA, OneMap, or OpenAI.
"""

import math
from datetime import datetime, timedelta, timezone

from catch_heuristic import MISSED_AFTER_S, headway_seconds
from config import LEAVE_MARGIN_SECONDS, WALK_SPEED_DEFAULT_MPS
from destination_stops import _service_record, list_destination_stops
from lta_static import StopAndRouteCache
from nearby import haversine_m
from walk_speed import range_speeds, walk_minutes

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
RIDE_TOLERANCE = 0.15
CHIP_STEP_MINUTES = 5
PAST_ARRIVE_BY = "That time has already passed. Choose a later time."


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
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
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
        walk_speed_m_s=walk_speed_m_s,
    )
    stop = _find_stop(listed, destination_stop_code)
    if transfer:
        terms = transfer_arrival_terms(
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
            walk_speed_m_s=walk_speed_m_s,
        )
        ride_minutes = None if terms is None else math.ceil(
            terms["board_walk_minutes"]
            + terms["wait_minutes"]
            + terms["ride_minutes"]
            + walk_minutes(terms["end_walk_metres"], walk_speed_m_s)
        )
    else:
        terms = None if stop is None else stop.get("arrival_terms")
        ride_minutes = None if stop is None else stop.get("rough_journey_minutes")
        if not isinstance(ride_minutes, int) or isinstance(ride_minutes, bool):
            ride_minutes = None
    services = [] if stop is None else list(stop.get("connecting_services") or [])
    comparison = _comparison(moment, ride_minutes, arrive_by)
    window = None
    if ride_minutes is not None and isinstance(terms, dict):
        window = arrival_window(
            moment,
            board_walk_minutes=terms["board_walk_minutes"],
            wait_minutes=terms["wait_minutes"],
            ride_minutes=terms["ride_minutes"],
            end_walk_metres=terms["end_walk_metres"],
            arrive_by=arrive_by,
            basis="planned",
            walk_speed_m_s=walk_speed_m_s,
        )
        if window is not None and window["point_minutes"] != ride_minutes:
            window = _shift_window(window, ride_minutes - window["point_minutes"], arrive_by)
    distance_m = _boarding_distance_m(cache, boarding_stop_code, user_lat, user_lon)
    leave_by = resolve_leave_by(
        eta=eta,
        distance_m=distance_m,
        arrival_status=arrival_status,
        now=moment,
        walk_speed_m_s=walk_speed_m_s,
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
        "arrival_point": None if window is None else _as_sgt_iso(window["estimated_arrival"]),
        "arrival_low": None if window is None else _as_sgt_iso(window["arrival_low"]),
        "arrival_high": None if window is None else _as_sgt_iso(window["arrival_high"]),
        "spare_minutes": None if window is None or arrive_by is None else window["spare_minutes"],
        "arrival_basis": None if window is None else window["basis"],
        "arrival_terms": terms if isinstance(terms, dict) else None,
        "leave_by": _as_sgt_iso(leave_by) if leave_by is not None else None,
    }


def resolve_leave_by(
    *,
    eta: datetime | None,
    distance_m: float | None,
    arrival_status: str,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
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
    return leave_by_time(arrival, distance_m, walk_speed_m_s)


def leave_by_time(eta: datetime, distance_m: float, speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> datetime:
    """leave_by = ETA - walk time - LEAVE_MARGIN_SECONDS. The walk time is raw seconds at the speed used (the
    probability's point walk). The one function for the live poll, the pinned bus, /api/journey and reroute rows."""
    walk_s = distance_m / speed_m_s
    return eta - timedelta(seconds=walk_s + LEAVE_MARGIN_SECONDS)


def leave_by_for_buses(
    buses: list[dict],
    *,
    stop_code: str,
    user_lat: float | None,
    user_lon: float | None,
    cache: StopAndRouteCache | None,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
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
        walk_speed_m_s=walk_speed_m_s,
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


def arrival_window(
    now: datetime,
    *,
    board_walk_minutes: float,
    wait_minutes: float,
    ride_minutes: float | None,
    end_walk_metres: float,
    arrive_by: datetime | None = None,
    basis: str = "planned",
    anchor: datetime | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict | None:
    """Point, range, and spare minutes from the Step 9 terms.

    The point uses the same sum the status uses. The range changes only the
    end walk and the ride. A live anchor replaces the half-headway wait with
    the wait for that bus, and the user is assumed to catch it.
    """
    ride = _usable_ride(ride_minutes)
    if ride is None:
        return None
    moment = _as_sgt(now)
    board = float(board_walk_minutes)
    wait = float(wait_minutes)
    if anchor is not None:
        gap = max(0.0, (_as_sgt(anchor) - moment).total_seconds() / 60)
        board = max(board, gap)
        wait = 0.0
    point_speed, slow_speed, fast_speed = range_speeds(walk_speed_m_s)
    point_minutes = _span_minutes(board, wait, ride, end_walk_metres, 1.0, point_speed)
    low_minutes = _span_minutes(
        board, wait, ride, end_walk_metres, 1 - RIDE_TOLERANCE, fast_speed
    )
    high_minutes = _span_minutes(
        board, wait, ride, end_walk_metres, 1 + RIDE_TOLERANCE, slow_speed
    )
    low_minutes = min(low_minutes, point_minutes)
    high_minutes = max(high_minutes, point_minutes)
    point = moment + timedelta(minutes=point_minutes)
    return {
        "estimated_arrival": point,
        "arrival_low": moment + timedelta(minutes=low_minutes),
        "arrival_high": moment + timedelta(minutes=high_minutes),
        "spare_minutes": _spare_minutes(point, arrive_by),
        "basis": basis,
        "point_minutes": point_minutes,
    }


def bus_arrival_window(
    now: datetime,
    terms: dict | None,
    eta: datetime | None,
    *,
    live: bool,
    arrive_by: datetime | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict | None:
    """The one estimate for a bus: anchored on its arrival when it is live, otherwise planned.

    The live tile, the new-journey overview and the reroute options all call this with the
    same Step 9 terms, so the same bus gives the same time. A schedule-only bus, or one with
    no usable arrival time, keeps the planned basis (half the headway as the wait).
    """
    if not isinstance(terms, dict):
        return None
    anchored = live and isinstance(eta, datetime)
    return arrival_window(
        now,
        board_walk_minutes=float(terms["board_walk_minutes"]),
        wait_minutes=float(terms["wait_minutes"]),
        ride_minutes=terms["ride_minutes"],
        end_walk_metres=float(terms["end_walk_metres"]),
        arrive_by=arrive_by,
        basis="live" if anchored else "planned",
        anchor=eta if anchored else None,
        walk_speed_m_s=walk_speed_m_s,
    )


def planning_warning(
    now: datetime,
    arrive_by: datetime | None,
    option_minutes: list[float | None],
) -> dict | None:
    """The earliest shown option, when every estimated option is after the target."""
    if arrive_by is None:
        return None
    usable = []
    for minutes in option_minutes:
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
            continue
        if math.isfinite(minutes):
            usable.append(float(minutes))
    if not usable:
        return None
    earliest = _as_sgt(now) + timedelta(minutes=min(usable))
    target = _as_sgt(arrive_by)
    if earliest <= target:
        return None
    return {
        "earliest_arrival": _as_sgt_iso(earliest),
        "target": _as_sgt_iso(target),
    }


def resolve_arrive_chip(now: datetime, offset_minutes: int) -> datetime:
    """An absolute Singapore time: now plus the offset, rounded up to 5 minutes."""
    moment = _as_sgt(now).replace(microsecond=0)
    target = moment + timedelta(minutes=offset_minutes)
    if target.second == 0 and target.minute % CHIP_STEP_MINUTES == 0:
        return target
    add = CHIP_STEP_MINUTES - (target.minute % CHIP_STEP_MINUTES)
    return target.replace(second=0, microsecond=0) + timedelta(minutes=add)


def past_arrive_by(now: datetime, chosen: datetime) -> bool:
    """True when the custom time is earlier than now."""
    return _as_sgt(chosen) < _as_sgt(now)


def show_if_you_miss(
    *,
    status: str,
    stale: bool,
    schedule_only: bool,
    arrival_count: int,
    on_board: bool,
) -> bool:
    """Live poll, at least two arrivals, and the user is not on board."""
    if on_board or stale or schedule_only or status != "ok":
        return False
    return arrival_count >= 2


def miss_line(
    now: datetime,
    service_no: str,
    buses: list[dict],
    terms: dict | None,
    arrive_by: datetime | None,
    tracked: dict | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict | None:
    """The first later arrival of the same service after the tracked one, with its Step 9 estimate.

    The tracked bus is the one passed in (by identity); with none given it is the first listed
    arrival that is not missed. A skipped (missed) earlier arrival is therefore never the answer.
    The estimate is anchored on that arrival only when it is live; otherwise the planned basis stays.
    """
    if not isinstance(buses, list):
        return None
    index = None
    for position, bus in enumerate(buses):
        if tracked is not None:
            if bus is tracked:
                index = position
                break
        elif isinstance(bus, dict) and not bus.get("is_missed"):
            index = position
            break
    if index is None or index + 1 >= len(buses):
        return None
    later = buses[index + 1]
    arrival = later.get("arrival_time") if isinstance(later, dict) else None
    if not isinstance(arrival, str) or not arrival.strip() or later.get("is_missed"):
        return None
    try:
        eta = parse_journey_time(arrival)
    except ValueError:
        return None
    seconds = (_as_sgt(eta) - _as_sgt(now)).total_seconds()
    in_minutes = max(0, int(math.floor(seconds / 60 + 0.5)))
    body = {
        "service_no": service_no,
        "in_minutes": in_minutes,
        "estimated_arrival": None,
        "arrival_low": None,
        "arrival_high": None,
        "spare_minutes": None,
        "basis": "live" if later.get("monitored") is True else "planned",
    }
    ride = None if not isinstance(terms, dict) else terms.get("ride_minutes")
    if _usable_ride(ride) is None:
        return body
    window = bus_arrival_window(
        now, terms, eta, live=later.get("monitored") is True, arrive_by=arrive_by, walk_speed_m_s=walk_speed_m_s
    )
    if window is None:
        return body
    body["estimated_arrival"] = _as_sgt_iso(window["estimated_arrival"])
    body["arrival_low"] = _as_sgt_iso(window["arrival_low"])
    body["arrival_high"] = _as_sgt_iso(window["arrival_high"])
    body["spare_minutes"] = None if arrive_by is None else window["spare_minutes"]
    body["basis"] = window["basis"]
    return body


def _span_minutes(
    board: float,
    wait: float,
    ride: float,
    end_walk_metres: float,
    ride_factor: float,
    end_walk_m_s: float,
) -> int:
    total = board + wait + ride * ride_factor + end_walk_metres / end_walk_m_s / 60
    return math.ceil(total)


def _spare_minutes(point: datetime, arrive_by: datetime | None) -> int | None:
    if arrive_by is None:
        return None
    delta = (_as_sgt(arrive_by) - point).total_seconds()
    return math.floor(delta / 60)


def _shift_window(window: dict, minutes: int, arrive_by: datetime | None) -> dict:
    shift = timedelta(minutes=minutes)
    point = window["estimated_arrival"] + shift
    return {
        "estimated_arrival": point,
        "arrival_low": window["arrival_low"] + shift,
        "arrival_high": window["arrival_high"] + shift,
        "spare_minutes": _spare_minutes(point, arrive_by),
        "basis": window["basis"],
        "point_minutes": window["point_minutes"] + minutes,
    }


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
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> int | None:
    """Door-to-door minutes for a transfer: both rides, one walk pair, one half-headway."""
    terms = transfer_arrival_terms(
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
        now=now,
        walk_speed_m_s=walk_speed_m_s,
    )
    if terms is None:
        return None
    total = (
        terms["board_walk_minutes"]
        + terms["wait_minutes"]
        + terms["ride_minutes"]
        + walk_minutes(terms["end_walk_metres"], walk_speed_m_s)
    )
    return math.ceil(total)


def transfer_arrival_terms(
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
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict | None:
    """Both rides plus one walk pair and Leg 1's half-headway. Either null ride yields nothing."""
    ride_1 = _usable_ride(leg1_ride_minutes)
    ride_2 = _usable_ride(leg2_ride_minutes)
    if ride_1 is None or ride_2 is None:
        return None
    walk_origin = _walk_minutes(cache, boarding_stop_code, user_lat, user_lon, walk_speed_m_s)
    walk_place = _walk_minutes(cache, destination_stop_code, dest_lat, dest_lon, walk_speed_m_s)
    if walk_origin is None or walk_place is None:
        return None
    headway = _leg1_headway_seconds(
        cache, leg1_service_no, leg1_direction, boarding_stop_code, now
    )
    return {
        "board_walk_minutes": walk_origin,
        "wait_minutes": (headway / 2) / 60,
        "ride_minutes": ride_1 + ride_2,
        "end_walk_metres": walk_place * walk_speed_m_s * 60,
    }


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
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
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
    return walk_minutes(haversine_m(lat, lon, float(stop_lat), float(stop_lon)), walk_speed_m_s)


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

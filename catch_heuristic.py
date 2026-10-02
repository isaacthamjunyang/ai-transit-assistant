"""Catch probability for one boarding stop and one service.

Python owns this math. The module does not read secrets, call the
network, or open a database. Historical lateness stays at zero until a
later step has enough observations.
"""

import math
from datetime import datetime, timedelta, timezone

from config import RING_BAND_MID_FROM, RING_BAND_OK_FROM
from nearby import haversine_m
from pace import pace_guidance

SGT = timezone(timedelta(hours=8))

POINT_WALK_M_S = 1.25
SLOW_WALK_M_S = 1.1
FAST_WALK_M_S = 1.4
BOARDING_BUFFER_S = 45
# The plan names gps_penalty on the point slack. The only specified GPS
# term is gps_accuracy_m / 1.25 on the low slack, so the point penalty is 0.
GPS_PENALTY_S = 0
HISTORICAL_LATENESS_S = 0
PROBABILITY_FLOOR = 0.05
PROBABILITY_CEILING = 0.92
SCHEDULE_CEILING = 0.60
SIGMOID_MIDPOINT_S = 90
SIGMOID_SLOPE = 0.025
MISSED_AFTER_S = 30
UNCERTAIN_ACCURACY_M = 100
UNCERTAIN_AGE_S = 60.0
FALLBACK_HEADWAY_S = 12 * 60
RELIABILITY_LABEL = "no historical reliability yet"


def straight_line_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_m(lat1, lon1, lat2, lon2)


def walk_seconds(distance_m: float, metres_per_second: float) -> float:
    return distance_m / metres_per_second


def point_slack(
    seconds_until_eta: float, distance_m: float, speed_m_s: float = POINT_WALK_M_S
) -> float:
    return (
        seconds_until_eta
        - walk_seconds(distance_m, speed_m_s)
        - BOARDING_BUFFER_S
        - GPS_PENALTY_S
        - HISTORICAL_LATENESS_S
    )


def low_slack(
    seconds_until_eta: float,
    distance_m: float,
    accuracy_m: float,
    speed_m_s: float = SLOW_WALK_M_S,
) -> float:
    return (
        seconds_until_eta
        - walk_seconds(distance_m, speed_m_s)
        - BOARDING_BUFFER_S
        - (accuracy_m / POINT_WALK_M_S)
        - HISTORICAL_LATENESS_S
    )


def high_slack(
    seconds_until_eta: float, distance_m: float, speed_m_s: float = FAST_WALK_M_S
) -> float:
    return (
        seconds_until_eta
        - walk_seconds(distance_m, speed_m_s)
        - BOARDING_BUFFER_S
        - HISTORICAL_LATENESS_S
    )


def catch_probability(slack: float) -> float:
    raw = 1 / (1 + math.exp(-SIGMOID_SLOPE * (slack - SIGMOID_MIDPOINT_S)))
    return _clamp(raw, PROBABILITY_FLOOR, PROBABILITY_CEILING)


def to_percent(unit_probability: float) -> int:
    return int(round(unit_probability * 100))


def ring_band(point: int | None) -> str | None:
    """Colour band for the probability ring: ok, mid or low. None when there is no point to show."""
    if isinstance(point, bool) or not isinstance(point, int):
        return None
    if point >= RING_BAND_OK_FROM:
        return "ok"
    if point >= RING_BAND_MID_FROM:
        return "mid"
    return "low"


def parse_headway_seconds(value: object) -> int | None:
    """Midpoint of a published minute range, in seconds. None if unusable."""
    if not isinstance(value, str):
        return None
    text = value.strip().replace("–", "-").replace("—", "-")
    if not text:
        return None
    parts = [part.strip() for part in text.split("-") if part.strip()]
    if len(parts) not in (1, 2):
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if any(number <= 0 for number in numbers):
        return None
    minutes = sum(numbers) / len(numbers)
    return int(round(minutes * 60))


def headway_seconds(
    services: list[dict],
    routes: list[dict],
    service_no: str,
    stop_code: str,
    origin_code: str | None,
    destination_code: str | None,
    now: datetime,
) -> int:
    """Published headway for a schedule-only bus, or 720 seconds."""
    field = _frequency_field(now)
    if field is None:
        return FALLBACK_HEADWAY_S
    record = _service_record(
        services, routes, service_no, stop_code, origin_code, destination_code
    )
    if record is None:
        return FALLBACK_HEADWAY_S
    parsed = parse_headway_seconds(record.get(field))
    if parsed is None:
        return FALLBACK_HEADWAY_S
    return parsed


def normalize_location_timestamp(location_timestamp: float) -> float:
    """Epoch seconds. Millisecond values above 1e11 are scaled down."""
    if isinstance(location_timestamp, bool) or not isinstance(location_timestamp, (int, float)):
        raise ValueError("location_timestamp must be a finite non-negative number.")
    stamp = float(location_timestamp)
    if not math.isfinite(stamp) or stamp < 0:
        raise ValueError("location_timestamp must be a finite non-negative number.")
    if stamp > 1e11:
        stamp /= 1000.0
    if not math.isfinite(stamp):
        raise ValueError("location_timestamp must be a finite non-negative number.")
    return stamp


def location_age_seconds(location_timestamp: float, now: datetime) -> float:
    """Seconds since the fix, using the injected clock. Never negative."""
    stamp = normalize_location_timestamp(location_timestamp)
    current = _as_sgt(now).timestamp()
    return max(0.0, current - stamp)


def is_location_uncertain(accuracy_m: float, age_seconds: float | None) -> bool:
    age_uncertain = age_seconds is not None and age_seconds > UNCERTAIN_AGE_S
    return accuracy_m > UNCERTAIN_ACCURACY_M or age_uncertain


def effective_accuracy_m(accuracy_m: float, age_seconds: float | None) -> float:
    """Low-end accuracy. A fix older than 60 s widens it; a fresher fix does not."""
    accuracy = float(accuracy_m)
    if age_seconds is None or age_seconds <= UNCERTAIN_AGE_S:
        return accuracy
    return max(accuracy, float(UNCERTAIN_ACCURACY_M)) + POINT_WALK_M_S * (
        age_seconds - UNCERTAIN_AGE_S
    )


def score_buses(
    buses: list[dict],
    *,
    user_lat: float | None,
    user_lon: float | None,
    accuracy_m: float | None,
    stop_lat: float | None,
    stop_lon: float | None,
    services: list[dict],
    routes: list[dict],
    service_no: str,
    stop_code: str,
    now: datetime,
    location_timestamp: float | None = None,
    reach_speed_m_s: float | None = None,
    reach_range_fraction: float = 0.25,
) -> list[dict]:
    """Return buses with probability filled in. Does not reorder them.

    reach_speed_m_s is set only while the user is on a vehicle (Leg 2 of a transfer). The
    time to reach the stop is then distance / speed, with a range of plus or minus
    reach_range_fraction, in place of the three walking speeds. Nothing else changes.
    """
    if reach_speed_m_s is not None:
        point_speed = reach_speed_m_s
        slow_speed = reach_speed_m_s / (1 + reach_range_fraction)
        fast_speed = reach_speed_m_s / (1 - reach_range_fraction)
    else:
        point_speed, slow_speed, fast_speed = POINT_WALK_M_S, SLOW_WALK_M_S, FAST_WALK_M_S
    moment = _as_sgt(now)
    age_seconds = (
        None
        if location_timestamp is None
        else location_age_seconds(location_timestamp, moment)
    )
    located = _location_ready(user_lat, user_lon, accuracy_m, stop_lat, stop_lon)
    distance_m = (
        straight_line_m(float(user_lat), float(user_lon), float(stop_lat), float(stop_lon))
        if located
        else None
    )
    scored = []
    primary_chosen = False
    for bus in buses:
        item = dict(bus)
        origin = item.pop("origin_code", None)
        destination = item.pop("destination_code", None)
        arrival = _parse_arrival(item.get("arrival_time"))
        missed = arrival is not None and (arrival - moment).total_seconds() < -MISSED_AFTER_S
        item["is_missed"] = missed
        item["is_primary"] = False
        if missed or arrival is None or not located or distance_m is None:
            item["probability"] = None
            if not missed and not primary_chosen:
                item["is_primary"] = True
                primary_chosen = True
            scored.append(item)
            continue
        if not primary_chosen:
            item["is_primary"] = True
            primary_chosen = True
        seconds_until = (arrival - moment).total_seconds()
        monitored = bool(item.get("monitored"))
        accuracy = float(accuracy_m)
        slack = point_slack(seconds_until, distance_m, point_speed)
        worse = low_slack(
            seconds_until,
            distance_m,
            effective_accuracy_m(accuracy, age_seconds),
            slow_speed,
        )
        better = high_slack(seconds_until, distance_m, fast_speed)
        if not monitored:
            half_headway = headway_seconds(
                services,
                routes,
                service_no,
                stop_code,
                origin if isinstance(origin, str) else None,
                destination if isinstance(destination, str) else None,
                moment,
            ) / 2
            worse -= half_headway
        point = catch_probability(slack)
        low = catch_probability(worse)
        high = catch_probability(better)
        if not monitored:
            point = min(point, SCHEDULE_CEILING)
            low = min(low, SCHEDULE_CEILING)
            high = min(high, SCHEDULE_CEILING)
        if is_location_uncertain(accuracy, age_seconds):
            quality = "location uncertain"
        elif not monitored:
            quality = "schedule"
        else:
            quality = "live"
        item["probability"] = {
            "point": to_percent(point),
            "range_low": to_percent(low),
            "range_high": to_percent(high),
            "slack_seconds": int(round(slack)),
            "data_quality": quality,
            "reliability_label": RELIABILITY_LABEL,
            "is_missed": False,
        }
        item["probability"]["band"] = ring_band(item["probability"]["point"])
        item["probability"]["pace"] = None if reach_speed_m_s is not None else pace_guidance(
            point=item["probability"]["point"],
            range_low=item["probability"]["range_low"],
            range_high=item["probability"]["range_high"],
            data_quality=quality,
            location_uncertain=quality == "location uncertain",
            distance_to_stop_m=distance_m,
            previous_category=None,
        )
        scored.append(item)
    return scored


def _frequency_field(moment: datetime) -> str | None:
    local = _as_sgt(moment)
    minute_of_day = local.hour * 60 + local.minute
    if minute_of_day < 6 * 60 + 30:
        return None
    if minute_of_day <= 8 * 60 + 30:
        return "AM_Peak_Freq"
    if minute_of_day <= 16 * 60 + 59:
        return "AM_Offpeak_Freq"
    if minute_of_day <= 19 * 60:
        return "PM_Peak_Freq"
    return "PM_Offpeak_Freq"


def _service_record(
    services: list[dict],
    routes: list[dict],
    service_no: str,
    stop_code: str,
    origin_code: str | None,
    destination_code: str | None,
) -> dict | None:
    matches = [
        record
        for record in services
        if str(record.get("ServiceNo", "")).strip() == service_no
    ]
    if not matches:
        return None
    direction = _target_direction(
        matches, routes, service_no, stop_code, origin_code, destination_code
    )
    if direction is not None:
        for record in matches:
            if record.get("Direction") == direction:
                return record
    return matches[0]


def _target_direction(
    service_matches: list[dict],
    routes: list[dict],
    service_no: str,
    stop_code: str,
    origin_code: str | None,
    destination_code: str | None,
) -> int | None:
    if origin_code and destination_code:
        for record in service_matches:
            if (
                record.get("OriginCode") == origin_code
                and record.get("DestinationCode") == destination_code
                and isinstance(record.get("Direction"), int)
                and not isinstance(record.get("Direction"), bool)
            ):
                return record["Direction"]
    directions: list[int] = []
    for route in routes:
        if (
            str(route.get("ServiceNo", "")).strip() != service_no
            or route.get("BusStopCode") != stop_code
        ):
            continue
        direction = route.get("Direction")
        if isinstance(direction, int) and not isinstance(direction, bool) and direction not in directions:
            directions.append(direction)
    if len(directions) == 1:
        return directions[0]
    return None


def _location_ready(
    user_lat: float | None,
    user_lon: float | None,
    accuracy_m: float | None,
    stop_lat: float | None,
    stop_lon: float | None,
) -> bool:
    values = (user_lat, user_lon, accuracy_m, stop_lat, stop_lon)
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not math.isfinite(float(value)):
            return False
    return float(accuracy_m) >= 0


def _parse_arrival(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_sgt(parsed)


def _as_sgt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SGT)
    return value.astimezone(SGT)


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))

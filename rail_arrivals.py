"""A train as the first leg: the same answers as a bus poll, from the timetable. No LTA call, no BusArrival.

The planner (pt_plan) gives the train's scheduled departure (OneMap's time for the leg). From it, the rail table
(service_hours.rail_headway_seconds) and the user's fix this module builds what the page asks the server for:
- rail_payload: the /api/arrivals and /api/rescore answer. `buses` holds the planned train and the next scheduled
  ones, scored by catch_heuristic.score_scheduled_rail (data quality "schedule", capped at 60, range from half the
  headway, never at_stop). leave_by goes through journey.resolve_leave_by, the one function the bus path uses.
- rail_journey: the /api/journey answer for a train first leg.
- next_departures: after a missed train, the next scheduled departures. The table holds first and last train and the
  headway by hour, not each train, so they are projected from the planned train by the headway and stop at the last
  train. They are "scheduled", and they are estimates of the minute.
Nothing here sends a notification: the leave-now notice is never eligible for a train until its wording is approved.
"""

import math
from datetime import datetime, timedelta, timezone

import pt_plan
from catch_heuristic import MISSED_AFTER_S, score_scheduled_rail, straight_line_m
from config import WALK_SPEED_DEFAULT_MPS
from explain import TRAIN_ABOUT, TRAIN_LEFT, TRAIN_NEXT, format_clock
from journey import _as_sgt_iso, parse_journey_time, resolve_leave_by
from nearby import haversine_m
from pace import is_near_stop
from service_hours import rail_headway_seconds, rail_runs_at
from walk_speed import walk_minutes

SGT = timezone(timedelta(hours=8))
NEXT_DEPARTURES = 3
LEG_KIND_RAIL = "rail"
LEG_KINDS = ("bus", LEG_KIND_RAIL)
BAD_TRAIN_MESSAGE = "train_departure must be an ISO timestamp for a train."
LEAVE_NOW_PENDING = "train_wording_pending"
_MAX_STEPS = 600


def station_point(table: dict | None, station_code: str) -> tuple[float, float] | None:
    station = ((table or {}).get("stations") or {}).get(str(station_code).strip())
    if not isinstance(station, dict):
        return None
    lat, lon = station.get("latitude"), station.get("longitude")
    if isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (int, float)) \
            or not isinstance(lon, (int, float)) or not math.isfinite(lat) or not math.isfinite(lon):
        return None
    return float(lat), float(lon)


def line_name(table: dict | None, line_code: str) -> str:
    """The line's name ("North-South Line"), or its code when the table has no name for it."""
    line = ((table or {}).get("lines") or {}).get(str(line_code).strip())
    name = line.get("name") if isinstance(line, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else str(line_code).strip()


def next_departures(
    table: dict | None, station_code: str, headsign: str | None, anchor: datetime, now: datetime,
    count: int = NEXT_DEPARTURES,
) -> list[datetime]:
    """Up to `count` scheduled departures at or after now (a train within the 30 s grace still counts), projected
    from the planned train by the headway, stopping when the last train has gone."""
    moment = _as_sgt(now)
    cutoff = moment - timedelta(seconds=MISSED_AFTER_S)
    departure = _as_sgt(anchor)
    found: list[datetime] = []
    for _ in range(_MAX_STEPS):
        if len(found) >= count:
            break
        if departure >= cutoff:
            if not rail_runs_at(table, station_code, headsign, departure):
                break  # the last train has gone
            found.append(departure)
        departure += timedelta(seconds=rail_headway_seconds(table, station_code, headsign, departure))
    return found


def next_departures_text(departures: list[datetime], now: datetime) -> str | None:
    """"Next trains: about 8:44 AM, about 8:46 AM, about 8:48 AM." The times are projected from the headway."""
    if not departures:
        return None
    about = [TRAIN_ABOUT.replace("{time}", format_clock(d, now)) for d in departures]
    return TRAIN_NEXT.replace("{list}", ", ".join(about))


def rail_payload(
    table: dict | None,
    *,
    station_code: str,
    line_code: str,
    headsign: str | None,
    departure_iso: str,
    user_lat: float | None,
    user_lon: float | None,
    accuracy: float | None,
    location_timestamp: float | None,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    """The poll-shaped answer for a train first leg. Raises ValueError when departure_iso is not a timestamp."""
    moment = _as_sgt(now)
    anchor = _as_sgt(parse_journey_time(departure_iso))
    point = station_point(table, station_code)
    upcoming = next_departures(table, station_code, headsign, anchor, moment)
    later = [d for d in upcoming if d > anchor]
    trains = [{"arrival_time": anchor.replace(microsecond=0).isoformat(), "scheduled": True}] + [
        {"arrival_time": d.replace(microsecond=0).isoformat(), "scheduled": True} for d in later[:NEXT_DEPARTURES]
    ]
    scored = score_scheduled_rail(
        trains,
        user_lat=user_lat, user_lon=user_lon, accuracy_m=accuracy,
        stop_lat=None if point is None else point[0], stop_lon=None if point is None else point[1],
        headway_for=lambda when: rail_headway_seconds(table, station_code, headsign, when),
        now=moment, location_timestamp=location_timestamp, walk_speed_m_s=walk_speed_m_s,
    )
    primary = next((t for t in scored if t.get("is_primary")), None)
    distance = _distance(user_lat, user_lon, point)
    eta = None if primary is None else parse_journey_time(primary["arrival_time"])
    leave_by = resolve_leave_by(
        eta=eta, distance_m=distance, arrival_status="ok", now=moment, walk_speed_m_s=walk_speed_m_s
    )
    missed = (anchor - moment).total_seconds() < -MISSED_AFTER_S
    name = line_name(table, line_code)
    chance = primary.get("probability") if primary else None
    return {
        "status": "ok",
        "stop_code": station_code,
        "service_no": line_code,
        "fetched_at": moment.replace(microsecond=0).isoformat(),
        "leg_kind": LEG_KIND_RAIL,
        "line_code": line_code,
        "line_name": name,
        "headsign": headsign,
        "scheduled": True,
        "live": False,
        "buses": scored,
        "headway_s": None if primary is None else primary.get("headway_s"),
        "leave_by": None if leave_by is None else _as_sgt_iso(leave_by),
        "notification_time": None,
        # Q12: no leave-now notification and no "5 minutes left" for a train until the wording is approved.
        "leave_now": {
            "bus_id": None, "eligible": False, "title": None, "body": None,
            "range_high": chance.get("range_high") if isinstance(chance, dict) else None,
            "reason": LEAVE_NOW_PENDING,
        },
        "notifications": {"leave_now": False, "five_minutes": False},
        "reroute": {"enabled": False, "switched": False},
        "next_departures": [d.replace(microsecond=0).isoformat() for d in upcoming],
        "next_departures_text": next_departures_text(upcoming, moment),
        "left_text": TRAIN_LEFT.replace("{line}", name).replace("{time}", format_clock(upcoming[0], moment))
        if missed and upcoming else None,
        "near_stop": distance is not None and is_near_stop(distance),
        "station_point": None if point is None else list(point),
    }


def rail_journey(
    table: dict | None,
    cache,
    *,
    station_code: str,
    line_code: str,
    headsign: str | None,
    departure_iso: str | None,
    user_lat: float,
    user_lon: float,
    dest_lat: float,
    dest_lon: float,
    destination_stop_code: str,
    arrive_by: datetime | None,
    ride_minutes: float | None,
    arrival_status: str,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    """/api/journey for a train first leg. `ride_minutes` is the whole ride from the first board to the last
    alighting (the planner's number). Leave by is departure - walk - 135 s, through resolve_leave_by."""
    moment = _as_sgt(now)
    point = station_point(table, station_code)
    distance = _distance(user_lat, user_lon, point)
    eta = None if departure_iso is None else _as_sgt(parse_journey_time(departure_iso))
    walk = 0.0 if distance is None else walk_minutes(distance, walk_speed_m_s)
    if eta is not None:
        wait = max(0.0, (eta - moment).total_seconds() / 60 - walk)
    else:
        wait = rail_headway_seconds(table, station_code, headsign, moment) / 2 / 60
    stop = cache.stop_by_code(destination_stop_code) if cache is not None else None
    end_m = 0.0
    if isinstance(stop, dict) and isinstance(stop.get("Latitude"), (int, float)) and isinstance(stop.get("Longitude"), (int, float)):
        end_m = haversine_m(float(stop["Latitude"]), float(stop["Longitude"]), dest_lat, dest_lon)
    ride = ride_minutes if isinstance(ride_minutes, (int, float)) and math.isfinite(ride_minutes) and ride_minutes >= 0 else None
    terms = {"board_walk_minutes": walk, "wait_minutes": wait, "ride_minutes": ride, "end_walk_metres": end_m}
    total = None if ride is None else math.ceil(walk + wait + ride + walk_minutes(end_m, walk_speed_m_s))
    leave_by = resolve_leave_by(
        eta=eta, distance_m=distance, arrival_status=arrival_status, now=moment, walk_speed_m_s=walk_speed_m_s
    )
    journey = pt_plan.journey_from_terms(
        moment, destination_stop_code=destination_stop_code, services=[line_code], terms=terms,
        ride_minutes=total, arrive_by=arrive_by, leave_by=leave_by, speed=walk_speed_m_s,
    )
    journey["leg_kind"] = LEG_KIND_RAIL
    return journey


def _distance(user_lat, user_lon, point) -> float | None:
    if point is None or user_lat is None or user_lon is None:
        return None
    if not (math.isfinite(user_lat) and math.isfinite(user_lon)):
        return None
    return straight_line_m(float(user_lat), float(user_lon), point[0], point[1])


def _as_sgt(value: datetime) -> datetime:
    return value.replace(tzinfo=SGT) if value.tzinfo is None else value.astimezone(SGT)

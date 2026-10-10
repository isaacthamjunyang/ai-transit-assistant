"""Auto-planned journey: the app picks the boarding stop and the route for the user.

Static data only (no live arrival calls). Every boarding stop within the existing
boarding radius is planned with the existing pathfinder, the options are merged
and kept in the existing order, and one option is picked:

- with an arrive-by target, the first option whose Step 9 estimated arrival is
  on or before the target; if none is, the first option (and the existing
  planning warning is shown);
- without a target, the first option.

Ties in the existing order break by fewest transfers, then shortest walk to the
boarding stop, then lowest service number, so the result is deterministic.
"""

import math
import re
from datetime import datetime, timedelta, timezone

from config import WALK_SPEED_DEFAULT_MPS
from journey import build_journey, parse_journey_time, planning_warning
from lta_static import StopAndRouteCache
from nearby import BOARDING_RADIUS_M, nearby_boarding_stops
from route_plan import _sort_key, plan_route
from service_hours import NO_SERVICE

SGT = timezone(timedelta(hours=8))
TARGET_MET = "target_met"
TARGET_MISSED = "target_missed"
NO_TARGET = "no_target"
NO_ROUTE = "no_route"


def service_number_key(service_no: str) -> tuple:
    """Lowest service number first: numeric part, then any suffix ("14" < "14e" < "36" < "106")."""
    text = str(service_no or "").strip()
    match = re.match(r"(\d+)(.*)", text)
    if match is None:
        return (1, 0, text)
    return (0, int(match.group(1)), match.group(2))


def merged_order_key(option: dict) -> tuple:
    """The existing order (generalized minutes with the transfer penalty) with the stated tie-breaks."""
    minutes = option.get("generalized_time_minutes")
    walk = option.get("boarding_walk_m")
    return (
        float("inf") if minutes is None else minutes,
        option.get("transfers", 0),
        float("inf") if walk is None else walk,
        tuple(service_number_key(leg.get("service_no", "")) for leg in option.get("legs") or []),
        _sort_key(option) if _has_sort_fields(option) else (),
    )


def _has_sort_fields(option: dict) -> bool:
    return all(key in option for key in ("generalized_time_minutes", "transfers", "total_route_km", "legs"))


def fewest_transfers_key(option: dict) -> tuple:
    """Fewest transfers first, then the usual order. Used by the static fallback of the fewest_transfers priority."""
    return (option.get("transfers", 0), *merged_order_key(option))


def pick_journey_option(options: list[dict], arrive_by: datetime | None, key=merged_order_key) -> dict:
    """Pure: order the options and pick one. Each option may carry `estimated_arrival` (datetime or None)."""
    ordered = sorted(options, key=key)
    if not ordered:
        return {"option": None, "reason": NO_ROUTE, "ordered": []}
    if arrive_by is None:
        return {"option": ordered[0], "reason": NO_TARGET, "ordered": ordered}
    for option in ordered:
        estimate = option.get("estimated_arrival")
        if isinstance(estimate, datetime) and estimate <= arrive_by:
            return {"option": option, "reason": TARGET_MET, "ordered": ordered}
    return {"option": ordered[0], "reason": TARGET_MISSED, "ordered": ordered}


def _journey_for(
    cache: StopAndRouteCache,
    option: dict,
    *,
    destination_stop_code: str,
    user_lat: float,
    user_lon: float,
    dest_lat: float,
    dest_lon: float,
    arrive_by: datetime | None,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    """The existing Step 9 journey for one option, with the parameters the page sends after Start."""
    legs = option["legs"]
    first = legs[0]
    transfer = option.get("route_type") == "one_transfer" and len(legs) >= 2
    return build_journey(
        cache,
        dest_lat,
        dest_lon,
        user_lat,
        user_lon,
        destination_stop_code,
        boarding_stop_code=first["boarding_stop_code"],
        service_no=first["service_no"],
        arrive_by=arrive_by,
        now=now,
        transfer=transfer,
        leg1_ride_minutes=first.get("ride_minutes") if transfer else None,
        leg2_ride_minutes=legs[1].get("ride_minutes") if transfer else None,
        leg1_service_no=first["service_no"] if transfer else None,
        leg1_direction=first.get("direction") if transfer else None,
        walk_speed_m_s=walk_speed_m_s,
    )


def plan_journey(
    cache: StopAndRouteCache,
    *,
    user_lat: float,
    user_lon: float,
    destination_stop_code: str,
    dest_lat: float,
    dest_lon: float,
    arrive_by: datetime | None = None,
    now: datetime | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
    priority: str = "fastest",
) -> dict:
    """priority is "fastest" (the default) or "fewest_transfers"; any other value plans as fastest."""
    moment = now if now is not None else datetime.now(SGT)
    order = fewest_transfers_key if priority == "fewest_transfers" else merged_order_key
    candidates = nearby_boarding_stops(
        cache, user_lat, user_lon, BOARDING_RADIUS_M, walk_speed_m_s=walk_speed_m_s
    )
    options = []
    closed = False
    for stop in candidates:
        planned = plan_route(
            cache,
            stop["stop_code"],
            destination_stop_code,
            user_lat,
            user_lon,
            dest_lat,
            dest_lon,
            now=moment,
            walk_speed_m_s=walk_speed_m_s,
            arrive_by=arrive_by,
        )
        if planned.get("route_status") == NO_SERVICE:
            closed = True
        if planned.get("route_status") != "ok":
            continue
        for option in planned.get("options") or []:
            options.append({**option, "boarding_walk_m": stop["distance_m"]})
    journeys: dict[int, dict] = {}
    if arrive_by is not None:
        for option in sorted(options, key=order):
            journey = _journey_for(
                cache,
                option,
                destination_stop_code=destination_stop_code,
                user_lat=user_lat,
                user_lon=user_lon,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                arrive_by=arrive_by,
                now=moment,
                walk_speed_m_s=walk_speed_m_s,
            )
            journeys[id(option)] = journey
            point = journey.get("arrival_point")
            option["estimated_arrival"] = parse_journey_time(point) if point else None
            if option["estimated_arrival"] is not None and option["estimated_arrival"] <= arrive_by:
                break
    picked = pick_journey_option(options, arrive_by, order)
    chosen = picked["option"]
    if chosen is None:
        return {
            "status": "ok",
            "route_status": NO_SERVICE if closed else "no_feasible_route",
            "reason": NO_SERVICE if closed else NO_ROUTE,
            "candidate_stop_count": len(candidates),
            "option": None,
            "journey": None,
            "planning_warning": None,
        }
    journey = journeys.get(id(chosen)) or _journey_for(
        cache,
        chosen,
        destination_stop_code=destination_stop_code,
        user_lat=user_lat,
        user_lon=user_lon,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        arrive_by=arrive_by,
        now=moment,
        walk_speed_m_s=walk_speed_m_s,
    )
    minutes = [option.get("generalized_time_minutes") for option in picked["ordered"]]
    warning = planning_warning(moment, arrive_by, minutes) if picked["reason"] == TARGET_MISSED else None
    option = {key: value for key, value in chosen.items() if key != "estimated_arrival"}
    return {
        "status": "ok",
        "route_status": "ok",
        "reason": picked["reason"],
        "candidate_stop_count": len(candidates),
        "option": option,
        "boarding_stop": next(
            (stop for stop in candidates if stop["stop_code"] == chosen["legs"][0]["boarding_stop_code"]),
            None,
        ),
        "journey": journey,
        "planning_warning": warning,
    }

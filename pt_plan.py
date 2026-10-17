"""The journey planner on OneMap itineraries (plan_edits_9 sections 3, 4.4 and 4.5).

One routing call (pt_route) replaces the old per-stop loop of the static pathfinder. What it does:
- Origin: the coordinate of the nearest stop or station (or the stop the caller names), never the user's position.
  Destination: the chosen place. The user's position is used here only to measure the walk to the first stop and is
  never put in a request, a cache key, a log line or a result.
- Hours: every bus leg is checked with service_runs_at and every rail leg with rail_runs_at, each at its own leg time.
  A leg is checked at OneMap's time for it, moved later by the amount the user reaches the first stop after OneMap's
  first boarding (never earlier: arriving early only means waiting). One failing leg drops the whole itinerary.
- Status: everything dropped for hours, or only a walk: "no_service". 404 or nothing usable: "no_feasible_route".
  OneMap unavailable: the static bus planner answers (bus only, one transfer) and the result carries fallback_note.
- Priorities: fastest (default), fewest_transfers, least_walking, bus_only, mrt_only. Ranking is ours over the one to
  three itineraries OneMap returns, with 3 minutes per transfer for ranking only. The 90 minute budget stays.
- Calls: 1 per planning request; up to 3 with an arrive-by time (pt_route.search_arrive_by) or fewest_transfers (a
  second and third call in BUS and RAIL mode when the first pool has no direct itinerary).
- Rail first leg: not scored here. The result describes the itinerary; catch probability is a later phase.
"""

import logging
import math
from datetime import datetime, timedelta, timezone

import httpx

import pt_route
from bus_traffic import bus_ride_minutes
from config import BUS_SPEED_KM_H, WALK_SPEED_DEFAULT_MPS
from destination_stops import _service_record
from journey import (
    _as_sgt_iso,
    _comparison,
    _shift_window,
    arrival_window,
    resolve_leave_by,
)
from journey_plan import NO_ROUTE, NO_TARGET, TARGET_MET, TARGET_MISSED, plan_journey
from lta_static import StopAndRouteCache
from nearby import haversine_m
from pt_route import (
    KIND_BUS,
    KIND_RAIL,
    KIND_WALK,
    MODE_BUS,
    MODE_RAIL,
    MODE_TRANSIT,
    BudgetExhausted,
    CallBudget,
    OneMapSession,
    PtRouter,
    RouteRejected,
    RouteUnavailable,
)
from route_plan import (
    ALTERNATIVE_ROUTE,
    FASTEST_ROUTE,
    FEWEST_TRANSFERS,
    JOURNEY_BUDGET_MINUTES,
    NO_FEASIBLE_ROUTE,
    _catalog,
    suggest_alternate_boarding,
)
from service_hours import NO_SERVICE, bus_closed_at, rail_closed_at, rail_runs_at, service_runs_at
from walk_speed import walk_minutes

SGT = timezone(timedelta(hours=8))

PRIORITY_FASTEST = "fastest"
PRIORITY_FEWEST_TRANSFERS = "fewest_transfers"
PRIORITY_LEAST_WALKING = "least_walking"
PRIORITY_BUS_ONLY = "bus_only"
PRIORITY_MRT_ONLY = "mrt_only"
PRIORITIES = (PRIORITY_FASTEST, PRIORITY_FEWEST_TRANSFERS, PRIORITY_LEAST_WALKING, PRIORITY_BUS_ONLY, PRIORITY_MRT_ONLY)
DEFAULT_PRIORITY = PRIORITY_FASTEST
PRIORITY_MESSAGE = "priority must be one of: " + ", ".join(PRIORITIES) + "."

TRANSFER_RANK_PENALTY_MINUTES = 3  # ranking only: real waits are already in the minutes
MAX_OPTIONS = 3
TOP_ORIGIN_RADIUS_M = 1000.0

NO_ROUTE_MESSAGE = "No route found for this trip."
NO_BUS_ONLY_MESSAGE = "No bus-only route found. Try another priority."
NO_MRT_ONLY_MESSAGE = "No MRT or LRT route found. Try another priority."
NEEDS_ROUTE_SERVICE_MESSAGE = "Needs the route service."
NO_BUS_CLOSED_MESSAGE = "Bus services have stopped for now. Try another priority."
NO_MRT_CLOSED_MESSAGE = "MRT and LRT services have stopped for now. Try another priority."
# the OneMap planner's no-service sentence; the static (bus only) planner keeps the old bus-only one on the page
NO_SERVICE_MESSAGE = "No services to this destination right now."
PRIORITY_UNAVAILABLE = "priority_unavailable"
STATIC_PRIORITIES = (PRIORITY_FASTEST, PRIORITY_FEWEST_TRANSFERS, PRIORITY_BUS_ONLY)  # what the fallback can do


def valid_priority(value: object) -> str | None:
    """The priority when it is exactly one of the five names, else None."""
    return value if isinstance(value, str) and value in PRIORITIES else None


# ---- the planner ------------------------------------------------------------------------------------------


def plan_multi_leg(
    cache: StopAndRouteCache,
    *,
    router: PtRouter,
    session: OneMapSession,
    client: httpx.Client,
    rail_table: dict | None,
    user_lat: float,
    user_lon: float,
    dest_lat: float,
    dest_lon: float,
    destination_name: str = "",
    destination_stop_code: str = "",
    end_lat: float | None = None,
    end_lon: float | None = None,
    origin_stop_code: str | None = None,
    arrive_by: datetime | None = None,
    priority: str = DEFAULT_PRIORITY,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
    now: datetime | None = None,
    token: str = "",
    email: str = "",
    password: str = "",
    clock: float | None = None,
) -> dict:
    """Plan with OneMap. Raises RouteUnavailable when OneMap cannot be used; plan_with_fallback catches it.

    dest_lat and dest_lon are the place. With end_lat and end_lon (the chosen destination stop or station) OneMap routes to
    that point, so the ride ends at the stop the user chose, and the walk from there to the place is added as the last leg."""
    if priority not in PRIORITIES:
        raise ValueError("unknown priority")
    moment = _as_sgt(now if now is not None else datetime.now(SGT))
    origin = (pt_route.stop_place(cache, origin_stop_code) if origin_stop_code
              else pt_route.nearest_origin_place(cache, user_lat, user_lon, _stations(rail_table), TOP_ORIGIN_RADIUS_M))
    if origin is None:
        return _failure(NO_FEASIBLE_ROUTE, priority, calls=0)
    ends_at_stop = end_lat is not None and end_lon is not None
    target_lat, target_lon = (end_lat, end_lon) if ends_at_stop else (dest_lat, dest_lon)
    destination = pt_route.destination_place(destination_name, target_lat, target_lon)
    depart = moment + timedelta(minutes=walk_minutes(haversine_m(user_lat, user_lon, origin.latitude, origin.longitude),
                                                     walk_speed_m_s))
    budget = CallBudget.extended() if (arrive_by is not None or priority == PRIORITY_FEWEST_TRANSFERS) \
        else CallBudget.single()
    args = {"session": session, "client": client, "lta_cache": cache, "rail_table": rail_table,
            "token": token, "email": email, "password": password, "now": clock}
    primary_mode = {PRIORITY_BUS_ONLY: MODE_BUS, PRIORITY_MRT_ONLY: MODE_RAIL}.get(priority, MODE_TRANSIT)
    if arrive_by is not None:
        km = haversine_m(origin.latitude, origin.longitude, target_lat, target_lon) / 1000
        estimate = max(20.0, bus_ride_minutes(km / BUS_SPEED_KM_H * 60, depart) * 1.2 + 10)
        first = pt_route.search_arrive_by(router, origin, destination, arrive_by, estimate_minutes=estimate,
                                          earliest=depart, mode=primary_mode, budget=budget, **args)
    else:
        first = router.route(origin, destination, depart, primary_mode, budget=budget, **args)
    pool = list(first["itineraries"])
    status = first["status"]
    if ends_at_stop:
        pool = [_end_at_place(item, dest_lat, dest_lon, walk_speed_m_s, destination_name) for item in pool]
    if priority == PRIORITY_FEWEST_TRANSFERS and arrive_by is None and pool and min(i["transfers"] for i in pool) > 0:
        for mode in (MODE_BUS, MODE_RAIL):  # a direct bus or train may exist that the mixed search did not return
            try:
                extra = router.route(origin, destination, depart, mode, budget=budget, **args)
            except (BudgetExhausted, RouteUnavailable, RouteRejected):
                break
            pool = _merge(pool, [_end_at_place(item, dest_lat, dest_lon, walk_speed_m_s, destination_name)
                                 if ends_at_stop else item for item in extra["itineraries"]])
    calls = budget.used
    dropped = {"hours": 0, "budget": 0, **first.get("dropped", {})}
    # a chip (Bus only, MRT only) says "stopped for now" only when its own service is known to be closed at the travel time
    travel = _as_sgt(arrive_by) if arrive_by is not None else depart
    stopped = _chip_closed(priority, cache, rail_table, travel)
    if not pool:
        return _empty(status, priority, calls, dropped, stopped)
    ahead = arrive_by is not None  # planning ahead: the user leaves in time for the departure, so the wait is theirs
    assessed = [_assess(cache, rail_table, item, moment, user_lat, user_lon, walk_speed_m_s, ahead) for item in pool]
    closed = sum(1 for a in assessed if not a["runs"])
    over = sum(1 for a in assessed if a["runs"] and a["minutes"] > JOURNEY_BUDGET_MINUTES)
    dropped.update(hours=closed, budget=over)
    usable = [a for a in assessed if a["runs"] and a["minutes"] <= JOURNEY_BUDGET_MINUTES]
    usable = [a for a in usable if _fits_priority(a, priority)]
    if not usable:
        if closed and not over:
            return _failure(NO_SERVICE, priority, calls, reason=NO_SERVICE, dropped=dropped, stopped=stopped)
        return _failure(NO_FEASIBLE_ROUTE, priority, calls, dropped=dropped, stopped=stopped)
    ranked = sorted(usable, key=_rank_key(priority))
    fastest = min(usable, key=_rank_key(PRIORITY_FASTEST))
    reason, chosen = NO_TARGET, ranked[0]
    warning = None
    if arrive_by is not None:
        target = _as_sgt(arrive_by)
        in_time = [a for a in ranked if a["arrival"] <= target]
        if in_time:
            reason, chosen = TARGET_MET, in_time[0]
        else:
            reason, chosen = TARGET_MISSED, fastest
            warning = _late_warning(ranked, target)
    message = ""
    options = [_option(cache, a, moment, walk_speed_m_s) for a in ([chosen] + [a for a in ranked if a is not chosen])[:MAX_OPTIONS]]
    best = options[0]
    return {
        "status": "ok",
        "route_status": "ok",
        "reason": reason,
        "message": message,
        "planner": "onemap",
        "priority": priority,
        "fallback_note": False,
        "calls": calls,
        "candidate_stop_count": 1,
        "option": best["option"],
        "itinerary": best["itinerary"],
        "options": [entry["option"] for entry in options],
        "itineraries": [entry["itinerary"] for entry in options],
        "boarding_stop": best["boarding_stop"],
        "journey": _journey(cache, chosen, destination_stop_code, arrive_by, moment, walk_speed_m_s),
        "starts": _starts(usable, walk_speed_m_s),
        "planning_warning": warning,
        "dropped": dropped,
    }


def _starts(usable: list[dict], speed: float) -> list[dict]:
    """Every usable itinerary (the hours verdict already covers every leg of it) as a first bus and the minutes from
    its own boarding to its end, bus legs with the traffic factor. The reroute search shifts these minutes to the real
    boarding time of that bus. Not capped like `options`."""
    found = []
    for assessed in usable:
        transit = _transit(assessed["itinerary"])
        first = transit[0] if transit else None
        if not first or first["kind"] != KIND_BUS or not first.get("service_no") or not first.get("boarding_stop_code"):
            continue
        found.append({
            "boarding_stop_code": first["boarding_stop_code"],
            "service_no": first["service_no"],
            "after_boarding_minutes": assessed["ride_min"] + walk_minutes(assessed["end_walk_m"], speed),
        })
    return found


FALLBACK_REASONS = frozenset({"no_credentials", "auth", "timeout", "network", "rate_limited", "http_error",
                              "rejected", "demo"})
_log = logging.getLogger("uvicorn.error")


def fallback_reason(exc: Exception) -> str:
    """The non-secret code for why OneMap was not used. Never the exception text, a URL or a coordinate."""
    if isinstance(exc, RouteRejected):
        return "rejected"
    code = getattr(exc, "reason", "")
    return code if code in FALLBACK_REASONS else "http_error"


def _with_reason(planned: dict, reason: str | None) -> dict:
    if reason is not None:
        _log.warning("OneMap routing not used, static planner answered: %s", reason)
    return {**planned, "fallback_reason": reason}


def journey_plan_result(cache, *, priority: str = DEFAULT_PRIORITY, use_onemap: bool = True, **kw) -> dict:
    """/api/journey-plan: the OneMap planner, or the static bus planner (fallback_note true) when OneMap fails or
    use_onemap is false (a Demo Mode OneMap failure). kw are the arguments of plan_multi_leg."""
    try:
        if not use_onemap:
            raise RouteUnavailable("demo")
        return _with_reason(plan_multi_leg(cache, priority=priority, **kw), None)
    except (RouteUnavailable, RouteRejected, BudgetExhausted) as exc:
        return _with_reason(static_journey_plan(
            cache, priority=priority, user_lat=kw["user_lat"], user_lon=kw["user_lon"],
            destination_stop_code=kw.get("destination_stop_code", ""), dest_lat=kw["dest_lat"],
            dest_lon=kw["dest_lon"], arrive_by=kw.get("arrive_by"),
            walk_speed_m_s=kw.get("walk_speed_m_s", WALK_SPEED_DEFAULT_MPS), now=kw.get("now")),
            fallback_reason(exc))


def route_plan_result(cache, *, origin_stop_code: str, alternates: list[str], priority: str = DEFAULT_PRIORITY,
                      use_onemap: bool = True, **kw) -> dict:
    """/api/route-plan: the same, for a boarding stop the page already chose."""
    try:
        if not use_onemap:
            raise RouteUnavailable("demo")
        planned = plan_multi_leg(cache, priority=priority, origin_stop_code=origin_stop_code, **kw)
        return _with_reason(route_plan_body(planned), None)
    except (RouteUnavailable, RouteRejected, BudgetExhausted) as exc:
        return _with_reason(static_route_plan(
            cache, priority=priority, origin=origin_stop_code, destination=kw.get("destination_stop_code", ""),
            user_lat=kw["user_lat"], user_lon=kw["user_lon"], dest_lat=kw["dest_lat"], dest_lon=kw["dest_lon"],
            alternates=alternates, now=kw.get("now"), walk_speed_m_s=kw.get("walk_speed_m_s", WALK_SPEED_DEFAULT_MPS),
            arrive_by=kw.get("arrive_by")), fallback_reason(exc))


def static_journey_plan(cache, *, priority, user_lat, user_lon, destination_stop_code, dest_lat, dest_lon, arrive_by,
                        walk_speed_m_s, now=None) -> dict:
    """The old planner as the fallback of /api/journey-plan. Bus only, up to one transfer."""
    if priority not in STATIC_PRIORITIES:
        return _unavailable_priority()
    planned = plan_journey(
        cache, user_lat=user_lat, user_lon=user_lon, destination_stop_code=destination_stop_code, dest_lat=dest_lat,
        dest_lon=dest_lon, arrive_by=arrive_by, now=now, walk_speed_m_s=walk_speed_m_s, priority=priority)
    return {**planned, "planner": "static", "priority": priority, "fallback_note": True, "calls": 0}


def static_route_plan(cache, *, priority, origin, destination, user_lat, user_lon, dest_lat, dest_lon, alternates,
                      now, walk_speed_m_s, arrive_by) -> dict:
    """The old planner as the fallback of /api/route-plan."""
    if priority not in STATIC_PRIORITIES:
        return {**_unavailable_priority(), "options": [], "option_count": 0, "legs": [], "route_type": None}
    planned = suggest_alternate_boarding(
        cache, origin, destination, user_lat, user_lon, dest_lat, dest_lon, alternates, now=now,
        walk_speed_m_s=walk_speed_m_s, arrive_by=arrive_by)
    options = planned.get("options") or []
    if priority == PRIORITY_FEWEST_TRANSFERS and len(options) > 1:
        reordered = sorted(options, key=lambda o: (o["transfers"], o["generalized_time_minutes"]))
        planned = {**planned, **_catalog([{**o, "label": label} for o, label in
                                          zip(reordered, (FASTEST_ROUTE, FEWEST_TRANSFERS, ALTERNATIVE_ROUTE))])}
    return {**planned, "planner": "static", "priority": priority, "fallback_note": True, "calls": 0}


def _unavailable_priority() -> dict:
    return {"status": "ok", "route_status": PRIORITY_UNAVAILABLE, "reason": PRIORITY_UNAVAILABLE,
            "message": NEEDS_ROUTE_SERVICE_MESSAGE, "option": None, "journey": None, "planning_warning": None,
            "planner": "static", "fallback_note": True, "calls": 0}


# ---- pool, hours, numbers ---------------------------------------------------------------------------------


def _merge(pool: list[dict], extra: list[dict]) -> list[dict]:
    seen = {_signature(item) for item in pool}
    return pool + [item for item in extra if _signature(item) not in seen]


END_AT_PLACE_MIN_M = 5.0


def _end_at_place(itinerary: dict, place_lat: float, place_lon: float, speed: float, name: str = "") -> dict:
    """The itinerary OneMap gave for the chosen stop, ending with the walk from that stop to the place: any walk OneMap
    added after the last ride (to the stop's own point) is replaced by the straight-line walk to the place, so the end
    walk, the totals and the arrival all describe the real last stretch. Nothing is added when the stop is the place."""
    legs = list(itinerary["legs"])
    while len(legs) > 1 and legs[-1]["kind"] == KIND_WALK:
        legs.pop()
    last = legs[-1]
    stops = last.get("stops") or []
    point = stops[-1] if stops else {}
    if not isinstance(point.get("latitude"), (int, float)) or not isinstance(point.get("longitude"), (int, float)):
        return itinerary
    metres = haversine_m(float(point["latitude"]), float(point["longitude"]), place_lat, place_lon)
    if metres < END_AT_PLACE_MIN_M:
        return {**itinerary, "legs": legs}
    seconds = metres / speed
    arrive = _as_sgt(datetime.fromisoformat(last["arrive"]))
    end = arrive + timedelta(seconds=seconds)
    walk = {
        "depart": arrive.isoformat(), "arrive": end.isoformat(), "duration_s": round(seconds, 1), "distance_m": round(metres, 1),
        "path": [[float(point["latitude"]), float(point["longitude"])], [place_lat, place_lon]], "kind": KIND_WALK,
        "from_name": last.get("alighting_stop_name", ""), "to_name": name or "Destination",
    }
    return {**itinerary, "legs": legs + [walk], "arrive": end.isoformat(), "walk_m": (itinerary.get("walk_m") or 0) + metres}


def _signature(itinerary: dict) -> tuple:
    return (itinerary["depart"], tuple(
        (leg["kind"], leg.get("service_no") or leg.get("line_code"), leg["boarding_stop_code"], leg["alighting_stop_code"])
        for leg in itinerary["legs"] if leg["kind"] != KIND_WALK))


def _transit(itinerary: dict) -> list[dict]:
    return [leg for leg in itinerary["legs"] if leg["kind"] != KIND_WALK]


def _assess(cache, rail_table, itinerary: dict, moment: datetime, user_lat: float, user_lon: float, speed: float,
            ahead: bool = False) -> dict:
    """Numbers and the hours verdict for one itinerary. With `ahead` (an arrive-by time) the wait before the first
    boarding is not counted: the user leaves later, and the arrival is OneMap's own time."""
    transit = _transit(itinerary)
    first = transit[0]
    start = first["stops"][0] if first.get("stops") else {}
    walk_m = (haversine_m(user_lat, user_lon, float(start["latitude"]), float(start["longitude"]))
              if isinstance(start.get("latitude"), (int, float)) and isinstance(start.get("longitude"), (int, float))
              else 0.0)
    at_stop = moment + timedelta(minutes=walk_minutes(walk_m, speed))
    boards = _as_sgt(datetime.fromisoformat(first["depart"]))
    late = max(timedelta(0), at_stop - boards)  # the user reaches the stop after OneMap's boarding; never earlier
    wait = max(0.0, (boards - at_stop).total_seconds() / 60)
    legs = itinerary["legs"]
    final = legs[-1] if legs[-1]["kind"] == KIND_WALK and len(legs) > 1 else None
    end_m = final["distance_m"] if final else 0.0
    ride_end = _as_sgt(datetime.fromisoformat(final["depart"] if final else itinerary["arrive"]))
    ride = (ride_end - boards).total_seconds() / 60
    for leg in transit:  # a bus leg takes longer in the peak; OneMap's own times are for a free road
        if leg["kind"] == KIND_BUS and isinstance(leg.get("duration_s"), (int, float)):
            scheduled = leg["duration_s"] / 60
            ride += bus_ride_minutes(scheduled, _as_sgt(datetime.fromisoformat(leg["depart"]))) - scheduled
    if ahead:
        wait = 0.0
    minutes = walk_minutes(walk_m, speed) + wait + ride + walk_minutes(end_m, speed)
    if ahead:
        arrival = boards + late + timedelta(minutes=ride + walk_minutes(end_m, speed))
    else:
        arrival = moment + timedelta(minutes=minutes)
    walking = walk_m + sum(leg["distance_m"] for index, leg in enumerate(legs)
                           if leg["kind"] == KIND_WALK and leg is not final and index > 0)
    transfers = itinerary["transfers"]
    runs = all(_leg_runs(cache, rail_table, leg, _as_sgt(datetime.fromisoformat(leg["depart"])) + late)
               for leg in transit)
    return {
        "itinerary": itinerary, "runs": runs, "transfers": transfers, "minutes": minutes,
        "generalized": minutes + TRANSFER_RANK_PENALTY_MINUTES * transfers,
        "walk_first_m": walk_m, "walk_total_m": walking, "wait_min": wait, "ride_min": ride, "end_walk_m": end_m,
        "arrival": arrival, "late_s": late.total_seconds(),
    }


def _leg_runs(cache, rail_table, leg: dict, when: datetime) -> bool:
    if leg["kind"] == KIND_BUS:
        return service_runs_at(cache, leg["service_no"], leg["boarding_stop_code"], when, leg.get("direction"))
    return rail_runs_at(rail_table, leg["boarding_stop_code"], leg.get("headsign"), when)


def _fits_priority(assessed: dict, priority: str) -> bool:
    kinds = {leg["kind"] for leg in _transit(assessed["itinerary"])}
    if priority == PRIORITY_BUS_ONLY:
        return kinds == {KIND_BUS}
    if priority == PRIORITY_MRT_ONLY:
        return KIND_RAIL in kinds and KIND_BUS not in kinds
    return True


def _rank_key(priority: str):
    if priority == PRIORITY_FEWEST_TRANSFERS:
        return lambda a: (a["transfers"], a["generalized"], a["walk_total_m"], a["itinerary"]["depart"])
    if priority == PRIORITY_LEAST_WALKING:
        return lambda a: (round(a["walk_total_m"]), a["generalized"], a["transfers"], a["itinerary"]["depart"])
    return lambda a: (a["generalized"], a["transfers"], a["walk_total_m"], a["itinerary"]["depart"])


def _late_warning(ranked: list[dict], target: datetime) -> dict | None:
    """The existing planning_warning shape: the earliest arrival any shown itinerary can make, and the target."""
    earliest = min(a["arrival"] for a in ranked)
    if earliest <= target:
        return None
    return {"earliest_arrival": _as_sgt_iso(earliest), "target": _as_sgt_iso(target)}


def _is_chip(priority: str) -> bool:
    return priority in (PRIORITY_BUS_ONLY, PRIORITY_MRT_ONLY)


def _chip_closed(priority: str, cache, rail_table, when: datetime) -> bool:
    """True when the priority's own mode is known to be closed at `when` (always False for the other priorities)."""
    if priority == PRIORITY_MRT_ONLY:
        return rail_closed_at(rail_table, when)
    if priority == PRIORITY_BUS_ONLY:
        return bus_closed_at(cache, when)
    return False


def _empty_message(priority: str, route_status: str, stopped: bool) -> str:
    """The sentence for an empty answer. A chip names its own mode (and says "stopped for now" when it is closed); the
    other priorities say no bus or MRT is running when nothing runs, and keep "No route found" for no route."""
    if priority == PRIORITY_MRT_ONLY:
        return NO_MRT_CLOSED_MESSAGE if stopped else NO_MRT_ONLY_MESSAGE
    if priority == PRIORITY_BUS_ONLY:
        return NO_BUS_CLOSED_MESSAGE if stopped else NO_BUS_ONLY_MESSAGE
    return NO_SERVICE_MESSAGE if route_status == NO_SERVICE else NO_ROUTE_MESSAGE


def _stations(rail_table: dict | None) -> list[dict]:
    stations = []
    for code, station in ((rail_table or {}).get("stations") or {}).items():
        if isinstance(station.get("latitude"), (int, float)) and isinstance(station.get("longitude"), (int, float)):
            stations.append({"code": code, "name": station.get("name", ""), "latitude": station["latitude"],
                             "longitude": station["longitude"]})
    return stations


# ---- results ----------------------------------------------------------------------------------------------


def _failure(route_status: str, priority: str, calls: int, reason: str | None = None, message: str | None = None,
             dropped: dict | None = None, stopped: bool = False) -> dict:
    text = _empty_message(priority, route_status, stopped) if message is None else message
    return {
        "status": "ok", "route_status": route_status, "reason": reason or (NO_SERVICE if route_status == NO_SERVICE else NO_ROUTE),
        "message": text, "stopped": bool(stopped) and _is_chip(priority), "planner": "onemap", "priority": priority,
        "fallback_note": False,
        "calls": calls, "candidate_stop_count": 1, "option": None, "itinerary": None, "options": [], "itineraries": [],
        "boarding_stop": None, "journey": None, "planning_warning": None,
        "dropped": dropped if dropped is not None else {"hours": 0, "budget": 0},
    }


def _empty(status: str, priority: str, calls: int, dropped: dict, stopped: bool = False) -> dict:
    """Nothing came back. A walk-only answer means nothing is running (or the trip is too short); 404 or an empty plan
    means no route. `stopped` is the chip's own mode being closed at the travel time (from the timetables, not OneMap)."""
    if status == pt_route.STATUS_NO_TRANSIT:
        return _failure(NO_SERVICE, priority, calls, reason=NO_SERVICE, dropped=dropped, stopped=stopped)
    return _failure(NO_FEASIBLE_ROUTE, priority, calls, dropped=dropped, stopped=stopped)


def _option(cache, assessed: dict, moment: datetime, speed: float) -> dict:
    itinerary = assessed["itinerary"]
    legs = [_decorate(cache, leg) for leg in itinerary["legs"]]
    transit = [leg for leg in legs if leg["kind"] != KIND_WALK]
    first = transit[0]
    between = [leg for index, leg in enumerate(legs[:-1]) if leg["kind"] == KIND_WALK and index > 0
               and legs[index - 1]["kind"] != KIND_WALK and legs[index + 1]["kind"] != KIND_WALK]
    totals = {
        "minutes": math.ceil(assessed["minutes"]), "transfers": assessed["transfers"],
        "walk_minutes": math.ceil(walk_minutes(assessed["walk_total_m"], speed)),
        "walk_m": int(round(assessed["walk_total_m"])), "wait_minutes": math.ceil(assessed["wait_min"]),
    }
    payload = {
        "route_type": itinerary["route_type"], "first_transit_kind": itinerary["first_transit_kind"],
        "depart": itinerary["depart"], "arrive": itinerary["arrive"], "totals": totals, "legs": legs,
    }
    handoff = transit[0]["alighting_stop_code"] if len(transit) > 1 else None
    option = {
        "route_type": itinerary["route_type"], "transfers": assessed["transfers"],
        "transfer_stop_code": handoff, "transfer_stop_name": transit[0]["alighting_stop_name"] if handoff else None,
        "transfer_penalty_minutes": TRANSFER_RANK_PENALTY_MINUTES * assessed["transfers"],
        "transfer_distance_m": float(sum(leg["distance_m"] for leg in between)),
        "wait_minutes": assessed["wait_min"], "legs": transit, "total_route_km": None,
        "generalized_time_minutes": assessed["generalized"], "boarding_walk_m": int(round(assessed["walk_first_m"])),
        "first_transit_kind": itinerary["first_transit_kind"], "totals": totals, "label": None,
    }
    stop = first["stops"][0]
    boarding = {"stop_code": first["boarding_stop_code"], "description": first["boarding_stop_name"],
                "latitude": stop["latitude"], "longitude": stop["longitude"],
                "distance_m": int(round(assessed["walk_first_m"])),
                "walk_minutes": walk_minutes(assessed["walk_first_m"], speed)}
    return {"option": option, "itinerary": payload, "boarding_stop": boarding}


def _decorate(cache, leg: dict) -> dict:
    """Every leg carries kind, line_code, line_name and headsign (None when not applicable)."""
    out = dict(leg)
    if leg["kind"] == KIND_BUS:
        out["line_code"] = leg["service_no"]
        out["line_name"] = None
        out["headsign"] = _bus_headsign(cache, leg["service_no"], leg.get("direction"))
    elif leg["kind"] == KIND_RAIL:
        out.setdefault("headsign", None)
    else:
        out.update(line_code=None, line_name=None, headsign=None)
    return out


def _bus_headsign(cache, service_no: str, direction) -> str | None:
    if direction is None:
        return None
    record = _service_record(cache.services, service_no, direction)
    code = record.get("DestinationCode") if record else None
    stop = cache.stop_by_code(code) if isinstance(code, str) else None
    return str(stop["Description"]) if stop and stop.get("Description") else None


def _journey(cache, assessed: dict, destination_stop_code: str, arrive_by, moment: datetime, speed: float) -> dict:
    """The Step 9 journey object, built from OneMap's numbers instead of the cached distances."""
    terms = {
        "board_walk_minutes": walk_minutes(assessed["walk_first_m"], speed), "wait_minutes": assessed["wait_min"],
        "ride_minutes": assessed["ride_min"], "end_walk_metres": assessed["end_walk_m"],
    }
    leave_by = resolve_leave_by(eta=None, distance_m=assessed["walk_first_m"], arrival_status="ok", now=moment,
                                walk_speed_m_s=speed)
    services = [leg["service_no"] for leg in _transit(assessed["itinerary"]) if leg["kind"] == KIND_BUS]
    return journey_from_terms(moment, destination_stop_code=destination_stop_code, services=services, terms=terms,
                              ride_minutes=math.ceil(assessed["minutes"]), arrive_by=arrive_by, leave_by=leave_by,
                              speed=speed)


def journey_from_terms(moment: datetime, *, destination_stop_code: str, services: list[str], terms: dict,
                       ride_minutes: int, arrive_by, leave_by: datetime | None, speed: float) -> dict:
    """The fields of journey.build_journey from the Step 9 terms (board walk, wait, ride, end walk)."""
    comparison = _comparison(moment, ride_minutes, arrive_by)
    window = arrival_window(moment, board_walk_minutes=terms["board_walk_minutes"], wait_minutes=terms["wait_minutes"],
                            ride_minutes=terms["ride_minutes"], end_walk_metres=terms["end_walk_metres"],
                            arrive_by=arrive_by, basis="planned", walk_speed_m_s=speed)
    if window is not None and window["point_minutes"] != ride_minutes:
        window = _shift_window(window, ride_minutes - window["point_minutes"], arrive_by)
    return {
        "status": "ok", "destination_stop_code": destination_stop_code, "ride_minutes": ride_minutes,
        "connecting_services": services,
        "ride_label": comparison["ride_label"], "comparison_label": comparison["comparison_label"],
        "comparison_note": comparison["comparison_note"], "estimated_arrival": comparison["estimated_arrival"],
        "arrival_point": None if window is None else _as_sgt_iso(window["estimated_arrival"]),
        "arrival_low": None if window is None else _as_sgt_iso(window["arrival_low"]),
        "arrival_high": None if window is None else _as_sgt_iso(window["arrival_high"]),
        "spare_minutes": None if window is None or arrive_by is None else window["spare_minutes"],
        "arrival_basis": None if window is None else window["basis"], "arrival_terms": terms,
        "leave_by": _as_sgt_iso(leave_by) if leave_by is not None else None,
    }


def route_plan_body(planned: dict) -> dict:
    """The /api/route-plan body from a plan_multi_leg result: every field the static answer has, plus the new ones."""
    options = planned.get("options") or []
    best = options[0] if options else None
    body = {
        "route_status": planned["route_status"], "message": planned.get("message", ""),
        "route_type": best["route_type"] if best else None, "legs": best["legs"] if best else [],
        "active_leg_index": 1 if best else None,
        "active_leg": None if not best else {
            "leg_index": 1, "boarding_stop_code": best["legs"][0]["boarding_stop_code"],
            "service_no": best["legs"][0].get("service_no") or best["legs"][0].get("line_code"),
            "direction": best["legs"][0].get("direction"),
        },
        "transfer_stop_code": best["transfer_stop_code"] if best else None,
        "transfer_distance_m": best["transfer_distance_m"] if best else None,
        "generalized_time_minutes": best["generalized_time_minutes"] if best else None,
        "transfer_penalty_minutes": best["transfer_penalty_minutes"] if best else None,
        "arrive_by_state": None if not best else ("existing" if best["transfers"] == 0 else "na"),
        "options": options, "option_count": len(options),
    }
    for key in ("planner", "priority", "fallback_note", "calls", "itinerary", "itineraries",
                "planning_warning", "reason", "stopped"):
        body[key] = planned.get(key)
    return body


def _as_sgt(value: datetime) -> datetime:
    return value.replace(tzinfo=SGT) if value.tzinfo is None else value.astimezone(SGT)

"""Auto-reroute choice for one fresh arrival poll.

Python selects the winning alternative. This module reuses the Step 6
scores it is given and the Step 8 ride-duration model. It does not call
OneMap or OpenAI, and it does not change leave-by or the catch formula.
"""

import math
from datetime import datetime, timedelta, timezone

from arrivals import BUS_POSITIONS, ArrivalUnavailable
from catch_heuristic import MISSED_AFTER_S, is_location_uncertain, location_age_seconds, ring_band
from config import MIN_REAL_CHANCE_RANGE_HIGH, WALK_SPEED_DEFAULT_MPS
from destination_stops import _arrival_terms, _hops, _links, _total_minutes
from journey import bus_arrival_window, leave_by_for_buses, leave_by_time
from leave_now import leave_now_notice, notification_time_iso
from nearby import BOARDING_RADIUS_M, haversine_m, walk_minutes
from observations import record_observation
from recommend import arrival_key, natural_key, pills, reason_text, recommend_option

SGT = timezone(timedelta(hours=8))
NORMAL_MARGIN = 15
COOLDOWN_MARGIN = 20
COOLDOWN_S = 120
ALTERNATE_STOP_LIMIT = 2
RANGE_HIGH_BELOW = MIN_REAL_CHANCE_RANGE_HIGH
CONTINUITY_WINDOW_S = 180
NO_BETTER_OPTION = (
    "Primary bus target has low catch probability ({point}%), "
    "but no better direct alternative meets the 15% improvement threshold."
)
POST_REROUTE_NO_BETTER = (
    "Primary bus target has low catch probability ({point}%), "
    "but no better direct alternative meets the post-reroute 20% improvement threshold."
)


def plan_reroute(
    *,
    cache,
    current: dict,
    user_lat: float,
    user_lon: float,
    accuracy_m: float | None,
    location_timestamp: float | None,
    destination_stop_code: str,
    place_lat: float,
    place_lon: float,
    arrive_by: datetime | None,
    last_reroute_at: datetime | None,
    now: datetime,
    loader,
    db_path=None,
    write_observation: bool = False,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    """Score alternatives for this fresh poll and decide whether to switch."""
    moment = _as_sgt(now)
    decision = _decide(
        cache=cache,
        current=current,
        user_lat=user_lat,
        user_lon=user_lon,
        accuracy_m=accuracy_m,
        location_timestamp=location_timestamp,
        destination_stop_code=destination_stop_code,
        place_lat=place_lat,
        place_lon=place_lon,
        arrive_by=arrive_by,
        last_reroute_at=last_reroute_at,
        now=moment,
        loader=loader,
        walk_speed_m_s=walk_speed_m_s,
    )
    # The arrivals pipeline inserts the scored-poll row. This flag does not.
    del write_observation, db_path
    decision.pop("log", None)
    return decision


def resolve_pinned_target(
    buses: list[dict],
    pinned_eta_epoch: float | None,
    now: datetime,
) -> tuple[dict | None, float | None]:
    """Match a same-stop pin by closest ETA, or clear it.

    Returns the matched bus and its current ETA epoch. A null pin, a stored
    ETA more than 30 seconds overdue, or no non-missed bus within 180 seconds
    returns (None, None). The bus list is not changed.
    """
    if isinstance(pinned_eta_epoch, bool) or not isinstance(pinned_eta_epoch, (int, float)):
        return None, None
    if not math.isfinite(pinned_eta_epoch):
        return None, None
    moment = _as_sgt(now)
    if moment.timestamp() - float(pinned_eta_epoch) > MISSED_AFTER_S:
        return None, None
    best = None
    best_diff = None
    for position in BUS_POSITIONS:
        for bus in buses:
            if bus.get("position") != position or bus.get("is_missed"):
                continue
            eta = _parse_eta(bus.get("arrival_time"), moment)
            if eta is None:
                continue
            if (eta - moment).total_seconds() < -MISSED_AFTER_S:
                continue
            difference = abs(eta.timestamp() - float(pinned_eta_epoch))
            if best_diff is None or difference < best_diff:
                best = bus
                best_diff = difference
            break
    if best is None or best_diff is None or best_diff > CONTINUITY_WINDOW_S:
        return None, None
    matched = _parse_eta(best.get("arrival_time"), moment)
    if matched is None:
        return None, None
    return best, matched.timestamp()


def apply_active_target(
    payload: dict,
    target: dict | None,
    *,
    user_lat: float | None,
    user_lon: float | None,
    cache,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> None:
    """Point leave-by and leave-now at an already-scored bus.

    Step 6 is_primary on the raw list stays as scored. When target is None,
    those clocks are recalculated from that Step 6 primary.
    """
    buses = payload.get("buses") or []
    for bus in buses:
        bus.pop("is_active_target", None)
    focused = buses
    if target is not None:
        target["is_active_target"] = True
        focused = []
        for bus in buses:
            item = dict(bus)
            item["is_primary"] = bus is target
            focused.append(item)
    stop_code = payload.get("stop_code") or ""
    service_no = payload.get("service_no") or ""
    leave_by = leave_by_for_buses(
        focused,
        stop_code=stop_code,
        user_lat=user_lat,
        user_lon=user_lon,
        cache=cache,
        now=now,
        walk_speed_m_s=walk_speed_m_s,
    )
    payload["leave_by"] = leave_by
    payload["notification_time"] = notification_time_iso(leave_by)
    stop_name = _stop_name(cache, stop_code) if cache is not None else ""
    payload["leave_now"] = leave_now_notice(
        focused,
        service_no=service_no,
        stop_code=stop_code,
        stop_name=stop_name,
        leave_by_iso=leave_by,
        notification_time=payload["notification_time"],
        arrival_status=payload.get("status") or "ok",
    )


def log_scored_poll(
    *,
    cache,
    current: dict,
    bus: dict | None,
    user_lat: float | None,
    user_lon: float | None,
    accuracy_m: float | None,
    now: datetime,
    reroute_fired: bool,
    reroute_reason: str,
    destination_stop_code: str | None = None,
    db_path=None,
) -> bool:
    """Insert one observations row for a poll that has a valid score."""
    if not _valid_score(bus):
        return False
    walk = None
    direction = None
    if (
        cache is not None
        and isinstance(user_lat, (int, float))
        and not isinstance(user_lat, bool)
        and isinstance(user_lon, (int, float))
        and not isinstance(user_lon, bool)
        and math.isfinite(user_lat)
        and math.isfinite(user_lon)
    ):
        walk, direction = _observation_place(
            cache,
            current,
            user_lat,
            user_lon,
            destination_stop_code or "",
        )
    holder = _with_log(
        {},
        current,
        bus,
        user_lat,
        user_lon,
        accuracy_m,
        now,
        bool(reroute_fired),
        reroute_reason or "",
        walk,
        direction,
    )
    row = holder.get("log")
    if not isinstance(row, dict):
        return False
    record_observation(row, db_path)
    return True


def closest_alternate_stops(
    cache,
    user_lat: float,
    user_lon: float,
    current_stop_code: str,
    destination_stop_code: str,
) -> list[dict]:
    """Up to two closest boarding stops within 400 m that reach the destination.

    The distance test runs first: the reachability check is the expensive part, and it
    only matters for the few stops inside the radius. The result is the same stops in
    the same order as testing every stop.
    """
    near = []
    for stop in cache.stops:
        code = stop.get("BusStopCode")
        if not isinstance(code, str) or code == current_stop_code:
            continue
        distance = haversine_m(user_lat, user_lon, stop["Latitude"], stop["Longitude"])
        if distance > BOARDING_RADIUS_M:
            continue
        near.append((distance, code, stop))
    near.sort(key=lambda item: (item[0], item[1]))
    found = []
    for distance, code, stop in near:
        if _reaching_services(cache, code, destination_stop_code):
            found.append(stop)
            if len(found) == ALTERNATE_STOP_LIMIT:
                break
    return found


def _decide(
    *,
    cache,
    current: dict,
    user_lat: float,
    user_lon: float,
    accuracy_m: float | None,
    location_timestamp: float | None,
    destination_stop_code: str,
    place_lat: float,
    place_lon: float,
    arrive_by: datetime | None,
    last_reroute_at: datetime | None,
    now: datetime,
    loader,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    held = _hold()
    if current.get("status") != "ok":
        return held
    primary = _primary(current.get("buses") or [])
    if _uncertain(accuracy_m, location_timestamp, now):
        return _logged(
            held, cache, current, primary, user_lat, user_lon, accuracy_m, now,
            False, "", destination_stop_code,
        )
    chance = None if primary is None else primary.get("probability")
    if not isinstance(chance, dict):
        return held
    current_high = chance.get("range_high")
    current_point = chance.get("point")
    if isinstance(current_high, bool) or not isinstance(current_high, int):
        return held
    if isinstance(current_point, bool) or not isinstance(current_point, int):
        return held
    if current_high >= RANGE_HIGH_BELOW:
        return _logged(
            held, cache, current, primary, user_lat, user_lon, accuracy_m, now,
            False, "", destination_stop_code,
        )
    margin = _required_margin(now, last_reroute_at)
    if margin is None:
        return _logged(
            held, cache, current, primary, user_lat, user_lon, accuracy_m, now,
            False, "", destination_stop_code,
        )
    candidates = _candidates(
        cache=cache,
        current=current,
        primary=primary,
        user_lat=user_lat,
        user_lon=user_lon,
        destination_stop_code=destination_stop_code,
        place_lat=place_lat,
        place_lon=place_lon,
        arrive_by=arrive_by,
        now=now,
        loader=loader,
        walk_speed_m_s=walk_speed_m_s,
    )
    rows = build_rows(cache, candidates, user_lat, user_lon, current, walk_speed_m_s)
    # The improvement rule decides whether a proposal exists; the recommender chooses among those that pass it.
    passing = {
        _option_id(candidate)
        for candidate in candidates
        if candidate["range_low"] >= current_high + margin
    }
    recommendation = recommend_option([row for row in rows if row["id"] in passing], arrive_by)
    if recommendation is None:
        text = None
        if isinstance(current_point, int) and not isinstance(current_point, bool):
            if margin == NORMAL_MARGIN:
                text = NO_BETTER_OPTION.format(point=current_point)
            elif margin == COOLDOWN_MARGIN:
                text = POST_REROUTE_NO_BETTER.format(point=current_point)
        decision = _hold()
        decision["no_better_option"] = text
        decision["options"] = rank_options(rows, None, arrive_by, "better")
        return _logged(
            decision, cache, current, primary, user_lat, user_lon, accuracy_m, now,
            False, "", destination_stop_code,
        )
    winner = next(candidate for candidate in candidates if _option_id(candidate) == recommendation["id"])
    copy = _switch_copy(
        old_service=current.get("service_no") or "",
        old_stop=current.get("stop_code") or "",
        old_high=current_high,
        old_point=current_point,
        winner=winner,
    )
    stop = _stop_payload(cache, winner["stop_code"], user_lat, user_lon, walk_speed_m_s)
    if winner["service_no"] not in stop["services"]:
        stop["services"].append(winner["service_no"])
    decision = {
        "switched": True,
        "no_better_option": None,
        "reroute": {
            "service_no": winner["service_no"],
            "stop": stop,
            "arrival_time": winner["eta"].replace(microsecond=0).isoformat(),
            "eta_epoch": winner["eta"].timestamp(),
            "destination_stop_code": destination_stop_code,
            **copy,
        },
        "winner_score": {
            "point": winner["point"],
            "range_low": winner["range_low"],
            "range_high": winner["range_high"],
            "slack_seconds": winner.get("slack_seconds"),
            "monitored": winner.get("monitored") if type(winner.get("monitored")) is bool else None,
            "data_quality": winner.get("data_quality"),
            "walk_minutes": stop.get("walk_minutes"),
            "estimated_arrival": _iso_or_none(winner.get("estimated_arrival")),
            "leave_by": _leave_by_iso(winner["eta"], stop.get("distance_m"), walk_speed_m_s),
        },
        "alternatives": _alternatives(cache, candidates, winner, arrive_by is not None, user_lat, user_lon),
        "options": rank_options(rows, recommendation, arrive_by, "better"),
    }
    return _logged(
        decision,
        cache,
        current,
        primary,
        user_lat,
        user_lon,
        accuracy_m,
        now,
        True,
        copy["reroute_reason"],
        destination_stop_code,
    )


def _candidates(
    *,
    cache,
    current: dict,
    primary: dict,
    user_lat: float,
    user_lon: float,
    destination_stop_code: str,
    place_lat: float,
    place_lon: float,
    arrive_by: datetime | None,
    now: datetime,
    loader,
    include_primary: bool = False,
    missed_eta_epoch: float | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> list[dict]:
    found = []
    current_stop = current.get("stop_code") or ""
    current_service = current.get("service_no") or ""
    for bus in current.get("buses") or []:
        if include_primary:
            # On-demand search: every listed bus of this service, except the one the user missed.
            if missed_eta_epoch is not None:
                listed = _parse_eta(bus.get("arrival_time"), now)
                if listed is not None and abs(listed.timestamp() - missed_eta_epoch) <= CONTINUITY_WINDOW_S:
                    continue
        else:
            if bus.get("position") not in ("NextBus2", "NextBus3"):
                continue
            if bus is primary or bus.get("is_primary"):
                continue
        candidate = _candidate_from_bus(
            cache,
            bus,
            stop_code=current_stop,
            service_no=current_service,
            user_lat=user_lat,
            user_lon=user_lon,
            destination_stop_code=destination_stop_code,
            place_lat=place_lat,
            place_lon=place_lon,
            arrive_by=arrive_by,
            now=now,
            walk_speed_m_s=walk_speed_m_s,
        )
        if candidate is not None:
            found.append(candidate)
    if loader is None:
        return found
    # One lookup per stop: the other services at the current stop, then up to two alternate stops.
    plan = []
    others = [
        service
        for service in _reaching_services(cache, current_stop, destination_stop_code)
        if service != current_service
    ]
    if others:
        plan.append((current_stop, others))
    for stop in closest_alternate_stops(
        cache, user_lat, user_lon, current_stop, destination_stop_code
    ):
        code = stop["BusStopCode"]
        plan.append((code, _reaching_services(cache, code, destination_stop_code)))
    prefetch = getattr(loader, "prefetch", None)
    if callable(prefetch) and plan:
        prefetch(plan)
    for code, services in plan:
        for service in services:
            try:
                loaded = loader(code, service)
            except ArrivalUnavailable:
                continue
            if not isinstance(loaded, dict) or loaded.get("status") != "ok":
                continue
            for bus in loaded.get("buses") or []:
                candidate = _candidate_from_bus(
                    cache,
                    bus,
                    stop_code=code,
                    service_no=service,
                    user_lat=user_lat,
                    user_lon=user_lon,
                    destination_stop_code=destination_stop_code,
                    place_lat=place_lat,
                    place_lon=place_lon,
                    arrive_by=arrive_by,
                    now=now,
                    walk_speed_m_s=walk_speed_m_s,
                )
                if candidate is not None:
                    found.append(candidate)
    return found


def _candidate_from_bus(
    cache,
    bus: dict,
    *,
    stop_code: str,
    service_no: str,
    user_lat: float,
    user_lon: float,
    destination_stop_code: str,
    place_lat: float,
    place_lon: float,
    arrive_by: datetime | None,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict | None:
    if bus.get("is_missed"):
        return None
    chance = bus.get("probability")
    if not isinstance(chance, dict):
        return None
    point = chance.get("point")
    low = chance.get("range_low")
    high = chance.get("range_high")
    if isinstance(low, bool) or not isinstance(low, int):
        return None
    if isinstance(high, bool) or not isinstance(high, int):
        return None
    if isinstance(point, bool) or not isinstance(point, int):
        return None
    links = _service_links(
        cache, stop_code, service_no, destination_stop_code, user_lat, user_lon
    )
    if not links:
        return None
    eta = _parse_eta(bus.get("arrival_time"), now)
    if eta is None:
        return None
    slack = chance.get("slack_seconds")
    quality = chance.get("data_quality")
    monitored = bus.get("monitored")
    # The same Step 9 terms and the same estimate function as the live tile and the overview.
    # A late option stays: the recommender and the row label handle "after the target".
    terms = _option_terms(cache, links, destination_stop_code, place_lat, place_lon, now, walk_speed_m_s)
    window = bus_arrival_window(
        now, terms, eta, live=monitored is True, arrive_by=arrive_by, walk_speed_m_s=walk_speed_m_s
    )
    estimated = None if window is None else window["estimated_arrival"]
    return {
        "service_no": service_no,
        "stop_code": stop_code,
        "stop_name": _stop_name(cache, stop_code),
        "point": point,
        "range_low": low,
        "range_high": high,
        "eta": eta,
        "estimated_arrival": estimated,
        "slack_seconds": slack if type(slack) is int else None,
        "monitored": monitored if type(monitored) is bool else None,
        "data_quality": quality if isinstance(quality, str) else None,
    }


def _iso_or_none(value) -> str | None:
    return value.replace(microsecond=0).isoformat() if isinstance(value, datetime) else None


def _leave_by_iso(eta: datetime, distance_m, walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> str | None:
    """The existing leave-by rule for the proposed bus (display only)."""
    if isinstance(distance_m, bool) or not isinstance(distance_m, (int, float)):
        return None
    return leave_by_time(eta, float(distance_m), walk_speed_m_s).replace(microsecond=0).isoformat()


def _alternatives(cache, candidates, winner, arrive_by_set, user_lat, user_lon, limit=3) -> list[dict]:
    """Other scored candidates, in the winner's order. Display only: they do not change the decision."""
    def key(candidate: dict):
        if arrive_by_set and candidate["estimated_arrival"] is not None:
            return (-candidate["range_low"], candidate["estimated_arrival"], candidate["eta"])
        return (-candidate["range_low"], candidate["eta"])

    rows = []
    for candidate in sorted((item for item in candidates if item is not winner), key=key)[:limit]:
        stop = cache.stop_by_code(candidate["stop_code"]) if cache is not None else None
        distance = None
        if isinstance(stop, dict):
            distance = int(haversine_m(user_lat, user_lon, stop["Latitude"], stop["Longitude"]) + 0.5)
        rows.append({
            "service_no": candidate["service_no"],
            "stop_code": candidate["stop_code"],
            "stop_name": candidate["stop_name"],
            "point": candidate["point"],
            "range_low": candidate["range_low"],
            "range_high": candidate["range_high"],
            "arrival_time": _iso_or_none(candidate["eta"]),
            "distance_m": distance,
            "monitored": candidate.get("monitored"),
        })
    return rows


FASTEST_RANGE_HIGH_MIN = RANGE_HIGH_BELOW


def _option_id(candidate: dict) -> str:
    return f"{candidate['service_no']}|{candidate['stop_code']}|{int(candidate['eta'].timestamp())}"


def rank_options(rows: list[dict], recommendation: dict | None, arrive_by: datetime | None, entry: str) -> dict:
    """Name the pills and order the list. Pure; there is no blended score.

    `recommendation` is the recommend_option result ({"id", "reason"}) or None. The recommended
    option is the card and is not in the list. The list is ordered by point probability (high
    first), then the earlier estimated arrival, then the service number. `entry` is "better"
    (the automatic entry) or "recommended" (the "No, I missed it" entry).
    """
    holders = pills(rows)
    deadline = None if arrive_by is None else _as_sgt(arrive_by)
    for row in rows:
        row["badges"] = [
            key for key in ("highest_chance", "fastest") if holders.get(key) == row["id"]
        ]
        row["unlikely"] = row["range_high"] < MIN_REAL_CHANCE_RANGE_HIGH
        estimate = _parse_eta(row["estimated_arrival"], deadline or datetime.now(SGT))
        row["after_target"] = bool(deadline is not None and estimate is not None and estimate > deadline)
        row["recommended"] = False
    chosen = next((row for row in rows if recommendation and row["id"] == recommendation["id"]), None)
    recommended = None
    if chosen is not None:
        chosen["recommended"] = True
        code = recommendation["reason"]
        chosen["reason_code"] = code
        chosen["reason_text"] = reason_text(code, chosen["service_no"])
        chosen["explanation"] = {
            "reason_code": code,
            "action": "switch_route",
            "text": chosen["reason_text"],
        }
        recommended = chosen

    def row_key(row: dict):
        return (-row["point"], arrival_key(row), natural_key(row["service_no"]))

    listed = sorted((row for row in rows if row is not recommended), key=row_key)
    return {
        "mode": "winner" if recommended is not None else "none",
        "entry": entry,
        "recommended_id": recommended["id"] if recommended else None,
        "recommended": recommended,
        "rows": listed,
    }


def _option_row(
    cache, candidate: dict, user_lat, user_lon, current_stop: str, current_service: str,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    stop = _stop_payload(cache, candidate["stop_code"], user_lat, user_lon, walk_speed_m_s)
    if candidate["service_no"] not in stop["services"]:
        stop["services"].append(candidate["service_no"])
    service = candidate["service_no"]
    name = candidate["stop_name"]
    code = candidate["stop_code"]
    line = f"Catch probability: about {candidate['point']}%."
    notification_line = (
        f"Catch probability: {candidate['point']}% "
        f"(range {candidate['range_low']}\u2013{candidate['range_high']}%)."
    )
    at_current = code == current_stop
    return {
        "id": _option_id(candidate),
        "service_no": service,
        "stop_code": code,
        "stop_name": name,
        "point": candidate["point"],
        "band": ring_band(candidate["point"]),
        "range_low": candidate["range_low"],
        "range_high": candidate["range_high"],
        "arrival_time": _iso_or_none(candidate["eta"]),
        "estimated_arrival": _iso_or_none(candidate.get("estimated_arrival")),
        "distance_m": stop.get("distance_m"),
        "walk_m": 0 if at_current else stop.get("distance_m"),
        "at_current_stop": at_current,
        "next_of_same_service": at_current and service == current_service,
        "monitored": candidate.get("monitored"),
        "leave_by": _leave_by_iso(candidate["eta"], stop.get("distance_m"), walk_speed_m_s),
        "reroute": {
            "service_no": service,
            "stop": stop,
            "arrival_time": candidate["eta"].replace(microsecond=0).isoformat(),
            "eta_epoch": candidate["eta"].timestamp(),
            "title": "Route Updated",
            "message": f"Switched to Bus {service} at {name} ({code}).",
            "probability_line": line,
            "notification_title": f"Route Updated \u2014 Bus {service}",
            "notification_body": f"Switched to Bus {service} at {name}. {notification_line}",
            "reroute_reason": f"Switched from Bus {current_service} ({current_stop}) to Bus {service} ({code})",
        },
    }


def build_rows(cache, candidates, user_lat, user_lon, current, walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> list[dict]:
    """One row per (service, stop, arrival). Uses no data the search did not already fetch."""
    current_stop = current.get("stop_code") or ""
    current_service = current.get("service_no") or ""
    rows = []
    seen = set()
    for candidate in candidates:
        key = _option_id(candidate)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            _option_row(cache, candidate, user_lat, user_lon, current_stop, current_service, walk_speed_m_s)
        )
    return rows


def plan_options(
    *,
    cache,
    current: dict,
    user_lat: float,
    user_lon: float,
    destination_stop_code: str,
    place_lat: float,
    place_lon: float,
    arrive_by: datetime | None,
    now: datetime,
    loader,
    missed_eta_epoch: float | None = None,
    entry: str = "recommended",
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    """On-demand search (missed or unlikely entry). It ignores the unlikely-trigger and the improvement rule."""
    moment = _as_sgt(now)
    if current.get("status") != "ok":
        return {"mode": "none", "entry": entry, "recommended_id": None, "recommended": None, "rows": []}
    candidates = _candidates(
        cache=cache,
        current=current,
        primary=None,
        user_lat=user_lat,
        user_lon=user_lon,
        destination_stop_code=destination_stop_code,
        place_lat=place_lat,
        place_lon=place_lon,
        arrive_by=arrive_by,
        now=moment,
        loader=loader,
        include_primary=True,
        missed_eta_epoch=missed_eta_epoch,
        walk_speed_m_s=walk_speed_m_s,
    )
    rows = build_rows(cache, candidates, user_lat, user_lon, current, walk_speed_m_s)
    return rank_options(rows, recommend_option(rows, arrive_by), arrive_by, entry)


def _required_margin(now: datetime, last_reroute_at: datetime | None) -> int | None:
    if last_reroute_at is None:
        return NORMAL_MARGIN
    elapsed = (now - _as_sgt(last_reroute_at)).total_seconds()
    if elapsed < COOLDOWN_S:
        return None
    return COOLDOWN_MARGIN


def _service_links(cache, origin_code, service, dest_code, user_lat, user_lon):
    stop = cache.stop_by_code(origin_code)
    if stop is None:
        return []
    user_m = haversine_m(user_lat, user_lon, stop["Latitude"], stop["Longitude"])
    links = _links(_hops(cache.routes), [{"stop_code": origin_code, "user_m": user_m}], dest_code)
    return [link for link in links if link["service"] == service]


def _reaching_services(cache, origin_code: str, dest_code: str) -> list[str]:
    links = _links(
        _hops(cache.routes),
        [{"stop_code": origin_code, "user_m": 0.0}],
        dest_code,
    )
    found = []
    for link in links:
        if link["service"] not in found:
            found.append(link["service"])
    return found


def _option_terms(
    cache, links, dest_code, place_lat, place_lon, now, walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS
) -> dict | None:
    """The four Step 9 terms of the quickest usable link, as the overview chooses it."""
    usable = [link for link in links if link.get("route_km") is not None]
    if not usable:
        return None
    dest = cache.stop_by_code(dest_code)
    if dest is None:
        return None
    place_m = haversine_m(place_lat, place_lon, dest["Latitude"], dest["Longitude"])

    def duration(link: dict) -> float:
        return _total_minutes(cache, link, place_m, now, walk_speed_m_s)

    return _arrival_terms(cache, min(usable, key=duration), place_m, now, walk_speed_m_s)


def _stop_payload(
    cache, stop_code: str, user_lat: float, user_lon: float, walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS
) -> dict:
    stop = cache.stop_by_code(stop_code) or {}
    lat = stop.get("Latitude")
    lon = stop.get("Longitude")
    distance = 0
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        distance = int(haversine_m(user_lat, user_lon, float(lat), float(lon)) + 0.5)
    services = []
    for route in cache.routes:
        if route.get("BusStopCode") != stop_code:
            continue
        service = route.get("ServiceNo")
        if isinstance(service, str) and service.strip() and service.strip() not in services:
            services.append(service.strip())
    road = stop.get("RoadName")
    return {
        "stop_code": stop_code,
        "description": stop.get("Description") or "",
        "road_name": road.strip() if isinstance(road, str) else None,
        "latitude": lat,
        "longitude": lon,
        "distance_m": distance,
        "walk_minutes": walk_minutes(distance, walk_speed_m_s),
        "services": services,
    }


def _switch_copy(*, old_service, old_stop, old_high, old_point, winner) -> dict:
    margin = winner["range_low"] - old_high
    service = winner["service_no"]
    name = winner["stop_name"]
    code = winner["stop_code"]
    low = winner["range_low"]
    high = winner["range_high"]
    point = winner["point"]
    return {
        "title": "Route Updated",
        "message": f"Switched to Bus {service} at {name} ({code}).",
        "probability_line": (
            f"Catch probability: about {point}% vs previous about {old_point}%."
        ),
        "notification_title": f"Route Updated \u2014 Bus {service}",
        "notification_body": (
            f"Switched to Bus {service} at {name}. "
            f"Catch probability: {point}% (range {low}\u2013{high}%)."
        ),
        "reroute_reason": (
            f"Switched from Bus {old_service} ({old_stop}) [high: {old_high}%] "
            f"to Bus {service} ({code}) [low: {low}%]: +{margin}% margin"
        ),
    }


def _with_log(
    decision, current, primary, user_lat, user_lon, accuracy, now, fired, reason,
    walk_metres, direction,
):
    chance = primary.get("probability") if isinstance(primary, dict) else None
    if not isinstance(chance, dict):
        return decision
    monitored = primary.get("monitored") if isinstance(primary, dict) else None
    decision["log"] = {
        "timestamp": now.replace(microsecond=0).isoformat(),
        "stop_code": current.get("stop_code"),
        "service": current.get("service_no"),
        "direction": direction,
        "eta": primary.get("arrival_time") if isinstance(primary, dict) else None,
        "monitored": 1 if monitored else 0 if monitored is not None else None,
        "bus_lat": primary.get("latitude") if isinstance(primary, dict) else None,
        "bus_lon": primary.get("longitude") if isinstance(primary, dict) else None,
        "user_lat": user_lat,
        "user_lon": user_lon,
        "gps_accuracy": accuracy,
        "walk_metres": walk_metres,
        "slack_seconds": chance.get("slack_seconds"),
        "p": chance.get("point"),
        "p_low": chance.get("range_low"),
        "p_high": chance.get("range_high"),
        "data_quality": chance.get("data_quality"),
        "reroute_fired": fired,
        "reroute_reason": reason,
    }
    return decision


def _logged(
    decision, cache, current, primary, user_lat, user_lon, accuracy, now, fired, reason,
    destination_stop_code,
):
    if not isinstance(primary, dict) or not isinstance(primary.get("probability"), dict):
        return decision
    walk, direction = _observation_place(
        cache, current, user_lat, user_lon, destination_stop_code
    )
    return _with_log(
        decision,
        current,
        primary,
        user_lat,
        user_lon,
        accuracy,
        now,
        fired,
        reason,
        walk,
        direction,
    )


def _observation_place(cache, current, user_lat, user_lon, destination_stop_code):
    stop = cache.stop_by_code(current.get("stop_code") or "")
    walk = None
    if isinstance(stop, dict):
        lat = stop.get("Latitude")
        lon = stop.get("Longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            walk = round(haversine_m(user_lat, user_lon, float(lat), float(lon)))
    links = _service_links(
        cache,
        current.get("stop_code") or "",
        current.get("service_no") or "",
        destination_stop_code,
        user_lat,
        user_lon,
    )
    direction = links[0]["direction"] if links else None
    return walk, direction


def _uncertain(accuracy_m, location_timestamp, now) -> bool:
    age = None
    if location_timestamp is not None:
        age = location_age_seconds(location_timestamp, now)
    accuracy = 0.0 if accuracy_m is None else float(accuracy_m)
    return is_location_uncertain(accuracy, age)


def _valid_score(bus: dict | None) -> bool:
    chance = bus.get("probability") if isinstance(bus, dict) else None
    if not isinstance(chance, dict):
        return False
    for key in ("point", "range_low", "range_high"):
        value = chance.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return False
    return True


def _primary(buses: list[dict]) -> dict | None:
    for bus in buses:
        if bus.get("is_primary") and not bus.get("is_missed"):
            return bus
    return None


def _hold() -> dict:
    return {"switched": False, "no_better_option": None, "reroute": None}


def _stop_name(cache, stop_code: str) -> str:
    stop = cache.stop_by_code(stop_code)
    if not isinstance(stop, dict):
        return ""
    name = stop.get("Description")
    return name.strip() if isinstance(name, str) else ""


def _parse_eta(value, now: datetime) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SGT)
    return parsed.astimezone(SGT)


def _as_sgt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SGT)
    return value.astimezone(SGT)

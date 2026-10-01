"""Direct and one-transfer bus routes from the cached route graph.

Uses cached BusRoutes, BusStops, and BusServices only.
"""

import math
from datetime import datetime, timedelta, timezone

from catch_heuristic import headway_seconds
from destination_stops import (
    BUS_SPEED_KM_H,
    WALK_SPEED_M_S,
    _kilometres,
    _route_km,
    _service_record,
)
from lta_static import StopAndRouteCache
from nearby import haversine_m

SGT = timezone(timedelta(hours=8))
TRANSFER_PENALTY_MINUTES = 10
JOURNEY_BUDGET_MINUTES = 90
COLOCATED_TRANSFER_M = 50
FASTEST_ROUTE = "Fastest Route"
FEWEST_TRANSFERS = "Fewest Transfers"
ALTERNATIVE_ROUTE = "Alternative Route"
NO_FEASIBLE_ROUTE = "no_feasible_route"
NO_FEASIBLE_MESSAGE = "No direct or 1-transfer bus connection available for this trip."


def reroute_enabled(route_type: str | None, leg_index: int | None) -> bool:
    """The active leg keeps the existing Step 11 check. The arguments stay accepted."""
    del route_type, leg_index
    return True


def plan_route(
    cache: StopAndRouteCache,
    boarding_stop_code: str,
    destination_stop_code: str,
    user_lat: float,
    user_lon: float,
    dest_lat: float,
    dest_lon: float,
    now: datetime | None = None,
) -> dict:
    """Rank a direct or one-transfer route from the selected boarding stop."""
    origin = boarding_stop_code.strip()
    destination = destination_stop_code.strip()
    moment = datetime.now(SGT) if now is None else now
    if not origin or not destination or origin == destination:
        return _no_feasible()
    coordinates = _coordinates(cache)
    sequences = _sequences(cache.routes, coordinates)
    if not sequences:
        return _no_feasible()
    candidates = _direct_candidates(sequences, origin, destination)
    candidates.extend(_transfer_candidates(sequences, origin, destination, coordinates))
    if not candidates:
        return _no_feasible()
    walk_origin = _walk_minutes(cache, origin, user_lat, user_lon)
    walk_place = _walk_minutes(cache, destination, dest_lat, dest_lon)
    rankable = []
    for candidate in candidates:
        _attach_duration(cache, candidate, walk_origin, walk_place, moment)
        minutes = candidate["generalized_time_minutes"]
        if minutes is None or minutes > JOURNEY_BUDGET_MINUTES:
            continue
        rankable.append(candidate)
    distinct = _distinct(rankable)
    if not distinct:
        return _no_feasible()
    options = _label_options(distinct)
    for option in options:
        for leg in option["legs"]:
            leg["boarding_stop_name"] = _stop_name(cache, leg["boarding_stop_code"])
            leg["alighting_stop_name"] = _stop_name(cache, leg["alighting_stop_code"])
        if option["transfer_stop_code"]:
            option["transfer_stop_name"] = _stop_name(cache, option["transfer_stop_code"])
    return _catalog(options)


def suggest_alternate_boarding(
    cache: StopAndRouteCache,
    origin: str,
    destination: str,
    user_lat: float,
    user_lon: float,
    dest_lat: float,
    dest_lon: float,
    alternate_codes: list[str],
    now: datetime | None = None,
) -> dict:
    """If the chosen origin has no route, rank other static nearby origins."""
    chosen = plan_route(
        cache, origin, destination, user_lat, user_lon, dest_lat, dest_lon, now=now
    )
    others = []
    for code in alternate_codes:
        text = code.strip()
        if text and text != origin and text not in others:
            others.append(text)
    if chosen["route_status"] == "ok" or not others:
        return chosen
    ranked = []
    for code in others:
        planned = plan_route(
            cache, code, destination, user_lat, user_lon, dest_lat, dest_lon, now=now
        )
        options = planned.get("options") or []
        if planned.get("route_status") != "ok" or not options:
            continue
        fastest = options[0]
        distance = _user_distance_m(cache, code, user_lat, user_lon)
        ranked.append((
            fastest["generalized_time_minutes"],
            fastest["transfers"],
            distance if distance is not None else 10**9,
            code,
            fastest,
            distance,
        ))
    if not ranked:
        return chosen
    ranked.sort()
    _time, _transfers, _sort_distance, code, fastest, distance = ranked[0]
    return {
        "route_status": "alternate_boarding",
        "message": "A route is available from a nearby stop.",
        "route_type": None,
        "legs": [],
        "options": [],
        "alternate_stop": {
            "stop_code": code,
            "description": _stop_name(cache, code),
            "distance_m": None if distance is None else int(distance + 0.5),
            "services": [leg["service_no"] for leg in fastest["legs"]],
            "route_type": fastest["route_type"],
            "generalized_time_minutes": fastest["generalized_time_minutes"],
            "transfer_stop_name": fastest.get("transfer_stop_name"),
        },
    }


def _user_distance_m(
    cache: StopAndRouteCache, stop_code: str, user_lat: float, user_lon: float
) -> float | None:
    point = _coordinates(cache).get(stop_code)
    if point is None:
        return None
    return haversine_m(user_lat, user_lon, point[0], point[1])


def projected_transfer_epoch(eta: datetime, ride_minutes: float) -> datetime:
    """When Leg 1 is expected to reach the transfer stop. Not a live arrival."""
    return eta + timedelta(minutes=float(ride_minutes))


def schedule_headway_minutes(
    cache: StopAndRouteCache,
    service_no: str,
    direction: int,
    stop_code: str,
    when: datetime,
) -> int:
    """Published headway at `when`, in whole minutes. Static frequency data only."""
    return round(
        _leg_headway(cache, service_no, direction, stop_code, when) / 60
    )


def _no_feasible() -> dict:
    body = _blank()
    body["route_status"] = NO_FEASIBLE_ROUTE
    body["message"] = NO_FEASIBLE_MESSAGE
    return body


def _catalog(options: list[dict]) -> dict:
    fastest = options[0]
    body = _winner(fastest)
    body["options"] = options
    body["option_count"] = len(options)
    return body


def _label_options(candidates: list[dict]) -> list[dict]:
    ordered = sorted(candidates, key=_sort_key)
    chosen = [ordered[0]]
    rest = ordered[1:]
    if rest:
        fewest = min(rest, key=_fewest_key)
        chosen.append(fewest)
        rest = [item for item in rest if item is not fewest]
    if rest:
        chosen.append(min(rest, key=_sort_key))
    labels = (FASTEST_ROUTE, FEWEST_TRANSFERS, ALTERNATIVE_ROUTE)
    labeled = []
    for label, candidate in zip(labels, chosen):
        labeled.append({**candidate, "label": label})
    return labeled


def _fewest_key(candidate: dict) -> tuple:
    return (
        candidate["transfers"],
        candidate["transfer_distance_m"],
        candidate["generalized_time_minutes"],
        tuple(leg["service_no"] for leg in candidate["legs"]),
        tuple(leg["direction"] for leg in candidate["legs"]),
    )


def _distinct(candidates: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for candidate in candidates:
        signature = tuple(
            (leg["service_no"], leg["direction"]) for leg in candidate["legs"]
        )
        current = best.get(signature)
        if current is None or _sort_key(candidate) < _sort_key(current):
            best[signature] = candidate
    return list(best.values())


def _blank() -> dict:
    return {
        "route_status": "ok",
        "message": "",
        "route_type": None,
        "legs": [],
        "active_leg_index": None,
        "active_leg": None,
        "transfer_stop_code": None,
        "generalized_time_minutes": None,
        "transfer_penalty_minutes": None,
        "arrive_by_state": None,
        "options": [],
        "option_count": 0,
    }


def _winner(candidate: dict) -> dict:
    legs = candidate["legs"]
    first = legs[0]
    return {
        "route_status": "ok",
        "message": "",
        "route_type": candidate["route_type"],
        "legs": legs,
        "active_leg_index": 1,
        "active_leg": {
            "leg_index": 1,
            "boarding_stop_code": first["boarding_stop_code"],
            "service_no": first["service_no"],
            "direction": first["direction"],
        },
        "transfer_stop_code": candidate["transfer_stop_code"],
        "transfer_distance_m": candidate["transfer_distance_m"],
        "generalized_time_minutes": candidate["generalized_time_minutes"],
        "transfer_penalty_minutes": candidate["transfer_penalty_minutes"],
        "arrive_by_state": "existing" if candidate["transfers"] == 0 else "na",
    }


def _sort_key(candidate: dict) -> tuple:
    """Leg 1 service, then Leg 2 service, then Leg 1 direction, then Leg 2 direction.

    A direct candidate has only the first service and the first direction.
    """
    services = tuple(leg["service_no"] for leg in candidate["legs"])
    directions = tuple(leg["direction"] for leg in candidate["legs"])
    return (
        candidate["generalized_time_minutes"],
        candidate["transfers"],
        candidate["total_route_km"],
        services,
        directions,
    )


def _sequences(routes: list[dict], coordinates: dict[str, tuple[float, float]]) -> dict[tuple[str, int], list[dict]]:
    grouped: dict[tuple[str, int], list[dict]] = {}
    for route in routes:
        service = route.get("ServiceNo")
        direction = route.get("Direction")
        sequence = route.get("StopSequence")
        code = route.get("BusStopCode")
        if (
            not isinstance(service, str)
            or not service.strip()
            or isinstance(direction, bool)
            or not isinstance(direction, int)
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or not isinstance(code, str)
            or not code.strip()
        ):
            continue
        point = coordinates.get(code.strip())
        grouped.setdefault((service.strip(), direction), []).append(
            {
                "code": code.strip(),
                "sequence": sequence,
                "distance_km": _kilometres(route.get("Distance")),
                "latitude": None if point is None else point[0],
                "longitude": None if point is None else point[1],
            }
        )
    for hops in grouped.values():
        hops.sort(key=lambda hop: (hop["sequence"], hop["code"]))
    return grouped


def _direct_candidates(
    sequences: dict[tuple[str, int], list[dict]],
    origin: str,
    destination: str,
) -> list[dict]:
    found = []
    for (service, direction), hops in sequences.items():
        for index, boarding in enumerate(hops):
            if boarding["code"] != origin:
                continue
            for alight_index in range(index + 1, len(hops)):
                alighting = hops[alight_index]
                if alighting["sequence"] <= boarding["sequence"]:
                    continue
                if alighting["code"] != destination:
                    continue
                found.append(
                    _candidate(
                        "direct",
                        [
                            _leg(service, direction, boarding, alighting, hops[index : alight_index + 1]),
                        ],
                        None,
                    )
                )
    return found


def _transfer_candidates(
    sequences: dict[tuple[str, int], list[dict]],
    origin: str,
    destination: str,
    coordinates: dict[str, tuple[float, float]],
) -> list[dict]:
    appearances: dict[str, list[tuple[tuple[str, int], int]]] = {}
    for key, hops in sequences.items():
        for index, hop in enumerate(hops):
            appearances.setdefault(hop["code"], []).append((key, index))
    buckets = _coordinate_buckets(coordinates)
    found = []
    for key_a, hops_a in sequences.items():
        service_a, direction_a = key_a
        for index, boarding in enumerate(hops_a):
            if boarding["code"] != origin:
                continue
            for transfer_index in range(index + 1, len(hops_a)):
                transfer = hops_a[transfer_index]
                if transfer["sequence"] <= boarding["sequence"]:
                    continue
                if transfer["code"] in (origin, destination):
                    continue
                for board_code in _colocated_codes(transfer["code"], coordinates, buckets):
                    if board_code in (origin, destination):
                        continue
                    for key_b, board_index in appearances.get(board_code, []):
                        if key_b == key_a:
                            continue
                        service_b, direction_b = key_b
                        hops_b = sequences[key_b]
                        board_b = hops_b[board_index]
                        for alight_index in range(board_index + 1, len(hops_b)):
                            alighting = hops_b[alight_index]
                            if alighting["sequence"] <= board_b["sequence"]:
                                continue
                            if alighting["code"] != destination:
                                continue
                            found.append(
                                _candidate(
                                    "one_transfer",
                                    [
                                        _leg(
                                            service_a,
                                            direction_a,
                                            boarding,
                                            transfer,
                                            hops_a[index : transfer_index + 1],
                                        ),
                                        _leg(
                                            service_b,
                                            direction_b,
                                            board_b,
                                            alighting,
                                            hops_b[board_index : alight_index + 1],
                                        ),
                                    ],
                                    transfer["code"],
                                )
                            )
    return found


def _coordinates(cache: StopAndRouteCache) -> dict[str, tuple[float, float]]:
    found = {}
    for stop in cache.stops:
        code = stop.get("BusStopCode")
        lat = stop.get("Latitude")
        lon = stop.get("Longitude")
        if not isinstance(code, str) or not code.strip():
            continue
        if isinstance(lat, bool) or not isinstance(lat, (int, float)):
            continue
        if isinstance(lon, bool) or not isinstance(lon, (int, float)):
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        found[code.strip()] = (float(lat), float(lon))
    return found


def _coordinate_buckets(coordinates: dict[str, tuple[float, float]]) -> dict[tuple[int, int], list[str]]:
    buckets: dict[tuple[int, int], list[str]] = {}
    for code, point in coordinates.items():
        buckets.setdefault(_bucket(point), []).append(code)
    return buckets


def _bucket(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] / 0.0005), round(point[1] / 0.0005))


def _colocated_codes(
    code: str,
    coordinates: dict[str, tuple[float, float]],
    buckets: dict[tuple[int, int], list[str]],
) -> list[str]:
    origin = coordinates.get(code)
    if origin is None:
        return [code]
    key = _bucket(origin)
    found = []
    for lat_step in (-1, 0, 1):
        for lon_step in (-1, 0, 1):
            for other in buckets.get((key[0] + lat_step, key[1] + lon_step), []):
                if other == code:
                    found.append(other)
                    continue
                other_point = coordinates[other]
                if haversine_m(origin[0], origin[1], other_point[0], other_point[1]) <= COLOCATED_TRANSFER_M:
                    found.append(other)
    return found


def _candidate(route_type: str, legs: list[dict], transfer_stop_code: str | None) -> dict:
    transfers = 0 if route_type == "direct" else 1
    kilometres = [leg["route_km"] for leg in legs]
    total = None if any(km is None for km in kilometres) else sum(kilometres)
    return {
        "route_type": route_type,
        "transfers": transfers,
        "transfer_stop_code": transfer_stop_code,
        "transfer_penalty_minutes": 0 if transfers == 0 else TRANSFER_PENALTY_MINUTES,
        "transfer_distance_m": 0.0 if transfers == 0 else _transfer_metres(legs),
        "transfer_stop_name": None,
        "legs": legs,
        "total_route_km": total,
        "generalized_time_minutes": None,
    }


def _leg(service: str, direction: int, boarding: dict, alighting: dict, between: list[dict]) -> dict:
    route_km = _route_km(boarding["distance_km"], alighting["distance_km"])
    return {
        "boarding_stop_code": boarding["code"],
        "service_no": service,
        "direction": direction,
        "alighting_stop_code": alighting["code"],
        "route_km": route_km,
        "ride_minutes": None if route_km is None else (route_km / BUS_SPEED_KM_H) * 60,
        "stops": [_stop_point(hop) for hop in between],
    }


def _stop_point(hop: dict) -> dict:
    return {
        "stop_code": hop["code"],
        "stop_sequence": hop["sequence"],
        "latitude": hop.get("latitude"),
        "longitude": hop.get("longitude"),
    }


def _transfer_metres(legs: list[dict]) -> float:
    if len(legs) < 2:
        return 0.0
    alighting = legs[0]["stops"][-1]
    boarding = legs[1]["stops"][0]
    if alighting["stop_code"] == boarding["stop_code"]:
        return 0.0
    lat_a = alighting.get("latitude")
    lon_a = alighting.get("longitude")
    lat_b = boarding.get("latitude")
    lon_b = boarding.get("longitude")
    if None in (lat_a, lon_a, lat_b, lon_b):
        return 0.0
    return haversine_m(lat_a, lon_a, lat_b, lon_b)


def _attach_duration(
    cache: StopAndRouteCache,
    candidate: dict,
    walk_origin: float | None,
    walk_place: float | None,
    now: datetime,
) -> None:
    rides = [leg["ride_minutes"] for leg in candidate["legs"]]
    if walk_origin is None or walk_place is None or any(ride is None for ride in rides):
        candidate["generalized_time_minutes"] = None
        return
    if candidate["total_route_km"] is None:
        candidate["generalized_time_minutes"] = None
        return
    first = candidate["legs"][0]
    headway = _leg_headway(
        cache,
        first["service_no"],
        first["direction"],
        first["boarding_stop_code"],
        now,
    )
    candidate["generalized_time_minutes"] = (
        walk_origin
        + (headway / 2) / 60
        + sum(rides)
        + walk_place
        + candidate["transfer_penalty_minutes"]
    )


def _leg_headway(
    cache: StopAndRouteCache,
    service: str,
    direction: int,
    boarding_stop_code: str,
    now: datetime,
) -> int:
    record = _service_record(cache.services, service, direction)
    origin_code = record.get("OriginCode") if record else None
    destination_code = record.get("DestinationCode") if record else None
    return headway_seconds(
        cache.services,
        cache.routes,
        service,
        boarding_stop_code,
        origin_code if isinstance(origin_code, str) else None,
        destination_code if isinstance(destination_code, str) else None,
        now,
    )


def _stop_name(cache: StopAndRouteCache, stop_code: str) -> str:
    stop = cache.stop_by_code(stop_code)
    if stop is None:
        return stop_code
    description = stop.get("Description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return stop_code


def _walk_minutes(
    cache: StopAndRouteCache,
    stop_code: str,
    lat: float,
    lon: float,
) -> float | None:
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
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    return haversine_m(lat, lon, float(stop_lat), float(stop_lon)) / WALK_SPEED_M_S / 60

"""Candidate destination stops around a selected place.

Uses the local stop, route, and service caches. It does not call LTA,
OneMap, or OpenAI, and it does not score a catch probability.
"""

import math
import re
from datetime import datetime, timedelta, timezone

from bus_traffic import bus_ride_minutes
from catch_heuristic import headway_seconds
from config import WALK_SPEED_DEFAULT_MPS
from lta_static import StopAndRouteCache
from nearby import BOARDING_RADIUS_M, haversine_m
from service_hours import boarding_times, service_runs_at
from walk_speed import walk_minutes

SGT = timezone(timedelta(hours=8))
DESTINATION_RADIUS_M = 600
STATION_FALLBACK_M = 1500  # no station within 600 m: the single nearest one within this distance is offered
STATION_MERGE_M = 200  # two station groups with one name this close are one place (Bukit Panjang MRT and LRT)
LINE_ORDER = ("NS", "EW", "CG", "NE", "CC", "DT", "TE", "BP", "SK", "PG", "SS")
WALK_SPEED_M_S = WALK_SPEED_DEFAULT_MPS
from config import BUS_SPEED_KM_H  # noqa: E402,F401  (defined once in config)


def list_destination_stops(
    cache: StopAndRouteCache,
    dest_lat: float,
    dest_lon: float,
    user_lat: float,
    user_lon: float,
    boarding_stop_code: str | None = None,
    service_no: str | None = None,
    now: datetime | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
    arrive_by: datetime | None = None,
    rail_table: dict | None = None,
) -> dict:
    """Stops within 600 m of the place, split into reachable and unreachable, and `candidates`: the same bus stops and the
    MRT and LRT stations in one list, nearest walk first (see station_cards).

    A service that does not run when the user would board it does not connect a stop (service_hours). The boarding
    time is now plus the walk, or works back from the arrive-by time. When the boarding stop and the service are both
    given the hours are still checked: a pinned service that is closed is not offered."""
    moment = now if now is not None else datetime.now(SGT)
    any_closed = False
    preferred = service_no.strip() if isinstance(service_no, str) and service_no.strip() else None
    origins = _origins(cache, user_lat, user_lon, boarding_stop_code)
    hops = _hops(cache.routes)
    reachable = []
    unreachable = []
    for stop in cache.stops:
        place_m = haversine_m(dest_lat, dest_lon, stop["Latitude"], stop["Longitude"])
        # A fraction of a millimetre keeps a true 600 m stop inside the
        # inclusive boundary when the haversine result is not exact.
        if place_m > DESTINATION_RADIUS_M + 1e-6:
            continue
        card = _card(stop, place_m, walk_speed_m_s)
        links = _links(hops, origins, card["stop_code"])
        if links:
            running = [
                link for link in links
                if _link_runs(cache, link, place_m, moment, arrive_by, walk_speed_m_s)
            ]
            if not running:
                any_closed = True
                card["no_service"] = True
            links = running
        if not links:
            card["is_reachable"] = False
            card["connecting_services"] = []
            card["arrival_terms"] = None
            card["rough_journey_minutes"] = None
            unreachable.append((place_m, card))
            continue
        services = _unique_services(link["service"] for link in links)
        estimate_origin = _estimate_origin(links, boarding_stop_code)
        chosen = _choose_link(cache, links, estimate_origin, preferred, place_m, moment, walk_speed_m_s)
        card["is_reachable"] = True
        card["connecting_services"] = services
        terms = None if chosen is None else _arrival_terms(cache, chosen, place_m, moment, walk_speed_m_s)
        card["arrival_terms"] = terms
        card["rough_journey_minutes"] = (
            None if terms is None else math.ceil(terms["total_minutes"])
        )
        reachable.append((place_m, card))
    reachable.sort(key=lambda item: (item[0], item[1]["stop_code"]))
    unreachable.sort(key=lambda item: (item[0], item[1]["stop_code"]))
    shown_buses = reachable + unreachable[:3]
    for _, card in shown_buses:
        card["kind"] = "bus"
    stations = station_cards(rail_table, dest_lat, dest_lon, walk_speed_m_s)
    candidates = sorted(shown_buses + stations, key=lambda item: (item[0], item[1]["kind"] != "bus", item[1]["stop_code"]))
    return {
        "status": "ok",
        "destination": {"lat": dest_lat, "lon": dest_lon},
        "reachable_stops": [card for _, card in reachable],
        "unreachable_stops": [card for _, card in unreachable[:3]],
        "candidates": [card for _, card in candidates],
        "no_service": bool(any_closed and not reachable),
    }


# ---- MRT and LRT stations ---------------------------------------------------------------------------------------


def _line_of(code: str) -> str:
    match = re.match(r"[A-Z]+", code)
    return match.group(0) if match else ""


def _code_order(code: str) -> tuple:
    line = _line_of(code)
    number = re.search(r"\d+", code)
    return (LINE_ORDER.index(line) if line in LINE_ORDER else len(LINE_ORDER), int(number.group(0)) if number else 0, code)


_station_memo: dict[int, tuple[dict, list[dict]]] = {}


def station_places(table: dict | None) -> list[dict]:
    """Stations of the rail timetable as places: one per physical station (the codes that share an interchange group,
    and one name within STATION_MERGE_M, are one place), each with its name, point, line codes and line names. Static data."""
    if not isinstance(table, dict):
        return []
    held = _station_memo.get(id(table))
    if held is not None and held[0] is table:
        return held[1]
    stations = table.get("stations") or {}
    lines = table.get("lines") or {}
    groups: dict[str, list[str]] = {}
    for code, station in stations.items():
        if not isinstance(station, dict) or not isinstance(station.get("latitude"), (int, float)) \
                or not isinstance(station.get("longitude"), (int, float)):
            continue
        groups.setdefault(station.get("interchange") or code, []).append(code)
    places: list[dict] = []
    for key, codes in groups.items():
        anchor = stations.get(key) or stations[min(codes, key=_code_order)]
        places.append({"codes": codes, "name": str(anchor.get("name") or key), "lat": float(anchor["latitude"]),
                       "lon": float(anchor["longitude"])})
    merged: list[dict] = []
    for place in sorted(places, key=lambda item: min(_code_order(code) for code in item["codes"])):
        twin = next((other for other in merged if other["name"].casefold() == place["name"].casefold()
                     and haversine_m(other["lat"], other["lon"], place["lat"], place["lon"]) <= STATION_MERGE_M), None)
        if twin is None:
            merged.append(place)
        else:
            twin["codes"] = twin["codes"] + place["codes"]
    result = []
    for place in merged:
        codes = sorted(set(place["codes"]), key=_code_order)
        found = []
        for code in codes:
            line = _line_of(code)
            if line and line in lines and line not in [item["code"] for item in found]:
                found.append({"code": line, "name": str(lines[line].get("name") or line), "mode": str(lines[line].get("mode") or "")})
        if not found:
            continue
        result.append({"codes": codes, "name": place["name"], "lat": place["lat"], "lon": place["lon"], "lines": found,
                       "mode": "MRT" if any(item["mode"] != "TRAM" for item in found) else "LRT"})
    _station_memo.clear()
    _station_memo[id(table)] = (table, result)
    return result


def station_cards(table: dict | None, dest_lat: float, dest_lon: float,
                  walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> list[tuple[float, dict]]:
    """(distance, card) of every station within 600 m of the place; when none is that close, the one nearest station
    within 1.5 km (its card says beyond_radius). A station card has the fields of a bus stop card, plus kind, mode, codes
    and lines. No reachability: a station never says "no direct bus"."""
    found = []
    for place in station_places(table):
        metres = haversine_m(dest_lat, dest_lon, place["lat"], place["lon"])
        found.append((metres, place))
    near = [item for item in found if item[0] <= DESTINATION_RADIUS_M + 1e-6]
    beyond = False
    if not near and found:
        nearest = min(found, key=lambda item: (item[0], item[1]["codes"][0]))
        if nearest[0] <= STATION_FALLBACK_M + 1e-6:
            near, beyond = [nearest], True
    cards = []
    for metres, place in near:
        distance_m = int(metres + 0.5)
        cards.append((metres, {
            "kind": "station", "stop_code": place["codes"][0], "stop_name": place["name"], "road_name": "",
            "lat": place["lat"], "lon": place["lon"], "distance_m": distance_m,
            "walk_minutes": walk_minutes(distance_m, walk_speed_m_s, "display"),
            "station_mode": place["mode"], "station_codes": list(place["codes"]), "lines": [dict(item) for item in place["lines"]],
            "beyond_radius": beyond, "is_reachable": None, "connecting_services": [], "arrival_terms": None,
            "rough_journey_minutes": None,
        }))
    return cards


def _link_runs(
    cache: StopAndRouteCache,
    link: dict,
    place_m: float,
    moment: datetime,
    arrive_by: datetime | None,
    walk_speed_m_s: float,
) -> bool:
    """Does this link's service run at the boarding stop when the user would board?"""
    if link["route_km"] is None:
        times = boarding_times(moment, walk_minutes(link["user_m"], walk_speed_m_s), 0.0, None, arrive_by)
    else:
        terms = _arrival_terms(cache, link, place_m, moment, walk_speed_m_s)
        times = boarding_times(
            moment, terms["board_walk_minutes"], terms["wait_minutes"],
            terms["total_minutes"] - terms["board_walk_minutes"], arrive_by,
        )
    return all(
        service_runs_at(cache, link["service"], link["origin_code"], board_at, link["direction"]) for board_at in times
    )


def _origins(
    cache: StopAndRouteCache,
    user_lat: float,
    user_lon: float,
    boarding_stop_code: str | None,
) -> list[dict]:
    if boarding_stop_code:
        stop = cache.stop_by_code(boarding_stop_code)
        if stop is None:
            return []
        return [_origin(stop, user_lat, user_lon)]
    found = []
    for stop in cache.stops:
        distance = haversine_m(user_lat, user_lon, stop["Latitude"], stop["Longitude"])
        if distance <= BOARDING_RADIUS_M:
            found.append(_origin(stop, user_lat, user_lon))
    return found


def _origin(stop: dict, user_lat: float, user_lon: float) -> dict:
    return {
        "stop_code": stop["BusStopCode"],
        "user_m": haversine_m(user_lat, user_lon, stop["Latitude"], stop["Longitude"]),
    }


def _hops(routes: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
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
        grouped.setdefault(code, []).append(
            {
                "service": service.strip(),
                "direction": direction,
                "sequence": sequence,
                "distance_km": _kilometres(route.get("Distance")),
            }
        )
    return grouped


def _links(hops: dict[str, list[dict]], origins: list[dict], dest_code: str) -> list[dict]:
    dest_hops = hops.get(dest_code, [])
    links = []
    for origin in origins:
        if origin["stop_code"] == dest_code:
            continue
        for boarding in hops.get(origin["stop_code"], []):
            for dest in dest_hops:
                if boarding["service"] != dest["service"] or boarding["direction"] != dest["direction"]:
                    continue
                if dest["sequence"] <= boarding["sequence"]:
                    continue
                route_km = _route_km(boarding["distance_km"], dest["distance_km"])
                links.append(
                    {
                        "service": boarding["service"],
                        "direction": boarding["direction"],
                        "origin_code": origin["stop_code"],
                        "user_m": origin["user_m"],
                        "route_km": route_km,
                    }
                )
    return links


def _route_km(boarding_km: float | None, dest_km: float | None) -> float | None:
    if boarding_km is None or dest_km is None:
        return None
    travelled = dest_km - boarding_km
    if travelled < 0:
        return None
    return travelled


def _estimate_origin(links: list[dict], boarding_stop_code: str | None) -> str:
    if boarding_stop_code:
        return boarding_stop_code
    closest = min(links, key=lambda link: (link["user_m"], link["origin_code"]))
    return closest["origin_code"]


def _choose_link(
    cache: StopAndRouteCache,
    links: list[dict],
    origin_code: str,
    preferred: str | None,
    place_m: float,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict | None:
    usable = [
        link
        for link in links
        if link["origin_code"] == origin_code and link["route_km"] is not None
    ]

    def duration(link: dict) -> tuple:
        return (_total_minutes(cache, link, place_m, now, walk_speed_m_s), link["service"])

    if preferred:
        preferred_links = [link for link in usable if link["service"] == preferred]
        if preferred_links:
            return min(preferred_links, key=duration)
    if not usable:
        return None
    return min(usable, key=duration)


def _arrival_terms(
    cache: StopAndRouteCache,
    link: dict,
    place_m: float,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    """The four Step 9 terms, unrounded. The total matches `_total_minutes`."""
    record = _service_record(cache.services, link["service"], link["direction"])
    origin_code = record.get("OriginCode") if record else None
    destination_code = record.get("DestinationCode") if record else None
    headway = headway_seconds(
        cache.services,
        cache.routes,
        link["service"],
        link["origin_code"],
        origin_code if isinstance(origin_code, str) else None,
        destination_code if isinstance(destination_code, str) else None,
        now,
    )
    board = walk_minutes(link["user_m"], walk_speed_m_s)
    wait = (headway / 2) / 60
    # the bus starts after the walk and the wait; its minutes carry the traffic factor of that time
    ride = bus_ride_minutes((link["route_km"] / BUS_SPEED_KM_H) * 60, now + timedelta(minutes=board + wait))
    end = walk_minutes(place_m, walk_speed_m_s)
    return {
        "board_walk_minutes": board,
        "wait_minutes": wait,
        "ride_minutes": ride,
        "end_walk_metres": place_m,
        "total_minutes": board + wait + ride + end,
    }


def _total_minutes(
    cache: StopAndRouteCache,
    link: dict,
    place_m: float,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> float:
    return _arrival_terms(cache, link, place_m, now, walk_speed_m_s)["total_minutes"]


def _service_record(services: list[dict], service_no: str, direction: int) -> dict | None:
    for record in services:
        if (
            str(record.get("ServiceNo", "")).strip() == service_no
            and record.get("Direction") == direction
        ):
            return record
    return None


def _card(stop: dict, place_m: float, walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> dict:
    distance_m = int(place_m + 0.5)
    road = stop.get("RoadName")
    return {
        "stop_code": stop["BusStopCode"],
        "stop_name": stop["Description"],
        "road_name": road.strip() if isinstance(road, str) else "",
        "lat": stop["Latitude"],
        "lon": stop["Longitude"],
        "distance_m": distance_m,
        "walk_minutes": walk_minutes(distance_m, walk_speed_m_s, "display"),
    }


def _unique_services(services) -> list[str]:
    found = []
    for service in services:
        if service not in found:
            found.append(service)
    found.sort(key=lambda service: (0, int(service)) if service.isdigit() else (1, service))
    return found


def _kilometres(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number

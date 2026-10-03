"""Candidate destination stops around a selected place.

Uses the local stop, route, and service caches. It does not call LTA,
OneMap, or OpenAI, and it does not score a catch probability.
"""

import math
from datetime import datetime, timedelta, timezone

from catch_heuristic import headway_seconds
from config import WALK_SPEED_DEFAULT_MPS
from lta_static import StopAndRouteCache
from nearby import BOARDING_RADIUS_M, haversine_m
from walk_speed import walk_minutes

SGT = timezone(timedelta(hours=8))
DESTINATION_RADIUS_M = 600
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
) -> dict:
    """Stops within 600 m of the place, split into reachable and unreachable."""
    moment = now if now is not None else datetime.now(SGT)
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
    return {
        "status": "ok",
        "destination": {"lat": dest_lat, "lon": dest_lon},
        "reachable_stops": [card for _, card in reachable],
        "unreachable_stops": [card for _, card in unreachable[:3]],
    }


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
    ride = (link["route_km"] / BUS_SPEED_KM_H) * 60
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

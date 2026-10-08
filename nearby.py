"""Boarding stops within 400 m of a point, using the local LTA cache.

Distance is straight-line haversine, not a walking route.
"""

import math
from datetime import datetime, timedelta, timezone

from config import WALK_SPEED_DEFAULT_MPS
from lta_static import StopAndRouteCache
from service_hours import service_runs_at
from walk_speed import walk_minutes as _walk_minutes

SGT = timezone(timedelta(hours=8))
EARTH_RADIUS_M = 6_371_000
BOARDING_RADIUS_M = 400
WALK_SPEED_M_S = WALK_SPEED_DEFAULT_MPS


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    arc = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * arc


def walk_minutes(distance_m: float, speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> int:
    """Nearest minute at the walking speed, at least 1. Half a minute rounds up (the "display" mode)."""
    return _walk_minutes(distance_m, speed_m_s, "display")


def nearby_boarding_stops(
    cache: StopAndRouteCache,
    latitude: float,
    longitude: float,
    radius_m: float = BOARDING_RADIUS_M,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
    now: datetime | None = None,
) -> list[dict]:
    """Stops near a point with the services that run there when the user would arrive (now plus the walk)."""
    moment = now if now is not None else datetime.now(SGT)
    services = _services_by_stop(cache.routes)
    found = []
    for stop in cache.stops:
        raw = haversine_m(
            latitude,
            longitude,
            stop["Latitude"],
            stop["Longitude"],
        )
        limit = BOARDING_RADIUS_M if radius_m is None else min(float(radius_m), 800.0)
        if raw > limit:
            continue
        distance_m = int(raw + 0.5)
        road_name = stop.get("RoadName")
        found.append(
            {
                "stop_code": stop["BusStopCode"],
                "description": stop["Description"],
                "road_name": road_name if isinstance(road_name, str) and road_name.strip() else None,
                "latitude": stop["Latitude"],
                "longitude": stop["Longitude"],
                "distance_m": distance_m,
                "walk_minutes": walk_minutes(distance_m, walk_speed_m_s),
                "_raw_m": raw,
            }
        )
    found.sort(key=lambda item: (item["_raw_m"], item["stop_code"]))
    for item in found:
        board_at = moment + timedelta(minutes=item["walk_minutes"])  # a stop list has no route, so no wait to add
        item["services"] = [
            service for service in services.get(item["stop_code"], [])
            if service_runs_at(cache, service, item["stop_code"], board_at)
        ]
        del item["_raw_m"]
    return found


def _services_by_stop(routes: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for route in routes:
        code = route.get("BusStopCode")
        service = route.get("ServiceNo")
        if not isinstance(code, str) or not isinstance(service, str):
            continue
        service = service.strip()
        if not service:
            continue
        known = seen.setdefault(code, set())
        if service in known:
            continue
        known.add(service)
        grouped.setdefault(code, []).append(service)
    for services in grouped.values():
        services.sort(key=_service_sort_key)
    return grouped


def _service_sort_key(service: str) -> tuple:
    number = ""
    suffix = ""
    for char in service:
        if char.isdigit() and not suffix:
            number += char
        else:
            suffix += char
    return (int(number) if number else 10**9, suffix.casefold(), service)

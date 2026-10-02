"""The alternate-stop search tests the distance first. It must give the same stops, in the same order, as testing every stop."""

import math

from lta_static import StopAndRouteCache
from nearby import BOARDING_RADIUS_M, EARTH_RADIUS_M, haversine_m
from reroute import ALTERNATE_STOP_LIMIT, _reaching_services, closest_alternate_stops

LAT = 1.3
LON = 103.8
DEST = "99999"


def _scan_all_stops(cache, user_lat, user_lon, current_stop_code, destination_stop_code):
    """The previous implementation: reachability first, for every stop in the cache."""
    found = []
    for stop in cache.stops:
        code = stop.get("BusStopCode")
        if not isinstance(code, str) or code == current_stop_code:
            continue
        if not _reaching_services(cache, code, destination_stop_code):
            continue
        distance = haversine_m(user_lat, user_lon, stop["Latitude"], stop["Longitude"])
        if distance > BOARDING_RADIUS_M:
            continue
        found.append((distance, code, stop))
    found.sort(key=lambda item: (item[0], item[1]))
    return [stop for _, _, stop in found[:ALTERNATE_STOP_LIMIT]]


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _fixture():
    stops = []
    routes = []
    # Stops at assorted distances, some that reach the destination, some that do not, two at the same distance.
    spec = [("A1", 50, True), ("A2", 120, True), ("A3", 120, True), ("A4", 200, False), ("A5", 380, True),
            ("A6", 399, True), ("A7", 401, True), ("A8", 900, True), ("A9", 30, False)]
    for code, metres, reaches in spec:
        lat, lon = _north(metres)
        stops.append({"BusStopCode": code, "Description": code, "RoadName": "Rd", "Latitude": lat, "Longitude": lon})
        if reaches:
            routes.append({"ServiceNo": "7", "Direction": 1, "BusStopCode": code, "StopSequence": 1, "Distance": 0})
    dest_lat, dest_lon = _north(3000)
    stops.append({"BusStopCode": DEST, "Description": "Dest", "RoadName": "Rd", "Latitude": dest_lat, "Longitude": dest_lon})
    routes.append({"ServiceNo": "7", "Direction": 1, "BusStopCode": DEST, "StopSequence": 9, "Distance": 3.0})
    for i in range(400):  # far stops that a full scan still has to test
        lat, lon = _north(5000 + i * 10)
        stops.append({"BusStopCode": "F%d" % i, "Description": "F", "RoadName": "Rd", "Latitude": lat, "Longitude": lon})
    return StopAndRouteCache(stops, routes, [])


def test_same_stops_in_the_same_order_as_the_full_scan():
    cache = _fixture()
    for current in ("", "A1", "A2", "A5"):
        new = closest_alternate_stops(cache, LAT, LON, current, DEST)
        old = _scan_all_stops(cache, LAT, LON, current, DEST)
        assert [s["BusStopCode"] for s in new] == [s["BusStopCode"] for s in old]
        assert len(new) <= ALTERNATE_STOP_LIMIT
    assert [s["BusStopCode"] for s in closest_alternate_stops(cache, LAT, LON, "", DEST)] == ["A1", "A2"]


def test_the_radius_and_current_stop_rules_hold():
    cache = _fixture()
    codes = [s["BusStopCode"] for s in closest_alternate_stops(cache, LAT, LON, "A1", DEST)]
    assert "A1" not in codes and "A7" not in codes and "A8" not in codes  # the current stop and stops past 400 m
    assert closest_alternate_stops(cache, LAT, LON, "", "NO-SUCH") == []


def test_reachability_is_only_checked_inside_the_radius(monkeypatch):
    import reroute

    cache = _fixture()
    seen = []
    real = reroute._reaching_services

    def spy(c, code, dest):
        seen.append(code)
        return real(c, code, dest)

    monkeypatch.setattr(reroute, "_reaching_services", spy)
    closest_alternate_stops(cache, LAT, LON, "", DEST)
    assert all(not code.startswith("F") for code in seen)  # far stops are never tested
    assert len(seen) <= 9

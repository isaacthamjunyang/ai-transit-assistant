"""Destination-stop selection from the local cache. No live APIs."""

import math
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import lta_static
from destination_stops import list_destination_stops
from lta_static import StopAndRouteCache, write_cache
from main import app
from nearby import EARTH_RADIUS_M, haversine_m

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
USER = (1.3, 103.8)
PLACE = (1.32, 103.8)


def _north(lat: float, lon: float, metres: float) -> tuple[float, float]:
    return lat + math.degrees(metres / EARTH_RADIUS_M), lon


def _stop(code: str, lat: float, lon: float, name: str, road: str = "Orchard Rd") -> dict:
    return {
        "BusStopCode": code,
        "Description": name,
        "RoadName": road,
        "Latitude": lat,
        "Longitude": lon,
    }


def _route(service: str, direction: int, sequence: int, code: str, distance: float | None) -> dict:
    record = {
        "ServiceNo": service,
        "Direction": direction,
        "StopSequence": sequence,
        "BusStopCode": code,
    }
    if distance is not None:
        record["Distance"] = distance
    return record


def _service(service: str, direction: int, offpeak: str) -> dict:
    return {
        "ServiceNo": service,
        "Direction": direction,
        "OriginCode": "A",
        "DestinationCode": "Z",
        "AM_Peak_Freq": offpeak,
        "AM_Offpeak_Freq": offpeak,
        "PM_Peak_Freq": offpeak,
        "PM_Offpeak_Freq": offpeak,
    }


def _cache(stops, routes, services=None) -> StopAndRouteCache:
    return StopAndRouteCache(stops, routes, [] if services is None else services)


def _list(cache, *, boarding=None, service=None, user=USER, place=PLACE):
    return list_destination_stops(
        cache,
        place[0],
        place[1],
        user[0],
        user[1],
        boarding_stop_code=boarding,
        service_no=service,
        now=NOW,
    )


def _codes(body, key):
    return [stop["stop_code"] for stop in body[key]]


def _place_at(metres: float) -> tuple[float, float]:
    guess = _north(*PLACE, metres)
    measured = haversine_m(PLACE[0], PLACE[1], guess[0], guess[1])
    return _north(*PLACE, metres * (metres / measured))


def test_radius_is_inclusive_at_600_metres_and_uses_haversine():
    inside = _north(*PLACE, 100)
    edge = _place_at(600)
    outside = _place_at(601)
    assert haversine_m(PLACE[0], PLACE[1], edge[0], edge[1]) <= 600 + 1e-6
    assert haversine_m(PLACE[0], PLACE[1], outside[0], outside[1]) > 600
    boarding = _stop("B", *USER, "Boarding")
    cache = _cache(
        [
            boarding,
            _stop("IN", *inside, "Inside"),
            _stop("EDGE", *edge, "Edge"),
            _stop("OUT", *outside, "Outside"),
        ],
        [],
    )
    body = _list(cache, boarding="B")
    assert body["destination"] == {"lat": PLACE[0], "lon": PLACE[1]}
    assert _codes(body, "reachable_stops") == []
    assert set(_codes(body, "unreachable_stops")) == {"IN", "EDGE"}
    by_code = {stop["stop_code"]: stop for stop in body["unreachable_stops"]}
    raw_inside = haversine_m(PLACE[0], PLACE[1], inside[0], inside[1])
    assert by_code["IN"]["distance_m"] == int(raw_inside + 0.5)
    assert by_code["IN"]["walk_minutes"] == max(1, math.floor(by_code["IN"]["distance_m"] / 75 + 0.5))  # one rule: round half up, at least 1
    assert by_code["IN"]["stop_name"] == "Inside"
    assert by_code["IN"]["road_name"] == "Orchard Rd"
    assert by_code["IN"]["lat"] == inside[0]
    assert by_code["IN"]["lon"] == inside[1]
    assert by_code["EDGE"]["distance_m"] == int(
        haversine_m(PLACE[0], PLACE[1], edge[0], edge[1]) + 0.5
    )
    assert "OUT" not in _codes(body, "unreachable_stops")


def test_all_reachable_stops_are_returned_and_unreachable_are_capped_at_three():
    boarding = _stop("B", *USER, "Boarding")
    stops = [boarding]
    routes = []
    for index in range(6):
        code = f"R{index}"
        point = _north(*PLACE, 20 * (index + 1))
        stops.append(_stop(code, *point, code))
        routes.extend(
            [
                _route("36", 1, 1, "B", 0),
                _route("36", 1, 2, code, 1),
            ]
        )
    for index in range(4):
        code = f"U{index}"
        stops.append(_stop(code, *_north(*PLACE, 100 * (index + 1)), code))
    body = _list(_cache(stops, routes, [_service("36", 1, "10-10")]), boarding="B")
    assert _codes(body, "reachable_stops") == [f"R{index}" for index in range(6)]
    assert _codes(body, "unreachable_stops") == ["U0", "U1", "U2"]
    assert all(stop["is_reachable"] for stop in body["reachable_stops"])
    assert all(stop["rough_journey_minutes"] is not None for stop in body["reachable_stops"])


def test_downstream_same_direction_is_reachable_and_the_reverse_is_not():
    boarding = _stop("B", *USER, "Boarding")
    dest = _stop("D", *PLACE, "Dest")
    upstream = _stop("UP", *_north(*PLACE, 30), "Upstream")
    wrong = _stop("WRONG", *_north(*PLACE, 40), "Wrong way")
    routes = [
        _route("36", 1, 1, "B", 0),
        _route("36", 1, 4, "D", 2.5),
        _route("36", 1, 1, "UP", 0),
        _route("36", 1, 8, "B", 3),
        _route("65", 2, 1, "WRONG", 0),
        _route("65", 2, 6, "B", 2),
    ]
    body = _list(
        _cache(
            [boarding, dest, upstream, wrong],
            routes,
            [_service("36", 1, "10-10"), _service("65", 2, "10-10")],
        ),
        boarding="B",
    )
    assert _codes(body, "reachable_stops") == ["D"]
    reached = body["reachable_stops"][0]
    assert reached["is_reachable"] is True
    assert reached["connecting_services"] == ["36"]
    assert set(_codes(body, "unreachable_stops")) == {"UP", "WRONG"}
    for stop in body["unreachable_stops"]:
        assert stop["is_reachable"] is False
        assert stop["connecting_services"] == []
        assert stop["rough_journey_minutes"] is None


def test_selected_boarding_stop_ignores_other_nearby_origins():
    near = _stop("NEAR", *USER, "Near")
    other = _stop("OTHER", *_north(*USER, 100), "Other")
    dest = _stop("D", *PLACE, "Dest")
    routes = [
        _route("36", 1, 1, "OTHER", 0),
        _route("36", 1, 3, "D", 2),
    ]
    body = _list(_cache([near, other, dest], routes, [_service("36", 1, "10-10")]), boarding="NEAR")
    assert body["reachable_stops"] == []
    assert _codes(body, "unreachable_stops") == ["D"]


def test_without_a_boarding_stop_a_stop_within_400_metres_can_connect():
    near = _stop("NEAR", *_north(*USER, 100), "Near")
    far = _stop("FAR", *_north(*USER, 500), "Far")
    dest = _stop("D", *PLACE, "Dest")
    only_far = [
        _route("36", 1, 1, "FAR", 0),
        _route("36", 1, 3, "D", 2),
    ]
    missed = _list(_cache([near, far, dest], only_far, [_service("36", 1, "10-10")]))
    assert missed["reachable_stops"] == []
    connected = [
        _route("65", 1, 1, "NEAR", 0),
        _route("65", 1, 2, "D", 1.5),
    ]
    body = _list(_cache([near, far, dest], only_far + connected, [_service("36", 1, "10-10"), _service("65", 1, "10-10")]))
    assert _codes(body, "reachable_stops") == ["D"]
    assert body["reachable_stops"][0]["connecting_services"] == ["65"]


def test_multiple_services_and_the_preselected_service_wins_even_when_slower():
    boarding = _stop("B", *USER, "Boarding")
    dest = _stop("D", *PLACE, "Dest")
    routes = [
        _route("36", 1, 1, "B", 1.0),
        _route("36", 1, 5, "D", 3.5),
        _route("65", 1, 1, "B", 0.0),
        _route("65", 1, 2, "D", 0.5),
    ]
    services = [_service("36", 1, "10-10"), _service("65", 1, "2-2")]
    cache = _cache([boarding, dest], routes, services)
    preferred = _list(cache, boarding="B", service="36")["reachable_stops"][0]
    fastest = _list(cache, boarding="B")["reachable_stops"][0]
    assert preferred["connecting_services"] == ["36", "65"]
    assert fastest["connecting_services"] == ["36", "65"]
    assert preferred["rough_journey_minutes"] == math.ceil(5 + (2.5 / 18) * 60)
    assert fastest["rough_journey_minutes"] == math.ceil(1 + (0.5 / 18) * 60)
    assert preferred["rough_journey_minutes"] > fastest["rough_journey_minutes"]
    missed = _list(cache, boarding="B", service="999")["reachable_stops"][0]
    assert missed["rough_journey_minutes"] == fastest["rough_journey_minutes"]


def test_rough_total_ceils_once_and_uses_each_component():
    boarding_at = _north(*USER, 100)
    dest_at = _north(*PLACE, 50)
    boarding = _stop("B", *boarding_at, "Boarding")
    dest = _stop("D", *dest_at, "Dest")
    cache = _cache(
        [boarding, dest],
        [_route("36", 1, 1, "B", 1.2), _route("36", 1, 4, "D", 3.7)],
        [_service("36", 1, "10-10")],
    )
    reached = _list(cache, boarding="B")["reachable_stops"][0]
    user_m = haversine_m(USER[0], USER[1], boarding_at[0], boarding_at[1])
    place_m = haversine_m(PLACE[0], PLACE[1], dest_at[0], dest_at[1])
    total = user_m / 1.25 / 60 + (600 / 2) / 60 + (2.5 / 18) * 60 + place_m / 1.25 / 60
    assert reached["rough_journey_minutes"] == math.ceil(total)
    assert reached["rough_journey_minutes"] != (
        math.ceil(user_m / 1.25 / 60)
        + math.ceil(5)
        + math.ceil((2.5 / 18) * 60)
        + math.ceil(place_m / 1.25 / 60)
    )


def test_a_missing_route_distance_does_not_invent_an_estimate():
    boarding = _stop("B", *USER, "Boarding")
    dest = _stop("D", *PLACE, "Dest")
    cache = _cache(
        [boarding, dest],
        [_route("36", 1, 1, "B", 2.0), _route("36", 1, 4, "D", 0.4)],
        [_service("36", 1, "10-10")],
    )
    reached = _list(cache, boarding="B")["reachable_stops"][0]
    assert reached["is_reachable"] is True
    assert reached["connecting_services"] == ["36"]
    assert reached["rough_journey_minutes"] is None


def test_closest_boarding_stop_is_used_when_none_was_selected():
    close = _stop("CLOSE", *_north(*USER, 50), "Close")
    farther = _stop("FARTHER", *_north(*USER, 300), "Farther")
    dest = _stop("D", *PLACE, "Dest")
    routes = [
        _route("65", 1, 1, "CLOSE", 0),
        _route("65", 1, 2, "D", 3),
        _route("36", 1, 1, "FARTHER", 0),
        _route("36", 1, 2, "D", 0.2),
    ]
    services = [_service("65", 1, "10-10"), _service("36", 1, "2-2")]
    body = _list(_cache([close, farther, dest], routes, services), service="36")
    reached = body["reachable_stops"][0]
    assert set(reached["connecting_services"]) == {"36", "65"}
    close_m = haversine_m(USER[0], USER[1], close["Latitude"], close["Longitude"])
    expected = math.ceil(close_m / 1.25 / 60 + 5 + (3 / 18) * 60)
    assert reached["rough_journey_minutes"] == expected


def _endpoint_cache(tmp_path, monkeypatch):
    boarding = _stop("08057", *USER, "Boarding")
    dest = _stop("09047", *PLACE, "Dest")
    write_cache(
        tmp_path,
        [boarding, dest],
        [_route("36", 1, 1, "08057", 0), _route("36", 1, 2, "09047", 1)],
        [_service("36", 1, "10-10")],
    )
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("a live client was opened")),
    )


def test_endpoint_uses_the_cache_and_does_not_call_out(tmp_path, monkeypatch):
    _endpoint_cache(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get(
            "/api/destination-stops",
            params={
                "dest_lat": PLACE[0],
                "dest_lon": PLACE[1],
                "user_lat": USER[0],
                "user_lon": USER[1],
                "boarding_stop_code": "08057",
                "service_no": "36",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["destination"]["lat"] == PLACE[0]
    assert body["destination"]["lon"] == PLACE[1]
    assert body["reachable_stops"][0]["stop_code"] == "09047"
    assert body["reachable_stops"][0]["connecting_services"] == ["36"]
    assert "probability" not in response.text
    assert "AccountKey" not in response.text
    assert "onemap" not in response.text.lower()


@pytest.mark.parametrize(
    "params",
    [
        {"dest_lon": 103.8, "user_lat": 1.3, "user_lon": 103.8},
        {"dest_lat": 1.3, "user_lat": 1.3, "user_lon": 103.8},
        {"dest_lat": 1.3, "dest_lon": 103.8, "user_lon": 103.8},
        {"dest_lat": 1.3, "dest_lon": 103.8, "user_lat": 1.3},
        {"dest_lat": 91, "dest_lon": 103.8, "user_lat": 1.3, "user_lon": 103.8},
        {"dest_lat": 1.3, "dest_lon": 181, "user_lat": 1.3, "user_lon": 103.8},
        {"dest_lat": "NaN", "dest_lon": 103.8, "user_lat": 1.3, "user_lon": 103.8},
        {"dest_lat": "Infinity", "dest_lon": 103.8, "user_lat": 1.3, "user_lon": 103.8},
        {
            "dest_lat": 1.3,
            "dest_lon": 103.8,
            "user_lat": 1.3,
            "user_lon": 103.8,
            "boarding_stop_code": " ",
        },
        {
            "dest_lat": 1.3,
            "dest_lon": 103.8,
            "user_lat": 1.3,
            "user_lon": 103.8,
            "service_no": " ",
        },
    ],
)
def test_destination_stop_parameters_are_validated(tmp_path, monkeypatch, params):
    _endpoint_cache(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/destination-stops", params=params)
    assert response.status_code == 422
    assert "reachable_stops" not in response.text

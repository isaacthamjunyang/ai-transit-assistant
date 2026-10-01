"""Nearby boarding stops. Fixtures only — these tests do not call LTA."""

import math

import httpx
import pytest
from fastapi.testclient import TestClient

import lta_static
from lta_static import StopAndRouteCache, write_cache
from main import app
from nearby import (
    BOARDING_RADIUS_M,
    EARTH_RADIUS_M,
    haversine_m,
    nearby_boarding_stops,
    walk_minutes,
)


def _forbid_live_client(*args, **kwargs):
    raise AssertionError("live HTTP client should not be created")


def _north(lat: float, lon: float, metres: float) -> tuple[float, float]:
    return lat + math.degrees(metres / EARTH_RADIUS_M), lon


def _stop(code: str, description: str, lat: float, lon: float, road: str | None = "Orchard Rd") -> dict:
    record = {
        "BusStopCode": code,
        "Description": description,
        "Latitude": lat,
        "Longitude": lon,
    }
    if road is not None:
        record["RoadName"] = road
    return record


def _route(service: str, code: str, direction: int = 1, sequence: int = 1) -> dict:
    return {
        "ServiceNo": service,
        "Operator": "SBST",
        "Direction": direction,
        "StopSequence": sequence,
        "BusStopCode": code,
        "Distance": 0,
    }


USER_LAT = 1.3
USER_LON = 103.8


def test_haversine_matches_known_arc_lengths():
    assert haversine_m(1.3, 103.8, 1.3, 103.8) == 0
    degree = haversine_m(1.3, 103.8, 2.3, 103.8)
    assert degree == pytest.approx(EARTH_RADIUS_M * math.pi / 180, abs=0.01)


def test_boundary_includes_400m_and_excludes_anything_farther():
    edge_lat, edge_lon = _north(USER_LAT, USER_LON, BOARDING_RADIUS_M)
    outside_lat, outside_lon = _north(USER_LAT, USER_LON, BOARDING_RADIUS_M + 1)
    assert haversine_m(USER_LAT, USER_LON, edge_lat, edge_lon) == pytest.approx(400, abs=1e-6)
    cache = StopAndRouteCache(
        [
            _stop("IN", "Inside", *_north(USER_LAT, USER_LON, 100)),
            _stop("EDGE", "Edge", edge_lat, edge_lon),
            _stop("OUT", "Outside", outside_lat, outside_lon),
        ],
        [_route("10", "IN")],
    )
    codes = [stop["stop_code"] for stop in nearby_boarding_stops(cache, USER_LAT, USER_LON)]
    assert codes == ["IN", "EDGE"]
    assert "OUT" not in codes


def test_nearby_stops_are_sorted_by_distance_with_no_cap():
    stops = []
    routes = []
    for index, metres in enumerate((300, 50, 150, 400, 10, 220, 80, 180, 260, 120, 340, 20)):
        code = f"{index:05d}"
        lat, lon = _north(USER_LAT, USER_LON, metres)
        stops.append(_stop(code, f"Stop {metres}", lat, lon))
        routes.append(_route("7", code))
    stops.append(_stop("FAR", "Too far", *_north(USER_LAT, USER_LON, 500)))
    cache = StopAndRouteCache(stops, routes)
    result = nearby_boarding_stops(cache, USER_LAT, USER_LON)
    assert len(result) == 12
    distances = [stop["distance_m"] for stop in result]
    assert distances == sorted(distances)
    assert "FAR" not in [stop["stop_code"] for stop in result]


def test_walk_minutes_uses_one_point_two_five_metres_per_second():
    assert walk_minutes(328) == 4
    assert walk_minutes(75) == 1
    assert walk_minutes(0) == 0
    cache = StopAndRouteCache(
        [_stop("08057", "Dhoby Ghaut Stn", *_north(USER_LAT, USER_LON, 328))],
        [_route("7", "08057")],
    )
    stop = nearby_boarding_stops(cache, USER_LAT, USER_LON)[0]
    assert stop["distance_m"] == 328
    assert stop["walk_minutes"] == walk_minutes(stop["distance_m"])


def test_services_come_from_routes_without_duplicates():
    lat, lon = _north(USER_LAT, USER_LON, 40)
    cache = StopAndRouteCache(
        [_stop("08057", "Dhoby Ghaut Stn", lat, lon, "Orchard Rd")],
        [
            _route("65", "08057", direction=1),
            _route("65", "08057", direction=2),
            _route("7", "08057"),
            _route("14", "08057"),
            _route("999", "99999"),
        ],
    )
    stop = nearby_boarding_stops(cache, USER_LAT, USER_LON)[0]
    assert stop["services"] == ["7", "14", "65"]


def test_response_shape_uses_cached_fields():
    lat, lon = _north(USER_LAT, USER_LON, 80)
    cache = StopAndRouteCache(
        [_stop("01012", "Hotel Grand Pacific", lat, lon, road=None)],
        [_route("10", "01012")],
    )
    stop = nearby_boarding_stops(cache, USER_LAT, USER_LON)[0]
    assert set(stop) == {
        "stop_code",
        "description",
        "road_name",
        "latitude",
        "longitude",
        "distance_m",
        "walk_minutes",
        "services",
    }
    assert stop["stop_code"] == "01012"
    assert stop["description"] == "Hotel Grand Pacific"
    assert stop["road_name"] is None
    assert stop["latitude"] == lat
    assert stop["longitude"] == lon
    assert stop["services"] == ["10"]


def test_no_stops_within_400m_returns_an_empty_list():
    cache = StopAndRouteCache(
        [_stop("01012", "Hotel Grand Pacific", *_north(USER_LAT, USER_LON, 900))],
        [_route("10", "01012")],
    )
    assert nearby_boarding_stops(cache, USER_LAT, USER_LON) == []


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    lat, lon = _north(USER_LAT, USER_LON, 100)
    write_cache(
        tmp_path,
        [_stop("08057", "Dhoby Ghaut Stn", lat, lon)],
        [_route("36", "08057"), _route("36", "08057", direction=2), _route("7", "08057")],
    )
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(httpx, "Client", _forbid_live_client)
    with TestClient(app) as client:
        yield client


def test_endpoint_returns_cached_stops_without_calling_lta(api_client):
    response = api_client.get(
        "/api/stops/nearby", params={"lat": USER_LAT, "lon": USER_LON}
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["stop_code"] == "08057"
    assert payload[0]["services"] == ["7", "36"]
    assert "LTA_ACCOUNT_KEY" not in response.text
    assert "AccountKey" not in response.text


def test_endpoint_returns_empty_list_when_nothing_is_nearby(api_client):
    response = api_client.get("/api/stops/nearby", params={"lat": 0, "lon": 0})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"lat": 91, "lon": 103.8},
        {"lat": -91, "lon": 103.8},
        {"lat": 1.3, "lon": 181},
        {"lat": 1.3, "lon": -181},
        {"lat": "north", "lon": 103.8},
        {"lon": 103.8},
        {},
    ],
)
def test_invalid_coordinates_are_rejected(api_client, params):
    response = api_client.get("/api/stops/nearby", params=params)
    assert response.status_code == 422
    assert "stop_code" not in response.text


def test_missing_cache_is_unavailable_and_has_no_fake_stops(api_client):
    app.state.lta_static = None
    response = api_client.get(
        "/api/stops/nearby", params={"lat": USER_LAT, "lon": USER_LON}
    )
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert isinstance(body, dict)
    assert "stop_code" not in body


def test_page_keeps_a_one_time_fix_and_allows_a_foreground_journey_watch(api_client):
    """Step 4 still takes one getCurrentPosition fix for the nearby list.

    Step 14 may call watchPosition while a transfer or missed-stop journey is
    active, and it must clear that watch. This is foreground tracking only.
    """
    html = api_client.get("/").text
    assert "navigator.geolocation.getCurrentPosition" in html
    assert "navigator.geolocation.watchPosition" in html
    assert "clearWatch" in html
    assert html.count("setInterval(") == 2
    assert "/api/stops/nearby" in html
    assert "/api/arrivals" in html
    assert "datamall" not in html
    assert "selectedBoardingStop" in html
    assert "1.3521" in html
    assert "103.8198" in html
    assert "leaflet.js" in html
    assert "BusArrival" not in html
    assert "LTA_ACCOUNT_KEY" not in html
    assert "OPENAI_API_KEY" not in html
    assert "0.025" not in html
    assert "sigmoid" not in html.lower()
    assert "position.timestamp" in html
    assert "userLocationTimestamp" in html
    assert "location_timestamp" in html
    assert "location_age_seconds" not in html
    assert "/api/destinations?q=" in html
    assert "selectedDestination" in html
    assert "Enter a destination." in html
    assert "No matches found. Try a building, road, or postal code." in html
    assert "onemap.gov.sg" not in html
    assert "ONEMAP_TOKEN" not in html
    assert "ONEMAP_PASSWORD" not in html
    assert "/api/destination-stops?dest_lat=" in html
    assert "confirmedDestinationStop" in html
    assert "selectedDestinationStop" in html
    # Step 9 adds the arrive-by input. Step 8 asserted it was absent.
    assert 'id="arrive-by"' in html
    assert "/api/journey?" in html
    assert "Leave-by: Unavailable" in html
    assert "new Notification(notice.title, { body: notice.body })" in html

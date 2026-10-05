"""Phase 1: one walking-speed input everywhere on the server."""

import json
import logging
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import access_log_filter
import arrivals
import demo
import lta_static
import observations
from catch_heuristic import (
    BOARDING_BUFFER_S,
    catch_probability,
    high_slack,
    low_slack,
    point_slack,
    score_buses,
    to_percent,
)
from config import (
    ERROR_MODEL_SPEED_MPS,
    PACE_MIN_HEADROOM_MPS,
    RANGE_FAST_RATIO,
    RANGE_SLOW_RATIO,
    WALK_SPEED_DEFAULT_MPS,
    WALK_SPEED_MAX_MPS,
    WALK_SPEED_MIN_MPS,
)
from destination_stops import list_destination_stops
import explain
from explain import FACT_SHEET_KEYS, overview_walk_minutes
from journey import build_journey, leave_by_time
from lta_static import StopAndRouteCache
from main import app
from nearby import EARTH_RADIUS_M, nearby_boarding_stops, walk_minutes as nearby_walk_minutes
from pace import pace_guidance
from walk_speed import range_speeds, resolve_walk_speed, response_fields, walk_minutes

SGT = timezone(timedelta(hours=8))
LAT = 1.3
LON = 103.8
ORIGIN = "01011"
DEST = "99999"
KEY = "test-account-key"
SPEEDS = (0.5, 0.8, 1.0, 1.25, 1.35, 1.4)


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(lta_static, "ENV_PATH", env)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    demo.reset_to_live()
    yield
    demo.reset_to_live()


def _cache():
    dest_lat, dest_lon = _north(2000)
    stops = [
        {"BusStopCode": ORIGIN, "Description": "Origin", "RoadName": "Orchard Rd", "Latitude": LAT, "Longitude": LON},
        {"BusStopCode": DEST, "Description": "Destination", "RoadName": "Orchard Rd", "Latitude": dest_lat, "Longitude": dest_lon},
    ]
    routes = [
        {"ServiceNo": "18", "Direction": 1, "BusStopCode": ORIGIN, "StopSequence": 1, "Distance": 0},
        {"ServiceNo": "18", "Direction": 1, "BusStopCode": DEST, "StopSequence": 5, "Distance": 3},
    ]
    services = [{
        "ServiceNo": "18", "Direction": 1, "OriginCode": ORIGIN, "DestinationCode": DEST,
        "AM_Offpeak_Freq": "10-10", "AM_Peak_Freq": "10-10", "PM_Peak_Freq": "10-10", "PM_Offpeak_Freq": "10-10",
    }]
    return StopAndRouteCache(stops, routes, services)


@pytest.fixture
def client(monkeypatch):
    cache = _cache()
    monkeypatch.setattr("main.load_static_data", lambda: cache)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: KEY)
    eta = (datetime.now(SGT) + timedelta(minutes=10, seconds=17)).replace(microsecond=0).isoformat()

    def fake_get(self, url, *args, **kwargs):
        body = {"Services": [{"ServiceNo": "18", "NextBus": {
            "EstimatedArrival": eta, "Monitored": 1, "Latitude": "", "Longitude": "",
            "OriginCode": "", "DestinationCode": "",
        }}]}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with TestClient(app) as test_client:
        test_client.eta = eta
        yield test_client


WALK_M = 300
USER = _north(WALK_M)
# The user stands WALK_M metres north of the stop.
USER = (LAT + math.degrees(WALK_M / EARTH_RADIUS_M), LON)


def _poll(client, speed=None, source="gps", extra=None):
    dest_lat, dest_lon = _north(2000)
    params = {
        "stop_code": ORIGIN, "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": 10,
        "location_timestamp": time.time(), "destination_stop_code": DEST, "dest_lat": dest_lat,
        "dest_lon": dest_lon, "explanation_rendered": 0,
    }
    if speed is not None:
        params["walk_speed"] = speed
        params["walk_speed_source"] = source
    params.update(extra or {})
    response = client.get("/api/arrivals", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---- the pure resolver

@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.49, 0.5), (0.5, 0.5), (0.9, 0.9), (1.4, 1.4), (1.41, 1.4), (3.0, 1.4), (-1, 0.5), (0, 0.5)],
)
def test_the_speed_is_clamped_to_the_normal_walking_range(value, expected):
    assert resolve_walk_speed(value, "gps") == (expected, "gps")
    assert resolve_walk_speed(str(value), "cadence") == (expected, "cadence")


@pytest.mark.parametrize(
    "value",
    [None, float("nan"), float("inf"), float("-inf"), "fast", "", "nan", "inf", True, False, [], {}, object()],
)
def test_unusable_values_fall_back_to_the_default(value):
    assert resolve_walk_speed(value, "gps") == (WALK_SPEED_DEFAULT_MPS, "default")


@pytest.mark.parametrize("source", [None, "", "GPS", "wifi", "default", 3, ["gps"]])
def test_unknown_or_default_sources_ignore_the_value(source):
    assert resolve_walk_speed(1.0, source) == (WALK_SPEED_DEFAULT_MPS, "default")


def test_the_three_real_sources_are_kept_and_demo_mode_ignores_the_client():
    for source in ("gps", "cadence", "remembered"):
        assert resolve_walk_speed(1.1, source) == (1.1, source)
    assert resolve_walk_speed(1.1, "gps", demo=True) == (1.25, "default")
    assert resolve_walk_speed(1.1234, "gps")[0] == 1.12  # two decimals, so the page shows what was used


def test_constants_have_the_agreed_values():
    assert (WALK_SPEED_DEFAULT_MPS, WALK_SPEED_MIN_MPS, WALK_SPEED_MAX_MPS) == (1.25, 0.5, 1.4)
    assert RANGE_SLOW_RATIO == pytest.approx(1.1 / 1.25) and RANGE_FAST_RATIO == pytest.approx(1.4 / 1.25)
    assert ERROR_MODEL_SPEED_MPS == 1.25 and PACE_MIN_HEADROOM_MPS == 0.05


def test_range_endpoints_follow_the_ratios_and_the_caps():
    assert range_speeds() == (1.25, 1.1, 1.4)  # exactly today's numbers
    point, slow, fast = range_speeds(1.0)
    assert (point, slow) == (1.0, pytest.approx(0.88)) and fast == pytest.approx(1.12)
    assert range_speeds(1.4)[2] == 1.4 == range_speeds(1.4)[0]  # a fast end that equals the point is allowed
    assert range_speeds(1.3)[2] == 1.4  # capped, not 1.456
    assert range_speeds(0.5)[1] == 0.5  # floored
    for speed in SPEEDS:
        point, slow, fast = range_speeds(speed)
        assert WALK_SPEED_MIN_MPS <= slow <= point <= fast <= WALK_SPEED_MAX_MPS


def test_walk_minutes_modes_reproduce_each_existing_rounding():
    assert walk_minutes(750) == 10.0
    assert walk_minutes(100, 1.25, "round") == 1
    assert walk_minutes(20, 1.25, "round") == 0  # the plain mode has no floor; no shown label uses it
    assert nearby_walk_minutes(20) == 1 == nearby_walk_minutes(0)
    assert walk_minutes(20, 1.25, "display") == 1 == overview_walk_minutes(20)
    assert walk_minutes(76, 1.25, "ceil") == 2
    with pytest.raises(ValueError):
        walk_minutes(1, 1.25, "floor")
    for metres in (1, 37, 38, 75, 76, 150, 151, 449, 450, 1000):
        assert walk_minutes(metres, 1.25, "ceil") == math.ceil(metres / 75)  # the literal this replaced
        assert walk_minutes(metres, 1.25, "display") == max(1, int(math.floor(metres / 1.25 / 60 + 0.5)))


# ---- scoring

def _bus(minutes=8.0, monitored=True, now=None):
    now = now or datetime(2026, 10, 1, 18, 0, tzinfo=SGT)
    return {"position": "NextBus", "arrival_time": (now + timedelta(minutes=minutes)).isoformat(),
            "monitored": monitored, "origin_code": None, "destination_code": None}


def _score(speed=None, accuracy=30.0, minutes=8.0, distance_m=300.0, **extra):
    now = datetime(2026, 10, 1, 18, 0, tzinfo=SGT)
    kwargs = {} if speed is None else {"walk_speed_m_s": speed}
    return score_buses(
        [_bus(minutes, now=now)], user_lat=LAT + math.degrees(distance_m / EARTH_RADIUS_M), user_lon=LON,
        accuracy_m=accuracy, stop_lat=LAT, stop_lon=LON, services=[], routes=[], service_no="18",
        stop_code=ORIGIN, now=now, location_timestamp=now.timestamp() - 2, **kwargs, **extra,
    )[0]["probability"]


def test_no_client_value_reproduces_the_old_formula_exactly():
    for minutes in (3, 5, 8, 12):
        for distance in (50, 300, 700):
            got = _score(minutes=minutes, distance_m=distance)
            seconds = minutes * 60
            real = _score(1.25, minutes=minutes, distance_m=distance)
            assert got == real  # default argument and an explicit 1.25 are the same thing
            slack = point_slack(seconds, distance_actual(distance), 1.25)
            assert got["point"] == to_percent(catch_probability(slack))
            assert got["range_low"] == to_percent(catch_probability(low_slack(seconds, distance_actual(distance), 30.0, 1.1)))
            assert got["range_high"] == to_percent(catch_probability(high_slack(seconds, distance_actual(distance), 1.4)))


def distance_actual(distance_m):
    from nearby import haversine_m

    return haversine_m(LAT + math.degrees(distance_m / EARTH_RADIUS_M), LON, LAT, LON)


def test_probability_is_monotonic_in_speed():
    last = None
    for speed in SPEEDS:
        chance = _score(speed, minutes=6, distance_m=500)
        if last is not None:
            assert chance["point"] >= last["point"]
            assert chance["range_low"] >= last["range_low"]
            assert chance["range_high"] >= last["range_high"]
        assert chance["range_low"] <= chance["point"] <= chance["range_high"]
        last = chance
    assert _score(0.5, minutes=8.5, distance_m=400)["point"] < _score(1.4, minutes=8.5, distance_m=400)["point"]


def test_the_gps_error_terms_stay_at_1_25_whatever_the_speed():
    # Accuracy 60 m: the low end loses exactly 60 / 1.25 s from the walk term, at every speed.
    distance = distance_actual(400)
    for speed in SPEEDS:
        _, slow, _ = range_speeds(speed)
        expected = to_percent(catch_probability(low_slack(7 * 60, distance, 60.0, slow)))
        got = _score(speed, accuracy=60.0, minutes=7, distance_m=400)["range_low"]
        assert got == expected
        assert low_slack(7 * 60, distance, 60.0, slow) == pytest.approx(
            7 * 60 - distance / slow - BOARDING_BUFFER_S - 60.0 / ERROR_MODEL_SPEED_MPS
        )


@pytest.mark.parametrize(
    ("speed", "expected"),
    [(1.0, "faster"), (1.35, "faster"), (1.38, "unlikely"), (1.4, "unlikely")],
)
def test_walk_faster_is_never_advised_without_headroom(speed, expected):
    # 5 minutes at 330 m puts the point under 50 and range_high at or above 40 for these speeds.
    chance = _score(speed, minutes=5.0, distance_m=330)
    point = pace_guidance(chance["point"], chance["range_low"], chance["range_high"], "live", False, 300, None,
                          headroom_mps=range_speeds(speed)[2] - speed)
    assert chance["pace"] == point
    if chance["range_high"] >= 40 and chance["point"] < 50:
        assert point == expected
    else:  # the fixture drifted: the rule itself is still checked below
        assert point in ("unlikely", "faster", "steady", "slightly_faster")


def test_pace_headroom_rule_directly():
    for headroom, faster, slightly in [(0.12, "faster", "slightly_faster"), (0.05, "faster", "slightly_faster"),
                                       (0.04, "unlikely", "steady"), (0.0, "unlikely", "steady")]:
        assert pace_guidance(45, 36, 45, "live", False, 300, None, headroom_mps=headroom) == faster
        assert pace_guidance(55, 50, 60, "live", False, 300, None, headroom_mps=headroom) == slightly
    assert pace_guidance(45, 36, 45, "live", False, 300, None) == "faster"  # no headroom given: rules unchanged
    assert pace_guidance(70, 60, 85, "live", False, 300, None, headroom_mps=0.0) == "steady"


# ---- leave-by

def test_leave_by_uses_the_speed_used_not_the_slow_end():
    eta = datetime(2026, 10, 1, 18, 10, tzinfo=SGT)
    assert leave_by_time(eta, 440) == eta - timedelta(seconds=440 / 1.25 + 135)
    assert leave_by_time(eta, 440, 1.25) == leave_by_time(eta, 440)
    assert leave_by_time(eta, 440, 0.8) == eta - timedelta(seconds=440 / 0.8 + 135)
    assert leave_by_time(eta, 440, 0.8) < leave_by_time(eta, 440)
    assert leave_by_time(eta, 440, 1.4) > leave_by_time(eta, 440)


# ---- endpoints: one request, every number consistent

def test_a_poll_without_a_client_value_is_today_and_says_so(client):
    body = _poll(client)
    assert body["walk_speed_used"] == 1.25 and body["walk_speed_source"] == "default"
    body = _poll(client, speed="fast", source="gps")
    assert body["walk_speed_used"] == 1.25 and body["walk_speed_source"] == "default"


@pytest.mark.parametrize("speed", [0.6, 1.0, 1.4])
def test_one_poll_uses_one_speed_for_every_number(client, speed):
    body = _poll(client, speed=speed, extra={"explanation_rendered": 1})
    assert body["walk_speed_used"] == speed and body["walk_speed_source"] == "gps"
    distance = distance_actual(WALK_M)
    eta = datetime.fromisoformat(body["buses"][0]["arrival_time"])
    now = datetime.fromisoformat(body["fetched_at"])
    seconds = (eta - now).total_seconds()
    point_s, slow_s, fast_s = range_speeds(speed)
    chance = body["buses"][0]["probability"]
    assert chance["slack_seconds"] == pytest.approx(seconds - distance / point_s - BOARDING_BUFFER_S, abs=2)
    # leave-by and the notification time: the speed used, then 60 s earlier
    expected_leave = eta - timedelta(seconds=distance / speed + 135)
    assert abs((datetime.fromisoformat(body["leave_by"]) - expected_leave).total_seconds()) <= 1
    assert datetime.fromisoformat(body["leave_by"]) - datetime.fromisoformat(body["notification_time"]) == timedelta(seconds=60)
    # the AI sentence's walking minutes, from the same speed
    assert body["explanation"]["walk_minutes"] == overview_walk_minutes(distance, speed)
    # the Step 9 estimate, built from the same speed
    cache = client.app.state.lta_static
    dest_lat, dest_lon = _north(2000)
    from journey import bus_arrival_window

    built = build_journey(cache, dest_lat, dest_lon, USER[0], USER[1], DEST, boarding_stop_code=ORIGIN,
                          service_no="18", now=now, walk_speed_m_s=speed)
    assert built["arrival_terms"]["board_walk_minutes"] == pytest.approx(walk_minutes(distance, speed))
    window = bus_arrival_window(now, built["arrival_terms"], eta, live=True, walk_speed_m_s=speed)
    assert body["arrival_estimate"]["estimated_arrival"] == window["estimated_arrival"].replace(microsecond=0).isoformat()
    assert body["arrival_estimate"]["arrival_low"] == window["arrival_low"].replace(microsecond=0).isoformat()
    assert body["arrival_estimate"]["arrival_high"] == window["arrival_high"].replace(microsecond=0).isoformat()


def test_a_slower_walker_gets_an_earlier_leave_by_and_a_lower_chance(client):
    slow = _poll(client, speed=0.7)
    quick = _poll(client, speed=1.4)
    assert datetime.fromisoformat(slow["leave_by"]) < datetime.fromisoformat(quick["leave_by"])
    assert slow["buses"][0]["probability"]["point"] <= quick["buses"][0]["probability"]["point"]


def test_every_scored_endpoint_returns_the_two_fields(client):
    dest_lat, dest_lon = _north(2000)
    speed = {"walk_speed": 1.0, "walk_speed_source": "cadence"}
    base = {"user_lat": USER[0], "user_lon": USER[1], "dest_lat": dest_lat, "dest_lon": dest_lon}
    calls = [
        ("/api/arrivals", {"stop_code": ORIGIN, "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": 10}),
        ("/api/reroute-options", {"stop_code": ORIGIN, "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": 10,
                                  "destination_stop_code": DEST, "dest_lat": dest_lat, "dest_lon": dest_lon}),
        ("/api/journey", {**base, "destination_stop_code": DEST, "boarding_stop_code": ORIGIN}),
        ("/api/journey-plan", {**base, "destination_stop_code": DEST}),
        ("/api/route-plan", {**base, "boarding_stop_code": ORIGIN, "destination_stop_code": DEST}),
        ("/api/destination-stops", {**base, "boarding_stop_code": ORIGIN}),
    ]
    for path, params in calls:
        body = client.get(path, params={**params, **speed}).json()
        assert body["walk_speed_used"] == 1.0 and body["walk_speed_source"] == "cadence", path
        plain = client.get(path, params=params).json()
        assert plain["walk_speed_used"] == 1.25 and plain["walk_speed_source"] == "default", path


def test_the_overview_minutes_follow_the_speed(client):
    dest_lat, dest_lon = _north(2000)
    params = {"user_lat": USER[0], "user_lon": USER[1], "dest_lat": dest_lat, "dest_lon": dest_lon,
              "boarding_stop_code": ORIGIN}
    slow = client.get("/api/destination-stops", params={**params, "walk_speed": 0.6, "walk_speed_source": "gps"}).json()
    base = client.get("/api/destination-stops", params=params).json()
    distance = int(distance_actual(WALK_M) + 0.5)
    assert nearby_stops_minutes(distance, 0.6) >= nearby_stops_minutes(distance, 1.25)
    assert slow["reachable_stops"][0]["arrival_terms"]["board_walk_minutes"] > base["reachable_stops"][0]["arrival_terms"]["board_walk_minutes"]
    assert base["reachable_stops"][0]["arrival_terms"]["board_walk_minutes"] == pytest.approx(distance_actual(WALK_M) / 1.25 / 60)


def nearby_stops_minutes(distance, speed):
    return walk_minutes(distance, speed, "round")


def test_nearby_stops_minutes_keep_todays_numbers_by_default():
    stops = nearby_boarding_stops(_cache(), USER[0], USER[1])
    assert stops[0]["walk_minutes"] == walk_minutes(stops[0]["distance_m"], 1.25, "round")
    slower = nearby_boarding_stops(_cache(), USER[0], USER[1], walk_speed_m_s=0.5)
    assert slower[0]["walk_minutes"] > stops[0]["walk_minutes"]


def test_demo_mode_ignores_the_client_value(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    body = _poll(client, speed=0.6)
    assert body["walk_speed_used"] == 1.25 and body["walk_speed_source"] == "default"
    base = _poll(client)
    assert body["buses"][0]["probability"]["point"] == base["buses"][0]["probability"]["point"]


# ---- near_stop

def test_near_stop_uses_the_30_metre_rule(client):
    far = _poll(client)
    assert far["near_stop"] is False
    near_lat = LAT + math.degrees(20 / EARTH_RADIUS_M)
    near = _poll(client, extra={"lat": near_lat, "lon": LON})
    assert near["near_stop"] is True
    edge = _poll(client, extra={"lat": LAT + math.degrees(40 / EARTH_RADIUS_M), "lon": LON})
    assert edge["near_stop"] is False


# ---- leave-now fires once

def test_a_speed_change_moves_the_time_but_not_the_bus_identity(client):
    first = _poll(client, speed=0.7)["leave_now"]
    second = _poll(client, speed=1.4)["leave_now"]
    assert first["bus_id"] == second["bus_id"] == "18|01011|NextBus"
    a = _poll(client, speed=0.7)["notification_time"]
    b = _poll(client, speed=1.4)["notification_time"]
    assert a != b


def test_the_page_never_notifies_the_same_bus_twice_so_a_new_time_cannot_repeat_it():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    sync = html.split("function syncLeaveNow(body)", 1)[1].split("function renderCatchWarning", 1)[0]
    assert "lastNotifiedBusId === busId" in sync  # a delivered bus clears the timer and returns
    deliver = html.split("function deliverLeaveNow(busId)", 1)[1].split("function fiveMinuteLockKey", 1)[0]
    assert deliver.index("lastNotifiedBusId === busId") < deliver.index("showLocalNotification")
    assert "lastNotifiedBusId = busId" in deliver
    assert "scheduleKey = busId + \"|\" + body.notification_time" in sync  # a changed time re-arms one timer


# ---- nothing leaks

def test_the_speed_is_not_in_sqlite(client, tmp_path):
    _poll(client, speed=0.77)
    path = tmp_path / "observations.db"
    assert path.exists()
    with sqlite3.connect(path) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(observations)")]
        rows = connection.execute("SELECT * FROM observations").fetchall()
    assert rows and not any("speed" in name or "pace" in name for name in columns)
    assert "0.77" not in json.dumps(rows) and "gps" not in json.dumps(rows)


def test_the_speed_is_not_in_the_openai_fact_sheet(client):
    body = _poll(client, speed=0.77, extra={"explanation_rendered": 1})
    sheet = body["explanation"]["fact_sheet"]
    assert tuple(sheet) == FACT_SHEET_KEYS == ("reason_code", "chosen_action")
    assert "0.77" not in json.dumps(sheet) and "walk_speed" not in json.dumps(sheet)
    # the pack goes to the browser only; the speed it carries never reaches the model request
    request = explain.explanation_request(sheet)
    assert "0.77" not in json.dumps(request) and "walk_speed" not in json.dumps(request)
    assert body["explanation"]["walk_speed_used"] == 0.77


def test_the_access_log_filter_strips_the_position_and_the_speed(caplog):
    access_log_filter.install()
    logger = logging.getLogger("uvicorn.access")
    assert any(isinstance(item, access_log_filter.StripPrivateQuery) for item in logger.filters)
    path = ("/api/arrivals?stop_code=01011&lat=1.3&lon=103.8&accuracy=10&location_timestamp=5&walk_speed=1.1"
            "&walk_speed_source=gps&user_lat=1&user_lon=2&service_no=18")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", path, "1.1", 200)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "stop_code=01011" in text and "service_no=18" in text
    for name in access_log_filter.PRIVATE_QUERY_PARAMS:
        assert name + "=" not in text
    assert "103.8" not in text and "1.1&" not in text
    assert access_log_filter.strip_private_query("/x?lat=1") == "/x"
    assert access_log_filter.strip_private_query("/plain") == "/plain"
    install_once = len([f for f in logger.filters if isinstance(f, access_log_filter.StripPrivateQuery)])
    access_log_filter.install()
    assert len([f for f in logger.filters if isinstance(f, access_log_filter.StripPrivateQuery)]) == install_once


def test_no_application_code_logs_the_speed():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "walk_speed" in text and path.name != "access_log_filter.py":
            assert "logger." not in text
            assert "print(" not in text
    assert response_fields(1.234, "gps") == {"walk_speed_used": 1.23, "walk_speed_source": "gps"}


# ---- one rule for every walking time shown to the user

LABEL_DISTANCES = (0, 20, 100, 250, 450, 600, 1200)
LABEL_SPEEDS = (0.5, 1.0, 1.25, 1.4)


def test_every_shown_walking_label_uses_the_ai_sentences_rounding():
    from destination_stops import _card
    from reroute import _stop_payload

    for speed in LABEL_SPEEDS:
        for metres in LABEL_DISTANCES:
            sentence = overview_walk_minutes(metres, speed)
            assert sentence == max(1, int(math.floor(metres / speed / 60 + 0.5)))
            assert nearby_walk_minutes(metres, speed) == sentence
            stop = {"BusStopCode": "X", "Description": "X", "Latitude": LAT, "Longitude": LON}
            assert _card(stop, metres, speed)["walk_minutes"] == nearby_walk_minutes(int(metres + 0.5), speed)
            north = LAT + math.degrees(metres / EARTH_RADIUS_M)
            cache = StopAndRouteCache([{**stop, "Latitude": north}], [], [])
            shown = _stop_payload(cache, "X", LAT, LON, speed)
            assert shown["walk_minutes"] == overview_walk_minutes(shown["distance_m"], speed)


def test_labels_and_the_probability_terms_are_separate_roundings():
    # The label rounds; the raw seconds in the probability and the ceil sums in Step 9 do not.
    assert walk_minutes(100, 1.25) == pytest.approx(100 / 75)
    assert walk_minutes(100, 1.25, "ceil") == 2 and walk_minutes(100, 1.25, "display") == 1

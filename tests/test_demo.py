"""Step 13 demo mode. Fixtures only — these tests do not call live providers."""

import json
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import arrivals
import catch_heuristic
import demo
import explain
import journey
import leave_now
import lta_static
import observations
import reroute
from catch_heuristic import catch_probability, to_percent
from explain import reset_explanation_gate
from lta_static import StopAndRouteCache
from main import app
from nearby import EARTH_RADIUS_M
from onemap import OneMapSession, search_destinations

SGT = timezone(timedelta(hours=8))
ROOT = lta_static.ENV_PATH.parent
INDEX = ROOT / "static" / "index.html"
LAT = 1.3
LON = 103.8
ORIGIN = "01011"
ALTERNATE = "01012"
DEST = "99999"
KEY = "test-account-key"
SECRET = "sk-demo-should-not-leak"
ONEMAP_SECRET = "onemap-demo-should-not-leak"


@pytest.fixture(autouse=True)
def _isolated_demo(monkeypatch, tmp_path):
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(lta_static, "ENV_PATH", env)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    demo.reset_to_live()
    reset_explanation_gate()
    yield
    demo.reset_to_live()
    reset_explanation_gate()


def _enable(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")


def _north(metres: float) -> tuple[float, float]:
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _stop(code: str, name: str, lat: float, lon: float) -> dict:
    return {
        "BusStopCode": code,
        "Description": name,
        "RoadName": "Orchard Rd",
        "Latitude": lat,
        "Longitude": lon,
    }


def _hop(service: str, code: str, sequence: int, distance: float) -> dict:
    return {
        "ServiceNo": service,
        "Direction": 1,
        "BusStopCode": code,
        "StopSequence": sequence,
        "Distance": distance,
    }


def _service(service: str, frequency: str) -> dict:
    return {
        "ServiceNo": service,
        "Direction": 1,
        "OriginCode": ORIGIN,
        "DestinationCode": DEST,
        "AM_Offpeak_Freq": frequency,
        "AM_Peak_Freq": frequency,
        "PM_Peak_Freq": frequency,
        "PM_Offpeak_Freq": frequency,
    }


def _cache(services: list[dict] | None = None, alternate: bool = False) -> StopAndRouteCache:
    dest_lat, dest_lon = _north(2000)
    stops = [
        _stop(ORIGIN, "Origin", LAT, LON),
        _stop(DEST, "Destination", dest_lat, dest_lon),
    ]
    routes = [
        _hop("18", ORIGIN, 1, 0),
        _hop("18", DEST, 5, 3),
    ]
    if alternate:
        alt_lat, alt_lon = _north(120)
        stops.append(_stop(ALTERNATE, "Alternate", alt_lat, alt_lon))
        routes.extend([
            _hop("36", ALTERNATE, 1, 0),
            _hop("36", DEST, 5, 3),
        ])
    return StopAndRouteCache(stops, routes, [] if services is None else services)


def _sheet(**overrides) -> dict:
    fact = {
        "reason_code": "LEAVE_BY",
        "chosen_action": "wait",
    }
    fact.update(overrides)
    return fact


def _body(fact: dict) -> dict:
    return {"fact_sheet": fact, "snapshot": "36|01011|2026-09-29T14:02:00+08:00|2026-09-29T14:00:00+08:00"}


def _client(monkeypatch, cache: StopAndRouteCache):
    monkeypatch.setattr("main.load_static_data", lambda: cache)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: KEY)
    return TestClient(app)


def _lta_gets(monkeypatch, payload: dict | None = None, status_code: int = 500) -> list[str]:
    seen = []
    real_get = httpx.Client.get

    def spy(self, url, *args, **kwargs):
        seen.append(str(url))
        if "/v3/BusArrival" in str(url):
            body = {"Services": []} if payload is None else payload
            return httpx.Response(status_code, json=body)
        return real_get(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "get", spy)
    return seen


def _bus_json(eta: str, monitored: int = 1) -> dict:
    return {
        "EstimatedArrival": eta,
        "Monitored": monitored,
        "Latitude": "",
        "Longitude": "",
        "OriginCode": "",
        "DestinationCode": "",
    }


@pytest.mark.parametrize(
    ("raw", "enabled"),
    [
        ("true", True),
        ("TRUE", False),
        ("True", False),
        ("1", False),
        ("yes", False),
        ("", False),
        (" true ", False),
        ("true ", False),
        (" true", False),
        ('"true"', False),
        ("'true'", False),
    ],
)
def test_only_exact_true_enables_demo_mode(monkeypatch, raw, enabled):
    if raw == "":
        monkeypatch.delenv("DEMO_MODE", raising=False)
    else:
        monkeypatch.setenv("DEMO_MODE", raw)
    assert demo.demo_enabled() is enabled


def test_missing_file_and_unset_environment_disable_demo_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(lta_static, "ENV_PATH", tmp_path / "missing.env")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert demo.demo_enabled() is False


def test_empty_file_value_disables_even_if_the_process_value_is_true(monkeypatch):
    lta_static.ENV_PATH.write_text("DEMO_MODE=\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_MODE", "true")
    assert demo.demo_enabled() is False


def test_file_value_must_be_exactly_true(monkeypatch):
    lta_static.ENV_PATH.write_text("DEMO_MODE=TRUE\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_MODE", "true")
    assert demo.demo_enabled() is False
    lta_static.ENV_PATH.write_text("DEMO_MODE=true\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_MODE", "yes")
    assert demo.demo_enabled() is True


@pytest.mark.parametrize(
    "raw",
    ["", "TRUE", "True", "1", "yes", " true ", "true ", " true", '"true"', "'true'"],
)
def test_quoted_or_padded_file_values_do_not_enable_demo_mode(monkeypatch, raw):
    lta_static.ENV_PATH.write_text(f"DEMO_MODE={raw}\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_MODE", "true")
    assert demo.demo_enabled() is False


def test_browser_cannot_enable_demo_mode(monkeypatch):
    seen = _lta_gets(monkeypatch)
    with _client(monkeypatch, _cache()) as client:
        status = client.get("/api/demo", params={"DEMO_MODE": "true"})
        blocked = client.post("/api/demo/run", json={"scenario": demo.LTA_TIMEOUT, "enabled": True})
        arrival = client.get("/api/arrivals", params={"stop_code": ORIGIN, "service_no": "18", "DEMO_MODE": "true"})
    assert status.status_code == 200
    assert status.json()["enabled"] is False
    assert status.json()["active"] is None
    assert blocked.status_code == 404
    assert demo.public_status()["active"] is None
    assert arrival.status_code == 503
    assert "simulated" not in arrival.json()
    assert any(url.endswith("/v3/BusArrival") for url in seen)
    assert "DEMO_MODE" not in INDEX.read_text(encoding="utf-8")
    assert "localStorage" not in INDEX.read_text(encoding="utf-8")


def test_demo_controls_exist_and_stay_hidden_until_the_server_enables_them():
    html = INDEX.read_text(encoding="utf-8")
    assert html.count("setInterval(") == 3
    assert '<div id="demo-banner" class="alert alert--simulated" hidden>' in html and "SIMULATED DEMO MODE</p></div>" in html
    assert '<details id="demo-controls" hidden>' in html
    assert "<summary>Demo Controls</summary>" in html
    assert 'id="demo-run">Run Scenario</button>' in html
    assert 'id="demo-reset">Reset to Live</button>' in html
    options = [
        "LTA API Timeout / Proxy Error",
        "Stale Data Poll",
        "Schedule-Only / Monitored = 0",
        "GPS Fix/Age Penalty",
        "Auto-Reroute Opportunity",
        "OneMap Zero Results / API Error",
        "Unsafe / Contradictory OpenAI Output",
    ]
    select = html.split('id="demo-scenario">', 1)[1].split("</select>", 1)[0]
    assert select.count("<option>") == 7
    for name in options:
        assert f"<option>{name}</option>" in select
    assert "banner.hidden = enabled !== true" in html
    assert "controls.hidden = enabled !== true" in html
    assert "[SIMULATED]" in html
    assert "Notification.requestPermission" in html
    assert html.count("Notification.requestPermission") == 1


def test_enabled_status_lists_the_seven_scenarios_and_no_secrets(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("LTA_ACCOUNT_KEY", KEY)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("ONEMAP_EMAIL", ONEMAP_SECRET)
    with _client(monkeypatch, _cache()) as client:
        body = client.get("/api/demo").json()
        page = client.get("/")
    assert body["enabled"] is True
    assert body["scenarios"] == list(demo.SCENARIOS)
    assert body["active"] is None
    dumped = json.dumps(body) + page.text
    assert KEY not in dumped
    assert SECRET not in dumped
    assert ONEMAP_SECRET not in dumped


def test_lta_timeout_is_unavailable_and_leaves_other_providers_live(monkeypatch):
    _enable(monkeypatch)
    assert demo.run_scenario(demo.LTA_TIMEOUT) is True
    seen = _lta_gets(monkeypatch)
    searches = []

    def spy_search(client, token, query):
        searches.append(query)
        return {"found": 0, "results": []}

    monkeypatch.setattr("onemap._search_once", spy_search)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", lta_static.ENV_PATH.parent / "no-observations.db")
    with _client(monkeypatch, _cache()) as client:
        failed = client.get(
            "/api/arrivals",
            params={"stop_code": ORIGIN, "service_no": "18", "lat": LAT, "lon": LON, "accuracy": 10},
        )
    session = OneMapSession()
    session.token = "token"
    found = search_destinations("Raffles Place", session=session, client=httpx.Client(), token="token")
    assert failed.status_code == 503
    body = failed.json()
    assert body["status"] == "unavailable"
    assert body["simulated"] is True
    assert "buses" not in body
    assert "point" not in failed.text
    assert "probability" not in failed.text
    assert "arrival_time" not in failed.text
    assert "leave_by" not in failed.text
    assert "leave_now" not in failed.text
    assert "reroute" not in failed.text
    assert not any(url.endswith("/v3/BusArrival") for url in seen)
    assert searches == ["Raffles Place"]
    assert found["results"] == []
    assert not (lta_static.ENV_PATH.parent / "no-observations.db").exists()


def test_stale_fixture_is_older_than_120_seconds_and_does_not_alert(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.STALE_POLL)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", lta_static.ENV_PATH.parent / "stale.db")
    with _client(monkeypatch, _cache()) as client:
        response = client.get(
            "/api/arrivals",
            params={"stop_code": ORIGIN, "service_no": "18", "lat": LAT, "lon": LON, "accuracy": 10},
        )
    body = response.json()
    fetched = datetime.fromisoformat(body["fetched_at"])
    age = datetime.now(SGT) - fetched
    assert response.status_code == 200
    assert age.total_seconds() > 120
    assert body["simulated"] is True
    assert body["demo_stale"] is True
    assert body["leave_now"] is None
    assert "reroute" not in body
    assert body["buses"][0]["arrival_time"]
    assert "STALE_MS = 60000" in INDEX.read_text(encoding="utf-8")
    assert "(Date.now() - fetchedAt) > STALE_MS" in INDEX.read_text(encoding="utf-8")
    assert not (lta_static.ENV_PATH.parent / "stale.db").exists()


def test_schedule_only_uses_the_real_cap_and_frequency_adjustment(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.SCHEDULE_ONLY)
    moment = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
    short = _cache([_service("18", "4-4")])
    fallback = _cache([])
    capped = arrivals.fetch_arrivals(
        ORIGIN, "18", account_key=KEY, now=moment, user_lat=LAT, user_lon=LON,
        accuracy=10, cache=short,
    )
    wider = arrivals.fetch_arrivals(
        ORIGIN, "18", account_key=KEY, now=moment, user_lat=LAT, user_lon=LON,
        accuracy=10, cache=fallback,
    )
    capped_bus = capped["buses"][0]
    wider_bus = wider["buses"][0]
    assert capped_bus["monitored"] is False
    assert capped_bus["probability"]["data_quality"] == "schedule"
    assert capped_bus["probability"]["range_high"] == 60
    assert wider_bus["probability"]["range_high"] == 60
    assert capped_bus["probability"]["range_low"] < 60
    assert wider_bus["probability"]["range_low"] < capped_bus["probability"]["range_low"]
    assert to_percent(catch_probability(160)) > 60
    assert catch_heuristic.SCHEDULE_CEILING == 0.60
    assert "catch_probability" not in (ROOT / "demo.py").read_text(encoding="utf-8")


def test_schedule_poll_is_logged_on_the_existing_observations_table(monkeypatch, tmp_path):
    _enable(monkeypatch)
    demo.run_scenario(demo.SCHEDULE_ONLY)
    database = tmp_path / "observations.db"
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", database)
    with _client(monkeypatch, _cache([_service("18", "4-4")])) as client:
        response = client.get(
            "/api/arrivals",
            params={
                "stop_code": ORIGIN,
                "service_no": "18",
                "lat": LAT,
                "lon": LON,
                "accuracy": 10,
            },
        )
    assert response.status_code == 200
    assert response.json()["simulated"] is True
    with sqlite3.connect(database) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        columns = [row[1] for row in connection.execute("PRAGMA table_info(observations)")]
        row = connection.execute("SELECT data_quality, p_high, reroute_fired FROM observations").fetchone()
        count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    assert "observations" in tables
    assert not any(name != "observations" and name != "sqlite_sequence" for name in tables)
    assert columns == [
        "id", "timestamp", "stop_code", "service", "direction", "eta", "monitored",
        "bus_lat", "bus_lon", "user_lat", "user_lon", "gps_accuracy", "walk_metres",
        "slack_seconds", "p", "p_low", "p_high", "data_quality", "reroute_fired", "reroute_reason",
    ]
    assert row[0] == "schedule"
    assert row[1] == 60
    assert row[2] == 0


def test_gps_penalty_widens_the_low_side_and_blocks_leave_now_and_reroute(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.GPS_PENALTY)
    now = datetime.now(SGT)
    soon = (now + timedelta(seconds=65)).replace(microsecond=0).isoformat()
    later = (now + timedelta(seconds=233)).replace(microsecond=0).isoformat()
    payload = {
        "Services": [{
            "ServiceNo": "18",
            "NextBus": _bus_json(soon),
            "NextBus2": _bus_json(later),
        }]
    }
    seen = _lta_gets(monkeypatch, payload, status_code=200)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", lta_static.ENV_PATH.parent / "gps.db")
    dest_lat, dest_lon = _north(2000)
    params = {
        "stop_code": ORIGIN,
        "service_no": "18",
        "lat": LAT,
        "lon": LON,
        "accuracy": 10,
        "location_timestamp": now.timestamp(),
        "destination_stop_code": DEST,
        "dest_lat": dest_lat,
        "dest_lon": dest_lon,
    }
    with _client(monkeypatch, _cache(alternate=True)) as client:
        uncertain = client.get("/api/arrivals", params=params)
        demo.reset_to_live()
        certain = client.get("/api/arrivals", params=params)
    uncertain_body = uncertain.json()
    certain_body = certain.json()
    uncertain_score = uncertain_body["buses"][0]["probability"]
    certain_score = certain_body["buses"][0]["probability"]
    assert uncertain.status_code == 200
    assert uncertain_body["simulated"] is True
    assert uncertain_score["data_quality"] == "location uncertain"
    assert uncertain_score["range_low"] < certain_score["range_low"]
    assert uncertain_body["leave_now"]["eligible"] is False
    assert uncertain_body["reroute"]["switched"] is False
    assert certain_body["reroute"]["switched"] is True
    assert any(url.endswith("/v3/BusArrival") for url in seen)
    assert catch_heuristic.UNCERTAIN_ACCURACY_M == 100
    assert catch_heuristic.UNCERTAIN_AGE_S == 60.0
    assert demo.GPS_ACCURACY_M > 100
    assert demo.GPS_AGE_S > 60


def test_reroute_scenario_uses_step_11_and_logs_the_switch(monkeypatch, tmp_path):
    _enable(monkeypatch)
    demo.run_scenario(demo.REROUTE)
    database = tmp_path / "observations.db"
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", database)
    seen = _lta_gets(monkeypatch)
    dest_lat, dest_lon = _north(2000)
    with _client(monkeypatch, _cache(alternate=True)) as client:
        response = client.get(
            "/api/arrivals",
            params={
                "stop_code": ORIGIN,
                "service_no": "18",
                "lat": LAT,
                "lon": LON,
                "accuracy": 10,
                "location_timestamp": time.time(),
                "destination_stop_code": DEST,
                "dest_lat": dest_lat,
                "dest_lon": dest_lon,
            },
        )
    body = response.json()
    decision = body["reroute"]
    assert response.status_code == 200
    assert body["simulated"] is True
    assert decision["switched"] is True
    assert decision["reroute"]["destination_stop_code"] == DEST
    assert decision["reroute"]["title"] == "Route Updated"
    primary = next(bus for bus in body["buses"] if bus["is_primary"])
    assert primary["probability"]["range_high"] < 40
    assert decision["reroute"]["probability_line"]
    assert "Route Updated" not in (ROOT / "demo.py").read_text(encoding="utf-8")
    assert not any(url.endswith("/v3/BusArrival") for url in seen)
    assert reroute.NORMAL_MARGIN == 15
    assert reroute.RANGE_HIGH_BELOW == 40
    assert leave_now.LEAVE_NOW_MARGIN_S == 60
    with sqlite3.connect(database) as connection:
        fired = connection.execute(
            "SELECT reroute_fired, reroute_reason FROM observations WHERE reroute_fired = 1"
        ).fetchall()
    assert len(fired) == 1
    assert fired[0][1]
    html = INDEX.read_text(encoding="utf-8")
    assert 'Notification.permission !== "granted"' in html
    assert "startMonitoring(reroute.service_no)" in html


def test_onemap_zero_results_and_api_error_do_not_guess_a_place(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.ONEMAP_FAILURE)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"found": 1, "results": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        session = OneMapSession()
        zero = search_destinations("nowhere", session=session, client=http, token="token")
        demo.run_scenario(demo.ONEMAP_FAILURE)
        with pytest.raises(Exception) as caught:
            search_destinations("nowhere", session=session, client=http, token="token")
    assert zero == {"status": "ok", "query": "nowhere", "results": [], "simulated": True}
    assert caught.value.status == "unavailable"
    assert calls == []
    assert "latitude" not in json.dumps(zero)
    with _client(monkeypatch, _cache()) as client:
        failed = client.get("/api/destinations", params={"q": "nowhere"})
    assert failed.status_code == 503
    assert failed.json()["status"] == "unavailable"
    assert failed.json()["simulated"] is True
    assert "Orchard" not in failed.text


def test_openai_unsafe_contradictory_and_timeout_use_the_guardrails(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(explain, "ENV_PATH", lta_static.ENV_PATH)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert explain.read_openai_api_key() == ""
    constructed = []
    seen = []
    real_interpret = explain.interpret_explanation

    class Marker:
        def __init__(self, *args, **kwargs):
            constructed.append("openai")
            raise AssertionError("live OpenAI")

    def spy(raw, fact_sheet):
        seen.append(raw)
        return real_interpret(raw, fact_sheet)

    monkeypatch.setattr("openai.OpenAI", Marker)
    monkeypatch.setattr(explain, "interpret_explanation", spy)
    fact = _sheet()
    demo.run_scenario(demo.OPENAI_GUARD)
    unsafe_status, unsafe = explain.handle_explain_request(_body(fact))
    demo.run_scenario(demo.OPENAI_GUARD)
    contrary_status, contrary = explain.handle_explain_request(_body(fact))
    started = time.monotonic()
    demo.run_scenario(demo.OPENAI_GUARD)
    timeout_status, timed = explain.handle_explain_request(_body(fact))
    elapsed = time.monotonic() - started
    clause = explain.ACTION_ADVICE["wait"]
    assert unsafe_status == contrary_status == timeout_status == 200
    assert len(seen) == 2
    unsafe_body = seen[0]["body"]
    contrary_body = seen[1]["body"]
    assert set(unsafe_body) == set(contrary_body) == {"advice"}  # the new schema: one field
    assert not explain.advice_is_valid(unsafe_body["advice"], "wait") and explain.contains_unsafe(unsafe_body["advice"])
    assert not explain.advice_is_valid(contrary_body["advice"], "wait")  # digits and a promise
    for view in (unsafe, contrary, timed):
        assert view["source"] == "fallback"
        assert view["advice"] == clause  # the deterministic clause
        assert view["clause"] == f"It is advisable to {clause}."
        assert "run" not in view["clause"].lower().split() and "jaywalk" not in view["clause"]
        assert view["snapshot"].startswith("36|01011|")  # every reply carries the key of its poll
    assert elapsed < 1
    assert constructed == []
    assert SECRET not in json.dumps([unsafe, contrary, timed])
    assert demo.OPENAI_DEMO_ELAPSED_S > explain.TIMEOUT_SECONDS
    demo.reset_to_live()
    missing = explain.produce_explanation(fact)
    assert missing["source"] == "fallback" and missing["advice"] == clause
    assert constructed == []
    assert "alert(" not in INDEX.read_text(encoding="utf-8")


def test_openai_scenario_leaves_lta_and_onemap_live(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.OPENAI_GUARD)
    seen = _lta_gets(monkeypatch)
    searches = []

    def spy_search(client, token, query):
        searches.append(query)
        return {"found": 0, "results": []}

    monkeypatch.setattr("onemap._search_once", spy_search)
    with _client(monkeypatch, _cache()) as client:
        client.get("/api/arrivals", params={"stop_code": ORIGIN, "service_no": "18"})
    session = OneMapSession()
    session.token = "token"
    search_destinations("City Hall", session=session, client=httpx.Client(), token="token")
    assert any(url.endswith("/v3/BusArrival") for url in seen)
    assert searches == ["City Hall"]


def test_switching_scenarios_and_reset_drop_the_previous_fixture(monkeypatch):
    _enable(monkeypatch)
    seen = _lta_gets(monkeypatch)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", lta_static.ENV_PATH.parent / "switch.db")
    with _client(monkeypatch, _cache()) as client:
        client.post("/api/demo/run", json={"scenario": demo.LTA_TIMEOUT})
        timed = client.get("/api/arrivals", params={"stop_code": ORIGIN, "service_no": "18"})
        client.post("/api/demo/run", json={"scenario": demo.SCHEDULE_ONLY})
        scheduled = client.get(
            "/api/arrivals",
            params={"stop_code": ORIGIN, "service_no": "18", "lat": LAT, "lon": LON, "accuracy": 10},
        )
        client.post("/api/demo/reset")
        live = client.get("/api/arrivals", params={"stop_code": ORIGIN, "service_no": "18"})
        status = client.get("/api/demo").json()
    assert timed.status_code == 503
    assert timed.json()["simulated"] is True
    assert scheduled.status_code == 200
    assert scheduled.json()["buses"][0]["monitored"] is False
    assert scheduled.json()["simulated"] is True
    assert live.status_code == 503
    assert "simulated" not in live.json()
    assert status["enabled"] is True
    assert status["active"] is None
    assert any(url.endswith("/v3/BusArrival") for url in seen)
    assert "startDemoControls" in INDEX.read_text(encoding="utf-8")
    assert 'fetch("/api/demo/reset"' in INDEX.read_text(encoding="utf-8")


def test_reload_reset_does_not_restore_a_scenario(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.STALE_POLL)
    demo.reset_to_live()
    assert demo.public_status()["enabled"] is True
    assert demo.public_status()["active"] is None
    assert demo.lta_script_active() is False


def test_simulated_leave_by_is_marked_and_a_stale_or_failed_poll_is_not():
    html = INDEX.read_text(encoding="utf-8")
    assert '<p id="journey-leave-by-simulated" class="simulated-badge" hidden>[SIMULATED]</p>' in html
    rendered = html.split("function renderJourneyLeaveBy()", 1)[1].split("function renderJourney(", 1)[0]
    assert rendered.count("setLeaveBySimulated(false)") >= 2
    assert "setLeaveBySimulated(lastSuccess.simulated === true)" in rendered
    assert 'journeyLeaveBy.textContent = "Leave-by: " + formatTime(lastSuccess.leave_by, true);' in rendered
    marks = html.split("function clearSimulatedMarks()", 1)[1].split("function clearDemoIntercept", 1)[0]
    assert "setLeaveBySimulated(false)" in marks
    reset = html.split("function clearDemoIntercept()", 1)[1].split("function runDemoScenario", 1)[0]
    assert "clearSimulatedMarks()" in reset


def test_failed_reset_keeps_the_demo_banner_and_simulated_marks():
    html = INDEX.read_text(encoding="utf-8")
    reset = html.split("function clearDemoIntercept()", 1)[1].split("function runDemoScenario", 1)[0]
    assert "if (!response.ok)" in reset
    assert 'typeof body.enabled !== "boolean"' in reset
    assert "showDemoChrome(false)" not in reset
    assert reset.index("clearSimulatedMarks()") > reset.index('typeof body.enabled !== "boolean"')
    assert reset.index("requestArrivals(monitorGeneration)") > reset.index('typeof body.enabled !== "boolean"')
    assert "alert(" not in reset


def test_onemap_scenario_leaves_lta_and_openai_live(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.ONEMAP_FAILURE)
    seen = _lta_gets(monkeypatch)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", lta_static.ENV_PATH.parent / "onemap-live.db")
    with _client(monkeypatch, _cache()) as client:
        arrival = client.get("/api/arrivals", params={"stop_code": ORIGIN, "service_no": "18"})
    assert arrival.status_code == 503
    assert "simulated" not in arrival.json()
    assert any(url.endswith("/v3/BusArrival") for url in seen)
    assert demo.simulated_openai_result(_sheet()) is None
    monkeypatch.setattr(explain, "read_openai_api_key", lambda: "sk-live-not-used")
    constructed = []

    class Marker:
        def __init__(self, *args, **kwargs):
            constructed.append("openai")
            raise AssertionError("live OpenAI")

    monkeypatch.setattr("openai.OpenAI", Marker)
    with pytest.raises(AssertionError, match="live OpenAI"):
        explain.produce_explanation(_sheet())
    assert constructed == ["openai"]


def test_lta_timeout_leaves_openai_live(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.LTA_TIMEOUT)
    assert demo.simulated_openai_result(_sheet()) is None
    monkeypatch.setattr(explain, "read_openai_api_key", lambda: "sk-live-not-used")
    constructed = []

    class Marker:
        def __init__(self, *args, **kwargs):
            constructed.append("openai")
            raise AssertionError("live OpenAI")

    monkeypatch.setattr("openai.OpenAI", Marker)
    with pytest.raises(AssertionError, match="live OpenAI"):
        explain.produce_explanation(_sheet())
    assert constructed == ["openai"]


def test_stale_card_keeps_the_eta_and_does_not_render_a_percentage(monkeypatch):
    _enable(monkeypatch)
    demo.run_scenario(demo.STALE_POLL)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", lta_static.ENV_PATH.parent / "stale-ui.db")
    with _client(monkeypatch, _cache()) as client:
        response = client.get(
            "/api/arrivals",
            params={"stop_code": ORIGIN, "service_no": "18", "lat": LAT, "lon": LON, "accuracy": 10},
        )
    body = response.json()
    assert body["demo_stale"] is True
    assert body["buses"][0]["arrival_time"]
    assert body["leave_now"] is None
    assert "reroute" not in body
    assert not (lta_static.ENV_PATH.parent / "stale-ui.db").exists()
    html = INDEX.read_text(encoding="utf-8")
    branch = html.split("result.body.simulated && isFinite(fetchedAt)", 1)[1].split("applySuccess(result.body)", 1)[0]
    assert "freezeStale();" in branch
    assert "return;" in branch
    frozen = html.split("function freezeStale()", 1)[1].split("function refreshDisplay", 1)[0]
    assert 'arrivalStatus.textContent = "Status: Stale / Unavailable"' in frozen
    assert "renderBusCards(lastSuccess)" in frozen
    assert "clearLeaveNowTimer()" in frozen
    assert "syncLeaveNow" not in frozen
    assert "applyRouteSwitch" not in frozen
    # Stale keeps the last ETA on screen (bus tiles) but no percentage (probability card).
    cards = html.split("function renderBusCards(body)", 1)[1].split("function agoAmount", 1)[0]
    assert "renderCatchCard(hero)" in cards
    catch = html.split("function renderCatchCard(hero)", 1)[1].split("function renderLeaveTiles", 1)[0]
    assert "!displayFrozen && chance" in catch
    tiles = html.split("function renderNextBuses(buses, hero)", 1)[1].split("// Reserved rectangles", 1)[0]
    assert "countdownLabel(bus.arrival_time)" in tiles
    live = html.split("function renderLiveTracking()", 1)[1].split('document.getElementById("live-refresh")', 1)[0]
    assert "renderNextBuses(buses, hero)" in live


def test_reroute_cooldown_blocks_an_immediate_second_switch(monkeypatch, tmp_path):
    _enable(monkeypatch)
    demo.run_scenario(demo.REROUTE)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "cooldown.db")
    _lta_gets(monkeypatch)
    dest_lat, dest_lon = _north(2000)
    params = {
        "stop_code": ORIGIN,
        "service_no": "18",
        "lat": LAT,
        "lon": LON,
        "accuracy": 10,
        "location_timestamp": time.time(),
        "destination_stop_code": DEST,
        "dest_lat": dest_lat,
        "dest_lon": dest_lon,
    }
    with _client(monkeypatch, _cache(alternate=True)) as client:
        first = client.get("/api/arrivals", params=params)
        cooled = dict(params)
        cooled["last_reroute_at"] = datetime.now(SGT).isoformat()
        second = client.get("/api/arrivals", params=cooled)
    assert first.json()["reroute"]["switched"] is True
    assert second.status_code == 200
    assert second.json()["reroute"]["switched"] is False
    primary = next(bus for bus in second.json()["buses"] if bus["is_primary"])
    assert primary["probability"]["range_high"] < reroute.RANGE_HIGH_BELOW
    assert reroute.COOLDOWN_S == 120


def test_post_reroute_leave_by_and_leave_now_use_the_new_route(monkeypatch, tmp_path):
    _enable(monkeypatch)
    demo.run_scenario(demo.REROUTE)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "after.db")
    _lta_gets(monkeypatch)
    cache = _cache(alternate=True)
    dest_lat, dest_lon = _north(2000)
    params = {
        "stop_code": ORIGIN,
        "service_no": "18",
        "lat": LAT,
        "lon": LON,
        "accuracy": 10,
        "location_timestamp": time.time(),
        "destination_stop_code": DEST,
        "dest_lat": dest_lat,
        "dest_lon": dest_lon,
    }
    with _client(monkeypatch, cache) as client:
        first = client.get("/api/arrivals", params=params)
        winner = first.json()["reroute"]["reroute"]
        followed_params = {
            **params,
            "stop_code": winner["stop"]["stop_code"],
            "service_no": winner["service_no"],
        }
        same_target = winner["stop"]["stop_code"] == ORIGIN and winner["service_no"] == "18"
        if same_target:
            followed_params["pinned_eta"] = winner["eta_epoch"]
        followed = client.get("/api/arrivals", params=followed_params)
    first_body = first.json()
    assert first_body["reroute"]["switched"] is True
    assert winner["destination_stop_code"] == DEST
    body = followed.json()
    assert body["stop_code"] == winner["stop"]["stop_code"]
    assert body["service_no"] == winner["service_no"]
    if body["reroute"].get("switched"):
        assert body["reroute"]["reroute"]["destination_stop_code"] == DEST
    distance = journey._boarding_distance_m(cache, body["stop_code"], LAT, LON)
    expected = journey.leave_by_time(journey.parse_journey_time(winner["arrival_time"]), distance)
    actual = journey.parse_journey_time(body["leave_by"])
    assert abs((actual - expected).total_seconds()) < 1
    assert actual != journey.parse_journey_time(first_body["leave_by"])
    assert body["notification_time"] == leave_now.notification_time_iso(body["leave_by"])
    active = [bus for bus in body["buses"] if bus.get("is_active_target")]
    assert len(active) == 1
    assert body["leave_now"]["bus_id"] == (
        f"{winner['service_no']}|{winner['stop']['stop_code']}|{active[0]['position']}"
    )
    html = INDEX.read_text(encoding="utf-8")
    switch = html.split("function applyRouteSwitch(decision)", 1)[1].split("function highlightBoardingSelection", 1)[0]
    assert "selectedBoardingStop = reroute.stop" in switch
    assert "startMonitoring(reroute.service_no)" in switch
    assert "confirmedDestinationStop" not in switch


def test_scenario_state_is_cleared_on_reset_and_reload_and_is_not_stored(monkeypatch, tmp_path):
    _enable(monkeypatch)
    database = tmp_path / "observations.db"
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", database)
    demo.run_scenario(demo.SCHEDULE_ONLY)
    assert demo.public_status()["active"] == demo.SCHEDULE_ONLY
    assert not database.exists()
    demo.reset_to_live()
    assert demo.public_status()["enabled"] is True
    assert demo.public_status()["active"] is None
    demo.run_scenario(demo.STALE_POLL)
    assert demo.lta_script_active() is True
    demo.reset_to_live()
    assert demo.public_status()["active"] is None
    assert demo.lta_script_active() is False
    html = INDEX.read_text(encoding="utf-8")
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "startDemoControls" in html
    assert 'fetch("/api/demo/reset"' in html
    source = (ROOT / "demo.py").read_text(encoding="utf-8")
    assert "sqlite" not in source.lower()
    assert "open(" not in source
    assert not database.exists()


def test_step_formulas_stay_at_their_locked_values():
    assert catch_heuristic.POINT_WALK_M_S == 1.25
    assert catch_heuristic.SLOW_WALK_M_S == 1.1
    assert catch_heuristic.BOARDING_BUFFER_S == 45
    assert explain.TIMEOUT_SECONDS == 3
    assert "background" not in (ROOT / "demo.py").read_text(encoding="utf-8").lower()

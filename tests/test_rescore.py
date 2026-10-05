"""Page W's rescore: the poll's own scoring from a short-lived copy of the latest arrivals, with no LTA call.

Limits under test: arrival data only (never a position), TTL 60 s, a size cap, bypassed in Demo Mode, "use the poll"
when the copy is old, the poll's own parameter names (so the log filter covers it), nothing stored, nothing logged.
"""

import json
import logging
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
from arrivals import RESCORE_MAX_ENTRIES, RESCORE_TTL_SECONDS, fetch_arrivals, remember_arrivals, rescore_latest
from lta_static import StopAndRouteCache
from main import app
from nearby import EARTH_RADIUS_M

import math

SGT = timezone(timedelta(hours=8))
LAT, LON = 1.3, 103.8
ORIGIN = "01011"
SECRET_LAT, SECRET_LON = 1.3027251, 103.8000017  # about 300 m from the stop; distinct digits to search for


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _cache():
    stops = [{"BusStopCode": ORIGIN, "Description": "Origin", "RoadName": "Orchard Rd", "Latitude": LAT, "Longitude": LON}]
    services = [{"ServiceNo": "18", "Direction": 1, "OriginCode": ORIGIN, "DestinationCode": "99999",
                 "AM_Offpeak_Freq": "10-10", "AM_Peak_Freq": "10-10", "PM_Peak_Freq": "10-10", "PM_Offpeak_Freq": "10-10"}]
    return StopAndRouteCache(stops, [], services)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(lta_static, "ENV_PATH", env)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    demo.reset_to_live()
    arrivals.clear_remembered_arrivals()
    yield
    arrivals.clear_remembered_arrivals()
    demo.reset_to_live()


class Lta:
    """A fake LTA that counts its calls."""

    def __init__(self, minutes=(10, 20, 30)):
        self.calls = 0
        self.minutes = minutes

    def __call__(self, self_client, url, *args, **kwargs):
        self.calls += 1
        service = {"ServiceNo": "18"}
        for name, minutes in zip(("NextBus", "NextBus2", "NextBus3"), self.minutes):
            eta = (datetime.now(SGT) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
            service[name] = {"EstimatedArrival": eta, "Monitored": 1, "Latitude": "", "Longitude": "", "OriginCode": "", "DestinationCode": ""}
        return httpx.Response(200, json={"Services": [service]})


@pytest.fixture
def lta(monkeypatch):
    fake = Lta()
    monkeypatch.setattr("main.load_static_data", _cache)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: "test-account-key")
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, *a, **k: fake(self, url))
    return fake


@pytest.fixture
def client(lta):
    with TestClient(app) as test_client:
        yield test_client


PARAMS = {"stop_code": ORIGIN, "service_no": "18", "lat": SECRET_LAT, "lon": SECRET_LON, "accuracy": 12}


def _poll(client, **extra):
    params = dict(PARAMS, location_timestamp=time.time(), **extra)
    response = client.get("/api/arrivals", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _rescore(client, **extra):
    params = dict(PARAMS, location_timestamp=time.time(), **extra)
    return client.get("/api/rescore", params=params)


# ---- it rescores without calling LTA, with the poll's own scoring

def test_rescore_uses_the_remembered_arrivals_and_makes_no_lta_call(client, lta):
    poll = _poll(client)
    assert lta.calls == 1
    body = _rescore(client).json()
    assert lta.calls == 1  # no new LTA call
    assert body["status"] == "ok" and body["rescored"] is True
    assert [bus["arrival_time"] for bus in body["buses"]] == [bus["arrival_time"] for bus in poll["buses"]]
    assert all(set(bus) == {"arrival_time", "monitored", "is_primary", "is_missed", "probability"} for bus in body["buses"])
    assert body["walk_speed_used"] == 1.25 and body["walk_speed_source"] == "default"
    assert body["leave_now_threshold_s"] == 60 and isinstance(body["near_stop"], bool)
    for _ in range(5):
        _rescore(client)
    assert lta.calls == 1  # five more rescores, still one LTA call


def test_the_same_inputs_give_the_same_probability_as_the_poll(client):
    now = datetime.now(SGT)
    stamp = now.timestamp()
    cache = _cache()
    with httpx.Client(transport=httpx.MockTransport(lambda r: Lta()(None, str(r.url)))) as http:
        polled = fetch_arrivals(ORIGIN, "18", client=http, account_key="k", now=now, user_lat=SECRET_LAT,
                                user_lon=SECRET_LON, accuracy=12, location_timestamp=stamp, cache=cache)
    again = rescore_latest(ORIGIN, "18", user_lat=SECRET_LAT, user_lon=SECRET_LON, accuracy=12, location_timestamp=stamp,
                           cache=cache, now=now)
    assert [bus["probability"] for bus in again["buses"]] == [bus["probability"] for bus in polled["buses"]]
    assert again["leave_by"] == polled["leave_by"]
    assert all(bus["probability"] is not None for bus in again["buses"])


def test_a_newer_fix_changes_the_score_and_the_walk_speed_is_used(client):
    _poll(client)
    near = _rescore(client, **{}).json()["buses"][0]["probability"]
    far = client.get("/api/rescore", params=dict(PARAMS, lat=_north(900)[0], lon=LON, location_timestamp=time.time())).json()
    assert far["buses"][0]["probability"]["point"] < near["point"]
    slow = _rescore(client, walk_speed=0.8, walk_speed_source="gps").json()
    assert slow["walk_speed_used"] == 0.8 and slow["walk_speed_source"] == "gps"
    assert slow["buses"][0]["probability"]["point"] <= near["point"]


# ---- "use the poll"

def test_no_copy_says_use_the_poll(client, lta):
    body = _rescore(client).json()
    assert body == {"status": "use_poll", "reason": "no_recent_arrivals", "near_stop": False}  # 300 m from the stop
    assert lta.calls == 0


def test_a_copy_older_than_60_seconds_says_use_the_poll_and_is_dropped(client, monkeypatch):
    _poll(client)
    assert _rescore(client).json()["status"] == "ok"
    real = time.monotonic
    monkeypatch.setattr(arrivals.time, "monotonic", lambda: real() + RESCORE_TTL_SECONDS + 1)
    assert RESCORE_TTL_SECONDS == 60
    assert _rescore(client).json()["status"] == "use_poll"
    assert (ORIGIN, "18") not in arrivals._latest_arrivals


def test_the_copy_is_bypassed_in_demo_mode(client, monkeypatch):
    monkeypatch.setattr(demo, "demo_enabled", lambda *a, **k: True)
    _poll(client)
    assert arrivals._latest_arrivals == {}  # nothing is remembered in Demo Mode
    assert _rescore(client).json() == {"status": "use_poll", "reason": "demo"}


# ---- what the copy holds and its size

def test_the_copy_holds_arrival_data_only_never_a_position_or_a_score(client):
    _poll(client, walk_speed=1.1, walk_speed_source="gps")
    stored = json.dumps(arrivals._latest_arrivals[(ORIGIN, "18")][1])
    for secret in (str(SECRET_LAT), str(SECRET_LON), "1.3027251", "103.8000017"):
        assert secret not in stored
    for key in ("probability", "leave_by", "walk_speed", "accuracy", "user_lat", "user_lon", "lat\":", "lon\":"):
        assert key not in stored, key
    assert set(arrivals._latest_arrivals[(ORIGIN, "18")][1]) <= {"status", "stop_code", "service_no", "fetched_at", "buses"}


def test_the_copy_is_capped_and_old_entries_expire(monkeypatch):
    for index in range(RESCORE_MAX_ENTRIES + 20):
        remember_arrivals(f"{index:05d}", "18", {"status": "ok", "buses": [], "fetched_at": "x"})
    assert len(arrivals._latest_arrivals) == RESCORE_MAX_ENTRIES
    assert ("00000", "18") not in arrivals._latest_arrivals  # the oldest went first
    real = time.monotonic
    monkeypatch.setattr(arrivals.time, "monotonic", lambda: real() + RESCORE_TTL_SECONDS + 1)
    remember_arrivals("99999", "18", {"status": "ok", "buses": [], "fetched_at": "x"})
    assert list(arrivals._latest_arrivals) == [("99999", "18")]  # the expired ones were pruned


# ---- the poll's own parameter names, nothing stored, nothing logged

def test_the_rescore_query_uses_the_polls_parameter_names_and_the_log_filter_covers_them(caplog):
    import inspect

    import main

    names = set(inspect.signature(main.rescore).parameters)
    assert names == {"stop_code", "service_no", "lat", "lon", "accuracy", "location_timestamp", "walk_speed", "walk_speed_source"}
    poll_names = set(inspect.signature(main.arrivals).parameters)
    assert names <= poll_names  # the same names as the poll
    assert {"lat", "lon", "accuracy", "location_timestamp", "walk_speed", "walk_speed_source"} <= access_log_filter.PRIVATE_QUERY_PARAMS
    access_log_filter.install()
    logger = logging.getLogger("uvicorn.access")
    path = (f"/api/rescore?stop_code={ORIGIN}&service_no=18&lat={SECRET_LAT}&lon={SECRET_LON}&accuracy=12"
            "&location_timestamp=5&walk_speed=1.1&walk_speed_source=gps")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", path, "1.1", 200)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert f"stop_code={ORIGIN}" in text and "service_no=18" in text
    for secret in ("1.3027251", "103.8000017", "accuracy=", "walk_speed", "location_timestamp="):
        assert secret not in text, secret


def test_a_rescore_logs_nothing_and_stores_nothing(client, caplog, capsys, tmp_path):
    _poll(client)
    database = observations.DEFAULT_DB_PATH
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    with caplog.at_level(0):
        for _ in range(3):
            assert _rescore(client).json()["status"] == "ok"
    output = capsys.readouterr()
    # the test client's own httpx logger prints the request it sends; the app's loggers are what count
    app_records = [r.getMessage() for r in caplog.records if not r.name.startswith(('httpx', 'httpcore'))]
    logged = " ".join(app_records) + output.out + output.err
    for secret in ("1.3027251", "103.8000017", "lat=", "lon="):
        assert secret not in logged, secret
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == before  # no observation row
    assert [path for path in tmp_path.iterdir() if path.name not in ("demo.env", "observations.db")] == []


def test_rescore_validates_its_query(client):
    assert client.get("/api/rescore", params={"stop_code": ORIGIN, "service_no": "18"}).status_code == 422
    bad = client.get("/api/rescore", params=dict(PARAMS, accuracy=-1))
    assert bad.status_code == 422
    assert client.get("/api/rescore", params=dict(PARAMS, location_timestamp=-5)).status_code == 422

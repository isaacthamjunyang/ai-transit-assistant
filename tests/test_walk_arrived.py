"""Page W's "Arrived": the server's near_stop (the poll's own function and 30 m rule), asked by the rescore."""

import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import arrivals
import demo
import lta_static
import observations
from main import app
from pace import PACE_HIDE_DISTANCE_M, is_near_stop

from page_runner import require_edge, run_scenario, running_app
from test_rescore import LAT, LON, Lta, ORIGIN, _cache, _north

SGT = timezone(timedelta(hours=8))


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


@pytest.fixture
def client(monkeypatch):
    fake = Lta()
    monkeypatch.setattr("main.load_static_data", _cache)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: "test-account-key")
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, *a, **k: fake(self, url))
    with TestClient(app) as test_client:
        yield test_client


def _params(metres):
    return {"stop_code": ORIGIN, "service_no": "18", "lat": _north(metres)[0], "lon": LON, "accuracy": 8,
            "location_timestamp": time.time()}


@pytest.mark.parametrize("metres, near", [(12, True), (29, True), (29.9, True), (31, False), (60, False), (300, False)])
def test_the_rescore_and_the_poll_say_the_same_near_stop_at_the_same_distance(client, metres, near):
    poll = client.get("/api/arrivals", params=_params(metres)).json()
    rescored = client.get("/api/rescore", params=_params(metres)).json()
    assert rescored["status"] == "ok"
    assert poll["near_stop"] is near and rescored["near_stop"] is near  # one function (pace.is_near_stop), one constant
    assert is_near_stop(metres) is near and PACE_HIDE_DISTANCE_M == 30


def test_use_poll_answers_carry_near_stop_too(client):
    # no copy of the arrivals yet: the answer is "use_poll" but the near_stop flag is still the server's 30 m rule
    near = client.get("/api/rescore", params=_params(12)).json()
    far = client.get("/api/rescore", params=_params(31)).json()
    assert near == {"status": "use_poll", "reason": "no_recent_arrivals", "near_stop": True}
    assert far == {"status": "use_poll", "reason": "no_recent_arrivals", "near_stop": False}


def test_the_threshold_is_the_polls_own_constant_not_a_new_one():
    import inspect

    import main

    source = inspect.getsource(main.rescore)
    assert "_near_stop(cache" in source and "PACE_HIDE" not in source and "< 30" not in source and "<= 30" not in source  # reused
    assert "is_near_stop" in inspect.getsource(main._near_stop)


@pytest.fixture(scope="module")
def arrived(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("arrived"), eta_minutes=[10.3]) as base:
        return run_scenario("walkarrived", base, {"dark": True})["result"]


def test_31_m_is_not_arrived_and_29_m_is_within_one_rescore_interval(arrived):
    limit = arrived["interval"] + 1500  # one 5 s rescore interval plus the request
    steps = arrived["steps"]
    assert steps["at31"]["nearStop"] is False and arrived["at31After"]["state"] != "Arrived"
    assert steps["to29"]["text"] == "Arrived" and steps["to29"]["ms"] is not None and steps["to29"]["ms"] <= limit, steps["to29"]
    assert steps["to29"]["nearStop"] is True


def test_back_from_29_to_31_m_leaves_arrived(arrived):
    limit = arrived["interval"] + 1500
    step = arrived["steps"]["back31"]
    assert step["ms"] is not None and step["ms"] <= limit and step["text"] != "Arrived", step
    assert arrived["back31After"]["nearStop"] is False and arrived["back31After"]["state"] != "Arrived"


def test_12_m_shows_arrived_and_it_beats_the_movement_states(arrived):
    assert arrived["steps"]["to12"]["text"] == "Arrived" and arrived["steps"]["to12"]["ms"] <= arrived["interval"] + 1500
    assert arrived["priority"]["state"] == "Arrived"
    fresh = arrived["freshOpen"]
    assert fresh["text"] == "Arrived" and fresh["span"] < 10000 and fresh["ms"] is not None  # not "Checking your movement…"
    assert fresh["ms"] <= 3000  # the rescore at opening already answered


def test_the_estimators_two_poll_latch_is_not_used_and_a_new_fix_asks_at_once():
    import re
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    block = page.split("// ---- Page W:", 1)[1].split("// Screen 8:", 1)[0]
    assert "isLatched" not in block and "noteNearStop" not in block and "paceEstimator.status().latched" not in block.split("function walkStateOf", 1)[1].split("function walkTrendNext", 1)[0]
    assert re.search(r"typeof body\.near_stop === \"boolean\"", block)  # the rescore's flag, in every answer
    assert "walkRescoreTick();" in block.split("function walkOnFix", 1)[1].split("function walkWatching", 1)[0]  # a new fix asks

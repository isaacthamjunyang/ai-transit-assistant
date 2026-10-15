"""Bus crowding: the LTA Load field (SEA, SDA, LSD) is carried as a display-only label. A blank, missing or unknown value
is None. It never changes the probability. No live service is called."""

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import catch_heuristic
from arrivals import fetch_arrivals
from test_arrivals import ACCOUNT_KEY, FETCHED, _client, _payload

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
SGT = timezone(timedelta(hours=8))


def _loads(values):
    payload = _payload()
    service = payload["Services"][0]
    for key, value in zip(("NextBus", "NextBus2", "NextBus3"), values):
        if value is _MISSING:
            service[key].pop("Load", None)
        else:
            service[key]["Load"] = value
    with _client(payload) as client:
        result = fetch_arrivals("08057", "36", client=client, account_key=ACCOUNT_KEY, now=FETCHED)
    return [bus["load"] for bus in result["buses"]]


_MISSING = object()


@pytest.mark.parametrize("code", ["SEA", "SDA", "LSD"])
def test_each_guide_value_is_carried(code):
    assert _loads([code, code, code]) == [code, code, code]


def test_blank_missing_and_unknown_values_are_none():
    assert _loads(["", _MISSING, "XYZ"]) == [None, None, None]
    assert _loads([None, 5, " sea "]) == [None, None, "SEA"]


def test_load_never_changes_the_probability():
    now = datetime(2026, 9, 29, 14, 54, 20, tzinfo=SGT)

    def scored(load):
        bus = {"position": "NextBus", "arrival_time": "2026-09-29T14:59:00+08:00", "monitored": True,
               "latitude": None, "longitude": None, "origin_code": None, "destination_code": None, "load": load}
        return catch_heuristic.score_buses(
            [bus], user_lat=1.3005, user_lon=103.8001, accuracy_m=18, stop_lat=1.3, stop_lon=103.8,
            services=[], routes=[], service_no="36", stop_code="08057", now=now,
        )[0]["probability"]

    base = scored(None)
    assert base is not None
    for code in ("SEA", "SDA", "LSD"):
        assert scored(code) == base


def test_the_page_shows_text_and_icon_from_one_place_and_the_plan_says_so():
    block = COPY.split("crowding: {", 1)[1].split("},", 1)[0]
    for key, text in (("SEA", "Seats"), ("SDA", "Standing"), ("LSD", "Crowded")):
        assert f'{key}: "{text}"' in block
    assert 'var CROWD_TEXT = { SEA: "Seats", SDA: "Standing", LSD: "Crowded" };' in INDEX
    assert "setCrowd(document.getElementById(\"catch-load\"), hero);" in INDEX and 'id="catch-load"' in INDEX
    assert "**Bus crowding.**" in PLAN and "The Bus Arrival `Load` field is ignored" not in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()  # the plan keeps its CRLF line endings


# ---- the real page --------------------------------------------------------------------------------------------

from page_runner import require_edge, run_scenario, running_app


def _page(tmp_path_factory, loads, width, dark, name):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), eta_minutes=[10.3, 16.3, 24.3], loads=loads) as base:
        return run_scenario("crowding", base, {"name": name, "width": width, "height": 800, "dark": dark},
                            timeout=300)["result"]


@pytest.fixture(scope="module", params=[(360, False), (1280, True)], ids=["360-light", "1280-dark"])
def shown(request, tmp_path_factory):
    width, dark = request.param
    return _page(tmp_path_factory, ["SEA", "SDA", "LSD"], width, dark, f"crowd{width}")


@pytest.fixture(scope="module")
def silent(tmp_path_factory):
    return _page(tmp_path_factory, ["", "XYZ"], 360, False, "crowdnone")


def test_the_tiles_and_page_a_show_a_word_and_an_icon(shown):
    assert [t["text"] for t in shown["pageB"]["tiles"]] == ["Seats", "Standing", "Crowded"]
    assert all(t["icon"] for t in shown["pageB"]["tiles"])
    assert shown["pageA"]["catchShown"] is True and shown["pageA"]["catchText"] == "Seats"
    assert shown["pageA"]["catchIcon"] is True
    assert shown["pageB"]["scrollWidth"] <= shown["pageB"]["innerWidth"]
    assert all(t["right"] <= shown["pageB"]["innerWidth"] for t in shown["pageB"]["tiles"])


def test_a_blank_or_unknown_value_draws_nothing(silent):
    assert silent["pageA"]["catchShown"] is False
    assert [t["text"] for t in silent["pageB"]["tiles"]] == [None, None, None]
    assert silent["pageB"]["loads"][:2] == [None, None]

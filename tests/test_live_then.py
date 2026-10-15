"""The live page's "Then ..." line shows the next leg's data type: Live (In n min, Arriving soon, Now) for a bus with a live
answer, Scheduled otherwise and always for a train. The answer is kept 90 s so the label does not flicker. Mock transports
only: nothing here calls LTA, OneMap or any other service."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
NB = " "
DOT = "·"


def _run(tmp_path_factory, name, builder, **config):
    require_edge()
    log = []
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode({"TRANSIT": builder}),
                     lta_services={"36": [4.5]}, lta_log=log) as base:
        out = run_scenario("livethen", base, {"name": name, **config})["result"]
    out["lta"] = log
    return out


@pytest.fixture(scope="module")
def narrow_light(tmp_path_factory):
    return _run(tmp_path_factory, "then_narrow", stub.bus_transfer, width=360, height=800)


@pytest.fixture(scope="module")
def wide_dark(tmp_path_factory):
    return _run(tmp_path_factory, "then_wide", stub.bus_transfer, width=1280, height=900, dark=True)


@pytest.fixture(scope="module")
def rail(tmp_path_factory):
    return _run(tmp_path_factory, "then_rail", stub.bus_rail, mode="rail", width=390)


@pytest.fixture(scope="module")
def single(tmp_path_factory):
    return _run(tmp_path_factory, "then_single", stub.bus_only, mode="single", width=390)


@pytest.mark.parametrize("fixture", ["narrow_light", "wide_dark"])
def test_page_b_draws_no_then_line_while_the_later_leg_is_looked_up(fixture, request):
    live = request.getfixturevalue(fixture)["live"]
    assert live["top"] == "arrivals" and live["thenElement"] is False
    assert "Then Bus" not in live["text"] and "Live " + DOT + " In" not in live["text"]
    assert live["kept"] is True and live["stops"] >= 1  # the answer is still fetched and kept internally
    assert live["right"] <= live["innerWidth"] and live["scrollWidth"] <= live["innerWidth"]


def test_the_live_answer_is_still_kept_for_90_seconds_and_survives_a_failed_lookup(wide_dark):
    assert wide_dark["at80"]["kept"] is True  # 80 s old: kept
    assert wide_dark["afterFailure"]["kept"] is True  # a failed lookup changes nothing
    assert wide_dark["at95"]["kept"] is False  # after 90 s without an answer it is dropped
    for key in ("at80", "afterFailure", "at95"):
        text = wide_dark[key]["text"].lower()
        assert "then bus" not in text and "scheduled " + DOT not in text and "error" not in text


def test_a_train_next_leg_is_never_looked_up_and_nothing_is_drawn(rail):
    assert rail["rail"]["thenElement"] is False and "Then North-South Line" not in rail["rail"]["text"]
    assert rail["requests"] == []
    assert all("NS17" not in str(query) for query in rail["lta"])  # no BusArrival call for the station


def test_a_journey_with_one_bus_makes_no_later_lookup(single):
    assert single["single"]["thenElement"] is False
    assert single["requests"] == []  # the first leg uses its own poll, unchanged


def test_the_first_leg_still_polls_and_the_later_lookup_sends_only_a_stop_and_services(narrow_light):
    queries = narrow_light["lta"]
    assert any(query.get("ServiceNo") == "18" for query in queries)  # the first bus: the existing per-service poll
    later = [query for query in queries if "ServiceNo" not in query]
    assert later and all(set(query) == {"BusStopCode"} for query in later)  # no position, no service number


def test_the_hold_and_the_lookup_code_are_what_the_plan_says():
    assert "var LATER_HOLD_MS = 90000;" in INDEX
    fn = INDEX.split("function laterLiveFor(leg)", 1)[1].split("function laterLiveText", 1)[0]
    assert "LATER_HOLD_MS" in fn and "STALE_MS" not in fn
    for gone in ("renderThenLine", "THEN_BUS_TEXT", "THEN_TRAIN_TEXT", "live-then"):
        assert gone not in INDEX, gone
    for fn_name in ("requestArrivals(", "renderCatchCard(", "syncCatchBar(", "handleSuccess("):
        if f"function {fn_name}" in INDEX:
            body = INDEX.split(f"function {fn_name}", 1)[1].split("\n    function ", 1)[0]
            assert "laterLiveFor" not in body and "laterCache" not in body, fn_name
    assert INDEX.count("setInterval(") == 3


def test_the_then_strings_are_gone_from_copy_js_the_page_and_the_guide():
    for text in ("thenBus", "thenTrain", "Then Bus {service} at {stop}", "Then {line} at {station}", "live-then"):
        assert text not in COPY and text not in INDEX and text not in GUIDE, text
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    assert ".live-then" not in css

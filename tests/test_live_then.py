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
def test_the_line_names_the_next_bus_and_says_live_with_the_minutes(fixture, request):
    live = request.getfixturevalue(fixture)["live"]
    assert live["shown"] and live["top"] == "arrivals"  # the bus card, Page B, is where the line is
    assert live["text"].startswith("Then Bus 36 at Opp Toh Guan Rd (03011)")
    assert re.fullmatch(r"Live " + DOT + r" In \d+" + NB + "min", live["when"]), live["when"]
    assert live["text"].endswith(live["when"].replace(NB, " "))  # the label sits on the same line element, under the words


@pytest.mark.parametrize("fixture", ["narrow_light", "wide_dark"])
def test_the_line_fits_at_360_and_1280_in_both_themes(fixture, request):
    live = request.getfixturevalue(fixture)["live"]
    assert live["right"] <= live["innerWidth"] and live["scrollWidth"] <= live["innerWidth"]
    assert live["width"] > 100 and live["color"].startswith("rgb")


def test_the_live_answer_is_kept_for_90_seconds_and_survives_a_failed_lookup(wide_dark):
    assert re.fullmatch(r"Live " + DOT + r" In \d+" + NB + "min", wide_dark["at80"]["when"])  # 80 s old: no flicker
    assert wide_dark["afterFailure"]["when"].startswith("Live " + DOT)  # a failed lookup changes nothing
    assert "error" not in wide_dark["afterFailure"]["text"].lower()


def test_after_90_seconds_without_an_answer_the_line_is_scheduled_with_no_error_text(wide_dark):
    after = wide_dark["at95"]
    assert re.fullmatch(r"Scheduled " + DOT + r" \d{1,2}:\d\d" + NB + "(AM|PM)( [(]tomorrow[)])?", after["when"]), after["when"]
    assert after["shown"] and after["text"].startswith("Then Bus 36 at")  # the line stays, only its label changes
    assert "error" not in after["text"].lower() and "unavailable" not in after["text"].lower()


def test_a_train_next_leg_always_says_scheduled_and_is_never_looked_up(rail):
    line = rail["rail"]
    assert line["shown"] and line["text"].startswith("Then North-South Line at Bishan MRT Station (NS17)")
    assert re.fullmatch(r"Scheduled " + DOT + r" \d{1,2}:\d\d" + NB + "(AM|PM)( [(]tomorrow[)])?", line["when"]), line["when"]
    assert rail["requests"] == []
    assert all("NS17" not in str(query) for query in rail["lta"])  # no BusArrival call for the station


def test_a_journey_with_one_bus_has_no_line_and_makes_no_later_lookup(single):
    assert single["single"]["shown"] is False
    assert single["requests"] == []  # the first leg uses its own poll, unchanged


def test_the_first_leg_still_polls_and_the_later_lookup_sends_only_a_stop_and_services(narrow_light):
    queries = narrow_light["lta"]
    assert any(query.get("ServiceNo") == "18" for query in queries)  # the first bus: the existing per-service poll
    later = [query for query in queries if "ServiceNo" not in query]
    assert later and all(set(query) == {"BusStopCode"} for query in later)  # no position, no service number


def test_the_hold_and_the_label_code_are_what_the_plan_says():
    assert "var LATER_HOLD_MS = 90000;" in INDEX
    fn = INDEX.split("function laterLiveFor(leg)", 1)[1].split("function laterLiveText", 1)[0]
    assert "LATER_HOLD_MS" in fn and "STALE_MS" not in fn
    then = INDEX.split("function renderThenLine(then, second)", 1)[1].split("function stepItem(", 1)[0]
    assert "legIsRail(next) ? null : laterLiveFor(next)" in then and "scheduleLine(next)" in then
    assert "setInterval" not in then and "fetch(" not in then  # no timer and no lookup of its own
    for fn_name in ("requestArrivals(", "renderCatchCard(", "syncCatchBar(", "handleSuccess("):
        if f"function {fn_name}" in INDEX:
            body = INDEX.split(f"function {fn_name}", 1)[1].split("\n    function ", 1)[0]
            assert "laterLiveFor" not in body and "laterCache" not in body and "renderThenLine" not in body, fn_name
    assert INDEX.count("setInterval(") == 3


def test_the_new_train_line_is_in_copy_js_and_the_page_and_the_guide_shows_the_line():
    assert 'thenTrain: "Then {line} at {station}"' in COPY and 'var THEN_TRAIN_TEXT = "Then {line} at {station}";' in INDEX
    guide = GUIDE.split("Live page line under the bus card", 1)[1].split("Train leg row", 1)[0]
    for needle in ("jo.liveIn", "jo.liveArrivingSoon", "jo.liveNow", "jo.scheduledAt", "cp.thenTrain", "live-then__when"):
        assert needle in guide, needle
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    assert ".live-then__when {\n  display: block;" in css.replace("\r\n", "\n")

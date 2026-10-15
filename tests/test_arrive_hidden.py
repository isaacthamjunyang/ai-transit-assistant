"""The Arrive by card is not drawn in an empty overview answer, and never drawn blank on any screen.

Static checks of the page, the style guide and the plan, then the real page in headless Edge at 360 and 1280 px, light
and dark, against the test app with a stubbed OneMap (no live API). The empty answers for each priority are in
tests/test_empty_messages_page.py; this file checks the shown case, the toggling, and the no-estimate guard."""

from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    return text.split(start, 1)[1].split(end, 1)[0]


def test_each_card_has_an_id_and_starts_hidden():
    for prefix in ("overview", "on-way", "new-journey"):
        assert f'<div id="{prefix}-arrive-box" class="arrive-box" role="group" aria-label="Arrive by" hidden>' in INDEX


def test_the_card_needs_its_main_line_and_the_overview_hides_it_in_every_empty_state():
    render = _between(INDEX, "function renderArriveCard(prefix, iso) {", "function renderArrivalViews")
    assert 'document.getElementById(prefix + "-arrive-box")' in render
    assert 'box.hidden = !line || (prefix === "overview" && OVERVIEW_EMPTY_STATES.indexOf(overviewState) !== -1);' in render
    assert 'var OVERVIEW_EMPTY_STATES = ["no-route", "no-service", "unavailable", "no-location"];' in INDEX
    state = _between(INDEX, "function setOverviewState(state) {", "function planJourney()")
    assert "overviewState = state;" in state
    assert 'renderArriveCard("overview", overviewEstimateIso);' in state
    assert 'document.getElementById("start-journey").disabled = state !== "ready";' in state


def test_every_empty_answer_goes_through_an_empty_state():
    plan = _between(INDEX, "function planJourney() {", "// Priority: a native select.")
    assert plan.count('setOverviewState("no-service")') == 1 and plan.count('setOverviewState("no-route")') == 1
    assert plan.count('setOverviewState("unavailable")') >= 2 and 'setOverviewState("no-location")' in plan
    assert plan.index('setOverviewState("no-service")') < plan.index("showRideApps(body)")


def test_the_style_guide_and_the_plan_say_so():
    assert "the card is not drawn" in GUIDE
    para = _between(PLAN, "**Arrive by card.**", "\n")
    for needle in ("the whole card is not drawn", "never blank", "no service for bus, MRT or both", "no feasible route",
                   "walk only", "static-fallback", "ride-app card", "`Edit arrive-by time` button", "Start journey stays disabled"):
        assert needle in para, needle


@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)],
                ids=["360-light", "1280-dark"])
def report(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(name)) as base:
        return run_scenario("arrivebox", base, {"name": name, "width": width, "height": height, "dark": dark})["result"]


def test_the_card_shows_with_a_route_and_is_not_blank(report):
    route = report["route"]
    assert route["state"] == "ready" and route["shown"] is True
    assert route["value"] and route["value"].startswith("Arrive by")
    assert route["edit"] is True and route["start"] is False
    assert route["scrollWidth"] <= route["innerWidth"]


def test_it_hides_at_once_in_each_empty_state_and_shows_again_with_a_route(report):
    assert report["noRoute"]["shown"] is False and report["noRoute"]["start"] is True
    assert report["noService"]["shown"] is False and report["noService"]["start"] is True
    assert report["back"]["shown"] is True and report["back"]["value"]


def test_it_keeps_its_place_while_loading_so_a_replan_does_not_blink(report):
    assert report["loading"]["state"] == "loading"
    assert report["loading"]["shown"] is False  # it was hidden by the empty answer just before


def test_with_no_estimate_no_card_is_drawn_and_with_one_it_has_its_main_line(report):
    assert report["noEstimate"] == {"overview": False, "onWay": False, "newJourney": False}
    assert report["withEstimate"] == {"onWay": True, "newJourney": True}

"""Edit destination on the journey overview: in the route state and in the two empty states (no service, no route), for each of
the five priorities, reached through the search results and through a saved place (which never visits the results page). The
button used to do nothing from a saved place: it went back to a "results" screen that was not in the history stack. Now it goes
to the search results when the user came through them and to the destination stops page when not, keeping the destination.
No live API is called."""

from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import DEST, require_edge, run_scenario, running_app, north
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
ALL = ["fastest", "fewest_transfers", "least_walking", "bus_only", "mrt_only"]


def _walk_only():
    return stub.answer(stub.itinerary(stub.walk(0, 6, 400)))


STATES = {
    "route": ({"onemap": stub.by_mode({"TRANSIT": stub.train_first, "BUS": stub.train_first, "RAIL": stub.train_first}), "rail_table": _table()}, "route"),
    "no-service": ({"onemap": stub.by_mode({"TRANSIT": _walk_only, "BUS": _walk_only, "RAIL": _walk_only}), "rail_table": _table()}, "overview-no-service"),
    "no-route": ({"onemap": stub.by_mode({"TRANSIT": None, "BUS": None, "RAIL": None}), "rail_table": _table()}, "overview-no-route"),
}


@pytest.fixture(scope="module", params=[(s, f) for s in STATES for f in ("search", "saved")], ids=lambda p: f"{p[0]}-{p[1]}")
def run(request, tmp_path_factory):
    state, flow = request.param
    require_edge()
    kwargs, _ = STATES[state]
    with running_app(tmp_path_factory.mktemp(f"ed{state}{flow}"), **kwargs) as base:
        result = run_scenario("editdest", base, {"width": 390, "height": 844, "dark": False, "flow": flow, "priorities": ALL,
                                                 "dest": DEST, "destPos": north(2000)}, timeout=600)["result"]
    return state, flow, result


@pytest.mark.parametrize("priority", ALL)
def test_edit_destination_leaves_the_overview_for_the_right_page_and_keeps_the_destination(run, priority):
    state, flow, result = run
    entry = result["byPriority"][priority]
    before, target, after = entry["before"], entry["target"], entry["after"]
    assert before["state"] == STATES[state][1] and before["priority"] == priority, before
    assert target is not None and target["text"] == "Edit destination", state  # the button is there
    assert target["disabled"] is False and target["covered"] is False and target["h"] >= 44, target  # and nothing covers it
    expected = "results" if flow == "search" else "stops"  # the results page is only in the stack for a search
    assert after["top"] == expected, (state, flow, priority, after["stack"])
    assert after["stack"] == ["home", expected]
    assert after["destination"] == "Destination" and after["stop"] == before["stop"]  # the chosen destination is kept


def test_the_screen_to_go_back_to_is_one_helper_used_by_every_edit_destination_control():
    assert "function editDestination() {" in INDEX
    body = INDEX.split("function editDestination() {", 1)[1].split("\n    }", 1)[0]
    assert 'screenStack.indexOf("results") === -1' in body and "destinationSkipped()" in body and 'backToScreen(' in body
    for old in ('id="overview-edit-destination").addEventListener("click", function () {\n      backToScreen("results");',
                'id="overview-edit-destination-service").addEventListener("click", function () {\n      backToScreen("results");',
                'action: function () { backToScreen("results"); } }));'):
        assert old not in INDEX, old
    assert INDEX.count("editDestination") >= 5  # the definition and four controls


def test_the_plan_says_edit_destination_returns_to_the_stops_page_for_a_saved_place():
    assert "goes back to the search results when the user came through them and to the destination stops page when they came through a saved place" in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()

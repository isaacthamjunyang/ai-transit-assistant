"""The overview's empty states by priority, in the real page against the real app and a stubbed OneMap: a walk-only answer
and a 404, for each of the five priorities, at 360 and 1280 px in light and dark. The closed ("stopped for now") words and
the static planner's sentence are checked on the page's own word choice, fed bodies directly."""

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ALL = ["fastest", "fewest_transfers", "least_walking", "bus_only", "mrt_only"]
ANY = ALL[:3]
OLD = "No service to this destination right now."
GENERIC = "No services to this destination right now."
TEXT = {
    "bus_only": ("No bus-only route found. Try another priority.", "Bus services have stopped for now. Try another priority."),
    "mrt_only": ("No MRT or LRT route found. Try another priority.", "MRT and LRT services have stopped for now. Try another priority."),
}


def _walk_only():
    return stub.answer(stub.itinerary(stub.walk(0, 6, 400)))


def _run(tmp_path_factory, name, builders, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode(builders), rail_table=_table()) as base:
        return run_scenario("emptymsg", base, {"name": name, "priorities": ALL, **config}, timeout=300)["result"]


@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)], ids=["360-light", "1280-dark"])
def walk_only(request, tmp_path_factory):
    name, width, height, dark = request.param
    builders = {"TRANSIT": _walk_only, "BUS": _walk_only, "RAIL": _walk_only}
    return _run(tmp_path_factory, "walk" + name, builders, width=width, height=height, dark=dark)


@pytest.fixture(scope="module")
def no_route(tmp_path_factory):
    return _run(tmp_path_factory, "noroute", {"TRANSIT": None, "BUS": None, "RAIL": None}, width=390, height=844)


@pytest.mark.parametrize("priority", ALL)
def test_a_walk_only_answer_shows_the_priority_sentence_in_the_no_service_state(walk_only, priority):
    state = walk_only["byPriority"][priority]
    assert state["priority"] == priority and state["select"] == priority and state["ready"] is False
    expected = TEXT[priority][0] if priority in TEXT else GENERIC
    assert state["noService"] == expected and state["noRoute"] is None, state
    assert OLD not in (state["noService"] or "")
    assert state["buttons"] == ["Edit destination", "Edit arrive-by time"]
    assert state["scrollWidth"] <= state["innerWidth"]


@pytest.mark.parametrize("priority", ALL)
def test_a_404_shows_the_chip_sentence_or_no_route_found(no_route, priority):
    state = no_route["byPriority"][priority]
    expected = TEXT[priority][0] if priority in TEXT else "No route found for this trip."
    assert state["noRoute"] == expected and state["noService"] is None, state
    assert state["select"] == priority and state["buttons"] == ["Edit destination", "Edit arrive-by time"]


@pytest.mark.parametrize("priority", ALL)
def test_the_page_says_stopped_for_now_only_for_a_chip_the_server_marked_stopped(walk_only, priority):
    words = walk_only["words"]
    for kind in ("service", "route"):
        open_text, stopped_text = words[f"{priority}|{kind}|open"], words[f"{priority}|{kind}|stopped"]
        if priority in TEXT:
            assert open_text == TEXT[priority][0] and stopped_text == TEXT[priority][1], (kind, open_text, stopped_text)
        elif kind == "service":
            assert open_text == stopped_text == GENERIC
        else:
            assert open_text == stopped_text == "No route found for this trip."


def test_the_static_planner_keeps_its_bus_only_sentence_and_its_own_no_route_sentence(walk_only):
    words = walk_only["words"]
    assert words["static|service"] == OLD
    assert words["static|service|bus_only"] == OLD  # the bus planner is bus only: the old sentence is accurate
    assert words["static|route"] == "No direct or 1-transfer route for this trip."


# ---- the Arrive by card is not drawn in an empty answer (tests/test_arrive_hidden.py checks it with a route) -----------


@pytest.mark.parametrize("priority", ALL)
def test_the_arrive_by_card_is_hidden_in_a_walk_only_answer_and_the_ride_apps_show(walk_only, priority):
    state = walk_only["byPriority"][priority]
    assert state["arriveBox"] is False and state["arriveBoxHeight"] == 0, state
    assert state["rideApps"] is True and state["startDisabled"] is True
    assert state["buttons"] == ["Edit destination", "Edit arrive-by time"]  # the message card keeps its button


@pytest.mark.parametrize("priority", ALL)
def test_the_arrive_by_card_is_hidden_in_a_404_answer_and_start_stays_disabled(no_route, priority):
    state = no_route["byPriority"][priority]
    assert state["arriveBox"] is False and state["arriveBoxHeight"] == 0, state
    assert state["startDisabled"] is True and state["buttons"] == ["Edit destination", "Edit arrive-by time"]


def test_empty_answers_leave_no_gap_for_the_hidden_card_and_do_not_jump_between_priorities(walk_only, no_route):
    # the sentence may wrap to one line more or less, but the space between the card and Start journey is the same
    for report in (walk_only, no_route):
        gaps = {state["cardGap"] for state in report["byPriority"].values()}
        assert len(gaps) == 1, gaps
        assert all(state["arriveBoxHeight"] == 0 for state in report["byPriority"].values())

"""The 5 s rescore on Page A (and Page W): when it runs, when it never runs, and one scoring for every view.

The browser part drives the real page in headless Edge (tests/js/scenarios/rescorea.mjs). The server part checks that
one rescore answer is one scoring: the probability, leave_by, the action and the explanation pack agree.
"""

from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app
from test_rescore import _poll, _rescore, client, lta  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("rescorea"), eta_minutes=[10.3]) as base:
        return run_scenario("rescorea", base, {})["result"]


# ---- when it runs

def test_it_runs_on_page_a_after_start_journey(report):
    assert report["onPageA"] == {"top": "live", "allowed": True, "timer": True}
    assert report["firstAsked"] == 1
    assert report["url"].startswith("/api/rescore?stop_code=")
    assert "explanation_rendered=" not in report["url"] or "explanation_in_flight=" in report["url"]


def test_it_never_runs_before_start_journey(report):
    assert report["never"]["beforeStart"] == {"allowed": False, "timer": False, "asked": 0}


def test_it_never_runs_on_a_hidden_page_and_the_timer_is_cleared(report):
    assert report["never"]["hidden"] == {"asked": 0, "timerCleared": True}
    assert report["never"]["visibleAgain"] is True


def test_it_never_runs_in_demo_mode(report):
    assert report["never"]["demo"] == {"asked": 0, "allowed": False}


def test_it_never_runs_on_leg_2_but_does_on_leg_1(report):
    assert report["never"]["leg2"] == {"asked": 0, "allowed": False}
    assert report["never"]["leg1"] is True


def test_it_never_runs_on_page_b_and_comes_back_on_page_a(report):
    assert report["never"]["pageB"] == {"asked": 0, "allowed": False, "timerCleared": True}
    assert report["never"]["backOnA"] is True


def test_it_never_runs_after_the_end_of_tracking(report):
    assert report["never"]["afterAnswer"] == {"asked": 0, "allowed": False, "timerCleared": True}


def test_the_gates_are_one_function_for_the_timer_and_the_tick():
    block = INDEX.split("function rescoreAllowed()", 1)[1].split("function syncWalkTimers", 1)[0]
    for part in ("rescoreScreenOk()", "!document.hidden", "monitoringActive", "!endedKind", "!missedMode", "!demoModeOn()",
                 "rescoreLegOk()"):
        assert part in block, part
    screens = INDEX.split("function rescoreScreenOk()", 1)[1].split("function rescoreLegOk", 1)[0]
    assert '"walk"' in screens and '"live" && !pageC' in screens and "arrivals" not in screens
    assert "leg_index === 1" in INDEX.split("function rescoreLegOk()", 1)[1].split("}", 1)[0]
    tick = INDEX.split("function walkRescoreTick(fromTimer)", 1)[1].split("function mergeRescore", 1)[0]
    assert tick.index("rescoreAllowed()") < tick.index("fetch(")  # checked before any request
    assert "rescoreAllowed()" in tick.split("fetch(", 1)[1]  # and again when the answer arrives


def test_the_full_route_fit_never_runs_while_page_w_shows():
    body = INDEX.split("function fitFullRoute()", 1)[1].split("var points", 1)[0]
    assert 'classList.contains("is-page-w")' in body and "return;" in body


# ---- what a good answer does

def test_a_good_answer_replaces_ring_tile_card_and_chip_from_one_body(report):
    applied = report["applied"]
    assert report["answerStatus"] == "ok" and applied["replaced"] is True
    assert applied["point"] == applied["bodyPoint"] != report["beforePoint"]
    assert applied["leaveBy"] == applied["bodyLeaveBy"]
    assert applied["packIsBodys"] is True  # the card is the answer's own pack
    view = applied["view"]
    assert str(applied["point"]) in view["ring"] and str(applied["point"]) in view["aria"]
    assert view["card"] == applied["expectedCard"]
    assert view["tile"] == applied["expectedTile"]["value"]
    assert view["detail"] == applied["expectedTile"]["meta"]
    # the chip comes from the answer's own pace category (a "slower" one is smoothed over two ticks)
    raw = applied["bodyPace"]
    if raw not in ("slower", "slightly_slower"):
        assert applied["paceShown"] == raw


def test_use_poll_changes_nothing(report):
    assert report["usePoll"] == {"same": True, "viewSame": True}


def test_while_a_reroute_is_active_a_good_answer_is_ignored(report):
    assert report["reroute"] == {"same": True, "viewSame": True}


# ---- the server: one answer, one scoring

def test_one_rescore_answer_is_one_scoring(client):
    _poll(client)
    body = _rescore(client, explanation_rendered=1, explanation_in_flight=0).json()
    hero = next(bus for bus in body["buses"] if bus["is_primary"])
    pack = body["explanation"]
    assert pack["leave_by"] == body["leave_by"]
    assert pack["band"] == hero["probability"]["band"]
    assert pack["uncertain"] == (hero["probability"]["data_quality"] == "location uncertain")
    assert pack["arrival_time"] == hero["arrival_time"]
    assert pack["action"] == body["chosen_action"]
    assert pack["walk_speed_used"] == body["walk_speed_used"]


def test_a_rescore_never_says_switch_route_and_asks_no_one(client, lta):
    _poll(client)
    calls = lta.calls
    body = _rescore(client, explanation_rendered=1).json()
    assert body["chosen_action"] != "switch_route"  # no reroute search runs here: the page ignores it while the poll's holds
    assert lta.calls == calls


def test_the_pack_is_left_out_unless_the_page_asks_for_it(client):
    _poll(client)
    assert "explanation" not in _rescore(client).json()
    assert "explanation" in _rescore(client, explanation_rendered=1).json()

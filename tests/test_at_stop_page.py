"""At the stop in the real page (headless Edge, tests/js/scenarios/atstop.mjs) and in the page source."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
NB = " "


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("atstop"), eta_minutes=[10.3]) as base:
        return run_scenario("atstop", base, {})["result"]


def test_60_m_away_is_the_normal_formula(report):
    far = report["far"]
    assert far["atStop"] is False and far["packAtStop"] is False
    assert far["tile"] != "At the stop" and "You are at the stop" not in far["card"]


def test_at_the_stop_the_ring_the_tile_the_card_and_the_aria_say_so(report):
    view = report["atStop"]
    assert view["atStop"] is True and view["packAtStop"] is True and view["action"] == "wait"
    assert "97" in view["ring"] and "about 97 percent" in view["aria"].replace(NB, " ")
    assert view["tile"] == "At the stop"
    assert view["detail"] == "" and view["detailHidden"] is True  # no subline under "At the stop"
    assert view["card"] == f"You are at the stop. You have {view['e']} minutes to wait."
    assert view["cautionHidden"] is True  # the location-uncertain line cannot appear with a good fix
    assert view["chip"] == ""  # no pace chip (hidden inside 30 m)
    assert view["banner"] is True  # no Leave now banner
    assert report["atStopRescore"]["near"] is True


def test_the_pace_chip_is_hidden_inside_30_m_and_comes_back_after_each_way_out(report):
    assert report["far"]["chipHidden"] is False and report["far"]["tilesShown"] is True
    assert report["atStop"]["chipHidden"] is True and report["atStop"]["tilesShown"] is True
    assert report["poorFix"]["chipHidden"] is True  # still inside the 30 m rule (near_stop), whatever the fix quality
    assert report["rescored"]["chipHidden"] is True
    assert report["afterRescoreAway"]["chipHidden"] is False  # a rescore that clears near_stop
    assert report["afterRescoreAway"]["atStop"] is False


def test_a_poor_fix_does_not_use_the_rule(report):
    view = report["poorFix"]
    assert view["atStop"] is False and view["tile"] != "At the stop" and "You are at the stop" not in view["card"]


def test_a_rescore_alone_brings_the_at_stop_text_back(report):
    view = report["rescored"]
    assert view["atStop"] is True and view["tile"] == "At the stop"
    assert view["card"] == f"You are at the stop. You have {view['e']} minutes to wait."
    assert "97" in view["ring"]


def test_a_rescore_that_says_at_the_stop_hides_a_showing_leave_now_banner(report):
    assert report["bannerShown"] is True and report["bannerAfter"] is True


# ---- the strings are in copy.js and the page, character for character

def test_the_at_stop_strings_are_in_the_page_and_in_copy_js():
    for text in ("You are at the stop. You have {e} to wait.", "You are at the stop. The bus is arriving now.",
                 "At the stop", "The bus is arriving now."):
        assert text in INDEX and text in COPY, text
    assert "The bus is {e}\\u00a0min away." not in INDEX and "The bus is {e}\\u00a0min away." not in COPY  # no subline


def test_one_place_decides_the_tile_the_card_and_the_action_between_polls():
    assert INDEX.count("pack.at_stop === true") >= 3  # sentence one, sentence two, the tile
    action = INDEX.split("function trackedAction(body)", 1)[1].split("function boardingStopName", 1)[0]
    assert "probability.at_stop === true" in action and "return action;" in action
    banner = INDEX.split("function leaveNowStillHolds", 1)[1].split("function deliverLeaveNow", 1)[0]
    assert "chance.at_stop !== true" in banner
    assert len(re.findall(r"chance\.at_stop === true", INDEX)) >= 2  # the timer and the delivery

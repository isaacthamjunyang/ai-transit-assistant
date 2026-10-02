"""recommend_option: ordered, deterministic rules. Each case is one table row."""

import re
from datetime import datetime, timedelta, timezone

import pytest

from config import MIN_REAL_CHANCE_RANGE_HIGH, PROB_TIE_POINTS, RUSH_MARGIN_MINUTES
from recommend import REASON_CODES, REASON_TEXT, pills, reason_text, recommend_option

SGT = timezone(timedelta(hours=8))
T0 = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)


def opt(name, point, high=None, arrive=30, d=0, service=None):
    return {
        "id": name,
        "service_no": service or name,
        "point": point,
        "range_low": max(0, point - 10),
        "range_high": point + 10 if high is None else high,
        "estimated_arrival": None if arrive is None else T0 + timedelta(minutes=arrive),
        "distance_m": d,
        "walk_m": d,
    }


def target(minutes):
    return T0 + timedelta(minutes=minutes)


CASES = [
    ("no target, one option", [opt("7", 60)], None, ("7", "HIGHEST_CHANCE")),
    ("no target, highest probability wins", [opt("7", 60), opt("16", 80, d=300)], None, ("16", "HIGHEST_CHANCE")),
    ("tie within 5 points goes to the shorter walk", [opt("7", 80, d=300), opt("16", 76, d=0)], None, ("16", "SHORTER_WALK")),
    ("difference of 4 is a tie", [opt("7", 80, d=300), opt("16", 76, d=0)], None, ("16", "SHORTER_WALK")),
    ("difference of 5 is a tie", [opt("7", 80, d=300), opt("16", 75, d=0)], None, ("16", "SHORTER_WALK")),
    ("difference of 6 is not a tie", [opt("7", 80, d=300), opt("16", 74, d=0)], None, ("7", "HIGHEST_CHANCE")),
    ("target set and relaxed: highest chance", [opt("7", 80, arrive=40), opt("16", 70, arrive=20)], target(60), ("7", "HIGHEST_CHANCE_ON_TIME")),
    ("target set and rushing: earliest on-time option", [opt("7", 80, arrive=55), opt("16", 70, arrive=40)], target(60), ("16", "FASTEST_RUSHING")),
    ("rushing and the fastest is also the highest chance", [opt("7", 80, arrive=55)], target(60), ("7", "HIGHEST_CHANCE_ON_TIME")),
    ("none on time: earliest arrival", [opt("7", 80, arrive=90), opt("16", 60, arrive=70)], target(60), ("16", "NONE_BY_TARGET")),
    ("margin 9 minutes is rushing", [opt("7", 80, arrive=51), opt("16", 70, arrive=30)], target(60), ("16", "FASTEST_RUSHING")),
    ("margin 10 minutes is relaxed", [opt("7", 80, arrive=50), opt("16", 70, arrive=30)], target(60), ("7", "HIGHEST_CHANCE_ON_TIME")),
    ("margin 11 minutes is relaxed", [opt("7", 80, arrive=49), opt("16", 70, arrive=30)], target(60), ("7", "HIGHEST_CHANCE_ON_TIME")),
    ("range_high below 40 is never recommended", [opt("7", 90, high=39), opt("16", 20, high=40)], None, ("16", "HIGHEST_CHANCE")),
    ("a late option is not on time", [opt("7", 90, arrive=70), opt("16", 50, arrive=40)], target(60), ("16", "HIGHEST_CHANCE_ON_TIME")),
    ("no estimate is never preferred over a usable one when a target is set", [opt("7", 90, arrive=None), opt("16", 50, arrive=90)], target(60), ("16", "NONE_BY_TARGET")),
    ("no estimate can be recommended with no target", [opt("7", 90, arrive=None), opt("16", 50, arrive=40)], None, ("7", "HIGHEST_CHANCE")),
]


@pytest.mark.parametrize("name,options,deadline,expected", CASES, ids=[c[0] for c in CASES])
def test_recommendation_table(name, options, deadline, expected):
    result = recommend_option(options, deadline)
    assert (result["id"], result["reason"]) == expected


def test_constants_are_the_agreed_ones():
    assert (RUSH_MARGIN_MINUTES, PROB_TIE_POINTS, MIN_REAL_CHANCE_RANGE_HIGH) == (10, 5, 40)


def test_no_eligible_option_gives_no_recommendation():
    assert recommend_option([opt("7", 90, high=39), opt("16", 50, high=10)], None) is None
    assert recommend_option([], target(60)) is None


def test_an_ineligible_option_never_gets_the_quick_pill_but_may_hold_the_chance_pill():
    options = [opt("7", 90, high=39, arrive=10), opt("16", 50, high=60, arrive=40)]
    holders = pills(options)
    assert holders["fastest"] == "16" and holders["highest_chance"] == "7"
    assert pills([opt("7", 30, high=39)])["fastest"] is None


def test_quick_pill_ties_go_to_the_higher_probability_and_no_estimate_never_holds_it():
    options = [opt("7", 50, arrive=30), opt("16", 70, arrive=30), opt("36", 99, arrive=None)]
    assert pills(options)["fastest"] == "16"


def test_reason_strings_have_no_digits_but_the_service_and_no_guarantee_wording():
    assert set(REASON_TEXT) == set(REASON_CODES)
    for code in REASON_CODES:
        text = reason_text(code, "7")
        assert re.findall(r"\d+", text) == ["7"], text
        assert "{" not in text
        for phrase in ("guarantee", "will catch", "definitely", "certain"):
            assert phrase not in text.lower()
        assert "should" in text.lower() or code in ("HIGHEST_CHANCE", "SHORTER_WALK")

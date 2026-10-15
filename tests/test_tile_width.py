"""The Leave by tile in the REAL page: the clock time and "Leave now" stay on one line at every phone width."""

import re

import pytest

from page_runner import require_edge, run_scenario, running_app

WIDTHS = [340, 360, 375, 381, 390, 412, 430]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("tilewidth"), eta_minutes=[10.3]) as base:
        return run_scenario("tilewidth", base, {"widths": WIDTHS})["result"]["widths"]


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("state", ["by", "now", "tomorrow"])
def test_the_leave_by_value_is_one_line_and_not_clipped(report, width, state):
    m = report[str(width)][state]
    assert m["valueLines"] == 1, m  # the time or "Leave now" is not split
    assert m["spanWidth"] <= m["valueBox"], m  # it fits inside the value box
    assert m["valueScroll"] <= m["valueClient"], m  # nothing spills sideways (even with " (tomorrow)")
    assert m["tileScroll"] <= m["tileClient"] and m["tileRight"] <= m["viewport"], m
    assert m["clipped"] is False and m["pageScroll"] is False, m
    assert m["arrivalGone"] is True and m["tileFull"] is True, m  # no destination arrival tile; Leave by is full width
    assert re.fullmatch(r"\d+\u00a0min walk", m["walkLine"]), m  # one short line, the walk minutes
    assert (m["text"] == "Leave now") == (state == "now"), m
    # "Leave by: {time}" carries the label; "Leave now" stands alone; the tile's accessible name is always "Leave by"
    assert m["labelHidden"] == (state == "now") and m["tileName"] == "Leave by", m  # a time or "Leave now", never both

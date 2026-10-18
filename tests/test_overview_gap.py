"""The journey overview: 12 px between the "Your journey" heading and the priority select, in every overview state (route, loading,
no location, no route, no service, unavailable, and the static planner's empty sentences), at 320, 360 and 1280 px in light and
dark, with nothing below the select moved and no overflow. It was 8 px. No live API."""

from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
COMBOS = [(w, d) for w in (320, 360, 1280) for d in (False, True)]
STATES = ["ready", "loading", "no-location", "no-route", "no-service", "unavailable", "fallbackNoRoute", "fallbackNoService", "rideApps"]
# the space under the select before this change (the same in every state: the skeleton's own 8 px, otherwise a 7 px line)
BELOW = {"loading": 8}


@pytest.fixture(scope="module", params=COMBOS, ids=[f"{w}-{'dark' if d else 'light'}" for w, d in COMBOS])
def run(request, tmp_path_factory):
    width, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(f"og{width}{dark}")) as base:
        return run_scenario("overviewgap", base, {"width": width, "height": 800, "dark": dark}, timeout=300)["result"]


@pytest.mark.parametrize("state", STATES)
def test_the_gap_under_the_heading_is_12px_in_every_state(run, state):
    read = run[state]
    assert abs(read["gap"] - 12) <= 1 and abs(read["wrapGap"] - 12) <= 1, (state, read["gap"])
    assert abs(read["selectH"] - 48) <= 1  # the select keeps its 48 px


@pytest.mark.parametrize("state", STATES)
def test_nothing_else_moves_and_nothing_overflows(run, state):
    read = run[state]
    assert abs(read["below"] - BELOW.get(read["state"], 7)) <= 1, (state, read["below"], read["nextId"])  # the gap under the select is as before
    assert read["scrollWidth"] <= read["innerWidth"] and read["selectRight"] <= read["cardRight"] + 0.5, state


def test_the_gap_is_the_same_in_every_state_so_a_state_change_shifts_nothing(run):
    gaps = {round(run[state]["gap"], 1) for state in STATES}
    assert len(gaps) == 1, gaps
    assert len({round(run[state]["titleH"], 1) for state in STATES}) == 1


def test_the_css_uses_existing_spacing_tokens_only_and_the_plan_says_12px():
    rule = CSS.split("#overview-card .overview-title {", 1)[1].split("}", 1)[0]
    assert rule.strip() == "margin-bottom: calc(var(--space-2) + var(--space-1));"  # 8 px + 4 px, no new token
    assert ".overview-card .overview-title {\n  margin: 0 0 var(--space-2);" in CSS  # the other screens keep 8 px
    theme = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
    assert "--space-12" not in theme and "--space-overview" not in theme
    assert "the priority select (12 px under the title, in every overview state)" in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()

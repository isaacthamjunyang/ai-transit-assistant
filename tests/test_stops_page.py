"""The destination stops page: no row chosen at first, Select stop with nothing chosen says so in the shared red alert, and the pulse moves
between Skip (a fully filled green button) and Select stop. 320, 360 and 1280 px, light and dark. No live API."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
COMBOS = [(w, d) for w in (320, 360, 1280) for d in (False, True)]
CHOOSE = "Choose a stop or station first."


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [round(float(v)) for v in re.findall(r"[\d.]+", text)[:3]]


@pytest.fixture(scope="module", params=COMBOS, ids=[f"{w}-{'dark' if d else 'light'}" for w, d in COMBOS])
def run(request, tmp_path_factory):
    width, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(f"sp{width}{dark}")) as base:
        return run_scenario("stopspage", base, {"width": width, "height": 800, "dark": dark}, timeout=300)["result"]


def test_nothing_is_chosen_when_the_page_opens_and_the_nearest_keeps_its_label(run):
    opened = run["opened"]
    assert opened["top"] == "stops" and len(opened["rows"]) == 2
    assert not any(row["selected"] for row in opened["rows"]) and all(row["pressed"] == "false" for row in opened["rows"])
    assert opened["selectedCode"] is None and opened["markerSelected"] == 0  # no row, no state, no selected marker on the map
    assert opened["focusInList"] is False and not any(row["focused"] for row in opened["rows"])  # and no focus on the first row
    assert [row["pill"] for row in opened["rows"]] == [True, False]  # Best option stays on the nearest row, as a label
    assert opened["error"]["shown"] is False


def test_select_stop_with_nothing_chosen_stays_and_shows_the_red_alert_with_room_around_it(run):
    refused = run["refused"]
    assert refused["top"] == "stops"  # it did not navigate
    error = refused["error"]
    assert error["shown"] is True and error["text"] == CHOOSE and error["icon"] is True
    assert "alert--error" in error["cls"].split() and "alert" in error["cls"].split()  # the shared red alert
    assert error["marginTop"] >= 12 and error["marginBottom"] >= 8  # a gap above and below
    assert error["selectRect"]["top"] - error["rect"]["bottom"] >= 8
    assert error["rect"]["left"] >= 0 and error["rect"]["right"] <= refused["innerWidth"] and refused["scrollWidth"] <= refused["innerWidth"]


def test_choosing_a_row_dismisses_the_alert_and_select_stop_then_goes_on(run):
    chosen = run["chosen"]
    assert chosen["error"]["shown"] is False
    assert [row["selected"] for row in chosen["rows"]] == [False, True] and chosen["selectedCode"] == "S2"
    assert run["confirmed"]["top"] == "confirm" and run["confirmed"]["stop"] == "Beta Road"


def test_skip_pulses_while_nothing_is_chosen_and_select_stop_does_not(run):
    for key in ("opened", "refused"):
        state = run[key]
        assert state["skip"]["pulses"] is True and state["skip"]["anims"] == 1, key
        assert state["select"]["pulses"] is False and state["select"]["anims"] == 0, key


def test_once_a_row_is_chosen_the_pulse_moves_to_select_stop(run):
    chosen = run["chosen"]
    assert chosen["skip"]["pulses"] is False and chosen["skip"]["anims"] == 0
    assert chosen["select"]["pulses"] is True and chosen["select"]["anims"] == 1
    reopened = run["reopened"]  # a fresh list: nothing chosen, so Skip has it again
    assert reopened["skip"]["pulses"] is True and reopened["skip"]["anims"] == 1 and reopened["select"]["anims"] == 0


def test_neither_pulses_under_reduced_motion_and_select_stop_is_enabled(run):
    reduced = run["reduced"]
    assert reduced["skip"]["anims"] == 0 and reduced["select"]["anims"] == 0
    assert run["opened"]["select"]["disabled"] is False  # enabled, so the alert can show


def test_skip_is_a_fully_filled_green_with_a_bold_white_label_4_5_to_1_and_44px(run):
    skip = run["opened"]["skip"]
    assert _rgb(skip["bg"]) == _rgb(skip["tokenFill"]) and _rgb(skip["color"]) == _rgb(skip["tokenInk"]) == [255, 255, 255]  # --action-yes, the white label of the Just-In-Time button
    assert skip["border"] == "0px" and int(skip["weight"]) >= 700 and float(skip["size"][:-2]) >= 16 and skip["shadow"] == "none"
    assert skip["ratio"] >= 4.5, skip["ratio"]  # white on --action-yes (5.4 light, 6.6 dark)
    assert skip["rect"]["height"] >= 44 and skip["rect"]["right"] <= run["opened"]["innerWidth"]
    assert skip["text"] == "Skip: Let us plan your route"


def test_the_info_tooltip_has_the_new_text_and_neither_clips_nor_overflows(run):
    tip = run["tip"]
    assert tip["hidden"] is False
    assert tip["text"] == "Stops and stations within 600 m, nearest first. If none, the nearest within 1.5 km."
    assert "pre-selected" not in tip["text"]
    assert tip["left"] >= 0 and tip["right"] <= tip["innerWidth"] and tip["top"] >= 0 and tip["bottom"] <= tip["innerHeight"]
    assert tip["clipped"] is False and tip["scrollWidth"] <= tip["innerWidth"]


def test_the_sources_the_style_guide_and_the_plan():
    assert 'chooseFirst: "Choose a stop or station first."' in COPY
    assert '<p class="alert__text">Choose a stop or station first.</p>' in INDEX and 'id="select-stop-error"' in INDEX
    assert 'class="primary skip-stop pulse-button" id="skip-stop"' in INDEX
    assert 'id="select-destination-stop" class="primary primary--icon">' in INDEX  # no pulse class and not disabled in the markup
    assert "function syncStopPulse() {" in INDEX and 'classList.toggle("pulse-button", chosen)' in INDEX and 'classList.toggle("pulse-button", !chosen)' in INDEX
    block = CSS.split(".back-bar .skip-stop {", 1)[1].split("}", 1)[0]
    assert "background: var(--action-yes);" in block and "color: var(--action-ink);" in block and "font-size: 1.125rem;" in block and "text-shadow: none;" in block
    assert 'info: "Stops and stations within 600 m, nearest first. If none, the nearest within 1.5 km.",' in COPY
    assert "pre-selected" not in COPY and "pre-selected" not in INDEX and "pre-selected" not in PLAN
    assert "chooseFirst" in GUIDE and "select-stop-error" in GUIDE
    assert "No row is chosen when the page opens" in PLAN and "`Choose a stop or station first.`" in PLAN and "Skip pulses" in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()

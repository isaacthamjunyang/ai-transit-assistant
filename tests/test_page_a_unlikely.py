"""Page A's probability card at 92% and at 5%: the same card apart from the ring's number, arc and colour; and, only when the catch is
unlikely, the warning above the blue and the green buttons in the bottom bar, with nothing shifting when it comes or goes. 360 and
1280 px, light and dark. No live API."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
COMBOS = [("l360", 360, 800, False), ("d360", 360, 800, True), ("l1280", 1280, 900, False), ("d1280", 1280, 900, True)]
PARTS = ["catch-ring", "catch-leg", "catch-node", "catch-line", "catch-to", "catch-arrives", "catch-pill", "catch-load"]


@pytest.fixture(scope="module", params=COMBOS, ids=["360-light", "360-dark", "1280-light", "1280-dark"])
def run(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    out = {"width": width, "dark": dark}
    base_config = {"width": width, "height": height, "dark": dark}
    with running_app(tmp_path_factory.mktemp("pah" + name), eta_minutes=[10.3]) as base:
        out["high"] = run_scenario("pageaunlikely", base, {**base_config, "metres": 60}, timeout=300)["result"]["read"]
    with running_app(tmp_path_factory.mktemp("pal" + name), eta_minutes=[3.0]) as base:
        result = run_scenario("pageaunlikely", base, {**base_config, "metres": 1500, "toggle": True}, timeout=300)["result"]
    out.update({"low": result["read"], "hidden": result["hidden"], "restored": result["restored"]})
    return out


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [round(float(v)) for v in re.findall(r"[\d.]+", text)[:3]]


def test_the_two_states_are_the_92_and_5_percent_cases(run):
    assert run["high"]["ring"] == "92%" and run["low"]["ring"] == "5%"
    for key in ("high", "low"):
        assert run[key]["top"] == "live" and run[key]["pageA"] is True
        assert run[key]["ringLabel"] and run[key]["ring"][:-1] in run[key]["ringLabel"]  # the accessible name carries the percentage


def test_the_card_is_the_same_apart_from_the_ring_number_arc_and_colour(run):
    high, low = run["high"], run["low"]
    assert high["card"]["width"] == low["card"]["width"] and high["card"]["height"] == low["card"]["height"]
    for part in PARTS:  # every element sits at the same place and size inside the card
        assert high["parts"][part] == low["parts"][part], part
    for key in ("legBg", "legRadius", "nodeRing", "toColor", "toFont", "timeFont", "timeColor", "pillBg", "loadColor"):
        assert high[key] == low[key], key
    assert high["ringStroke"] != low["ringStroke"] and high["ringDash"] != low["ringDash"]  # the arc and its colour
    assert _rgb(low["ringStroke"]) == _rgb(low["lowToken"]) and _rgb(high["ringStroke"]) == _rgb(high["okToken"])  # the existing tokens


def test_the_card_has_the_logo_ring_badge_to_destination_time_pill_and_crowding_in_order(run):
    for key in ("high", "low"):
        read = run[key]
        tops = read["cardOrder"]
        assert None not in tops and tops == sorted(tops), (key, tops)  # node and badge, To, time, pill, crowding, top to bottom
        assert read["cardText"][0].startswith("To ") and re.fullmatch(r"\d{1,2}:\d{2} [AP]M", read["cardText"][1].replace(chr(0xA0), " "))
        assert read["cardText"][2] in ("live", "schedule only") and read["cardText"][3] in ("Seats Available", "Standing Available", "Crowded", "No Data")
        for gone in ("Chance to catch your Bus", "Bus arrives", "if you leave now and walk at a normal pace", "Arriving in"):
            assert gone not in read["text"], gone


def test_the_alert_shows_only_when_unlikely_between_the_card_and_the_buttons(run):
    assert run["high"]["alert"] is None and run["high"]["slotBanner"] is False
    low = run["low"]
    alert = low["alert"]
    assert alert is not None and alert["text"] == "Catching this bus is unlikely." and "alert--warning" in alert["cls"]
    assert low["slotBanner"] is False  # it is drawn once, in the bar
    assert low["card"]["bottom"] <= alert["rect"]["top"] + 0.5 or low["bar"]["top"] >= low["card"]["top"]  # in the bar, under the card
    assert alert["rect"]["bottom"] <= low["see"]["top"] + 0.5 and low["see"]["bottom"] <= low["other"]["top"] + 0.5  # alert, blue, green
    assert abs(alert["rect"]["width"] - low["see"]["width"]) <= 1 and abs(alert["rect"]["left"] - low["see"]["left"]) <= 1  # full width


def test_the_gaps_around_the_alert_are_even(run):
    low = run["low"]
    above_buttons = low["see"]["top"] - low["alert"]["rect"]["bottom"]
    between_buttons = low["other"]["top"] - low["see"]["bottom"]
    assert abs(above_buttons - between_buttons) <= 1 and 6 <= above_buttons <= 10, (above_buttons, between_buttons)
    assert low["alert"]["rect"]["top"] - low["bar"]["top"] >= 6  # room above the alert inside the bar


def test_the_alert_coming_and_going_moves_neither_the_card_nor_the_tile(run):
    low, hidden, restored = run["low"], run["hidden"], run["restored"]
    assert hidden["alert"] is None and restored["alert"] is not None
    for other in (hidden, restored):
        assert other["card"] == low["card"] and other["tile"] == low["tile"], "the card and the Leave by tile stay where they were"
        assert other["parts"] == low["parts"]
    assert hidden["see"]["top"] == low["see"]["top"] and hidden["other"]["top"] == low["other"]["top"]  # the buttons stay put too
    assert hidden["bar"]["height"] < low["bar"]["height"]  # the bar is what grows and shrinks
    assert low["pad"] >= low["innerHeight"] - low["bar"]["top"], "nothing is covered by the taller bar"


def test_the_blue_button_is_start_journey_s_blue_without_the_pulse(run):
    for key in ("high", "low"):
        read = run[key]
        see, start = read["seeStyle"], read["startStyle"]
        for field in ("bg", "color", "radius", "minH"):
            assert see[field] == start[field], field  # the same colour, radius and height
        assert "pulse-button" not in see["cls"].split() and see["anim"] == "none" and read["anims"] == 0  # Start journey pulses, this does not
        assert "pulse-button" in start["cls"].split()
        assert read["see"]["height"] >= 44 and abs(read["see"]["width"] - read["other"]["width"]) <= 1
        assert read["seeInk"]["ratio"] >= 4.5  # white on the fill
        assert read["alert"] is None or read["alert"]["ink"]["ratio"] >= 4.5


def test_the_bar_is_not_a_bordered_box_and_the_other_button_is_the_same_blue_without_the_pulse(run):
    for key in ("high", "low"):
        read = run[key]
        assert read["barStyle"]["border"] == "0px" and read["barStyle"]["shadow"] == "none"  # no outline or shadow
        assert _rgb(read["barStyle"]["bg"]) == _rgb(read["paper"])  # the page colour
        other, see = read["otherStyle"], read["seeStyle"]
        assert other["bg"] == see["bg"] and other["color"] == see["color"] and other["radius"] == see["radius"]  # the same filled blue
        assert "pulse-button" not in other["cls"].split() and "primary--icon" in other["cls"].split()  # an arrow, and no pulse
        assert read["scrollWidth"] <= read["innerWidth"]
        assert read["bar"]["bottom"] >= read["innerHeight"] - 1  # still fixed at the foot of the screen


def test_the_sources_and_the_plan(run):
    assert 'id="unlikely-bar-alert"' in INDEX.split('id="see-arrivals-bar"', 1)[1].split('id="see-arrivals"', 1)[0]
    assert "barAlert.hidden = !(showing && onPageA);" in INDEX
    assert "body.is-page-a #see-arrivals-bar,\n.catch-bar.catch-bar--flat {" in CSS and "border-top: 0;" in CSS
    assert "catch-bar--flat" in GUIDE and "sgAlert(\"warning\"" in GUIDE
    assert "the warning above the two buttons in the bar" in PLAN and "the same filled blue primary button as `Start journey`" in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()

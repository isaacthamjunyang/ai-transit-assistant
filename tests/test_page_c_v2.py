"""The approved Page C design (tmp/design/pagec-v2.html) on the real page at 320, 360 and 1280 px, light and dark: the
current-bus card, two recommended cards that hold their own Switch button, the Leave by and Reach destination by tiles
(Page A's Leave by tile), the alternative rows with a ring and their alerts, and the empty answer. Nothing here calls an API."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")


def _rgb(text):
    return [int(v) for v in re.findall(r"\d+", text)[:3]]


def _lum(rgb):
    channels = [c / 255 for c in rgb]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _ratio(a, b):
    hi, lo = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_plan_and_the_style_guide_describe_the_approved_page_c_design():
    assert "tmp/design/pagec-v2.html" in PLAN and "supersedes the mockup for Page C" in PLAN
    assert "function sgTimeTile(" in GUIDE and "leave-tile--reach" in GUIDE and "prob-ring--large" in GUIDE
    assert "alt-row__alert" in GUIDE and "sgAlert(\"warning\", rp.afterTarget)" in GUIDE


def test_the_page_c_markup_uses_the_shared_alert_for_every_message():
    assert '<div id="pc-warn" class="alert alert--warning" hidden>' in INDEX
    assert '<div id="reroute-notice" class="alert alert--info" role="status" hidden>' in INDEX
    assert '<div id="page-c-none" class="alert alert--info" hidden>' in INDEX
    card = INDEX.split("function buildOptionCard(row)", 1)[1].split("function buildTimeTile", 1)[0]
    assert 'buildAlert("warning", AFTER_TARGET_TEXT)' in card and card.index("buildTimeTile") < card.index("buildSwitchButton")
    assert "card.appendChild(buildSwitchButton(row))" in card  # the Switch button is inside the card


def test_the_time_tiles_are_page_as_leave_by_tile_with_the_label_above():
    assert ".leave-tile--option .leave-tile__value" in CSS and ".leave-tile--reach" in CSS
    tile = CSS.split(".leave-tile {", 1)[1].split("}", 1)[0]
    assert "background: var(--color-primary);" in tile and "color: var(--color-primary-ink);" in tile


VIEWPORTS = [(320, 800, False), (360, 800, True), (1280, 900, False), (1280, 900, True)]


@pytest.fixture(scope="module", params=VIEWPORTS, ids=[f"{w}-{'dark' if d else 'light'}" for w, _, d in VIEWPORTS])
def page(request, tmp_path_factory):
    width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp("pcv2")) as base:
        return run_scenario("pagecv2", base, {"width": width, "height": height, "dark": dark}, timeout=300)["result"], width


def test_the_current_bus_card_has_the_time_large_no_caption_and_a_shared_alert(page):
    result, width = page
    current = result["route"]["current"]
    assert current["arrivesTime"] >= 28 and current["labelAbove"] is True and current["captionInCopy"] is False
    warn = current["warn"]
    assert warn["text"] == "Catching this bus is unlikely."
    assert warn["cls"].startswith("alert alert--warning") and warn["radius"] == "12px"
    assert abs(warn["box"]["w"] - (current["card"]["w"] - 2 * 16 - 2)) < 6  # full width of the card's content
    assert current["button"]["h"] >= 48 and abs(current["button"]["w"] - warn["box"]["w"]) < 2


def test_each_recommended_card_has_the_ring_at_the_left_the_two_tiles_and_its_own_switch_button(page):
    result, width = page
    cards = result["route"]["cards"]
    assert len(cards) == 2
    for card in cards:
        assert "prob-ring--large" in card["ringClass"] and card["ring"]["w"] >= 96
        assert card["ring"]["r"] <= card["copy"]["x"] + 1  # the vehicle row is at the right of the ring
        assert card["tags"] and card["tagIsAlert"] is False  # a recommendation tag is a compact label, not an alert
        assert card["leaveLabelAbove"] is True and card["leaveValue"] >= 28 and card["reachValue"] >= 24
        assert card["mainTop"] < card["leaveTop"] < card["reachTop"] < card["buttonTop"]  # ring row, Leave by, Reach, Switch
        assert card["buttonInside"] is True and card["button"]["h"] >= 48
        assert abs(card["button"]["w"] - card["leave"]["w"]) < 2  # the button, the tiles: one width
        assert card["button"]["r"] <= card["card"]["r"]


def test_leave_by_is_the_strong_fill_and_reach_destination_by_the_tint_both_readable(page):
    result, _ = page
    for card in result["route"]["cards"]:
        assert _ratio(card["leaveColor"], card["leaveBg"]) >= 4.5, card
        assert _ratio(card["reachColor"], card["reachBg"]) >= 4.5, card
        assert card["leaveBg"] != card["reachBg"]


def test_the_alternative_rows_have_a_ring_the_bold_time_and_alerts_the_full_row_width(page):
    result, _ = page
    rows = result["route"]["rows"]
    assert len(rows) == 3
    for item in rows:
        assert item["ring"]["r"] <= item["body"]["x"] + 1 and item["hit"]["h"] >= 44
        assert item["reachBold"] == "800" and re.search(r"Reach destination by: \d{1,2}:\d{2}", item["reach"])
        assert re.fullmatch(r"\d+% chance", item["chance"])
    warned = [item for item in rows if item["alerts"]]
    assert [a["text"] for item in warned for a in item["alerts"]] == ["Unlikely at a normal pace", "After your target"]
    for item in warned:
        for alert in item["alerts"]:
            assert alert["kind"].startswith("alert alert--warning")
            assert abs(alert["box"]["w"] - (item["item"]["w"] - 2 * 16)) < 4 and alert["box"]["r"] <= item["item"]["r"]


def test_the_section_head_keeps_updated_and_the_refresh_button_at_the_right(page):
    result, _ = page
    head = result["route"]["headRow"]
    assert float(head["headingSize"][:-2]) >= 22
    assert head["updated"]["x"] > head["heading"]["x"] and head["refresh"]["x"] >= head["updated"]["r"] - 1
    assert head["refresh"]["w"] >= 44 and head["refresh"]["h"] >= 44


def test_nothing_overflows_at_320_360_or_1280(page):
    result, width = page
    for key in ("route", "empty"):
        assert result[key]["scrollWidth"] <= result[key]["innerWidth"] == width
    for card in result["route"]["cards"]:
        assert card["card"]["r"] <= width


def test_the_empty_answer_is_an_info_alert_and_the_ride_app_card_with_two_columns(page):
    result, width = page
    empty = result["empty"]
    assert empty["notice"]["text"] == "No other buses or routes are available right now."
    assert empty["notice"]["cls"].startswith("alert alert--info")
    ride = empty["ride"]
    assert ride["border"] == "1px" and len(ride["links"]) == 5
    assert all(link["h"] >= 44 for link in ride["links"])
    assert ride["links"][0]["y"] == ride["links"][1]["y"] and ride["links"][0]["x"] < ride["links"][1]["x"]
    assert ride["links"][4]["w"] > ride["links"][0]["w"] * 1.8  # the fifth takes the full row

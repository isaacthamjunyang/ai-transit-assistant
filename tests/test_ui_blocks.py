"""Header and back row blocks, the back button, the one-time pulse and the destination flag (headless Edge)."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
FLAG_PATH = "M6 21V4M6 4h11l-2 4 2 4H6"
PAGES = ["home", "results", "stops", "confirm", "journey", "live", "arrivals", "newjourney", "onway", "walk"]


def _lum(rgb):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [int(float(n)) for n in re.findall(r"[\d.]+", text)[:3]]


def _contrast(a, b):
    la, lb = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _rule(selector):
    return CSS.replace("\r\n", "\n").split(selector + " {", 1)[1].split("}", 1)[0]


# ---- static -----------------------------------------------------------------------------------------------------------


def test_the_reachability_note_and_its_string_icon_and_css_are_gone_everywhere():
    for name, body in (("index", INDEX), ("copy", COPY), ("guide", GUIDE), ("plan", PLAN), ("css", CSS)):
        assert "no direct bus from near you" not in body and "a transfer may still work" not in body, name
        assert "noDirectBus" not in body and "dest-stop-row__note" not in body, name
    assert "NOTE_SVG" not in INDEX
    tests = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py") if p.name != "test_ui_blocks.py")
    assert "no direct bus from near you" not in tests


def test_the_page_has_no_row_filtering_and_lists_every_candidate_in_order():
    body = INDEX.split("function renderDestinationStops(body) {", 1)[1].split("function loadDestinationStops", 1)[0]
    assert ".filter(" not in body and "listed" not in body and "reduce(" not in body  # nothing drops or reorders rows
    assert "var all = Array.isArray(body.candidates) ? body.candidates : body.reachable_stops.concat(body.unreachable_stops);" in body
    assert "bestDestinationStopCode(body.reachable_stops)" in body and "selectDestinationStop(all[0])" not in body  # no row is chosen for the user
    assert "all.forEach(function (stop) {" in body and "renderDestinationStopCard(stop, reachableStopList," in body
    assert 'setDestinationStopStatus("No stops within 600 m.", "caution")' in body  # the unchanged "no stops" logic
    assert 'setDestinationStopStatus("No service to this destination right now.", "caution")' in body
    card = INDEX.split("function renderDestinationStopCard(stop, list, best) {", 1)[1].split("function addDestinationMarker", 1)[0]
    assert "is_reachable" in card and "note" not in card.replace("Note", "")  # no note element is built


def test_the_destination_icon_is_the_green_flag_and_the_category_icons_are_gone():
    assert "place-icons.js" not in INDEX and "place-icons.js" not in GUIDE
    assert not (ROOT / "static" / "place-icons.js").exists()
    assert "place-icons" not in (ROOT / "main.py").read_text(encoding="utf-8")
    for body in (INDEX, GUIDE):
        assert "placeIconSvg" not in body and "placeIconId" not in body and "PLACE_ICON" not in body
    assert "icon.innerHTML = FLAG_SVG;" in INDEX and 'getElementById("confirm-place-icon").innerHTML = FLAG_SVG;' in INDEX
    assert FLAG_PATH in INDEX.split("var FLAG_SVG =", 1)[1][:400] and FLAG_PATH in GUIDE.split("var DEST_FLAG_ICON =", 1)[1][:400]
    assert "color: var(--marker-end);" in _rule(".place-tile")
    assert "destination flag" in (ROOT / ".cursor" / "rules" / "mockup-fidelity.mdc").read_text(encoding="utf-8")


def test_the_pulse_is_pure_css_every_2_seconds_on_one_shared_class():
    block = CSS.replace("\r\n", "\n").split("/* Pulse every 2 seconds:", 1)[1]
    selector = '.pulse-button:not(:disabled):not([aria-disabled="true"]):not(:active):not(:focus-visible)'
    assert selector + " {\n  animation: button-pulse 2s ease-in-out infinite;" in block
    assert "0% { transform: scale(1); }\n  10% { transform: scale(1.04); }\n  20% { transform: scale(1); }" in block  # 400 ms of 2 s
    assert "100% { transform: scale(1); }" in block
    assert "@media (prefers-reduced-motion: reduce) {\n  " + selector + " {\n    animation: none;" in block
    for body in (INDEX, GUIDE):
        assert "MutationObserver" not in body and "is-pulsing" not in body and "Pulse once" not in body
    assert "is-pulsing" not in CSS and "Pulse once" not in CSS and "Pulse once" not in PLAN
    assert "is-ready" not in CSS and "is-ready" not in INDEX and "find-ready" not in CSS  # Find my route's one-time pulse is gone
    for ident in ("find-route", "select-destination-stop", "confirm-destination-stop", "start-journey", "see-arrivals"):
        tag = INDEX.split(f'id="{ident}"', 1)[0].rsplit("<button", 1)[1] + INDEX.split(f'id="{ident}"', 1)[1].split(">", 1)[0]
        # Find my route, Confirm and Start journey carry the class; Select stop gets it only once a row is chosen (the page moves it
        # from Skip); See times never pulses
        assert ("pulse-button" in tag) is (ident not in ("see-arrivals", "select-destination-stop")), ident
    assert ":is(#select-destination-stop" not in CSS  # no id list any more
    assert "Pulse every 2 s" in PLAN and "CSS animation alone" in PLAN and "`pulse-button`" in PLAN
    assert "Action buttons pulse every 2 s" in GUIDE and GUIDE.count("pulse-button") >= 6


def test_the_leave_dialog_reuses_the_add_panels_save_and_cancel_classes_and_focuses_stay():
    dialog = INDEX.split('id="leave-dialog"', 1)[1].split("</div>\n    </div>", 1)[0]
    assert 'class="leave-dialog__actions saved-panel__actions saved-panel__actions--form"' in dialog
    assert '<button type="button" class="primary" id="leave-stay">Stay</button>' in dialog
    assert '<button type="button" class="secondary" id="leave-leave">Leave</button>' in dialog
    assert 'document.getElementById("leave-stay").focus();' in INDEX.split("function openLeaveDialog() {", 1)[1].split("}", 1)[0]
    assert ".leave-dialog__actions .button" not in CSS  # the old styling is gone
    assert "class=\"leave-dialog__actions saved-panel__actions saved-panel__actions--form\"" in GUIDE.replace('\\"', '"') or "leave-dialog__actions saved-panel__actions" in GUIDE
    plan = PLAN.split("the history stack and the \"Leave this journey?\" confirm", 1)[1][:300]
    assert "`Stay`" in plan and "`Leave`" in plan and "keyboard focus" in plan


def test_the_plan_no_longer_calls_the_back_arrow_sticky():
    para = PLAN.split("Back is a left-arrow icon button", 1)[1].split("\n", 1)[0]
    assert "It is sticky" not in para and "It is not sticky" in para and "scrolls away with the page" in para


def test_the_back_button_shares_the_menu_buttons_rule():
    rule = CSS.replace("\r\n", "\n").split(".back-bar .icon-button,\n.app-header .icon-button {", 1)[1].split("}", 1)[0]
    assert "background: var(--fill-warning);" in rule and "border: 2px solid var(--status-uncertain);" in rule
    assert "color: var(--line-cc-ink);" in rule
    assert 'aria-label="Back"' in INDEX and 'id="back-home"' in INDEX


def test_the_header_and_back_row_blocks_use_the_bottom_blocks_surface_and_the_card_radius():
    header, back = _rule(".app-header"), _rule(".back-bar")
    bottom = _rule(".catch-bar")
    for block in (header, back):
        assert "background: var(--color-card);" in block and "background: var(--color-card);" in bottom  # one surface token
        assert "border: 1px solid var(--color-line);" in block and "border-radius: var(--radius-card);" in block
        assert "box-shadow: var(--shadow-card);" in block and "var(--shadow-card)" in bottom
    assert "margin: max(var(--space-2), env(safe-area-inset-top)) auto var(--space-2);" in header
    for forbidden in ("position:", "sticky", "fixed", "top:", "z-index", "safe-area-inset-top"):
        assert forbidden not in back, forbidden  # the back row is not sticky: no offset, no layer, no safe-area padding
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", header + back) is None


def test_the_plan_and_the_style_guide_describe_the_new_blocks_pulse_and_flag():
    for text in ("rounded block", "pulse", "green flag"):
        assert text in PLAN.replace("rounded blocks", "rounded block").replace("pulses", "pulse"), text
    assert "DEST_FLAG_ICON" in GUIDE and "Destination (green flag)" in GUIDE
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()


# ---- the real page ------------------------------------------------------------------------------------------------------

CASES = [(w, d) for w in (320, 360, 1280) for d in (False, True)]


@pytest.fixture(scope="module", params=CASES, ids=[f"{w}-{'dark' if d else 'light'}" for w, d in CASES])
def report(request, tmp_path_factory):
    require_edge()
    width, dark = request.param
    with running_app(tmp_path_factory.mktemp("uiblocks")) as base:
        return run_scenario("uiblocks", base, {"width": width, "dark": dark}, timeout=300)["result"]


def test_every_page_has_a_rounded_header_block_with_a_gap_above_it(report):
    assert [p["page"] for p in report["pages"]] == PAGES
    for page in report["pages"]:
        header = page["header"]
        assert header["top"] >= 8 - 0.5, page["page"]  # a small gap above, from the very top edge
        assert header["radius"] == "12px" and header["borderWidth"] == "1px", page["page"]
        assert header["position"] != "fixed"
        assert header["left"] >= 8 - 0.5 and header["right"] <= report["pages"][0]["header"]["right"] + 0.5
        assert page["scrollWidth"] <= page["innerWidth"], page["page"]  # no sideways scroll


def test_every_page_but_home_has_a_static_back_block_a_small_gap_under_the_header(report):
    for page in report["pages"]:
        if page["page"] in ("home", "walk", "arrivals"):
            assert page["back"] is None  # Home has none; Pages W and B show their own back button beside the title instead
            continue
        back = page["back"]
        assert back is not None, page["page"]
        assert abs(page["gap"] - 8) <= 1, (page["page"], page["gap"])  # the gap between header and back row
        assert back["position"] == "static" and back["zIndex"] == "auto", page["page"]  # not sticky, not fixed, no layer
        assert back["radius"] == "12px" and back["borderWidth"] == "1px", page["page"]
        assert back["background"] == page["header"]["background"] and back["shadow"] == page["header"]["shadow"]


def test_the_blocks_use_the_same_surface_as_the_bottom_bar_in_this_theme(report):
    for page in report["pages"]:
        card = page["header"]["background"]
        assert _rgb(card) == _rgb(report["pages"][0]["header"]["background"])
        assert page["header"]["borderColor"] == report["pages"][0]["header"]["borderColor"]


def test_the_back_button_has_the_menu_buttons_colours_outline_and_size(report):
    menu, back = report["menuButton"], report["backButton"]
    for key in ("background", "color", "border", "borderWidth", "borderStyle", "radius", "iconColor", "w", "h"):
        assert menu[key] == back[key], key
    assert back["w"] >= 44 and back["h"] >= 44 and back["label"] == "Back"  # the accessible name is kept
    assert _contrast(back["iconColor"], back["background"]) >= 3.0  # the icon (3:1 is the bar; it is far above)
    assert back["borderWidth"] == "2px" and _rgb(back["background"]) == [242, 169, 0]


def test_each_button_pulses_every_2_seconds_while_visible_and_enabled(report):
    pulse = report["pulse"]
    assert pulse["see"]["count"] == 0  # See bus arrival times and See train times never pulse
    for key in ("selectEnabled", "confirm", "start", "find"):
        shown = pulse[key]
        assert shown["count"] == 1 and shown["state"] == "running" and shown["name"] == "button-pulse", key
        assert shown["duration"] == 2000 and shown["iterations"] == "Infinity", key  # a 2 s period, for as long as it shows
        assert shown["keyframes"] == [[0, "scale(1)"], [10, "scale(1.04)"], [20, "scale(1)"], [100, "scale(1)"]], key
    assert pulse["afterRelease"]["count"] == 1 and pulse["afterBlur"]["count"] == 1  # it comes back after press and focus


def test_the_pulse_stops_while_disabled_hidden_pressed_or_keyboard_focused(report):
    pulse = report["pulse"]
    for key in ("selectDisabled", "confirmDisabled", "startDisabled", "seeHidden", "findDisabled", "pressed", "keyboardFocus"):
        assert pulse[key]["count"] == 0, key
    assert pulse["keyboardFocus"]["focusVisible"] is True  # it was a keyboard focus that stopped it


def test_with_reduced_motion_there_is_no_animation_at_all(report):
    assert report["pulse"]["reduced"]["count"] == 0 and report["pulse"]["reducedFind"]["count"] == 0


def test_the_pulse_moves_nothing_and_never_scrolls_the_page_sideways_at_any_moment(report):
    samples = report["pulse"]["samples"]
    assert len(samples) == 6
    for sample in samples:
        assert sample["scrollWidth"] <= sample["innerWidth"]
    assert len({tuple(sample["offset"]) for sample in samples} | {tuple(report["pulse"]["selectEnabled"]["offset"])}) == 1


def test_every_nearby_stop_is_listed_in_order_including_ones_with_no_direct_bus(report):
    stops = report["stops"]
    codes = ["S1", "S2", "S3", "S4", "S5"]
    assert stops["order"] == codes and [row["code"] for row in stops["rows"]] == codes
    assert stops["selected"] is None and stops["rows"][0]["pill"] is True  # no row is chosen; the nearest keeps its Best option label
    assert [("is-unreachable" in row["cls"]) for row in stops["rows"]] == [False, True, False, True, False]  # listed, not dropped
    assert stops["scrollWidth"] <= stops["innerWidth"]


def test_no_row_has_a_note_and_the_bus_rows_keep_one_height(report):
    rows = report["stops"]["rows"]
    for row in rows:
        assert row["note"] is False, row["code"]
        assert "no direct bus" not in row["text"].lower() and "transfer" not in row["text"].lower(), row["code"]
    buses = [row for row in rows if row["code"] in ("S2", "S4", "S5")]  # not the first (it has the Best option pill)
    assert len({row["h"] for row in buses}) == 1, [row["h"] for row in buses]  # with and without a direct bus: the same height
    assert len({row["metas"] for row in buses}) == 1  # one meta line each (the walk), nothing extra


def test_every_destination_row_shows_the_green_flag_with_3_to_1(report):
    assert len(report["rows"]) >= 2
    for row in report["rows"]:
        assert row["path"] == FLAG_PATH and row["hidden"] == "true", row["title"]  # the map's flag; the title keeps the label
        assert _rgb(row["color"]) == _rgb(report["markerEnd"]), row["title"]
        assert _contrast(row["color"], row["background"]) >= 3.0, row["title"]


def test_four_buttons_carry_the_shared_pulse_class_in_the_page_and_see_times_does_not(report):
    assert report["pulse"]["classes"] == [[ident, ident not in ("see-arrivals", "select-destination-stop")] for ident in
                                          ("find-route", "select-destination-stop", "confirm-destination-stop",
                                           "start-journey", "see-arrivals")]


def test_the_back_row_is_not_sticky_it_scrolls_out_after_600px_and_returns_on_scroll_up(report):
    assert [entry["page"] for entry in report["scroll"]] == [p for p in PAGES if p not in ("home", "walk", "arrivals")]
    for entry in report["scroll"]:
        name, top, down, part, up = entry["page"], entry["top"], entry["down"], entry["part"], entry["up"]
        assert top["position"] == "static" and down["position"] == "static", name
        assert top["y"] == 0 and down["y"] == 600 and part["y"] == 300 and up["y"] == 0, name  # the page really scrolled
        assert down["backBottom"] <= 0 and down["headerBottom"] <= 0, name  # both are out of view after 600 px
        assert part["backTop"] == top["backTop"] - 300, name  # it moves 1:1 with the page: nothing holds it in place
        assert up["backTop"] == top["backTop"] and up["backBottom"] == top["backBottom"], name  # scrolling up reveals it again
        assert top["height"] == down["height"] == part["height"] == up["height"], name  # the page does not jump or reflow
        assert top["mainTop"] >= top["backBottom"] - 0.5, name  # the content starts under the back row: nothing is covered
        assert abs((top["backTop"] - top["headerBottom"]) - 8) <= 1, name  # the small gap under the header block
        assert top["scrollWidth"] <= top["innerWidth"] and down["scrollWidth"] <= down["innerWidth"], name


def test_stay_is_the_save_look_and_leave_is_the_cancel_look_with_the_focus_on_stay(report):
    dialog, panel = report["dialog"], report["panelButtons"]
    assert dialog["hidden"] is False and dialog["order"] == ["leave-stay", "leave-leave"]
    assert dialog["labels"] == ["Stay", "Leave"]  # the labels are text
    assert dialog["focus"] == "leave-stay"  # Stay is the default keyboard focus
    stay, leave = dialog["buttons"]
    save, cancel = panel
    assert save["text"] == "Save" and cancel["text"] == "Cancel"
    for key in ("color", "background", "border", "borderWidth", "borderStyle", "radius", "fontSize", "fontWeight", "paddingLeft", "paddingTop", "h"):
        assert stay[key] == save[key], ("Stay is the panel's Save", key)
        assert leave[key] == cancel[key], ("Leave is the panel's Cancel", key)
    assert stay["h"] >= 44 and leave["h"] >= 44 and stay["borderWidth"] == "2px"
    assert stay["border"] != leave["border"]  # green against red; the words still tell them apart
    assert dialog["scrollWidth"] <= dialog["innerWidth"]


def test_stay_and_leave_have_4_5_to_1_text_and_3_to_1_outlines_in_this_theme(report):
    dialog = report["dialog"]
    for button in dialog["buttons"]:
        assert _contrast(button["color"], dialog["background"]) >= 4.5, button["text"]
        assert _contrast(button["border"], dialog["background"]) >= 3.0, button["text"]

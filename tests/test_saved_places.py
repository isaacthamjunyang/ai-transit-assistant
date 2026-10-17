"""Saved places on Home: up to five places the user named, kept in this phone's localStorage only.

Three layers, none of which calls a live API: (1) static/saved-places.js run in node with a fake localStorage (add, edit,
delete, the limit of five, duplicates, long and empty names, malformed and unavailable storage); (2) static checks of the
page, copy.js, the style guide, the plan and the css; (3) the real page in headless Edge at 360 and 1280 px, light and
dark, with the destination search answered inside the page (no OneMap call). Every time in these tests is a fixed value."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "saved-places.js").read_text(encoding="utf-8")
KEY = "bus-catch-saved-places-v1"
STORAGE_LINE = "Can't save on this device."
COORDINATES = ["1.29667", "103.77639", "1.30421", "103.83197", "1.35711", "103.98905", "1.28349", "103.86026",
               "1.31386", "103.81589"]


# ---- (1) the storage module in node -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def unit():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "saved_places_unit.js")], capture_output=True, text=True,
                          timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_add_trims_keeps_the_order_and_stores_one_versioned_key(unit):
    add = unit["add"]
    assert add["first"] is True and add["second"] is True and add["stored"] is True
    assert add["names"] == ["Uni", "Shops"]  # in the order added, most recent last, trimmed
    assert add["raw"]["v"] == 1 and [p["name"] for p in add["raw"]["places"]] == ["Uni", "Shops"]
    assert set(add["raw"]["places"][0]) == {"id", "name", "address", "latitude", "longitude"}
    assert add["max"] == 5 and add["nameMax"] == 24


def test_empty_long_duplicate_invalid_and_sixth_places_are_refused(unit):
    errors = unit["errors"]
    assert errors["empty"] == {"ok": False, "error": "name"}
    assert errors["tooLong"] == {"ok": False, "error": "long"}
    assert errors["exactly24"] is True
    assert errors["duplicate"] == {"ok": False, "error": "duplicate"}  # the same point under another name
    assert errors["invalid"] == {"ok": False, "error": "invalid"}
    assert errors["full"] == {"ok": False, "error": "full"} and errors["count"] == 5


def test_edit_and_delete(unit):
    assert unit["edit"] == {"renamed": True, "name": "Campus", "empty": "name", "long": "long", "missing": "missing"}
    assert unit["remove"] == {"removed": True, "left": 0, "again": "missing"}


def test_malformed_storage_is_dropped_on_read_and_capped_at_five(unit):
    malformed = unit["malformed"]
    # bad entries, a repeat of the same point and everything past five are dropped; a repeated id is given a new one
    assert malformed["mixed"] == ["Good", "Two", "Same id", "Four", "Five"]
    for name in ("wrongVersion", "notJson", "notObject", "noList", "nullText"):
        assert malformed[name] == [], name
    assert len(set(malformed["ids"])) == len(malformed["ids"]) == 5  # every entry has its own id


def test_unavailable_storage_works_for_the_session_and_says_it_could_not_keep_it(unit):
    assert unit["unavailable"] == {"before": False, "ok": True, "stored": False, "names": ["Uni"], "after": False,
                                   "renamed": True, "renamedName": "Campus"}
    assert unit["quota"] == {"ok": True, "stored": False, "names": ["Uni"], "after": False}
    assert unit["missing"] == {"ok": True, "names": ["Uni"], "available": False}


def test_the_module_has_no_network_url_or_logging_and_one_key(unit):
    assert unit["source"] == {"fetch": False, "sessionStorage": False, "usesKey": 1}  # defined once
    assert "XMLHttpRequest" not in SCRIPT and "sendBeacon" not in SCRIPT


# ---- (2) static: words, wiring, privacy --------------------------------------------------------------------------


def _ui() -> str:
    """The page's saved-places code: from its banner comment to the first render at load."""
    start = INDEX.split("// ---- Saved places", 1)[1]
    return start.split(chr(10) + "    renderSavedPlaces();", 1)[0]


def test_only_the_estimator_the_theme_and_saved_places_use_storage():
    for name in ("index.html", "copy.js", "format-distance.js", "sw.js"):
        assert "localStorage" not in (ROOT / "static" / name).read_text(encoding="utf-8"), name
    assert "localStorage" in SCRIPT and "sessionStorage" not in INDEX and "indexedDB" not in INDEX
    assert 'src="saved-places.js"' in INDEX
    assert "saved-places.js" in PLAN.split("**Saved places (Home).**", 1)[0]  # the storage rule names the file


def test_copy_js_and_the_page_carry_the_same_words():
    block = COPY.split("savedPlaces: {", 1)[1].split("\n    },", 1)[0]
    for key, value in (("addLabel", "Add place"), ("add", "Add place"), ("editToggle", "Edit"),
                       ("doneToggle", "Done"), ("menuLabel", "Rename {name}"), ("deleteMarkLabel", "Delete {name}"),
                       ("count", "{n} of {max} saved"), ("save", "Save"), ("cancel", "Cancel"),
                       ("deleteConfirm", "Delete {name}?"), ("deleteYes", "Delete"),
                       ("errorName", "Enter a name for this place."), ("errorDuplicate", "That place is already saved."),
                       ("errorFull", "You can save up to {max} places."), ("storageUnavailable", STORAGE_LINE)):
        assert f'{key}: "{value}"' in block, key
        assert f'"{value}"' in INDEX or f">{value}<" in INDEX, value
    assert STORAGE_LINE in INDEX


def test_the_row_markup_is_the_plus_chip_alone_and_no_starters_exist_anywhere():
    row = INDEX.split('id="quick-picks"', 1)[1].split("</div>", 1)[0]
    texts = re.findall(r"<span>([^<]+)</span></button>", row)
    assert texts == ["Add place"]  # the plus mark and the words "Add place"
    for text in (INDEX, COPY, GUIDE):
        assert "QUICK_PICKS" not in text and "quickPicks" not in text and "starters" not in text.lower()
    para = PLAN.split("**Saved places (Home).**", 1)[1].split("\n", 1)[0]
    assert "starter" not in para.lower() and "With nothing saved the row is the `Add place` chip alone." in para
    assert INDEX.count('class="quick-pick"') == 0  # no plain suggestion chip in the markup


def test_the_row_handler_only_runs_saved_actions_and_never_fills_the_search_box_or_sends_anything():
    handler = INDEX.split('getElementById("quick-picks").addEventListener("click"', 1)[1].split("});", 1)[0]
    assert "savedPlaceAction(chip)" in handler and "destinationInput.value" not in handler
    assert "fetch(" not in handler and "pushScreen" not in handler
    ui = _ui()
    # the only request the saved-places code makes is the ordinary destination search typed in the add panel
    assert ui.count("fetch(") == 1 and 'fetch("/api/destinations?q=" + encodeURIComponent(query))' in ui
    for banned in ("sendBeacon", "XMLHttpRequest", "localStorage", "sessionStorage", "console.", "location.", "history."):
        assert banned not in ui, banned
    # a tap behaves like a picked result: the same pending destination and the same confirm step
    assert "pendingDestination = {" in ui and "confirmPendingDestination();" in ui
    assert "latitude: place.latitude" in ui and "longitude: place.longitude" in ui


def test_the_rows_render_the_name_and_address_but_never_the_point():
    ui = _ui()
    row = ui.split("function renderSavedPlaces() {", 1)[1].split("function selectSavedPlace", 1)[0]
    panels = ui.split("function openEditPanel(id) {", 1)[1].split("function openAddPanel() {", 1)[0]
    picked = ui.split("function showPicked() {", 1)[1].split("}", 1)[0]
    for text in (row, panels, picked):
        assert "latitude" not in text and "longitude" not in text
    assert "innerHTML" not in ui  # names and addresses go in as text, never as markup


def test_css_44px_ellipsis_tokens_and_no_inline_styles():
    block = CSS.split("/* Saved places on Home", 1)[1].split(".hairline {", 1)[0]
    assert "text-overflow: ellipsis;" in block and "min-width: var(--tap-min);" in block
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block) is None
    assert ".quick-pick {\n  min-height: var(--tap-min);" in CSS
    ui = _ui()
    assert ".style." not in ui and 'setAttribute("style"' not in ui


def test_the_style_guide_shows_empty_one_selected_five_edit_mode_add_and_delete():
    assert "copy.home.quickPicks" not in GUIDE and "starters" not in GUIDE.lower()
    assert "is-concealed" not in GUIDE.split("function sgSavedRow(", 1)[1].split("function sgSavedField", 1)[0]
    for needle in ("sgSavedRow([])", 'sgSavedRow(["Home"])', "sgSavedRow([\"Home\", \"School\"", ", true)",
                   'sgSavedRow(["Home", "School"], false, 0)', 'sgSavedPanel("add")', 'sgSavedPanel("delete")',
                   "storageUnavailable", "copy.home.savedPlaces", "sp.deleteMarkLabel", "sp.editToggle",
                   "saved-chip__badge"):
        assert needle in GUIDE, needle


def test_there_is_no_ellipsis_menu_circle_anywhere():
    block = COPY.split("savedPlaces: {", 1)[1].split("\n    },", 1)[0]
    assert "menu:" not in block and chr(0x2026) not in block
    ui = _ui()
    guide = GUIDE.split("function sgSavedRow(", 1)[1].split("function sgSavedField", 1)[0]
    for text in (ui, guide):
        assert "saved-chip__menu" not in text and "saved-chip__delete" not in text
        assert chr(0x2026) not in text.replace("Searching" + chr(0x2026), "") and "SP.menu," not in text
    assert "saved-chip__menu" not in CSS and "saved-chip__delete" not in CSS
    para = PLAN.split("**Saved places (Home).**", 1)[1].split("\n", 1)[0]
    assert "There is no `" + chr(0x2026) + "` button in the normal row" in para


def test_the_chips_are_arrive_by_chips_with_no_green_outline_and_the_shared_selected_ring():
    block = CSS.split(".saved-chip__main {", 1)[1].split(".saved-chip__name {", 1)[0]
    assert "border-color" not in block and "success" not in block  # no green outline: the chip's own light outline
    assert "color: var(--color-ink);" in block
    assert "background" not in block  # no tint: the normal chip background
    assert "--tint-success" not in CSS.split("/* Saved places on Home", 1)[1].split(".hairline {", 1)[0]
    assert "0 0 0 2px var(--color-card), 0 0 0 4px" not in CSS  # no gap ring
    shared = CSS.split(".menu-radio.is-selected,\n.arrive-chip.is-selected,\n.saved-chip__main.is-selected {", 1)[1].split("}", 1)[0]
    assert "box-shadow: 0 0 0 2px var(--color-selected-outline);" in shared  # the Arrive by chip's selected look
    theme = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
    for token in ("--color-selected-outline-success", "--color-selected-outline", "--color-ink"):
        assert token in theme
    saved_css = CSS.split("/* Saved places on Home", 1)[1].split(".hairline {", 1)[0]
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", saved_css) is None


def test_there_is_no_tick_icon_anywhere():
    ui = _ui()
    guide = GUIDE.split("function sgSavedRow(", 1)[1].split("function sgSavedField", 1)[0]
    for name, text in (("page", ui), ("css", CSS), ("guide", guide)):
        assert "saved-chip__tick" not in text and "spTick" not in text and "SG_TICK" not in text, name
    assert "createElementNS" not in ui
    assert "tick" not in PLAN.split("**Saved places (Home).**", 1)[1].split("\n", 1)[0].lower()


def test_the_delete_badge_is_24px_with_a_44px_hit_area_inside_the_row_gap_and_a_focus_ring():
    badge = CSS.split(".saved-chip__badge {", 1)[1].split("}", 1)[0]
    assert "position: absolute;" in badge and "top: -12px;" in badge and "right: -12px;" in badge
    assert "width: var(--tap-min);" in badge and "height: var(--tap-min);" in badge
    mark = CSS.split(".saved-chip__badge-mark {", 1)[1].split("}", 1)[0]
    assert "width: 24px;" in mark and "height: 24px;" in mark
    row = CSS.split(".quick-picks {", 1)[1].split("}", 1)[0]
    assert "gap: 14px;" in row  # more than the 12 px the hit area reaches beyond a chip
    focus = CSS.split(".saved-chip__badge:focus-visible .saved-chip__badge-mark {", 1)[1].split("}", 1)[0]
    assert "outline: 2px solid var(--color-focus);" in focus
    ui = _ui()
    assert 'spFill(SP.deleteMarkLabel, { name: place.name })' in ui and "if (savedEditMode) {\n          var badge" in ui


def test_there_is_no_custom_chip_anywhere():
    block = COPY.split("savedPlaces: {", 1)[1].split("\n    },", 1)[0]
    assert "custom" not in block.lower() and "Custom place" not in INDEX and "Custom place" not in GUIDE
    ui = _ui()
    assert "customPlace" not in INDEX and 'data-saved-action="custom"' not in INDEX
    assert "Custom" not in ui and "custom" not in ui.replace("customize", "")
    saved_guide = GUIDE.split("function sgSavedRow(", 1)[1].split("function screenSample()", 1)[0]
    assert "Custom" not in saved_guide and "sp.custom" not in GUIDE
    para = PLAN.split("**Saved places (Home).**", 1)[1].split("\n", 1)[0]
    assert "There is no `Custom` chip" in para
    row = INDEX.split('id="quick-picks"', 1)[1].split("</div>", 1)[0]
    assert "Custom" not in row


def test_the_plan_says_saved_places_stay_on_the_phone():
    para = PLAN.split("**Saved places (Home).**", 1)[1].split("\n", 1)[0]
    for text in ("Saved places stay on the phone", "localStorage", "never the coordinates", STORAGE_LINE, "`Edit`",
                 "`Done`", "`Delete {name}?`", "Escape", "five", "Demo Mode is unchanged"):
        assert text in para, text
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()  # the line endings are kept


# ---- (3) the real page ---------------------------------------------------------------------------------------------


def _run(tmp_path_factory, name, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name)) as base:
        return run_scenario("savedplaces", base, {"name": name, **config}, timeout=300)["result"]


@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)],
                ids=["360-light", "1280-dark"])
def flow(request, tmp_path_factory):
    name, width, height, dark = request.param
    return _run(tmp_path_factory, "saved" + name, mode="flow", width=width, height=height, dark=dark)


@pytest.fixture(scope="module")
def private_mode(tmp_path_factory):
    return _run(tmp_path_factory, "savedprivate", mode="storage", width=390, height=844, dark=False)


def _names(snap):
    return [item["text"] for item in snap["row"]]


def test_with_nothing_saved_the_row_is_plus_alone_with_no_edit(flow):
    empty = flow["steps"]["empty"]
    assert _names(empty) == ["Add place"]
    assert [item["saved"] for item in empty["row"]] == [False]
    assert empty["toggle"] is None
    assert empty["count"] is None and empty["storage"] is None and empty["stored"] is None
    none = flow["steps"]["none"]
    assert _names(none) == ["Add place"] and none["toggle"] is None
    assert none["edit"]["toggle"] is None and none["edit"]["badgeCount"] == 0 and none["edit"]["badges"] == []


def test_edit_appears_after_the_first_save(flow):
    steps = flow["steps"]
    after = steps["afterFirst"]
    assert _names(after) == ["Uni", "Add place", "Edit"] and after["toggle"] == "Edit"
    assert steps["solo"]["toggle"] == "Edit"


def test_edit_disappears_and_edit_mode_ends_after_the_last_delete(flow):
    steps = flow["steps"]
    assert steps["soloEdit"]["toggle"] == "Done" and steps["soloEdit"]["edit"]["badgeCount"] == 1
    last = steps["lastDeleted"]
    assert _names(last) == ["Add place"] and last["toggle"] is None
    assert last["edit"]["badgeCount"] == 0 and last["edit"]["toggle"] is None
    assert last["panel"] is None and last["stored"] is not None and json.loads(last["stored"])["places"] == []


def test_the_add_panel_opens_and_closes_with_no_muted_note_anywhere(flow):
    steps = flow["steps"]
    assert steps["noneAddOpen"]["panel"] is not None and "Pick a place from the results, then" not in steps["noneAddOpen"]["panel"]
    assert steps["noneAfterCancel"]["panel"] is None and steps["noneAfterCancel"]["toggle"] is None
    assert steps["addOpen"]["toggle"] is None
    for step in (steps["none"], steps["solo"], steps["five"]):
        assert "Saved on this phone only." not in json.dumps(step)


def test_the_empty_and_saved_states_have_the_same_layout_so_nothing_shifts(flow):
    none, solo, closed = flow["steps"]["none"], flow["steps"]["solo"], flow["steps"]["noneAfterCancel"]
    for other in (solo, closed):
        assert other["layout"]["row"]["top"] == none["layout"]["row"]["top"]
        assert other["layout"]["row"]["height"] == none["layout"]["row"]["height"]
        assert other["layout"]["below"]["top"] == none["layout"]["below"]["top"]


def test_add_picks_a_result_then_the_user_types_their_own_name(flow):
    steps = flow["steps"]
    assert "Add a saved place" in steps["addOpen"]["panel"]
    assert steps["noPickSave"]["error"] == "Pick a place from the results first."
    assert steps["picked"]["picked"] == "National University of Singapore · 21 Lower Kent Ridge Road"
    assert steps["picked"]["nameShown"] is True and steps["picked"]["focus"] == "saved-name"
    assert steps["picked"]["maxLength"] == 24
    assert steps["emptyName"]["error"] == "Enter a name for this place."  # empty (spaces only) is rejected
    assert steps["picked"]["maxLength"] == 24  # the field stops typing at 24 characters
    assert steps["longRefused"]["error"] == "Use 24 characters or fewer."  # and a longer value is refused outright
    after = steps["afterFirst"]
    assert _names(after)[:1] == ["Uni"]  # trimmed
    assert after["panel"] is None
    stored = json.loads(after["stored"])
    assert stored["v"] == 1 and stored["places"][0]["name"] == "Uni"
    assert stored["places"][0]["latitude"] == 1.29667 and stored["places"][0]["longitude"] == 103.77639


def test_a_duplicate_is_refused_with_a_short_message(flow):
    duplicate = flow["steps"]["duplicate"]
    assert duplicate["error"] == "That place is already saved."
    assert _names(duplicate)[:1] == ["Uni"] and _names(duplicate).count("Again") == 0


def test_the_limit_of_five_hides_plus_and_shows_the_count_in_the_order_added(flow):
    four, five = flow["steps"]["four"], flow["steps"]["five"]
    assert _names(four) == ["Uni", "Shops", "Grandmother's flat Bedok", "Work", "Add place", "Edit"]
    assert _names(five) == ["Uni", "Shops", "Grandmother's flat Bedok", "Work", "Park", "Edit"]
    assert five["count"] == "5 of 5 saved" and four["count"] is None
    assert len(json.loads(five["stored"])["places"]) == 5


def test_layout_44px_ellipsis_and_nothing_scrolls_sideways(flow):
    layout = flow["steps"]["fiveLayout"]
    assert layout["minHeight"] >= 44 and layout["maxRight"] <= layout["innerWidth"]
    assert all(value == "ellipsis" for value in layout["ellipsis"])
    for snap in flow["steps"].values():
        if isinstance(snap, dict) and "scrollWidth" in snap:
            assert snap["scrollWidth"] <= snap["innerWidth"]
    # a long name keeps its full name in the aria-label
    long_label = next(item for item in flow["steps"]["five"]["row"] if item["text"] and "Grandmother" in item["text"])
    assert long_label["label"].startswith("Grandmother's flat Bedok, saved place")


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [int(value) for value in re.findall(r"\d+", text)[:3]]


def _luminance(rgb):
    channels = [value / 255 for value in rgb]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground, background):
    high, low = sorted((_luminance(_rgb(foreground)), _luminance(_rgb(background))), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_saved_chips_have_the_arrive_by_outline_no_tint_and_no_icon(flow):
    look, tokens = flow["steps"]["look"], flow["steps"]["tokens"]
    assert look["icons"] == 0 and look["tickNodes"] == 0 and look["name"] == "Uni"
    assert look["borderWidth"] == "1px"
    assert _rgb(look["border"]) == _rgb(tokens["line"]) and _rgb(look["border"]) != _rgb(tokens["outlineSuccess"])  # not green
    assert _rgb(look["background"]) == _rgb(tokens["card"])  # the normal chip background: no tint
    assert _rgb(look["background"]) != _rgb(tokens["tint"])
    assert _rgb(look["color"]) == _rgb(tokens["ink"]) and _rgb(look["nameColor"]) == _rgb(tokens["ink"])
    assert _contrast(look["nameColor"], look["background"]) >= 4.5


def test_the_plus_chip_has_the_normal_chip_background(flow):
    look = flow["steps"]["look"]
    assert _rgb(look["addBackground"]) == _rgb(look["background"])


def test_the_selected_chip_has_the_arrive_by_blue_selected_outline(flow):
    selected, unselected, tokens = flow["steps"]["selected"], flow["steps"]["unselected"], flow["steps"]["tokens"]
    assert "is-selected" in selected["cls"] and selected["pressed"] == "true"
    assert selected["others"] == 1
    shadow = selected["shadow"].replace(" ", "")
    blue, card = _rgb(tokens["outlineSelected"]), _rgb(tokens["card"])
    assert shadow == f"rgb({blue[0]},{blue[1]},{blue[2]})0px0px0px2px"  # the 2 px selected outline, as a selected Arrive by chip
    assert _rgb(selected["border"]) == _rgb(tokens["line"])  # no green outline
    assert _contrast(tokens["outlineSelected"], tokens["card"]) >= 3.0
    assert "is-selected" not in unselected["cls"] and unselected["pressed"] == "false"
    assert unselected["width"] == selected["width"]  # selecting does not change the chip's size


def test_chips_sit_side_by_side_with_no_ellipsis_circle_between_them(flow):
    look = flow["steps"]["look"]
    assert look["chipCount"] == 5 and look["menus"] == 0 and look["menuButtons"] == 0
    assert all(10 <= gap <= 14 for gap in look["gaps"]), look["gaps"]  # side by side, one even gap


def test_edit_mode_puts_a_small_delete_badge_on_each_chips_upper_right_corner(flow):
    steps = flow["steps"]
    normal, editing = steps["normalRead"], steps["editRead"]
    assert normal["toggle"] == "Edit" and normal["pressed"] == "false" and normal["badgeCount"] == 0
    assert normal["menus"] == 0
    assert editing["toggle"] == "Done" and editing["pressed"] == "true" and editing["badgeCount"] == 5
    assert len(editing["badges"]) == 5
    for badge in editing["badges"]:
        assert badge["text"] == "\u00d7" and badge["label"].startswith("Delete ")
        assert badge["tag"] == "BUTTON" and badge["tabindex"] >= 0
        assert badge["hitWidth"] >= 44 and badge["hitHeight"] >= 44  # the invisible hit area
        assert badge["markWidth"] == 24 and badge["markHeight"] == 24  # the visible badge
        assert abs(badge["dx"]) <= 1.5 and abs(badge["dy"]) <= 1.5  # centred on the chip's upper right corner
        assert badge["overlapsNeighbour"] is False  # never over another chip's tap area
        assert badge["overlapsOwnChip"] is True
    assert editing["scrollWidth"] <= editing["innerWidth"]
    assert steps["badgeFocus"] == {"focused": True, "tag": "BUTTON"}


def test_no_layout_shift_entering_or_leaving_edit_mode(flow):
    steps = flow["steps"]
    assert steps["normalGeometry"] == steps["editGeometry"]


def test_in_edit_mode_the_chip_name_opens_the_rename_panel_and_does_not_select(flow):
    steps = flow["steps"]
    assert [main["action"] for main in steps["editRead"]["mains"]] == ["rename"] * 5
    assert all(main["label"].startswith("Rename ") for main in steps["editRead"]["mains"])
    assert [main["action"] for main in steps["normalRead"]["mains"]] == ["open"] * 5
    assert steps["edit"]["value"] == "Shops" and "Edit name" in steps["edit"]["panel"]
    assert steps["edit"]["screen"] == "home" and steps["edit"]["saved"] is None
    assert steps["editEmpty"]["error"] == "Enter a name for this place."
    assert _names(steps["renamed"])[:2] == ["Uni", "Mall"]
    assert steps["renamed"]["edit"]["toggle"] == "Done"  # still editing after a rename


def test_delete_asks_first_cancel_keeps_it_and_delete_removes_it_with_no_request(flow):
    steps = flow["steps"]
    assert "Delete Mall?" in steps["confirm"]["panel"]
    assert "Delete" in steps["confirm"]["panel"] and "Cancel" in steps["confirm"]["panel"]
    cancelled = steps["cancelled"]
    assert cancelled["panel"] is None and cancelled["edit"]["toggle"] == "Done"  # still editing
    assert [item["text"] for item in cancelled["row"] if item["saved"]][:2] == ["Uni", "Mall"]
    assert len(json.loads(cancelled["stored"])["places"]) == 5
    deleted = steps["deleted"]
    saved = [item["text"] for item in deleted["row"] if item["saved"]]
    assert "Mall" not in saved and len(saved) == 4
    assert [place["name"] for place in json.loads(deleted["stored"])["places"]] == saved  # storage and row agree
    assert deleted["edit"]["toggle"] == "Edit" and deleted["edit"]["badgeCount"] == 0  # edit mode ended
    assert "Add place" in _names(deleted) and deleted["count"] is None  # room again: "+" is back
    assert steps["sentAfterDelete"] == []  # no network request of any kind


def test_escape_and_done_leave_edit_mode_and_every_control_is_a_button(flow):
    steps = flow["steps"]
    assert steps["escapeBefore"] == "Done" and steps["escapeAfter"] == "Edit"
    assert steps["escapeFromConfirm"]["panel"] is None and steps["escapeFromConfirm"]["edit"]["toggle"] == "Edit"
    assert steps["done"]["toggle"] == "Edit" and steps["done"]["badgeCount"] == 0
    for control in steps["keyboard"] + steps["keyboardEdit"]:
        assert control["tag"] == "BUTTON" and control["type"] == "button" and control["tabindex"] >= 0
        assert control["label"] is True  # a name for every control
    assert len(steps["keyboardEdit"]) == len(steps["keyboard"]) + 4  # the four badges join the tab order


def test_malformed_storage_is_dropped_and_garbage_gives_the_plus_chip_alone(flow):
    steps = flow["steps"]
    saved = [item["text"] for item in steps["malformed"]["row"] if item["saved"]]
    assert saved == ["Good", "Two", "Three", "Four", "Five"]
    assert [item["text"] for item in steps["garbage"]["row"]] == ["Add place"]
    assert steps["garbage"]["toggle"] is None


def test_a_tap_goes_to_the_stops_step_like_a_search_result_with_the_stored_point(flow):
    steps = flow["steps"]
    assert steps["tapNoArrive"]["screen"] == "home" and steps["tapNoArrive"]["prompted"] is True
    assert steps["tapNoArrive"]["prompt"] == "Choose when you need to arrive, or select No target."
    assert steps["tapNoArrive"]["selected"] is None and steps["tapNoArrive"]["value"] == "Uni"
    tap = steps["tap"]
    assert tap["screen"] == "stops" and tap["name"] == "Uni" and tap["heading"] == "Uni"
    assert tap["address"] == "21 Lower Kent Ridge Road"
    assert (tap["latitude"], tap["longitude"]) == (1.29667, 103.77639)
    assert tap["searches"] >= 0
    # the only request a tap makes is the destination-stops load a picked result makes, with that point
    stops = [r for r in tap["requests"] if "/api/destination-stops" in r]
    assert stops and all("dest_lat=1.29667" in r and "dest_lon=103.77639" in r for r in stops)
    assert not [r for r in tap["requests"] if "/api/destinations" in r]  # no search for a saved place


def test_typing_in_the_search_box_clears_a_chosen_saved_place(flow):
    steps = flow["steps"]
    assert steps["typedBefore"]["saved"] == "Uni"
    assert steps["typedAfter"]["saved"] is None and steps["typedAfter"]["value"] == "Marina"
    assert steps["noCustom"] is True


def test_coordinates_are_stored_but_never_rendered(flow):
    text = flow["steps"]["text"]
    for coordinate in COORDINATES:
        assert coordinate not in text, coordinate
    for snap in flow["steps"].values():
        if isinstance(snap, dict) and snap.get("panel"):
            assert not re.search(r"\b1\.\d{4,}|\b103\.\d{4,}", snap["panel"])
    for item in flow["steps"]["five"]["row"]:
        assert not re.search(r"\b1\.\d{4,}|\b103\.\d{4,}", (item["label"] or "") + (item["text"] or ""))


def test_no_network_request_carries_saved_data(flow):
    saved_words = ["Uni", "Shops", "Grandmother", "Work", "Park", "Mall", "Again", "bus-catch-saved-places"]
    for line in flow["steps"]["network"]:
        if "/api/destination-stops" in line:  # the tap, the same request a picked search result makes
            continue
        for word in saved_words:
            assert word not in line, (word, line)
        for coordinate in COORDINATES:
            assert coordinate not in line, (coordinate, line)


def test_private_mode_works_for_the_session_and_says_so_once(private_mode):
    steps = private_mode["steps"]
    assert steps["empty"]["storage"] is None
    assert _names(steps["firstSave"])[:1] == ["School"] and steps["firstSave"]["storage"] == STORAGE_LINE
    assert _names(steps["secondSave"])[:2] == ["School", "Shops"]
    assert steps["secondSave"]["storage"] == STORAGE_LINE  # still the one line, not a second one
    assert steps["secondSave"]["stored"] == "unavailable"


# ---- the "+" and Edit chips ------------------------------------------------------------------------------------------


def test_css_gives_plus_a_dashed_green_outline_and_edit_a_red_one_from_existing_tokens():
    add = CSS.split(".quick-picks .quick-pick--add {", 1)[1].split("}", 1)[0]
    assert "border-style: dashed;" in add and "border-color: var(--color-selected-outline-success);" in add
    assert "color: var(--status-live);" in add
    toggle = CSS.split(".quick-picks .saved-edit-toggle {", 1)[1].split("}", 1)[0]
    assert "border-color: var(--status-stale);" in toggle and "color: var(--status-stale);" in toggle
    done = CSS.split('.quick-picks .saved-edit-toggle[aria-pressed="true"] {', 1)[1].split("}", 1)[0]
    assert "border-color: var(--color-selected-outline);" in done and "color: var(--color-ink);" in done
    assert "background: var(--color-secondary);" in done
    theme = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
    for token in ("--status-stale", "--status-live", "--color-selected-outline-success", "--color-line"):
        assert token in theme
    saved_css = CSS.split("/* Saved places on Home", 1)[1].split(".hairline {", 1)[0]
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", saved_css + add + toggle + done) is None


def test_the_plan_and_the_style_guide_describe_the_plus_and_edit_colours():
    para = PLAN.split("**Saved places (Home).**", 1)[1].split("\n", 1)[0]
    for text in ("dashed green outline", "red outline and red text", "blue selected outline", "4.5:1", "3:1"):
        assert text in para, text
    assert "dashed green" in GUIDE and "Edit red" in GUIDE and "Done has the blue outline" in GUIDE


def test_plus_is_a_dashed_green_chip_with_green_text_and_keeps_its_label(flow):
    steps, tokens = flow["steps"], flow["steps"]["tokens"]
    add, saved = steps["controlsNormal"]["add"], steps["controlsNormal"]["saved"]
    assert add["text"] == "Add place" and add["label"] == "Add place" and add["visible"] is True
    assert add["borderStyle"] == "dashed" and saved["borderStyle"] == "solid"  # differs from the saved chips
    assert _rgb(add["borderColor"]) == _rgb(tokens["outlineSuccess"])
    assert _rgb(add["color"]) == _rgb(tokens["live"])
    assert _contrast(add["color"], add["background"]) >= 4.5  # the "+" against the chip
    assert _contrast(add["borderColor"], add["background"]) >= 3.0  # the outline against the chip
    assert add["height"] >= 44 and add["width"] >= 44


def test_edit_is_a_red_chip_that_reads_done_and_goes_neutral_while_editing(flow):
    steps, tokens = flow["steps"], flow["steps"]["tokens"]
    normal, editing, back = (steps[name]["toggle"] for name in ("controlsNormal", "controlsEditing", "controlsBack"))
    assert normal["text"] == "Edit" and normal["label"] == "Edit saved places" and normal["visible"] is True
    assert _rgb(normal["borderColor"]) == _rgb(tokens["stale"]) and _rgb(normal["color"]) == _rgb(tokens["stale"])
    assert _contrast(normal["color"], normal["background"]) >= 4.5
    assert _contrast(normal["borderColor"], normal["background"]) >= 3.0
    assert editing["text"] == "Done" and editing["pressed"] == "true" and editing["visible"] is True
    assert _rgb(editing["borderColor"]) == _rgb(tokens["outlineSelected"]) and _rgb(editing["color"]) == _rgb(tokens["ink"])
    assert _contrast(editing["color"], editing["background"]) >= 4.5
    assert back["text"] == "Edit" and _rgb(back["color"]) == _rgb(tokens["stale"])  # red again after Done
    # the size does not change between Edit and Done (so nothing moves)
    assert normal["width"] == editing["width"] == back["width"] and normal["height"] == editing["height"] >= 44


def test_plus_and_edit_differ_from_each_other_and_from_a_saved_chip(flow):
    controls = flow["steps"]["controlsNormal"]
    colours = {tuple(_rgb(controls[name]["borderColor"])) for name in ("add", "toggle", "saved")}
    assert len(colours) >= 2
    assert _rgb(controls["add"]["borderColor"]) != _rgb(controls["toggle"]["borderColor"])
    assert _rgb(controls["toggle"]["color"]) != _rgb(controls["add"]["color"])

"""Page W follows the approved design tmp/design/pagew-v2.html: the order of its parts, the six states, the big distance,
the chance card with the vehicle marker and badge, its own back button, and the sensor details (headless Edge)."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
import test_train_pages as ttp
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
RULES = (ROOT / ".cursor" / "rules" / "mockup-fidelity.mdc").read_text(encoding="utf-8")


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


def test_the_page_parts_are_in_the_designs_order():
    page = INDEX.split('<section id="walk-page"', 1)[1].split('<section class="live-page"', 1)[0]
    ids = ["walk-back", "walk-title", "walk-ring", "walk-state-alert", "walk-map-slot", "walk-sensors"]
    positions = [page.index(f'id="{ident}"') for ident in ids]
    assert positions == sorted(positions), positions  # back and title, the chance card, the distance card, the map, the sensors


def test_the_state_line_is_the_shared_alert_with_one_kind_per_state():
    assert '<div id="walk-state-alert" class="alert alert--neutral">' in INDEX and '<p id="walk-state" class="alert__text">' in INDEX
    kinds = INDEX.split("var WALK_STATE_KIND = ", 1)[1].split(";", 1)[0]
    assert kinds == '{ waiting: "neutral", checking: "info", onway: "success", away: "error", still: "warning", arrived: "success" }'
    assert "setAlertKind(document.getElementById(\"walk-state-alert\"), WALK_STATE_KIND[state]);" in INDEX
    assert 'id="walk-sensor-why" class="alert alert--info"' in INDEX  # the sensor details' note too
    for gone in ("walk-status__state", "walk-sensors__why"):
        assert gone not in CSS and gone not in INDEX, gone


def test_the_movement_logic_the_rescore_and_the_words_are_unchanged():
    for word in ("Waiting for your location…", "Checking your movement…", "On your way", "Moving away", "Not moving", "Arrived"):
        assert word in INDEX and word in COPY, word
    assert "function walkStateOf(" in INDEX and "WALK_RESCORE_MS" in INDEX
    assert "{distance} to go" in COPY and "{distance} to the station" in COPY  # the strings are the same; the page splits them


def test_page_w_has_its_own_back_button_in_the_menu_buttons_rule_and_hides_the_back_row():
    assert 'id="walk-back" class="icon-button walk-back" aria-label="Back"' in INDEX
    assert 'getElementById("walk-back").addEventListener("click", function () {\n      requestBack();' in INDEX.replace("\r\n", "\n")
    rule = CSS.replace("\r\n", "\n").split(".walk-page .icon-button,\n.back-bar .icon-button,\n.app-header .icon-button {", 1)[1].split("}", 1)[0]
    assert "background: var(--fill-warning);" in rule and "border: 2px solid var(--status-uncertain);" in rule
    assert "body.is-page-w .back-bar {\n  display: none;" in CSS.replace("\r\n", "\n")


def test_the_new_page_w_rules_use_tokens_only():
    block = CSS.replace("\r\n", "\n").split("/* The approved Page W design", 1)[1].split("/* Style guide frames for the Page W samples", 1)[0]
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block) is None
    assert "style=" not in INDEX.split('<section id="walk-page"', 1)[1].split('<section class="live-page"', 1)[0]


def test_the_plan_the_rules_and_the_style_guide_name_the_approved_design():
    para = PLAN.split("**Page W (the approved design supersedes the mockup for Page W).**", 1)[1].split("\n", 1)[0]
    for text in ("tmp/design/pagew-v2.html", "own back button", "shared alert", "300 px", "`--ring-neutral`", "Sensor details"):
        assert text in para, text
    assert "Page W follows tmp/design/pagew-v2.html" in RULES
    assert "function sgWalkPage(" in GUIDE and "walk-band" in GUIDE and "walk-back" in GUIDE and "SG_TREND_ICON" in GUIDE
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()  # the line endings are kept


# ---- the real page ------------------------------------------------------------------------------------------------------

CASES = [("bus", 360, False), ("bus", 360, True), ("bus", 1280, False), ("bus", 1280, True), ("bus", 320, False), ("bus", 320, True),
         ("train", 360, False), ("train", 360, True), ("train", 1280, False), ("train", 1280, True)]


@pytest.fixture(scope="module", params=CASES, ids=[f"{k}-{w}-{'dark' if d else 'light'}" for k, w, d in CASES])
def page(request, tmp_path_factory):
    require_edge()
    kind, width, dark = request.param
    if kind == "bus":
        with running_app(tmp_path_factory.mktemp("pwbus")) as base:
            result = run_scenario("pagewv2", base, {"width": width, "dark": dark, "kind": kind}, timeout=300)["result"]
    else:
        with running_app(tmp_path_factory.mktemp("pwtrain"), onemap=stub.by_mode({"TRANSIT": stub.train_first}),
                         rail_table=ttp._table(), lta_status=500) as base:
            result = run_scenario("pagewv2", base, {"width": width, "dark": dark, "kind": kind}, timeout=300)["result"]
    return {"kind": kind, "width": width, **result}


EXPECTED = {
    "onway": ("On your way", "success"), "checking": ("Checking your movement…", "info"), "away": ("Moving away", "error"),
    "still": ("Not moving", "warning"), "waiting": ("Waiting for your location…", "neutral"),
}


def test_the_parts_are_in_order_and_the_page_back_row_is_replaced_by_the_title_back_button(page):
    assert page["order"] is True
    assert page["globalBack"] == "none"
    back, menu = page["backButton"], page["menuButton"]
    for key in ("background", "color", "border", "borderWidth", "radius", "w", "h"):
        assert back[key] == menu[key], key  # the menu button's colours, outline and size
    assert back["w"] >= 44 and back["h"] >= 44 and back["label"] == "Back" and back["tag"] == "BUTTON"
    assert page["title"]["size"] == 22 and page["title"]["weight"] == "800"


def test_each_state_has_its_words_and_its_shared_alert_kind(page):
    for name, (text, kind) in EXPECTED.items():
        state = page["states"][name]
        assert state["text"] == text and state["kind"] == [kind], name
        assert state["isAlert"] is True and state["alertIcon"] is True, name  # drawn by the shared alert component
    arrived = page["states"]["arrived"]
    assert arrived["text"] == ("Arrived at the station" if page["kind"] == "train" else "Arrived") and arrived["kind"] == ["success"]


def test_the_distance_is_the_big_number_with_its_label_and_the_walk_time(page):
    for name in ("onway", "checking", "away", "still", "arrived"):
        state = page["states"][name]
        assert state["valueSize"] >= 32 and state["valueWeight"] == "800", name  # emphasised, as in the design
        assert state["labelSize"] == 18 and state["minutesIcon"] is True and "min walk" in state["minutes"], name
        want = "to the station" if page["kind"] == "train" else "to go"
        assert state["label"].strip() == want and state["distance"].replace(" ", " ").endswith(want), name
        assert state["progressHeight"] >= 12 - 0.5, name
    assert page["states"]["waiting"]["value"] == "—" and page["states"]["waiting"]["distance"] == "—"
    assert page["states"]["arrived"]["progress"] == 100


def test_no_layout_shift_when_the_state_changes(page):
    boxes = {name: state["geom"] for name, state in page["states"].items()}
    keys = ("back", "title", "ring", "chance", "status", "map", "sensors")
    for key in keys:
        tops = {(box[key]["top"], box[key]["height"]) for box in boxes.values()}
        assert len(tops) == 1, (key, tops)  # every part keeps its place and its size across all six states


def test_opening_sensor_details_moves_nothing_above_it_and_uses_the_shared_alert(page):
    before, after = page["sensorShift"]["before"], page["sensorShift"]["after"]
    for key in ("back", "title", "ring", "chance", "status", "map"):
        assert before[key]["top"] == after[key]["top"] and before[key]["height"] == after[key]["height"], key
    assert after["sensors"]["top"] == before["sensors"]["top"] and after["sensors"]["height"] > before["sensors"]["height"]
    sensors = page["sensors"]
    assert sensors["open"] is True and sensors["expanded"] == "true" and sensors["toggleHeight"] >= 56
    assert sensors["toggleSize"] == 17 and sensors["toggleWeight"] == "800"
    assert sensors["whyIsAlert"] is True and sensors["whyShown"] is True and sensors["whyIcon"] is True
    assert len(sensors["rows"]) == 6 and sensors["scrollWidth"] <= sensors["innerWidth"]


def test_the_chance_card_has_the_ring_the_vehicle_marker_the_badge_and_the_time(page):
    vehicle = page["vehicle"]
    assert vehicle["ringSize"] == 120 and vehicle["timeBelowLabel"] is True and vehicle["timeSize"] >= 32
    assert vehicle["nodeSvg"] is True and vehicle["ringText"].endswith("%")
    if page["kind"] == "bus":
        assert vehicle["badge"] == "Bus 18" or vehicle["badge"].endswith("18")  # the service number
        assert "line-badge--bus" in vehicle["badgeClass"] and "journey-step--rail" not in vehicle["cls"]  # the grey ring
        assert _rgb(re.search(r"rgb\([^)]*\)", vehicle["ringShadow"]).group(0)) == _rgb(vehicle["neutral"])
        assert vehicle["pill"].lower() == "live" and vehicle["title"].startswith("Chance to catch Bus")
    else:
        assert vehicle["badge"] == "NS" and "line-badge--ns" in vehicle["badgeClass"] and "journey-step--rail-ns" in vehicle["cls"]
        assert _rgb(re.search(r"rgb\([^)]*\)", vehicle["ringShadow"]).group(0)) == _rgb(vehicle["ns"])  # the line's colour ring
        assert "chance to catch the" in vehicle["title"].lower() and "train" in vehicle["title"].lower()
        assert "schedule" in vehicle["pill"].lower()


def test_arrived_shows_97_percent_on_a_bus_with_the_trend_icon_and_words(page):
    arrived = page["arrived"]
    assert arrived["state"].startswith("Arrived") and arrived["progress"] == 100
    if page["kind"] == "bus":
        assert arrived["ring"] == "97%"
        assert arrived["trendShown"] is True and arrived["trendIcon"] is True and arrived["trendText"].startswith("Rising")


def test_the_map_is_300px_and_nothing_scrolls_sideways(page):
    for name, state in page["states"].items():
        geom = state["geom"]
        assert abs(geom["map"]["height"] - 300) <= 1, name
        assert geom["scrollWidth"] <= geom["innerWidth"], name
    far = page["far"]
    assert far["valueRight"] <= far["bandRight"] + 0.5 and far["scrollWidth"] <= far["innerWidth"]  # "12.5 km" fits at 320 px too


def test_text_icons_and_the_state_alert_pass_contrast_in_this_theme(page):
    for name, state in page["states"].items():
        assert _contrast(state["valueColor"], state["band"]) >= 4.5, name  # the big number on its band
        assert _contrast(state["bandIcon"], state["band"]) >= 3.0, name  # the walking icon
        assert _contrast(state["alertColor"], state["alertBg"]) >= 4.5, name  # the state words on the alert
    arrived = page["arrived"]
    if page["kind"] == "bus":
        assert arrived["trendShown"] is True and "is-rising" in arrived["trendClass"]

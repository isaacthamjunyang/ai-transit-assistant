"""The two map markers: the red pin (current location) and the green flag (destination).

Static checks of the page, copy.js, the css, the style guide and the plan, then the real page in headless Edge at 360 and
1280 px, light and dark (no live API: the app runs against stubs). Every marker is checked on the maps that show it: the
destination stops page, the live map (Pages A and B share it), Page W and the journey overview's route preview."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")

PIN_PATH = "M12 21s6-5.2 6-10a6 6 0 1 0-12 0c0 4.8 6 10 6 10z"
FLAG_PATH = "M6 21V4M6 4h11l-2 4 2 4H6"


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    return text.split(start, 1)[1].split(end, 1)[0]


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.strip()
    if value.startswith("#"):
        value = value.lstrip("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    numbers = re.findall(r"[\d.]+", value)[:3]
    return tuple(round(float(n)) for n in numbers)  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(_rgb(a)), _luminance(_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---- static ---------------------------------------------------------------------------------------------------------


def test_the_icons_are_the_journey_overviews_pin_and_flag():
    overview_pin = _between(INDEX, "var PIN_SVG = ", "\n")
    overview_flag = _between(INDEX, "var FLAG_SVG = ", "\n")
    assert PIN_PATH in overview_pin and FLAG_PATH in overview_flag
    map_pin = _between(INDEX, "var MAP_PIN_HTML = ", "\n")
    map_flag = _between(INDEX, "var MAP_FLAG_HTML = ", "\n")
    assert PIN_PATH in map_pin and 'viewBox=\\"0 0 24 24\\"' in map_pin and "map-pin__hole" in map_pin
    assert map_flag.count(FLAG_PATH) == 2 and "map-flag__casing" in map_flag and "map-flag__body" in map_flag


def test_the_anchors_put_the_pin_tip_and_the_flag_base_on_the_coordinate():
    # a 48 px icon over a 24-unit view box: the pin's tip (12, 21) is at (24, 42) and the flag's pole base (6, 21) at (12, 42)
    assert "var MARKER_ICON_PX = 48;" in INDEX
    assert "var PIN_TIP_ANCHOR = [24, 42];" in INDEX and "var FLAG_BASE_ANCHOR = [12, 42];" in INDEX
    assert 48 * 12 / 24 == 24 and 48 * 21 / 24 == 42 and 48 * 6 / 24 == 12
    icon = _between(INDEX, "function userIcon() {", "// The flag's icon.")
    assert "iconAnchor: PIN_TIP_ANCHOR" in icon and "iconSize: [MARKER_ICON_PX, MARKER_ICON_PX]" in icon
    flag = _between(INDEX, "function flagIcon(", "// A text name for a marker's icon element")
    assert "FLAG_BASE_ANCHOR[1] + (lifted ? FLAG_LIFT_RISE : 0)" in flag
    # the lift is one pin height: the pin's head top (y 5 of 24) is 16 units, 32 px, above its tip (y 21)
    assert "var FLAG_LIFT_RISE = 32;" in INDEX and (21 - 5) * 48 / 24 == 32


def test_every_destination_marker_is_the_flag_and_none_is_the_old_pin():
    for text in (INDEX, CSS, GUIDE):
        assert "dest-pin" not in text
    assert "var(--map-destination)" not in CSS  # the red token is no longer drawn
    shown = _between(INDEX, "function showDestinationPin()", "function fitDestinationView()")
    assert 'flagIcon("dest-flag"' in shown and "flagMarkers.dest = flag" in shown
    live = _between(INDEX, "function syncLiveDestination()", "function routeLinePoints()")
    assert 'flagIcon("map-dest-live", labelHtml, lifted)' in live and "flagMarkers.live = liveDestMarker" in live
    route = _between(INDEX, "function routeDestinationFlag(latlng)", "// A leg's points")
    assert 'flagIcon("dest-flag route-flag"' in route and "flagMarkers.route = flag" in route
    assert 'routePin(place, "DESTINATION")' not in INDEX and "routeDestinationFlag(place);" in INDEX


def test_board_change_and_exit_pins_are_unchanged():
    preview = _between(INDEX, "function highlightJourneyRoute(option, legs)", "function walkPhrase(metres)")
    for pin in ('routePin(points[0], "BOARD")', 'routePin(points[points.length - 1], "CHANGE")',
                'routePin(points[points.length - 1], "EXIT")'):
        assert pin in preview
    assert 'className: "route-pin route-pin-" + label.toLowerCase()' in INDEX
    assert "iconSize: [92, 24]" in INDEX and "iconAnchor: [46, 12]" in INDEX


def test_the_user_marker_keeps_the_you_label_and_has_no_blue_circle():
    icon = _between(INDEX, "function userIcon() {", "// The flag's icon.")
    assert 'MAP_PIN_HTML + "<span class=\\"marker__label\\">" + MAP_COPY.you + "</span>"' in icon
    walk = _between(INDEX, "function walkYouIcon() {", "function walkStopIcon()")
    assert "MAP_PIN_HTML" in walk and "MAP_COPY.you" in walk and "walk-wedge" in walk
    rule = _between(CSS, ".leaflet-div-icon.marker.marker--user {\n  display: block;", "}")
    assert "background: transparent;" in rule and "border: 0;" in rule and "border-radius: 0;" in rule
    assert "var(--color-primary)" not in rule
    # the sample walk map's old blue circle is gone
    assert "var(--color-primary)" not in _between(CSS, ".sample-walk-map__you {", "}")


def test_the_markers_read_their_colours_from_tokens_only():
    block = _between(CSS, "/* The map markers: the red pin", ".marker__label {")
    assert "fill: var(--marker-start);" in block and "fill: var(--marker-end);" in block
    assert "stroke: var(--marker-end);" in block and "stroke: var(--map-marker-ring);" in block
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block) is None
    marker_js = _between(INDEX, "var MAP_COPY = ", "function userIcon() {")
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", marker_js) is None and "style=" not in marker_js
    assert THEME.count("--marker-start:") == 4 and THEME.count("--marker-end:") == 4


def test_the_words_come_from_copy_js_and_the_page_mirrors_them():
    block = _between(COPY, "  map: {", "  },")
    for key, value in (("you", "You"), ("yourLocation", "Your location"), ("destination", "Destination")):
        assert f'{key}: "{value}"' in block
    assert 'var MAP_COPY = { you: "You", yourLocation: "Your location", destination: "Destination" };' in INDEX
    assert "labelMarker(userMarker, MAP_COPY.yourLocation, true)" in INDEX
    assert "labelMarker(walkYou, MAP_COPY.yourLocation, false)" in INDEX
    assert INDEX.count("labelMarker(") >= 7


def test_the_style_guide_shows_each_marker_and_the_overlap_case():
    assert "MAP_PIN_SVG" in GUIDE and "MAP_FLAG_SVG" in GUIDE
    assert PIN_PATH in GUIDE and FLAG_PATH in GUIDE
    assert 'class=\\"sample-markers\\"' in GUIDE and "sample-markers__item--stack" in GUIDE
    assert "within a few metres the flag stands above the pin" in GUIDE
    assert "copy.map.you" in GUIDE and "copy.map.yourLocation" in GUIDE and "copy.map.destination" in GUIDE
    assert 'marker("You"' not in GUIDE and "iconAnchor: [24, 42]" in GUIDE


def test_the_plan_describes_the_markers():
    text = PLAN
    assert "red pin" in text and "green flag" in text
    para = _between(text, "**Map markers.**", "\n")
    for needle in ("--marker-start", "--marker-end", "pin's tip", "pole base", "`You`", "Your location", "Destination",
                   "above the pin", "BOARD", "3:1"):
        assert needle in para, needle


# ---- the real page ----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)],
                ids=["360-light", "1280-dark"])
def report(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), eta_minutes=[10.3]) as base:
        return run_scenario("mapmarkers", base, {"name": name, "width": width, "height": height, "dark": dark})["result"]


def _tip(point: dict) -> tuple[float, float]:
    return point["left"] + point["anchor"][0], point["top"] + point["anchor"][1]


def test_pin_tip_sits_on_the_users_coordinate_and_has_the_start_token(report):
    pin = report["stopsPin"]
    assert pin["point"]["anchor"] == [24, 42] and pin["point"]["size"] == [48, 48]
    x, y = _tip(pin["point"])
    assert abs(x - pin["point"]["x"]) <= 0.6 and abs(y - pin["point"]["y"]) <= 0.6
    assert _rgb(pin["fill"]) == _rgb(report["tokens"]["start"])
    assert _rgb(pin["stroke"]) == _rgb(report["tokens"]["ring"])  # the light casing
    assert pin["text"] == "You" and pin["labelVisibility"] == "visible"
    assert pin["labelLeft"] > pin["point"]["left"] + 24  # beside the pin, to its right
    assert pin["point"]["width"] >= 44 and pin["point"]["height"] >= 44  # the tap target


def test_flag_base_sits_on_the_destination_and_has_the_end_token(report):
    flag = report["stopsFlag"]
    assert flag["point"]["anchor"] == [12, 42] and flag["point"]["size"] == [48, 48]
    x, y = _tip(flag["point"])
    assert abs(x - flag["point"]["x"]) <= 0.6 and abs(y - flag["point"]["y"]) <= 0.6
    assert _rgb(flag["fill"]) == _rgb(report["tokens"]["end"])
    assert _rgb(flag["stroke"]) == _rgb(report["tokens"]["end"])
    assert _rgb(flag["casingStroke"]) == _rgb(report["tokens"]["ring"])
    assert flag["lifted"] is False and flag["display"] != "none"


def test_each_marker_has_a_text_label_and_the_pin_keeps_its_popup_and_focus(report):
    assert report["stopsAria"]["pin"] == "Your location" and report["stopsAria"]["popup"] == "Your location"
    assert report["stopsAria"]["tabindex"] == 0
    assert report["stopsFlag"]["ariaLabel"] == "Destination" and report["stopsFlag"]["role"] == "img"
    assert report["liveFlag"]["ariaLabel"] == "Destination" and report["liveFlag"]["role"] == "img"
    assert report["livePin"]["ariaLabel"] == "Your location"
    assert report["walk"]["ariaLabel"] == "Your location" and report["walk"]["role"] == "img"
    assert report["walk"]["text"] == "You"


def test_no_blue_circle_and_no_old_pin_is_left_on_any_map(report):
    for marker in report["stopsUserMarkers"]:
        assert marker["background"] in ("rgba(0, 0, 0, 0)", "transparent")
        assert marker["border"] == "0px" and marker["radius"] == "0px"
    assert report["liveBlue"] is False
    assert report["stopsOldPins"] == 0 and report["liveOldPins"] == 0
    assert "dest-pin" not in report["liveFlag"]["html"] and "map-flag__svg" in report["liveFlag"]["html"]


def test_the_colours_are_3_to_1_on_the_map_land_in_this_theme(report):
    tokens = report["tokens"]
    assert _contrast(tokens["start"], tokens["land"]) >= 3.0
    assert _contrast(tokens["end"], tokens["land"]) >= 3.0
    assert _contrast(tokens["ring"], tokens["land"]) >= 1.0 and _rgb(tokens["ring"]) == (255, 255, 255)


def test_the_live_map_flag_and_pin_use_the_same_anchors(report):
    flag, pin = report["liveFlag"], report["livePin"]
    assert flag["point"]["anchor"] == [12, 42] and pin["point"]["anchor"] == [24, 42]
    x, y = _tip(flag["point"])
    assert abs(x - flag["point"]["x"]) <= 0.6 and abs(y - flag["point"]["y"]) <= 0.6
    assert report["liveLabel"] == "Destination"
    assert _rgb(flag["fill"]) == _rgb(report["tokens"]["end"]) and _rgb(pin["fill"]) == _rgb(report["tokens"]["start"])


def test_a_flag_within_a_few_metres_stands_above_the_pin_and_both_stay_visible(report):
    over = report["overlap"]
    assert over["lifted"] is True and over["anchor"] == [12, 74]  # 42 + one pin height (32)
    assert over["flagVisible"] and over["pinVisible"]
    assert over["flagBottom"] <= over["pinTop"] + 3.5  # the pole base is on the pin's top (the casing is 3 px)
    assert over["pinLeft"] < over["flagRight"] and over["flagLeft"] < over["pinRight"]  # one above the other
    assert report["apart"] == {"lifted": False, "anchor": [12, 42]}
    live = report["liveOverlap"]
    assert live["lifted"] is True and live["anchor"] == [12, 74] and live["label"] == "Destination"


def test_page_w_shows_the_pin_with_its_wedge_from_the_tip_and_no_flag(report):
    walk = report["walk"]
    assert walk["point"]["anchor"] == [24, 42]
    x, y = _tip(walk["point"])
    assert abs(x - walk["point"]["x"]) <= 0.6 and abs(y - walk["point"]["y"]) <= 0.6
    assert _rgb(walk["fill"]) == _rgb(report["tokens"]["start"])
    assert walk["wedgeTop"] is not None and walk["accuracy"] == 1 and walk["flags"] == 0


# ---- the journey overview's route preview ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def route(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("routeflag"), onemap=stub.by_mode({"TRANSIT": stub.mixed})) as base:
        return run_scenario("routemap", base, {"name": "routeflag", "width": 390})["result"]


def test_the_route_preview_ends_in_the_flag_and_keeps_board_change_exit(route):
    assert route["pins"] == ["BOARD", "CHANGE", "CHANGE", "CHANGE", "EXIT", "FLAG Destination"]
    flag = route["flag"]
    assert flag["anchor"] == [12, 42] and flag["size"] == [48, 48] and flag["cls"] == "dest-flag route-flag"
    assert _rgb(flag["fill"]) == _rgb(route["tokens"]["end"])

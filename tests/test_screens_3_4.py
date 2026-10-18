"""Screens 3 and 4: destination stops map and list, then confirm and arrive-by. Static checks only."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
COPY = ROOT / "static" / "copy.js"
THEME = ROOT / "static" / "theme.css"
CSS = ROOT / "static" / "components.css"

STRINGS = (
    "Nearby stops and stations",
    "Stops and stations within 600 m, nearest first. If none, the nearest within 1.5 km.",
    "Best option",
    "Centre map on your location",
    "About these stops",
    "Selected destination",
    "Destination stop",
    "Edit destination",
    "Edit destination stop",
    "We'll find your best route and leave-by time.",
    "Confirm",
)


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_new_strings_live_in_copy_and_page():
    html = _page()
    copy = COPY.read_text(encoding="utf-8")
    for text in STRINGS:
        assert text in copy
        assert text in html
    assert "score" not in copy.split("destinationStops:", 1)[1].split("},", 1)[0].lower()


def test_best_option_only_marks_the_shortest_reachable_walk():
    html = _page()
    best = html.split("function bestDestinationStopCode(stops)", 1)[1].split("function renderDestinationStops", 1)[0]
    assert "stop.is_reachable" in best
    assert "distance_m" in best
    render = html.split("function renderDestinationStops(body)", 1)[1].split("function loadDestinationStops", 1)[0]
    assert "bestDestinationStopCode(body.reachable_stops)" in render  # the old two-list answer
    assert "all[0] ? all[0].stop_code" in render  # one list, nearest first: the first row is the best option
    assert "renderDestinationStopCard(stop, reachableStopList, stop.stop_code === bestCode)" in render


def test_no_row_is_chosen_at_first_and_marker_taps_do_not_navigate():
    html = _page()
    render = html.split("function renderDestinationStops(body)", 1)[1].split("function loadDestinationStops", 1)[0]
    assert "selectDestinationStop(all[0])" not in render and "selectDestinationStop(" not in render  # no default choice
    assert "chooseDestinationStop" not in render and "openDestinationConfirm" not in render  # no pan, no navigation
    marker = html.split("function addDestinationMarker(stop)", 1)[1].split("function addDestinationWalkLine", 1)[0]
    assert "openDestinationConfirm" not in marker
    assert "pushScreen" not in marker
    assert "bindPopup" not in marker


def test_screen_four_reuses_the_single_arrive_by_component():
    html = _page()
    assert html.count('id="arrive-by-field"') == 1
    assert html.count('id="arrive-by"') == 1
    assert 'id="confirm-arrive-slot"' in html
    place = html.split("function placeArriveBy(inConfirm)", 1)[1].split("function backToScreen", 1)[0]
    assert "appendChild(arriveWrapElement)" in place
    edits = html.split('getElementById("edit-destination")', 1)[1].split('getElementById("dest-stops-info")', 1)[0]
    assert 'addEventListener("click", editDestination)' in edits
    assert 'backToScreen("stops")' in edits


def test_map_tokens_have_light_and_dark_values():
    theme = THEME.read_text(encoding="utf-8")
    for token in ("--map-destination", "--map-marker-ring", "--map-walk-line", "--map-selected-ring"):
        assert theme.count(token + ":") == 4
    css = CSS.read_text(encoding="utf-8")
    assert "fill: var(--marker-end)" in css  # the destination is the green flag, not the red pin
    assert ".dest-map .leaflet-control-zoom" in css
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", css.split("/* Screen 3:", 1)[1]) is None


def _rule(css: str, selector: str) -> str:
    return css.split(selector + " {", 1)[1].split("}", 1)[0]


def test_old_info_string_is_gone():
    old = "Bus stops within 600 m of your destination, nearest first."
    assert old not in _page()
    assert old not in COPY.read_text(encoding="utf-8")


def test_range_chip_and_attribution_have_no_text_shadow_or_ruler():
    css = CSS.read_text(encoding="utf-8")
    html = _page()
    line = _rule(css, ".map-range .leaflet-control-scale-line,\n.map-range-chip .map-range-chip__text")
    assert "text-shadow: none" in line
    assert "border: 0" in line
    assert "color: var(--map-range-text)" in line
    assert "font-weight: 700" in line
    chip = _rule(css, ".dest-map .leaflet-top.leaflet-left .leaflet-control-scale.map-range,\n.map-range-chip")
    assert "background: var(--color-card)" in chip
    assert "border: 1px solid var(--color-line)" in chip
    assert "filter: none" in chip
    assert "transform: none" in chip
    assert "border: 2px solid var(--color-ink)" not in css
    control = html.split("var RangeControl = L.Control.Scale.extend({", 1)[1].split("});", 1)[0]
    assert "this._getRoundNum(maxMeters)" in control
    assert "_updateScale" not in control
    assert '"Range: {distance}"' in html
    attribution = _rule(css, ".leaflet-container .leaflet-control-attribution,\n.map-attribution-chip")
    assert "text-shadow: none" in attribution
    assert "background: var(--color-card)" in attribution
    assert "openstreetmap.org/copyright" in html


def test_stop_markers_share_one_circle_class_with_a_ring_stack():
    html = _page()
    css = CSS.read_text(encoding="utf-8")
    icon = html.split("function mapStopIcon(", 1)[1].split("function stopIcon", 1)[0]
    assert '"map-stop "' in icon and "is-selected" in icon
    assert "map-stop-label" in icon
    assert "selected ? [40, 40] : [32, 32]" in icon
    dest = html.split("function destStopIcon(stop, selected)", 1)[1].split("function destMarkerOffset", 1)[0]
    assert '"map-stop map-stop--dest "' in dest and "map-stop__dot" in dest and "map-stop-label" in dest
    assert "selected ? [40, 40] : [32, 32]" in dest
    assert 'mapStopIcon(boardingNamesByCode[code] || "", selected, "map-stop--boarding")' in html
    assert "setZIndexOffset(selected ? 1000 : 0)" in html
    dot = _rule(css, ".map-stop__dot")
    assert "border-radius: var(--radius-pill)" in dot
    assert "border: 2px solid var(--map-marker-ring)" in dot
    ring = _rule(css, ".map-stop.is-selected .map-stop__dot")
    stack = "0 0 0 var(--map-selected-width) var(--map-selected-ring),\n    0 0 0 calc(var(--map-selected-width) + var(--map-selected-halo-width)) var(--map-selected-halo)"
    assert stack in ring
    assert "width: 40px" in ring
    label = _rule(css, ".map-stop.is-selected .map-stop__label,\n.map-stop-label.is-selected")
    assert stack in label
    assert "scale(" not in css.split("/* Screen 3:", 1)[1].split("/* Pulse every 2 seconds:", 1)[0]  # the markers never scale (the button pulse is after)
    assert ".leaflet-marker-icon.map-stop" not in css.replace(".leaflet-div-icon.map-stop", "")


def test_change_time_opens_the_arrive_by_panel_in_a_visible_sheet():
    html = _page()
    assert 'getElementById("journey-change-time").addEventListener("click", openArriveSheet)' in html
    sheet = html.split("function openArriveSheet(event)", 1)[1].split("function closeArriveSheet", 1)[0]
    assert "event.stopPropagation()" in sheet
    assert 'getElementById("arrive-sheet-slot").appendChild(arriveWrapElement)' in sheet
    assert "openArrivePanel()" in sheet
    markup = html.split('id="arrive-sheet"', 1)[1].split("</main>", 1)[0]
    assert 'id="arrive-sheet-slot"' in markup
    assert "</form>" not in markup

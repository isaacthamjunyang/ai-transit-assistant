"""Page B's train card (plan 4.8): the badge and the line name on one row, the pill and the direction under the name, the
refresh button at the top right, and "Next trains" tiles that show the time only.

The browser tests drive the real page in headless Edge against the real app, a stubbed OneMap and a rail table. A long
name ("Thomson-East Coast Line") and a short one ("Circle Line") are put into the same markup to check the layout at 320,
360 and 1280 px, light and dark."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
NB = chr(0xA0)
LONG = "Thomson-East Coast Line"
SHORT = "Circle Line"


def test_the_tile_has_no_line_name_and_the_aria_label_string_is_in_copy_js_and_the_page():
    render = INDEX.split("function renderNextTrains(list) {", 1)[1].split("function renderNextBuses", 1)[0]
    assert "bus-tile-card__service" not in render and "trainLineName()" in render and "setAttribute(\"aria-label\"" in render
    assert 'tileLabel: "{line} train, {time}",' in COPY and 'tileLabel: "{line} train, {time}",' in INDEX


def test_the_tile_css_keeps_the_outline_and_the_minimum_height_and_the_header_uses_tokens_only():
    assert ".bus-tile-card.is-selected {\n  box-shadow: 0 0 0 2px var(--color-selected-outline);" in CSS
    tile = CSS.split(".bus-tile-card {", 1)[1].split("}", 1)[0]
    assert "min-height: var(--tap-min);" in tile
    header = CSS.split(".bus-card__title--train {", 1)[1].split(".bus-tile-card", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", header) and "style=" not in header
    assert ".bus-card__title .line-badge {" not in CSS  # the old margin rule is replaced by the row's gap


def test_the_plan_and_the_style_guide_describe_the_header_and_the_time_only_tiles():
    assert "with no line name on the tile" in PLAN and "North-South Line train, 8:16 PM" in PLAN
    assert "never under the badge" in PLAN
    sample = GUIDE.split("function trainPagesSample()", 1)[1].split("function legsSample()", 1)[0]
    assert "bus-card__title--train" in sample and "Thomson-East Coast Line" in sample and "Circle Line" in sample
    assert "bus-tile-card__service" not in sample and "aria-label" in sample


@pytest.fixture(scope="module", params=[
    ("l320", 320, 700, False), ("d320", 320, 700, True), ("l360", 360, 800, False), ("d360", 360, 800, True),
    ("l1280", 1280, 900, False), ("d1280", 1280, 900, True)],
    ids=["320-light", "320-dark", "360-light", "360-dark", "1280-light", "1280-dark"])
def run(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp("hdr" + name), onemap=stub.by_mode({"TRANSIT": stub.train_first}),
                     rail_table=_table(), lta_status=500) as base:
        return run_scenario("trainheader", base, {"name": name, "width": width, "height": height, "dark": dark,
                                                  "names": [LONG, SHORT]}, timeout=300)["result"]


def _all(run):
    return [("North-South Line", run["real"]), (LONG, run["sizes"][LONG]), (SHORT, run["sizes"][SHORT])]


def test_the_badge_and_the_name_share_a_row_and_a_wrapped_name_stays_under_the_name(run):
    for label, m in _all(run):
        badge, name = m["badge"], m["name"]
        assert name["left"] >= badge["right"] - 0.5, label  # the name is beside the badge, never under it
        first_line_top = min(r for r in [name["top"]])
        # one line: the badge and the name text centre on each other; wrapped: the badge centres on the first line
        centre_badge = (badge["top"] + badge["bottom"]) / 2
        centre_first = first_line_top + m["lineHeight"] / 2
        assert abs(centre_badge - centre_first) <= 3, (label, centre_badge, centre_first)
        assert m["scrollWidth"] <= m["innerWidth"], label
    if run["real"]["innerWidth"] >= 360:
        assert run["sizes"][SHORT]["nameLines"] == 1  # a short name stays on one line from 360 px up
    # a long name may wrap at a phone width; the alignment checks above hold either way, and no word is cut mid-word
    # when it has a space or a hyphen to break at (the longest piece, "Thomson-", fits the column)
    assert run["sizes"][LONG]["nameLines"] <= 4


def test_the_pill_and_the_direction_sit_under_the_name_left_aligned(run):
    for label, m in _all(run):
        line, pill, to = m["line"], m["pill"], m["to"]
        assert pill["top"] >= line["bottom"] - 1 and to["top"] >= pill["bottom"] - 1, label
        assert abs(pill["left"] - line["left"]) <= 1 and abs(to["left"] - line["left"]) <= 1, label
        assert to["left"] >= m["hero"]["right"] - 0.5, label  # the text column is beside the train icon tile


def test_the_refresh_button_is_at_the_top_right(run):
    for label, m in _all(run):
        refresh, card = m["refresh"], m["card"]
        assert refresh["right"] <= card["right"] and card["right"] - refresh["right"] <= 24, label
        assert refresh["top"] - card["top"] <= 24, label
        assert refresh["left"] >= m["to"]["left"] or refresh["left"] >= m["line"]["left"], label


def test_the_tiles_show_the_time_only_with_the_outline_44px_equal_widths_and_an_aria_label(run):
    tiles = run["real"]["tiles"]
    assert len(tiles) == 3
    for tile in tiles:
        assert re.fullmatch(r"\d{1,2}:\d{2}" + NB + "[AP]M( [(]tomorrow[)])?", tile["text"]), tile["text"]  # no name, no-break space
        assert tile["kids"] == 1 and tile["height"] >= 44
        assert re.fullmatch(r"North-South Line train, \d{1,2}:\d{2}" + NB + "[AP]M( [(]tomorrow[)])?", tile["aria"]), tile["aria"]
    assert max(t["width"] for t in tiles) - min(t["width"] for t in tiles) <= 0.5
    assert tiles[0]["selected"] and "0px 0px 0px 2px" in tiles[0]["shadow"].replace("  ", " ")
    assert not tiles[1]["selected"] and tiles[1]["shadow"] == "none"

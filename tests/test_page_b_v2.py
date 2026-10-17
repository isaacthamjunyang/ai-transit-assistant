"""The approved Page B design (tmp/design/pageb-v2.html), for a bus and a train: the title row with its own back button, the
vehicle card (a ringed logo, the badge, the pill, the refresh button), one row per arrival (the crowding label, the Arriving
chip), the map, the question bar, and the live, no-data and stale states. 360 px and 1280 px, light and dark. No live API."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
RULES = (ROOT / ".cursor" / "rules" / "mockup-fidelity.mdc").read_text(encoding="utf-8")
NB = chr(0xA0)
LIVE_LOADS = ["SEA", "SDA", "LSD"]
NODATA_LOADS = ["", "SEA", "LSD"]


# ---- the markup, the styles and the wording ------------------------------------------------------------------------------


def _page_b_markup():
    return INDEX.split('<section class="live-page" id="live-tracking"', 1)[1].split('<section class="card" id="journey-panel"', 1)[0]


def test_the_markup_is_the_title_row_the_vehicle_card_the_rows_the_map_and_nothing_else():
    page = _page_b_markup()
    order = ['id="live-back"', 'id="live-bus-to"', 'id="live-vehicle"', 'id="live-node"', 'id="live-bus-title"', 'id="live-bus-pill"',
             'id="live-refresh"', 'id="next-buses-label"', 'id="next-buses"', 'id="next-buses-empty"', 'id="live-map-slot"', 'id="live-full-route"']
    positions = [page.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert '<h2 id="live-bus-to" class="live-title">' in page and 'class="card bus-card live-vehicle"' in page
    assert "min walk" not in page and "pace" not in page and "walk-open" not in page  # no walk line, no pace content
    assert "style=" not in page
    assert 'document.getElementById("live-back").addEventListener("click"' in INDEX and "requestBack();" in INDEX.split('getElementById("live-back")', 1)[1][:400]


def test_the_page_has_its_own_back_button_so_the_back_row_is_hidden_on_it():
    assert "body.is-page-b .back-bar {\n  display: none;\n}" in CSS.replace("\r\n", "\n")


def test_the_new_styles_use_tokens_only_and_the_rows_keep_their_size_when_selected():
    block = CSS.replace("\r\n", "\n").split("/* The approved Page B design (tmp/design/pageb-v2.html)", 1)[1]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", block) and "style=" not in block
    row = CSS.replace("\r\n", "\n").split(".bus-tile-card {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--color-line);" in row and "box-sizing: border-box;" in row
    selected = CSS.replace("\r\n", "\n").split(".bus-tile-card.is-selected {", 1)[1].split("}", 1)[0]
    assert "box-shadow: 0 0 0 2px var(--color-selected-outline);" in selected and "background: var(--color-secondary);" in selected
    assert "border" not in selected  # the outline is a shadow, so the size does not change
    chip = CSS.replace("\r\n", "\n").split(".bus-tile-card__arriving {", 1)[1].split("}", 1)[0]
    assert "background: var(--tint-success);" in chip and "color: var(--status-live);" in chip


def test_the_arriving_chip_has_a_tick_and_the_word_and_no_brackets():
    assert 'arriving: "Arriving"' in COPY and "(Arriving)" not in COPY and "(Arriving)" not in INDEX
    render = INDEX.split("function renderNextBuses(buses, hero) {", 1)[1].split("// Reserved rectangles", 1)[0]
    assert "ARRIVING_CHECK_SVG" in render and 'textContent = "Arriving"' in render


def test_the_plan_the_rules_and_the_style_guide_describe_the_approved_design():
    assert "**Page B (the approved design supersedes the mockup for Page B).**" in PLAN and "tmp/design/pageb-v2.html" in PLAN
    assert "tmp/design/pageb-v2.html" in RULES and "Six screens" in RULES
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes() and b"\n" not in (ROOT / "PROJECT_PLAN.md").read_bytes().replace(b"\r\n", b"")
    for marker in ("function sgLiveTop(", "bus-tile-card__side", "bus-tile-card__arriving", "bus-card live-vehicle", "live-title", "live-back"):
        assert marker in GUIDE, marker
    assert "live-card" not in GUIDE and "bus-tile--hero" not in GUIDE.split("function sgBusCard(", 1)[1].split("function sgTiles(", 1)[0]


# ---- the page in a browser ----------------------------------------------------------------------------------------------


COMBOS = [("l360", 360, 800, False), ("d360", 360, 800, True), ("l1280", 1280, 900, False), ("d1280", 1280, 900, True)]


@pytest.fixture(scope="module", params=COMBOS, ids=["360-light", "360-dark", "1280-light", "1280-dark"])
def runs(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    config = {"name": name, "width": width, "height": height, "dark": dark}
    out = {"width": width, "dark": dark}
    with running_app(tmp_path_factory.mktemp("pbv2live" + name), eta_minutes=[10.3, 16.3, 24.3], loads=LIVE_LOADS) as base:
        out["bus"] = run_scenario("pagebv2", base, config, timeout=300)["result"]
    with running_app(tmp_path_factory.mktemp("pbv2nodata" + name), eta_minutes=[10.3, 16.3, 24.3], loads=NODATA_LOADS) as base:
        out["nodata"] = run_scenario("pagebv2", base, config, timeout=300)["result"]
    with running_app(tmp_path_factory.mktemp("pbv2train" + name), onemap=stub.by_mode({"TRANSIT": stub.train_first}),
                     rail_table=_table(), lta_status=500) as base:
        out["train"] = run_scenario("pagebv2", base, config, timeout=300)["result"]
    return out


def _states(runs):
    return [(f"{kind}/{state}", kind, state, runs[kind][state]) for kind in ("bus", "nodata", "train") for state in ("live", "stale", "again")]


def test_every_state_fits_the_page_and_has_the_title_row_the_vehicle_card_and_three_rows(runs):
    for label, kind, state, s in _states(runs):
        assert s["top"] == "arrivals" and s["pageB"] is True, label
        assert s["scrollWidth"] <= s["innerWidth"], label  # nothing scrolls sideways
        assert s["titleTag"] == "H2" and s["title"].startswith("To "), label
        assert s["back"]["width"] >= 44 and s["back"]["height"] >= 44 and s["backBar"] == "none", label
        assert s["back"]["right"] <= s["titleRect"]["left"] + 0.5, label  # the back button is beside the title
        assert s["titleRect"]["bottom"] <= s["vehicle"]["top"] + 0.5, label
        assert s["vehicleIsCard"] is True and s["refresh"]["width"] >= 44 and s["refresh"]["height"] >= 44, label
        assert s["refresh"]["right"] <= s["vehicle"]["right"] and s["refresh"]["left"] >= s["badgeRect"]["right"], label
        assert s["node"]["right"] <= s["badgeRect"]["left"] + 0.5 and s["pillRect"]["top"] >= s["badgeRect"]["bottom"] - 1, label
        assert len(s["rows"]) == 3 and s["label"] == ("Next 3 buses" if kind != "train" else "Next trains"), label
        assert s["walkLine"] is False and s["pace"] is False and "min walk" not in s["body"], label


def test_a_bus_shows_the_number_the_pill_the_crowding_labels_and_the_arriving_chip(runs):
    for state in ("live", "stale", "again"):
        s = runs["bus"][state]
        assert re.fullmatch(r"Bus \d+", s["badge"]), s["badge"]
        assert [row["crowd"]["text"] for row in s["rows"]] == ["Seats Available", "Standing Available", "Crowded"], state
        assert [row["crowd"]["code"] for row in s["rows"]] == LIVE_LOADS and all(row["crowd"]["icon"] for row in s["rows"])
        assert [bool(row["arriving"]) for row in s["rows"]] == [True, False, False], state
        assert s["rows"][0]["arriving"]["text"] == "Arriving" and s["rows"][0]["arriving"]["icon"] is True
        assert all(re.fullmatch(r"\d+ min", row["minutes"]) and re.fullmatch(r"Bus \d+", row["service"]) for row in s["rows"]), state
        assert [row["selected"] for row in s["rows"]] == [True, False, False], state
    assert runs["bus"]["live"]["pill"] in ("live", "schedule only") and "pill--stale" not in runs["bus"]["live"]["pillClass"]


def test_no_data_reads_no_data_with_its_icon_and_the_arriving_chip_stays(runs):
    for state in ("live", "stale", "again"):
        s = runs["nodata"][state]
        first = s["rows"][0]
        assert first["crowd"]["text"] == "No Data" and first["crowd"]["code"] == "UNKNOWN" and first["crowd"]["icon"] is True, state
        assert first["arriving"]["text"] == "Arriving" and first["selected"] is True, state
        assert [row["crowd"]["text"] for row in s["rows"][1:]] == ["Seats Available", "Crowded"], state


def test_a_train_shows_the_line_badge_a_line_colour_ring_and_time_only_rows_with_no_no_data_state(runs):
    for state in ("live", "stale", "again"):
        s = runs["train"][state]
        assert s["badge"] == "NS" and s["title"] == "To Marina South Pier", state
        assert "journey-step--rail-ns" in s["vehicleClass"] and s["pill"] in ("schedule only", "stale"), state
        for row in s["rows"]:
            assert re.fullmatch(r"\d{1,2}:\d{2} [AP]M( [(]tomorrow[)])?", row["text"]), row["text"]  # the page text folds the no-break space
            assert row["kids"] == 1 and row["crowd"] is None and row["arriving"] is None and row["side"] is False
        assert [row["selected"] for row in s["rows"]] == [True, False, False], state
        assert "No Data" not in s["body"], state
    bus = runs["bus"]["live"]
    assert "journey-step--rail" not in bus["vehicleClass"]  # a bus keeps the grey ring
    assert bus["ringShadow"] != runs["train"]["live"]["ringShadow"]  # the train's ring is the line colour


def test_the_stale_state_shows_the_shared_alert_and_the_stale_pill_and_only_then(runs):
    for kind in ("bus", "nodata", "train"):
        assert runs[kind]["live"]["stale"] is None and runs[kind]["again"]["stale"] is None, kind
        stale = runs[kind]["stale"]
        assert stale["stale"]["text"] == "LTA data is stale" and stale["stale"]["isAlert"] is True, kind
        assert "alert--error" in stale["stale"]["kind"], kind
        assert stale["pill"] == "stale" and "pill--stale" in stale["pillClass"], kind
        assert stale["refresh"]["width"] >= 44 and len(stale["rows"]) == 3 and stale["bar"] is not None, kind


def test_the_map_keeps_its_markers_and_the_question_bar_has_its_two_44px_answers(runs):
    for label, kind, state, s in _states(runs):
        assert 258 <= s["map"]["height"] <= 262, label
        markers = s["markers"]
        assert markers["stop"] and markers["range"] and markers["user"], label  # the red pin, the stop marker and the Range chip
        assert markers["full"] and markers["fullText"] == "Full route" and markers["fullRect"]["height"] >= 44, label
        assert markers["fullRect"]["right"] <= s["map"]["right"] + 0.5 and markers["fullRect"]["bottom"] <= s["map"]["bottom"] + 0.5, label
        bar = s["bar"]
        assert bar["title"] == ("Did you catch the train?" if kind == "train" else "Did you catch the bus?"), label
        assert bar["yes"]["text"] == "Yes, I caught it" and bar["no"]["text"] == "No, I missed it", label
        assert bar["yes"]["icon"] and bar["no"]["icon"], label  # an icon and a word, never colour alone
        for answer in (bar["yes"], bar["no"]):
            assert answer["rect"]["height"] >= 44 and answer["rect"]["width"] >= 44, label
        assert abs(bar["yes"]["rect"]["top"] - bar["no"]["rect"]["top"]) <= 1, label  # side by side
        assert abs(bar["rect"]["bottom"] - s["innerHeight"]) <= 1, label  # the sticky bar sits at the foot of the screen


def test_text_has_4_5_to_1_and_outlines_have_3_to_1_in_every_state(runs):
    for label, kind, state, s in _states(runs):
        assert s["pillRatio"] >= 4.5 and s["bar"]["yes"]["ratio"] >= 4.5 and s["bar"]["no"]["ratio"] >= 4.5, label
        assert s["ringRatio"] >= 3, (label, s["ringRatio"])  # the logo ring
        if s["stale"]:
            assert s["stale"]["ratio"] >= 4.5, label
        for row in s["rows"]:
            assert row["minutesRatio"] >= 4.5, (label, row["minutesRatio"])
            if row["service"]:
                assert row["serviceRatio"] >= 4.5, (label, row["serviceRatio"])
            if row["crowd"]:
                assert row["crowd"]["ratio"] >= 4.5, (label, row["crowd"])
            if row["arriving"]:
                assert row["arriving"]["ratio"] >= 4.5, (label, row["arriving"])
            if row["selected"]:
                assert row["outlineRatio"] >= 3 and row["outlineOnRow"] >= 3, (label, row["outlineRatio"], row["outlineOnRow"])


def test_the_selected_row_keeps_its_size_and_every_row_is_full_width_and_tall_enough(runs):
    for label, kind, state, s in _states(runs):
        rows = s["rows"]
        assert all(row["rect"]["height"] >= 75.5 for row in rows), label
        assert len({round(row["rect"]["width"], 1) for row in rows}) == 1 and len({round(row["rect"]["left"], 1) for row in rows}) == 1, label
        assert abs(rows[0]["rect"]["width"] - s["vehicle"]["width"]) <= 0.5, label
        assert all(row["border"] == "1px" for row in rows), label  # the outline is a shadow, not a thicker border
        assert rows[0]["bg"] != rows[1]["bg"] and rows[0]["shadow"] != "none" and rows[1]["shadow"] == "none", label


def test_a_state_change_moves_nothing_inside_the_page(runs):
    """No data against live: every row sits where it did. Stale against live: the alert strip above takes its own room, and
    from the title down nothing moves relative to the title."""
    for kind in ("bus", "train"):
        live, again = runs[kind]["live"], runs[kind]["again"]
        for a, b in zip(live["rows"], again["rows"]):
            assert abs(a["rect"]["top"] - b["rect"]["top"]) <= 0.5 and abs(a["rect"]["height"] - b["rect"]["height"]) <= 0.5, kind
        stale = runs[kind]["stale"]
        for a, b in zip(live["rows"], stale["rows"]):
            assert abs((a["rect"]["top"] - live["titleRect"]["top"]) - (b["rect"]["top"] - stale["titleRect"]["top"])) <= 0.5, kind
            assert abs(a["rect"]["height"] - b["rect"]["height"]) <= 0.5, kind
    for a, b in zip(runs["bus"]["live"]["rows"], runs["nodata"]["live"]["rows"]):
        assert abs(a["rect"]["top"] - b["rect"]["top"]) <= 0.5 and abs(a["rect"]["height"] - b["rect"]["height"]) <= 0.5
    assert abs(runs["bus"]["live"]["map"]["top"] - runs["nodata"]["live"]["map"]["top"]) <= 0.5


def test_the_back_button_goes_back_to_page_a(runs):
    for kind in ("bus", "train"):
        assert runs[kind]["afterBack"]["top"] == "live" and runs[kind]["afterBack"]["pageB"] is False, kind

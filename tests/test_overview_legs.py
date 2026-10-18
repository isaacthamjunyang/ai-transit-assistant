"""The journey overview with one row per leg, the line badges and the priority select (plan_edits_9 4.1, 4.2, 4.4, 4.9).

The static tests read the page, copy.js, theme.css and the style guide. The browser tests drive the real page in headless
Edge against the real app with a stubbed OneMap (tests/onemap_stub.py): no OneMap or LTA call is made."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
NB = chr(0xA0)
ESC = chr(92) + "u00a0"
CODES = ["ns", "ew", "cg", "ne", "cc", "dt", "te", "bp", "sk", "pg"]
FILLS = {"ns": "D62821", "ew": "189E4A", "cg": "189E4A", "ne": "844184", "cc": "F2AD27", "dt": "0354A6", "te": "9D5A25",
         "bp": "6E8270", "sk": "6E8270", "pg": "6E8270"}
INKS = {"ns": "FFFFFF", "ew": "000000", "cg": "000000", "ne": "FFFFFF", "cc": "000000", "dt": "FFFFFF", "te": "FFFFFF",
        "bp": "000000", "sk": "000000", "pg": "000000"}


def _luminance(hex6: str) -> float:
    channels = [int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _token(name: str) -> str:
    return re.search(rf"--{name}:\s*#([0-9A-Fa-f]{{6}})", THEME).group(1).upper()


def _rgb(hex6: str) -> str:
    return "rgb({}, {}, {})".format(int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16))


# ---- tokens, contrast and the style rules -------------------------------------------------------------------------


@pytest.mark.parametrize("code", CODES)
def test_each_line_has_a_fill_and_a_text_token_with_4_5_to_1(code):
    assert _token(f"line-{code}") == FILLS[code] and _token(f"line-{code}-ink") == INKS[code]
    assert _ratio(_token(f"line-{code}"), _token(f"line-{code}-ink")) >= 4.5, code


def test_the_official_white_text_that_fails_is_replaced_by_black_on_ew_cg_and_the_lrt_lines():
    for code in ("ew", "cg", "bp", "sk", "pg"):
        assert _ratio(_token(f"line-{code}"), "FFFFFF") < 4.5 <= _ratio(_token(f"line-{code}"), "000000"), code


def test_sentosa_express_uses_the_neutral_tint_and_the_ink_in_both_themes():
    assert "--line-ss: var(--tint-neutral);" in THEME and "--line-ss-ink: var(--color-ink);" in THEME
    assert ".line-badge--ss {" in CSS and "border: 1px solid var(--color-line-strong)" in CSS.split(".line-badge--ss {", 1)[1].split("}", 1)[0]


def test_colours_live_only_in_theme_css():
    for source in (CSS, INDEX):
        assert not re.search(r"#[0-9A-Fa-f]{6}\b(?![^<]*</style>)", re.sub(r"<!--.*?-->", "", source, flags=re.S)) or source is INDEX
    new_css = CSS.split("/* Line badge:", 1)[1].split(".overview-state__actions {", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", new_css)
    assert "style=" not in new_css
    for code in CODES:
        block = new_css.split(f".line-badge--{code} {{", 1)[1].split("}", 1)[0]
        assert f"background: var(--line-{code});" in block and f"color: var(--line-{code}-ink);" in block


def test_the_page_sets_no_colour_and_no_style_for_the_new_rows():
    region = INDEX.split("function legIsRail(leg)", 1)[1].split("function syncOverviewArrive()", 1)[0]
    assert ".style." not in region and "style=" not in region and "setAttribute(\"style\"" not in region
    assert not re.search(r"#[0-9A-Fa-f]{6}\b|rgb\(|hsl\(", region)
    assert "line-badge--" in region and "option.disabled = priorityDisabled(option.value)" in region


# ---- strings: copy.js and the page say the same ----------------------------------------------------------------------


PAIRS = {  # copy.js journeyOverview key: the page's constant
    "walkRow": "JO_WALK_ROW", "walkRowTo": "JO_WALK_ROW_TO", "busToward": "JO_TOWARD",
    "loopToward": "JO_LOOP_TOWARD", "clockwise": "JO_CLOCKWISE", "anticlockwise": "JO_ANTICLOCKWISE",
    "directionPlatform": "JO_DIRECTION_PLATFORM", "platformOnly": "JO_PLATFORM_ONLY", "stopsAndMin": "JO_STOPS", "stopOneAndMin": "JO_STOP_ONE",
    "scheduledIn": "JO_SCHEDULED_IN", "scheduledInOne": "JO_SCHEDULED_IN_ONE", "scheduledNow": "JO_SCHEDULED_NOW",
    "scheduledAt": "JO_SCHEDULED_AT",
    "summaryAria": "JO_SUMMARY_ARIA", "durationMin": "JO_DURATION_MIN", "durationHr": "JO_DURATION_HR",
    "durationHrMin": "JO_DURATION_HR_MIN", "transfersMany": "JO_TRANSFERS_MANY", "transfersOne": "JO_TRANSFERS_ONE",
    "transfersNone": "JO_TRANSFERS_NONE", "noRouteFound": "JO_NO_ROUTE_FOUND", "noBusOnly": "JO_NO_BUS_ONLY",
    "noMrtOnly": "JO_NO_MRT_ONLY", "needsRouteService": "JO_NEEDS_ROUTE_SERVICE",
    "noService": "JO_NO_SERVICE_STATIC", "noServiceAny": "JO_NO_SERVICE_ANY", "noBusClosed": "JO_NO_BUS_CLOSED",
    "noMrtClosed": "JO_NO_MRT_CLOSED",
    "fallbackNote": "JO_FALLBACK_NOTE",
    "destinationFallback": "JO_DESTINATION_FALLBACK",
}


def test_the_page_constants_are_copy_js_character_for_character():
    jo = COPY.split("journeyOverview: {", 1)[1].split("\n  },", 1)[0]
    for key, variable in PAIRS.items():
        copy_value = re.search(rf'\b{key}: "((?:[^"\\]|\\.)*)"', jo).group(1)
        page_value = re.search(rf'var {variable} = "((?:[^"\\]|\\.)*)";', INDEX).group(1)
        assert copy_value == page_value, (key, copy_value, page_value)
    names = COPY.split("lineNames: {", 1)[1].split("\n  },", 1)[0]
    for code, name in re.findall(r'(\w+): "([^"]+)"', names):
        assert f'{code}: "{name}"' in INDEX.split("var LINE_NAMES = {", 1)[1].split("};", 1)[0], code


def test_the_section_4_9_texts_are_exact():
    expected = {
        "walkRow": "Walk {n}" + ESC + "min", "busToward": "To {terminus}",
        "loopToward": "{direction} \\u00b7 To {terminus}", "clockwise": "Clockwise", "anticlockwise": "Anticlockwise",
        "directionPlatform": "{direction} \\u00b7 Platform {x}", "platformOnly": "Platform {x}",
        "scheduledNow": "Scheduled · Now", "scheduledInOne": "Scheduled · In 1" + ESC + "min",
        "scheduledIn": "Scheduled · In {n}" + ESC + "min", "scheduledAt": "Scheduled · {time}",
        "noBusOnly": "No bus-only route found. Try another priority.",
        "noMrtOnly": "No MRT or LRT route found. Try another priority.",
        "needsRouteService": "Needs the route service.",
        "noRouteFound": "No route found for this trip.",
        "fallbackNote": "Showing bus routes only. The route service is unavailable.",
    }
    for key, value in expected.items():
        assert f'{key}: "{value}"' in COPY, key


def test_numbers_keep_their_min_and_no_fares_or_street_names_appear_in_the_new_code():
    region = INDEX.split("function legIsRail(leg)", 1)[1].split("function syncOverviewArrive()", 1)[0]
    code = "\n".join(row for row in region.split("\n") if not row.strip().startswith("//"))
    assert "fare" not in code.lower() and "street" not in code.lower()
    for variable in ("JO_WALK_ROW", "JO_STOPS", "JO_STOP_ONE", "JO_SCHEDULED_IN", "JO_DURATION_MIN", "JO_DURATION_HR_MIN"):
        value = re.search(rf'var {variable} = "([^"]*)";', INDEX).group(1)
        assert "} min" not in value and "}" + ESC + "min" in value, variable  # a number never splits from "min"


def test_the_page_always_sends_the_priority_and_does_not_remember_it():
    plan = INDEX.split("function planJourney()", 1)[1].split("function peekOverviewArrivals", 1)[0]
    assert '"&priority=" + encodeURIComponent(planPriority)' in plan
    enter = INDEX.split('if (name === "journey") {', 1)[1].split("}", 1)[0]
    assert 'planPriority = "fastest";' in enter and enter.index("planPriority") < enter.index("planJourney();")
    assert "localStorage" not in INDEX.split("var PRIORITY_IDS", 1)[1].split("function syncOverviewArrive()", 1)[0]


def test_the_priority_is_a_native_select_with_a_label_and_the_five_options():
    block = INDEX.split('id="overview-priority"', 1)[1].split('<ol id="overview-skeleton"', 1)[0]
    assert "<label" not in block and "overview-priority__label" not in INDEX  # no visible label: the select has its aria-label
    assert '<select id="priority-select" class="priority-select" aria-label="Priority">' in block
    options = re.findall(r'<option value="(\w+)"[^>]*>([^<]+)</option>', block)
    assert options == [("fastest", "Fastest"), ("fewest_transfers", "Fewest transfers"), ("least_walking", "Least walking"),
                       ("bus_only", "Bus only"), ("mrt_only", "MRT only")]
    assert 'value="fastest" selected' in block
    assert "role=\"radio\"" not in block and "arrive-chip" not in block and "tabindex" not in block  # native, in the tab order
    code = INDEX.split("function syncPrioritySelect()", 1)[1].split("// The fallback note", 1)[0]
    assert "option.disabled = priorityDisabled(option.value)" in code
    assert 'getElementById("priority-select").addEventListener("change"' in code
    assert "syncPriorityChips" not in INDEX and "arrow" not in code.lower()


def test_the_style_guide_shows_every_badge_in_both_themes_and_the_new_rows():
    section = GUIDE.split('id="legs-heading"', 1)[1].split("</section>", 1)[0]
    assert 'class="place-row-samples theme-sample-light"' in section and 'class="place-row-samples theme-sample-dark"' in section
    assert "legs-sample-light" in section and "legs-sample-dark" in section
    program = GUIDE.split("var SG_LINE_CODES", 1)[1].split("document.getElementById(\"legs-sample-light\")", 1)[0]
    assert '["NS", "EW", "CG", "NE", "CC", "DT", "TE", "BP", "SK", "PG", "SS"]' in "var SG_LINE_CODES" + program
    for code in CODES + ["ss"]:
        assert code.upper() in program or "LINE_CODES" in program
    for needle in ("line-badge", "priority-select", 'sgLegRow("walk"', 'sgRailLeg("NS"', 'sgBusLeg(', " disabled"):
        assert needle in program, needle


# ---- the page in a browser ----------------------------------------------------------------------------------------

TABLE = {"schema": 1, "stations": {}, "lines": {}, "patterns": {
    "NS": {"Marina South Pier": ["NS17", "NS22", "NS26"]}, "EW": {"Tuas Link": ["EW14", "EW24"]}}}
ALL = {"TRANSIT": stub.mixed, "BUS": stub.bus_only, "RAIL": None}


def _run(tmp_path_factory, name, table=None, rail_table=TABLE, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode(table) if table else None,
                     rail_table=rail_table) as base:
        return run_scenario("overviewlegs", base, {"name": name, **config})["result"]


@pytest.fixture(scope="module")
def narrow(tmp_path_factory):
    return _run(tmp_path_factory, "narrow", ALL, width=360, height=800, choose="bus_only")


@pytest.fixture(scope="module")
def wide_dark(tmp_path_factory):
    return _run(tmp_path_factory, "wide", ALL, width=1280, height=900, dark=True)


@pytest.fixture(scope="module")
def train_first(tmp_path_factory):
    return _run(tmp_path_factory, "train", {"TRANSIT": stub.train_first}, width=390)


def _dirs(line, **headsigns):
    return {"directions": {h: {"line": line, "direction_id": d, "trips": 9, "platforms": p} for h, (d, p) in headsigns.items()}}


PLATFORM_TABLE = {  # NS17 has one platform for its direction; EW14 has two platforms serving its direction
    "schema": 1, "lines": {}, "stations": {
        "NS17": _dirs("NS", **{"Marina South Pier": (1, ["B"])}), "EW14": _dirs("EW", **{"Tuas Link": (1, ["A", "B"])})},
    "patterns": {"NS": {"Marina South Pier": ["NS17", "NS22", "NS26"]}, "EW": {"Tuas Link": ["EW14", "EW15", "EW24"]}}}
CIRCLE_TABLE = {  # the loop words come from the Anticlockwise and Clockwise headsigns and their direction ids
    "schema": 1, "lines": {}, "stations": {"CC4": _dirs("CC", Anticlockwise=(0, ["A"]), Clockwise=(1, ["B"]))},
    "patterns": {"CC": {"Anticlockwise": ["CC4", "CC15"]}}}
CIRCLE_STADIUM_TABLE = {  # a station headsign: "Anticlockwise" and the terminus, and no platform (two serve it)
    "schema": 1, "lines": {}, "stations": {
        "CC4": _dirs("CC", Anticlockwise=(0, ["A"]), Clockwise=(1, ["B"]), Stadium=(0, ["A", "B"]))},
    "patterns": {"CC": {"Stadium": ["CC4", "CC15"]}}}


@pytest.fixture(scope="module")
def platforms(tmp_path_factory):
    return _run(tmp_path_factory, "platforms", {"TRANSIT": stub.train_transfer}, rail_table=PLATFORM_TABLE, width=360)


SAME_LINE_TABLE = {
    "schema": 1, "lines": {}, "stations": {}, "patterns": {"NS": {"Marina South Pier": ["NS17", "NS22", "NS23", "NS26"]}}}


@pytest.fixture(scope="module")
def same_line(tmp_path_factory):
    return _run(tmp_path_factory, "same_line", {"TRANSIT": stub.same_line}, rail_table=SAME_LINE_TABLE, width=1280, dark=True)


@pytest.fixture(scope="module")
def later_buses(tmp_path_factory):
    return _run(tmp_path_factory, "later_buses", {"TRANSIT": stub.later_buses}, width=390)


@pytest.fixture(scope="module")
def circle(tmp_path_factory):
    return _run(tmp_path_factory, "circle", {"TRANSIT": stub.circle}, rail_table=CIRCLE_TABLE, width=360)


@pytest.fixture(scope="module")
def circle_stadium(tmp_path_factory):
    return _run(tmp_path_factory, "circle_stadium", {"TRANSIT": stub.circle}, rail_table=CIRCLE_STADIUM_TABLE, width=1280)


@pytest.fixture(scope="module")
def fallback(tmp_path_factory):
    return _run(tmp_path_factory, "fallback", None, width=390, choose="fewest_transfers")


@pytest.fixture(scope="module")
def fallback_no_route(tmp_path_factory):
    return _run(tmp_path_factory, "fallback_none", None, width=390, destPos=[1.20, 103.50], dest="00000")


@pytest.fixture(scope="module")
def onemap_empty(tmp_path_factory):
    return _run(tmp_path_factory, "onemap_none", {"TRANSIT": stub.mixed}, width=390, destPos=[1.20, 103.50], dest="00000")


@pytest.fixture(scope="module")
def empty_priority(tmp_path_factory):
    return _run(tmp_path_factory, "empty", {"TRANSIT": stub.mixed}, width=390, choose="mrt_only")


def _texts(rows):
    return [row["text"] for row in rows]


def _kinds(rows):
    return [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in rows]


def test_the_overview_has_one_row_per_leg_in_order(wide_dark):
    rows = wide_dark["first"]["rows"]
    # a change is a walk row only when OneMap gave a walk: NS26 to EW14 had none, so the two rail legs touch
    assert _kinds(rows) == ["origin", "walk", "bus", "walk", "rail", "rail", "walk", "rail", "walk", "destination"]
    assert rows[0]["lines"][0] == "From" and rows[0]["lines"][1] == "Your current location"
    assert rows[1]["title"].startswith("Walk ") and "to Origin" in rows[1]["text"]
    bus = rows[2]
    assert bus["lines"][0] == "Origin" and bus["lines"][1].startswith("Bus 18")
    assert re.fullmatch(r"4 stops · 8" + NB + "min", bus["lines"][-2]) and bus["lines"][-1] == "Bef Toh Guan Rd"
    assert "Board" not in bus["text"] and "Get off" not in bus["text"] and "Toward" not in bus["text"]
    assert any(line.startswith("Arriving in") for line in bus["lines"])  # the first bus keeps its live line


def test_a_change_is_a_plain_walk_row_for_every_pair_of_modes_and_has_no_wait(wide_dark, platforms, same_line):
    rows = wide_dark["first"]["rows"]
    texts = " ".join(_texts(rows) + _texts(platforms["first"]["rows"]) + _texts(same_line["first"]["rows"]))
    assert "Change" not in texts and "wait" not in texts and "about" not in texts.lower().replace("scheduled", "")
    # bus to rail: "Walk 2 min" and "130 m to Bishan MRT Station (NS17)"
    assert re.fullmatch(r"Walk \d+" + NB + "min", rows[3]["title"])
    assert rows[3]["lines"][1] == "130" + NB + "m to Bishan MRT Station (NS17)"
    assert "step-node--walk" in rows[3]["node"] and not rows[3]["leg"]
    # rail to bus or LRT: the walk names the next station and its own code
    assert re.fullmatch(r"Walk \d+" + NB + "min", rows[6]["title"])
    assert rows[6]["lines"][1].endswith("m to Bukit Panjang LRT Station (BP6)")
    # rail to rail with a walk (NS26 to EW14): the same row, naming the next leg's own code
    walk = platforms["first"]["rows"][3]
    assert _kinds(platforms["first"]["rows"]) == ["origin", "walk", "rail", "walk", "rail", "walk", "destination"]
    assert re.fullmatch(r"Walk \d+" + NB + "min", walk["title"])
    assert walk["lines"][1] == "90" + NB + "m to Raffles Place MRT Station (EW14)"
    assert platforms["first"]["rows"][2]["lines"][-1] == "Raffles Place MRT Station (NS26)"  # the end marker: its own code
    assert platforms["first"]["rows"][4]["lines"][0] == "Raffles Place MRT Station (EW14)"  # the next start marker
    # rail to rail on the same line: also a walk row
    assert _kinds(same_line["first"]["rows"]) == ["origin", "walk", "rail", "walk", "rail", "walk", "destination"]


def test_a_change_with_no_walk_from_onemap_has_no_row(wide_dark):
    rows = wide_dark["first"]["rows"]
    assert _kinds(rows)[4:6] == ["rail", "rail"]  # NS then EW at Raffles Place, no walk leg between them


def test_two_rail_legs_on_different_lines_switch_colour_and_on_the_same_line_share_it(platforms, same_line):
    different = platforms["first"]["rows"]
    ns, walk, ew = different[2], different[3], different[4]
    assert ns["leg"]["barBg"] == ns["badge"]["bg"] and ew["leg"]["barBg"] == ew["badge"]["bg"]
    assert ns["leg"]["barBg"] != ew["leg"]["barBg"]  # NS red, EW green: the colour switches at the interchange
    for leg, row in ((ns["leg"], ns), (ew["leg"], ew)):
        assert row["badge"]["bg"] in leg["startRing"] and row["badge"]["bg"] in leg["endRing"]
    assert ns["leg"]["startRing"] != ew["leg"]["startRing"]
    assert not walk["leg"] and "step-node--walk" in walk["node"]  # the walk row between is neutral, never a line colour
    assert walk["node"].count("rail") == 0
    same = [row for row in same_line["first"]["rows"] if row["leg"]]
    assert len(same) == 2 and same[0]["leg"]["barBg"] == same[1]["leg"]["barBg"] == same[0]["badge"]["bg"]
    assert same[0]["leg"]["startRing"] == same[1]["leg"]["endRing"]


def test_the_end_marker_uses_the_start_icon_and_both_markers_have_a_ring_in_the_line_colour(wide_dark):
    legs = [row for row in wide_dark["first"]["rows"] if row["leg"]]
    rails = [row for row in legs if row["badge"] and row["badge"]["text"] in ("NS", "EW", "BP")]
    assert len(rails) == 3
    for row in rails:
        info = row["leg"]
        assert info["startIcon"] == info["endIcon"] and "<svg" in info["startIcon"]  # the same train icon at both ends
        assert row["badge"]["bg"] in info["startRing"] and row["badge"]["bg"] in info["endRing"]
        assert info["startBg"] == info["endBg"] and info["startColor"] == info["endColor"]
        assert row["lines"][0].endswith(")") and row["lines"][-1].endswith(")")  # the name and code on both


def test_a_bus_leg_has_the_same_shape_with_bus_icons_and_neutral_rings(wide_dark):
    rows = wide_dark["first"]["rows"]
    bus, rail = rows[2], rows[4]
    info = bus["leg"]
    assert bus["markers"] == ["step-node step-node--bus", "step-node step-node--bus-end"] and bus["bar"]
    assert info["startIcon"] == info["endIcon"] and info["startIcon"] != rail["leg"]["startIcon"]  # a bus icon, not the train
    assert bus["badge"]["text"].replace(" ", "") == "Bus18" and bus["badge"]["cls"].endswith("line-badge--bus")  # neutral: its own outline, no line colour
    assert info["startRing"] == info["endRing"] and info["barBg"] != rail["leg"]["barBg"]
    for token in (row["badge"]["bg"] for row in rows if row["badge"] and row is not bus):
        assert token not in info["startRing"] and token != info["barBg"]  # no line colour on a bus leg
    assert info["barBg"] == info["startBg"]  # the plain primary connector colour
    assert bus["lines"][0] == "Origin" and bus["lines"][-1] == "Bef Toh Guan Rd"


def test_the_first_bus_only_text_is_gone_from_every_row(later_buses):
    rows = later_buses["first"]["rows"]
    assert "first bus only" not in " ".join(row["text"] for row in rows)
    assert all("Scheduled" in row["text"] or "Arriving" in row["text"] or row["badge"] is None for row in rows
               if "journey-step--bus" in row["cls"] or "journey-step--rail" in row["cls"])


def test_a_train_row_has_two_markers_the_line_row_the_schedule_and_the_ride(wide_dark):
    rows = wide_dark["first"]["rows"]
    ns, ew, lrt = rows[4], rows[5], rows[7]
    assert ns["badge"]["text"] == "NS" and ns["badge"]["name"] == "To Marina South Pier"
    # start station, line row, schedule, ride, end station: nothing else
    assert len(ns["lines"]) == 5, ns["lines"]
    assert ns["lines"][0] == "Bishan MRT Station (NS17)" and ns["lines"][1] == "NS To Marina South Pier"
    assert re.fullmatch(r"Scheduled · \d{1,2}:\d\d" + NB + "(AM|PM)( [(]tomorrow[)])?", ns["lines"][2])  # a later leg
    assert re.fullmatch(r"6 stops · 12" + NB + "min", ns["lines"][3])
    assert ns["lines"][4] == "Raffles Place MRT Station (NS26)"
    assert "Board" not in ns["text"] and "Get off" not in ns["text"] and "About" not in ns["text"]
    assert "Platform" not in ns["text"] and "Exit" not in ns["text"]  # the test table has no platforms
    assert ns["markers"] == ["step-node step-node--rail", "step-node step-node--rail-end"] and ns["bar"]
    assert ew["badge"]["text"] == "EW" and ew["badge"]["name"] == "To Tuas Link" and "Toward" not in ew["text"]
    assert lrt["badge"]["text"] == "BP"
    assert "first bus only" not in ns["text"] + ew["text"] + lrt["text"]


DOT = "\u00b7"


def test_a_platform_shows_on_the_line_row_only_when_one_platform_serves_the_direction(platforms):
    rows = platforms["first"]["rows"]
    kinds = [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in rows]
    assert kinds == ["origin", "walk", "rail", "walk", "rail", "walk", "destination"], kinds
    assert rows[2]["lines"][1] == f"NS To Marina South Pier {DOT} Platform B"
    assert rows[4]["lines"][1] == "EW To Tuas Link"  # two platforms serve it: nothing is shown
    assert "Platform" not in rows[4]["text"] and "Exit" not in " ".join(row["text"] for row in rows)


def test_a_circle_line_ride_says_clockwise_or_anticlockwise_then_the_terminus_when_known(circle, circle_stadium):
    plain = circle["first"]["rows"][2]
    assert plain["lines"][1] == f"CC Anticlockwise {DOT} Platform A"  # no terminus is known for the loop headsign
    assert "To " not in plain["lines"][1]
    stadium = circle_stadium["first"]["rows"][2]
    assert stadium["lines"][1] == f"CC Anticlockwise {DOT} To Stadium"  # two platforms serve it: no platform
    for result in (circle, circle_stadium):
        row = result["first"]["rows"][2]
        assert re.fullmatch(r"Scheduled · (In \d+" + NB + "min|In 1" + NB + "min|Now)", row["lines"][2]), row["lines"]
        assert row["lines"][0] == "Promenade MRT Station (CC4)" and row["lines"][4] == "Bishan MRT Station (CC15)"


@pytest.mark.parametrize("fixture", ["narrow", "wide_dark"])
def test_the_leg_markers_bar_and_end_label_fit_at_360_and_1280_in_both_themes(fixture, request):
    result = request.getfixturevalue(fixture)["first"]
    legs = [row for row in result["rows"] if row["leg"]]
    assert len(legs) == 4  # a bus and three train legs
    for row in legs:
        info = row["leg"]
        assert info["start"]["y"] < info["end"]["y"] and info["end"]["y"] - info["start"]["y"] > info["start"]["h"]
        assert info["bar"]["y"] <= info["start"]["y"] + info["start"]["h"] / 2 + 1
        assert info["bar"]["y"] + info["bar"]["h"] >= info["end"]["y"] + info["end"]["h"] / 2 - 1
        assert info["bar"]["w"] >= 3 and abs(info["bar"]["x"] + info["bar"]["w"] / 2 - (info["start"]["x"] + info["start"]["w"] / 2)) < 1.5
        assert info["endText"]  # a text label with the stop name: not colour alone
        assert info["endColor"] != info["endBg"]
        assert row["right"] <= result["innerWidth"]
    for row in legs[1:]:
        assert row["leg"]["barBg"] == row["badge"]["bg"]  # a rail leg's bar takes its line token colour
    assert result["scrollWidth"] <= result["innerWidth"]


def test_the_summary_card_has_three_labelled_cells_and_reads_as_one_sentence(wide_dark):
    summary = wide_dark["first"]["summary"]
    assert summary["labels"] == ["Total time", "Transfers", "Walking"] and summary["role"] == "group"
    assert re.fullmatch(rf"1{NB}hr \d{{1,2}}{NB}min", summary["values"][0]) and summary["values"][1] == "3"  # about 63 min; the stub's clock moves it by a minute
    assert re.fullmatch(rf"\d+{NB}min", summary["values"][2])
    assert summary["aria"] == f"Total time {summary['values'][0]}, 3 transfers, walking {summary['values'][2]}"
    assert "overview-summary--high" in summary["cls"]  # three transfers: red


@pytest.mark.parametrize("fixture", ["wide_dark", "narrow"])
def test_badges_show_the_code_and_the_name_in_the_line_colours(fixture, request):
    result = request.getfixturevalue(fixture)["first"]
    badges = [row["badge"] for row in result["rows"] if row["badge"] and "line-badge--" in row["badge"]["cls"]
              and "line-badge--bus" not in row["badge"]["cls"]]
    assert [b["text"] for b in badges] == ["NS", "EW", "BP"]  # the bus number badge is neutral and has its own test
    for badge in badges:
        code = badge["text"].lower()
        assert f"line-badge--{code}" in badge["cls"]
        assert badge["bg"] == _rgb(FILLS[code]) and badge["color"] == _rgb(INKS[code]), badge
        assert badge["box"]["h"] >= 22 and badge["box"]["w"] >= 30


def test_the_priority_select_starts_on_fastest(wide_dark):
    select = wide_dark["first"]["select"]
    assert select["tag"] == "SELECT" and select["value"] == "fastest" and select["text"] == "Fastest"
    assert [o["text"] for o in select["options"]] == ["Fastest", "Fewest transfers", "Least walking", "Bus only", "MRT only"]
    assert all(o["disabled"] is False for o in select["options"]) and select["disabled"] is False
    assert select["label"] is None and select["aria"] == "Priority" and select["tabIndex"] == 0
    assert wide_dark["first"]["visibleLabels"] == 0
    assert wide_dark["first"]["planRequests"][0].count("priority=fastest") == 1
    assert wide_dark["first"]["fallbackNote"] is None and wide_dark["first"]["chipsLeft"] == 0


def test_the_overview_fits_360_and_1280_without_sideways_scroll_and_the_select_is_44_px(narrow, wide_dark):
    for result in (narrow["first"], wide_dark["first"]):
        assert result["scrollWidth"] <= result["innerWidth"]
        assert all(row["right"] <= result["innerWidth"] + 1 for row in result["rows"])
        assert result["select"]["box"]["h"] >= 44 and result["select"]["box"]["right"] <= result["innerWidth"]
    assert narrow["first"]["innerWidth"] == 360 and wide_dark["first"]["innerWidth"] == 1280


def test_changing_the_select_refetches_with_that_priority_and_shifts_nothing(narrow):
    after = narrow["afterChoose"]
    assert after["planRequests"][-1].count("priority=bus_only") == 1 and len(after["planRequests"]) == 2
    assert after["select"]["value"] == "bus_only" and after["select"]["text"] == "Bus only"
    kinds = [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in after["rows"]]
    assert kinds == ["origin", "walk", "bus", "walk", "destination"] or "rail" not in kinds
    first = narrow["first"]["select"]["box"]
    assert after["select"]["box"]["h"] == first["h"] and after["select"]["box"]["w"] == first["w"]  # same size
    assert after["select"]["box"]["y"] == first["y"] and after["order"]["select"] == narrow["first"]["order"]["select"]  # same place


def test_an_empty_priority_says_so_and_the_select_stays(empty_priority):
    after = empty_priority["afterChoose"]
    assert after["noRoute"] == "No MRT or LRT route found. Try another priority."
    assert after["timelineVisible"] is False and after["startDisabled"] is True
    assert after["select"]["value"] == "mrt_only" and all(o["disabled"] is False for o in after["select"]["options"])
    assert after["noService"] is False


def test_no_best_available_line_is_ever_shown(wide_dark, narrow, fallback):
    for run in (wide_dark["first"], narrow["afterChoose"], fallback["first"]):
        assert run["priorityNote"] in (None, "Needs the route service.")
    assert "best available" not in INDEX.lower() and "best available" not in COPY.lower()
    assert "bestAvailable" not in COPY and "JO_BEST_AVAILABLE" not in INDEX and "best_available" not in INDEX


def test_a_train_first_route_is_shown_and_start_journey_is_on(train_first):
    first = train_first["first"]
    rows = first["rows"]
    assert rows[2]["badge"]["text"] == "NS" and rows[2]["badge"]["name"] == "To Marina South Pier"
    assert re.search(r"Scheduled · (In \d+" + NB + "min|In 1" + NB + "min|Now)", rows[2]["text"])  # a train: not "Arriving in"
    assert "Arriving in" not in rows[2]["text"]
    assert first["startDisabled"] is False  # the live pages for a train exist now (part 2)
    assert first["arrivalRequests"] == 0  # no bus poll and no bus lookup for a train


def test_the_bus_planner_fallback_shows_its_note_and_disables_the_options_it_cannot_do(fallback):
    first = fallback["first"]
    assert first["fallbackNote"] == "Showing bus routes only. The route service is unavailable."
    assert first["priorityNote"] == "Needs the route service."
    disabled = {o["value"]: o["disabled"] for o in first["select"]["options"]}
    assert disabled == {"fastest": False, "fewest_transfers": False, "least_walking": True, "bus_only": False, "mrt_only": True}
    assert first["startDisabled"] is False
    kinds = [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in first["rows"]]
    assert kinds == ["origin", "walk", "bus", "walk", "destination"]
    assert first["rows"][2]["lines"][1].startswith("Bus 18") and first["summary"]


def test_the_bus_planner_finding_nothing_shows_the_static_sentence_and_the_fallback_note(fallback_no_route):
    first = fallback_no_route["first"]
    assert first["noRoute"] == "No direct or 1-transfer route for this trip."
    assert first["fallbackNote"] == "Showing bus routes only. The route service is unavailable."
    assert first["timelineVisible"] is False and first["startDisabled"] is True


def test_onemap_working_but_finding_nothing_says_no_route_found(onemap_empty):
    first = onemap_empty["first"]
    assert first["noRoute"] == "No route found for this trip."
    assert first["fallbackNote"] is None


def test_under_the_fallback_a_change_to_an_enabled_option_refetches_and_a_disabled_one_cannot_be_picked(fallback):
    after = fallback["afterChoose"]
    assert after["select"]["value"] == "fewest_transfers"
    assert after["planRequests"][-1].count("priority=fewest_transfers") == 1
    disabled = {o["value"]: o["disabled"] for o in after["select"]["options"]}
    assert disabled["least_walking"] is True and disabled["mrt_only"] is True and after["priorityNote"] == "Needs the route service."


def test_the_plan_describes_the_overview_the_badges_and_the_select():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    for text in ("**Journey overview.**", "**Line badges.**", "**Priority select.**", "`--line-<code>-ink`",
                 "Needs the route service.",
                 "The page always sends `priority`", "a plain walk row"):
        assert text in plan, text

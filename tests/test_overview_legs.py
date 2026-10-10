"""The journey overview with one row per leg, the line badges and the priority chips (plan_edits_9 4.1, 4.2, 4.4, 4.9).

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
    assert "line-badge--" in region and "classList.toggle(\"is-selected\"" in region


# ---- strings: copy.js and the page say the same ----------------------------------------------------------------------


PAIRS = {  # copy.js journeyOverview key: the page's constant
    "walkRow": "JO_WALK_ROW", "walkRowTo": "JO_WALK_ROW_TO", "busToward": "JO_TOWARD", "board": "JO_BOARD",
    "getOff": "JO_GET_OFF", "stopsAndMin": "JO_STOPS", "stopOneAndMin": "JO_STOP_ONE",
    "changeAtStation": "JO_CHANGE_STATION", "changeAtStop": "JO_CHANGE_STOP", "changeCodes": "JO_CHANGE_CODES",
    "transferTimes": "JO_TRANSFER_TIMES", "transferWalkOnly": "JO_TRANSFER_WALK", "transferWaitOnly": "JO_TRANSFER_WAIT",
    "scheduledAbout": "JO_SCHEDULED_ABOUT", "scheduledAt": "JO_SCHEDULED_AT", "scheduledTime": "JO_SCHEDULED_TIME",
    "totals": "JO_TOTALS", "transfersMany": "JO_TRANSFERS_MANY", "transfersOne": "JO_TRANSFERS_ONE",
    "transfersNone": "JO_TRANSFERS_NONE", "noRouteFound": "JO_NO_ROUTE_FOUND", "noBusOnly": "JO_NO_BUS_ONLY",
    "noMrtOnly": "JO_NO_MRT_ONLY", "bestAvailable": "JO_BEST_AVAILABLE", "needsRouteService": "JO_NEEDS_ROUTE_SERVICE",
    "fallbackNote": "JO_FALLBACK_NOTE", "trainLiveSoon": "JO_TRAIN_LIVE_SOON",
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
        "walkRow": "Walk {n}" + ESC + "min", "busToward": "Toward {terminus}", "board": "Board", "getOff": "Get off",
        "changeAtStation": "Change at {station}", "changeAtStop": "Change at {stop}",
        "changeCodes": "Change from {a} to {b} at {station}", "scheduledAbout": "About {n}" + ESC + "min, scheduled",
        "noBusOnly": "No bus-only route found. Try another priority.",
        "noMrtOnly": "No MRT or LRT route found. Try another priority.",
        "bestAvailable": "This is the best available for this trip.", "needsRouteService": "Needs the route service.",
        "noRouteFound": "No route found for this trip.",
        "fallbackNote": "Showing bus routes only. The route service is unavailable.",
    }
    for key, value in expected.items():
        assert f'{key}: "{value}"' in COPY, key


def test_numbers_keep_their_min_and_no_fares_or_street_names_appear_in_the_new_code():
    region = INDEX.split("function legIsRail(leg)", 1)[1].split("function syncOverviewArrive()", 1)[0]
    code = "\n".join(row for row in region.split("\n") if not row.strip().startswith("//"))
    assert "fare" not in code.lower() and "street" not in code.lower()
    for variable in ("JO_WALK_ROW", "JO_STOPS", "JO_STOP_ONE", "JO_SCHEDULED_ABOUT", "JO_TRANSFER_TIMES", "JO_TRANSFER_WALK",
                    "JO_TRANSFER_WAIT", "JO_SCHEDULED_AT", "JO_TOTALS"):
        value = re.search(rf'var {variable} = "([^"]*)";', INDEX).group(1)
        assert "} min" not in value and "}" + ESC + "min" in value, variable  # a number never splits from "min"


def test_the_page_always_sends_the_priority_and_does_not_remember_it():
    plan = INDEX.split("function planJourney()", 1)[1].split("function peekOverviewArrivals", 1)[0]
    assert '"&priority=" + encodeURIComponent(planPriority)' in plan
    enter = INDEX.split('if (name === "journey") {', 1)[1].split("}", 1)[0]
    assert 'planPriority = "fastest";' in enter and enter.index("planPriority") < enter.index("planJourney();")
    assert "localStorage" not in INDEX.split("var PRIORITY_IDS", 1)[1].split("function syncOverviewArrive()", 1)[0]


def test_the_chips_are_a_radio_group_that_reuses_the_arrive_by_chip_style():
    block = INDEX.split('id="overview-priority"', 1)[1].split('<ol id="overview-skeleton"', 1)[0]
    assert 'role="radiogroup" aria-label="Priority"' in block and block.count('role="radio"') == 5
    assert block.count('class="arrive-chip"') + block.count('class="arrive-chip is-selected"') == 5 and 'aria-checked="true" tabindex="0" data-priority="fastest"' in block
    for label in ("Fastest", "Fewest transfers", "Least walking", "Bus only", "MRT only"):
        assert f">{label}</button>" in block
    assert block.index("Fastest") < block.index("Fewest transfers") < block.index("Least walking") < block.index("Bus only")


def test_the_style_guide_shows_every_badge_in_both_themes_and_the_new_rows():
    section = GUIDE.split('id="legs-heading"', 1)[1].split("</section>", 1)[0]
    assert 'class="place-row-samples theme-sample-light"' in section and 'class="place-row-samples theme-sample-dark"' in section
    assert "legs-sample-light" in section and "legs-sample-dark" in section
    program = GUIDE.split("var SG_LINE_CODES", 1)[1].split("document.getElementById(\"legs-sample-light\")", 1)[0]
    assert '["NS", "EW", "CG", "NE", "CC", "DT", "TE", "BP", "SK", "PG", "SS"]' in "var SG_LINE_CODES" + program
    for code in CODES + ["ss"]:
        assert code.upper() in program or "LINE_CODES" in program
    for needle in ("line-badge", "arrive-chip", 'sgLegRow("walk"', 'sgLegRow("rail"', 'sgLegRow("change"', "aria-disabled"):
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
    return _run(tmp_path_factory, "narrow", ALL, width=360, height=800, click="bus_only")


@pytest.fixture(scope="module")
def wide_dark(tmp_path_factory):
    return _run(tmp_path_factory, "wide", ALL, width=1280, height=900, dark=True)


@pytest.fixture(scope="module")
def train_first(tmp_path_factory):
    return _run(tmp_path_factory, "train", {"TRANSIT": stub.train_first}, width=390)


@pytest.fixture(scope="module")
def fallback(tmp_path_factory):
    return _run(tmp_path_factory, "fallback", None, width=390, keys="ArrowRight")


@pytest.fixture(scope="module")
def empty_chip(tmp_path_factory):
    return _run(tmp_path_factory, "empty", {"TRANSIT": stub.mixed}, width=390, click="mrt_only")


@pytest.fixture(scope="module")
def best_available(tmp_path_factory):
    return _run(tmp_path_factory, "best", {"TRANSIT": stub.mixed}, width=390, keys="ArrowRight")


def _texts(rows):
    return [row["text"] for row in rows]


def test_the_overview_has_one_row_per_leg_in_order(wide_dark):
    rows = wide_dark["first"]["rows"]
    kinds = [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in rows]
    assert kinds == ["origin", "walk", "bus", "change", "rail", "change", "rail", "change", "rail", "walk", "destination"]
    assert rows[0]["lines"][0] == "From" and rows[0]["lines"][1] == "Your current location"
    assert rows[1]["title"].startswith("Walk ") and "to Origin (01011)" in rows[1]["text"]
    bus = rows[2]
    assert bus["lines"][0].startswith("Bus 18") and "Board Origin (01011)" in bus["text"]
    assert "Get off Bef Toh Guan Rd (28059)" in bus["text"] and re.search(r"4 stops · 8" + NB + "min", bus["text"])


def test_walk_bus_and_transfer_rows_use_the_section_4_9_words(wide_dark):
    rows = wide_dark["first"]["rows"]
    assert rows[3]["title"] == "Change at Bef Toh Guan Rd"
    assert rows[3]["lines"][1] == "2" + NB + "min walk · about 2" + NB + "min wait"
    assert rows[5]["title"] == "Change from NS26 to EW14 at Raffles Place"
    assert rows[5]["lines"][1] == "About 3" + NB + "min wait"
    assert rows[7]["title"] == "Change at Jurong East"
    assert rows[7]["lines"][1] == "3" + NB + "min walk · about 3" + NB + "min wait"
    assert rows[9]["title"].startswith("Walk ") and "to Destination" in rows[9]["text"]
    assert rows[9]["edit"]["label"] == "Edit destination stop" and rows[10]["edit"]["label"] == "Edit destination"
    assert "Schedule" not in _texts(rows)[2] and "fare" not in " ".join(_texts(rows)).lower()


def test_a_train_row_has_its_badge_name_direction_stops_and_a_schedule_line(wide_dark):
    rows = wide_dark["first"]["rows"]
    ns, ew, lrt = rows[4], rows[6], rows[8]
    assert ns["badge"]["text"] == "NS" and ns["badge"]["name"] == "North-South Line"
    assert ns["lines"][1] == "Toward Marina South Pier" and "Board Bishan MRT Station (NS17)" in ns["text"]
    assert "Get off Raffles Place MRT Station (NS26)" in ns["text"] and re.search(r"6 stops · 12" + NB + "min", ns["text"])
    assert re.search(r"About \d{1,2}:\d\d" + NB + "(AM|PM)", ns["text"])  # a later leg: its schedule line
    assert ew["badge"]["text"] == "EW" and ew["badge"]["name"] == "East-West Line" and "Toward Tuas Link" in ew["text"]
    assert lrt["badge"]["text"] == "BP" and lrt["badge"]["name"] == "Bukit Panjang LRT"
    assert "Live tracking covers your first bus only." not in ns["text"] + ew["text"] + lrt["text"]


def test_the_totals_line_counts_minutes_transfers_and_walking(wide_dark):
    totals = wide_dark["first"]["totals"]
    assert re.fullmatch(rf"\d+{NB}min · 3 transfers · \d+{NB}min walking", totals), totals


@pytest.mark.parametrize("fixture", ["wide_dark", "narrow"])
def test_badges_show_the_code_and_the_name_in_the_line_colours(fixture, request):
    result = request.getfixturevalue(fixture)["first"]
    badges = [row["badge"] for row in result["rows"] if row["badge"]]
    assert [b["text"] for b in badges] == ["NS", "EW", "BP"]
    for badge in badges:
        code = badge["text"].lower()
        assert f"line-badge--{code}" in badge["cls"] and badge["name"]
        assert badge["bg"] == _rgb(FILLS[code]) and badge["color"] == _rgb(INKS[code]), badge
        assert badge["box"]["h"] >= 22 and badge["box"]["w"] >= 30


def test_the_priority_chips_start_on_fastest_with_radio_semantics(wide_dark):
    chips = wide_dark["first"]["chips"]
    assert [c["text"] for c in chips] == ["Fastest", "Fewest transfers", "Least walking", "Bus only", "MRT only"]
    assert [c["checked"] for c in chips] == ["true", "false", "false", "false", "false"]
    assert [c["tab"] for c in chips] == [0, -1, -1, -1, -1] and chips[0]["selected"] is True
    assert all(c["disabled"] is None for c in chips) and wide_dark["first"]["groupLabel"] == "Priority"
    assert wide_dark["first"]["planRequests"][0].count("priority=fastest") == 1
    assert wide_dark["first"]["fallbackNote"] is None


def test_the_overview_fits_360_and_1280_without_sideways_scroll_and_chips_are_44_px(narrow, wide_dark):
    for result in (narrow["first"], wide_dark["first"]):
        assert result["scrollWidth"] <= result["innerWidth"]
        assert all(row["right"] <= result["innerWidth"] + 1 for row in result["rows"])
        assert all(chip["box"]["h"] >= 44 for chip in result["chips"])
    assert narrow["first"]["innerWidth"] == 360 and wide_dark["first"]["innerWidth"] == 1280


def test_tapping_a_chip_selects_it_and_refetches_with_that_priority(narrow):
    after = narrow["afterClick"]
    assert after["planRequests"][-1].count("priority=bus_only") == 1 and len(after["planRequests"]) == 2
    assert [c["checked"] for c in after["chips"]] == ["false", "false", "false", "true", "false"]
    assert [c["tab"] for c in after["chips"]] == [-1, -1, -1, 0, -1] and after["chips"][3]["selected"] is True
    kinds = [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in after["rows"]]
    assert kinds == ["origin", "walk", "bus", "walk", "destination"] or "rail" not in kinds
    assert after["chips"][3]["box"]["w"] == narrow["first"]["chips"][3]["box"]["w"]  # selecting changes no size


def test_an_empty_chip_says_so_and_the_chips_stay(empty_chip):
    after = empty_chip["afterClick"]
    assert after["noRoute"] == "No MRT or LRT route found. Try another priority."
    assert after["timelineVisible"] is False and after["startDisabled"] is True
    assert [c["checked"] for c in after["chips"]] == ["false", "false", "false", "false", "true"]
    assert all(c["disabled"] is None for c in after["chips"])
    assert after["noService"] is False


def test_fewest_transfers_says_best_available_when_it_changes_nothing(best_available):
    after = best_available["afterKey"]
    assert after["chips"][1]["checked"] == "true" and after["chips"][1]["focused"] is True  # ArrowRight moved the focus too
    assert after["planRequests"][-1].count("priority=fewest_transfers") == 1
    assert after["priorityNote"] == "This is the best available for this trip."


def test_a_train_first_route_is_shown_but_start_journey_stays_off_with_a_note(train_first):
    first = train_first["first"]
    rows = first["rows"]
    assert rows[2]["badge"]["text"] == "NS" and rows[2]["badge"]["name"] == "North-South Line"
    assert re.search(r"About \d+" + NB + "min, scheduled", rows[2]["text"])  # the first leg, a train: not "Arriving in"
    assert "Arriving in" not in rows[2]["text"]
    assert first["startDisabled"] is True
    assert first["trainNote"] == "Live guidance for a train start is not ready yet. Choose Bus only to start this journey."
    assert first["arrivalRequests"] == 0  # no bus poll and no bus lookup for a train


def test_the_bus_planner_fallback_shows_its_note_and_disables_the_chips_it_cannot_do(fallback):
    first = fallback["first"]
    assert first["fallbackNote"] == "Showing bus routes only. The route service is unavailable."
    assert first["priorityNote"] == "Needs the route service."
    disabled = {c["id"]: c["disabled"] for c in first["chips"]}
    assert disabled == {"priority-fastest": None, "priority-fewest_transfers": None, "priority-least_walking": "true",
                        "priority-bus_only": None, "priority-mrt_only": "true"}
    assert first["startDisabled"] is False and first["trainNote"] is None
    kinds = [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in first["rows"]]
    assert kinds == ["origin", "walk", "bus", "walk", "destination"]
    assert first["rows"][2]["lines"][0].startswith("Bus 18") and first["totals"]


def test_arrow_keys_move_between_enabled_chips_and_refetch(fallback):
    after = fallback["afterKey"]
    assert after["chips"][1]["checked"] == "true" and after["chips"][1]["focused"] is True
    assert after["planRequests"][-1].count("priority=fewest_transfers") == 1
    least = after["chips"][2]
    assert least["disabled"] == "true" and least["checked"] == "false"


def test_the_plan_describes_the_overview_the_badges_and_the_chips():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    for text in ("**Journey overview.**", "**Line badges.**", "**Priority chips.**", "`--line-<code>-ink`",
                 "Needs the route service.", "Live guidance for a train start is not ready yet.",
                 "The page always sends `priority`", "Change from {a} to {b} at {station}"):
        assert text in plan, text

"""The journey overview: no arrival range on any screen, the order at the top of the card, the start pin and end flag with their
tokens, and the style guide sample of the priority select. Static checks, tokens from theme.css, and the real page with mock
transports: nothing here calls an API."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
import test_map_lines as tml
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
NB = "\u00a0"
TABLE = {"schema": 1, "stations": {}, "lines": {}, "patterns": {
    "NS": {"Marina South Pier": ["NS17", "NS22", "NS26"]}, "EW": {"Tuas Link": ["EW14", "EW24"]}}}


def _lum(hex6):
    channels = [int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _ratio(a, b):
    high, low = sorted((_lum(a), _lum(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _rgb(hex6):
    return "rgb({}, {}, {})".format(*(int(hex6[i:i + 2], 16) for i in (0, 2, 4)))


# ---- the range is gone from every screen --------------------------------------------------------------------


def test_no_screen_string_carries_the_arrival_range():
    assert 'estimateTarget: "Arrive about {point}"' in COPY and 'estimateOnly: "Estimated destination arrival about {point}"' in COPY
    assert "{range}" not in COPY
    assert "formatRange" not in INDEX and "tile-arrival-range" not in INDEX and "tile-arrival-range" not in CSS
    sentence = INDEX.split("function estimateSentence(estimate, withTarget) {", 1)[1].split("function renderArrivalViews", 1)[0]
    assert "arrival_low" not in sentence and "arrival_high" not in sentence and '" (" +' not in sentence
    for text in re.findall(r"(?:Arrive about|Estimated destination arrival about)[^<\"]*", GUIDE):
        assert "–" not in text and "(" not in text.replace("(tomorrow)", ""), text


def test_the_range_stays_in_the_data_and_the_decisions():
    assert "arrival_low" in INDEX.split("function renderArrivalViews(estimate)", 1)[1].split("function showMiss", 1)[0]  # the data is read
    assert "arrival_low" in (ROOT / "main.py").read_text(encoding="utf-8")  # and still sent by the server
    assert "never drawn on a screen" in PLAN or "The range is never drawn on a screen" in PLAN


def _run(tmp_path_factory, name, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode({"TRANSIT": stub.mixed}), rail_table=TABLE) as base:
        return run_scenario("overviewlegs", base, {"name": name, **config})["result"]


@pytest.fixture(scope="module")
def light(tmp_path_factory):
    return _run(tmp_path_factory, "sel_light", width=360, height=900, estimate=True)


@pytest.fixture(scope="module")
def dark(tmp_path_factory):
    return _run(tmp_path_factory, "sel_dark", width=1280, height=900, dark=True)


def test_the_arrival_sentences_show_the_point_time_only(light):
    seen = light["estimate"]
    for variant in ("without", "with"):
        for place in ("overview", "box", "live"):
            text = seen[variant][place]
            assert re.fullmatch(r"(Arrive about|Estimated destination arrival about) \d{1,2}:\d\d (AM|PM)( \(tomorrow\))?", text), text
    assert seen["with"]["overview"].startswith("Arrive about ") and seen["without"]["overview"].startswith("Estimated destination")
    assert seen["with"]["box"] == seen["with"]["overview"]  # the arrive-by box mirrors the one sentence


# ---- the order at the top of the card -----------------------------------------------------------------------


def test_the_html_order_is_title_select_summary_then_the_rows():
    card = INDEX.split('id="overview-card"', 1)[1].split('<div class="arrive-box">', 1)[0]
    ids = ["overview-title", "priority-select", "overview-summary", "overview-skeleton", "overview-timeline"]
    positions = [card.index(f'id="{name}"') for name in ids]
    assert positions == sorted(positions)
    assert INDEX.count('id="overview-summary"') == 1 and 'id="overview-totals"' not in INDEX


@pytest.mark.parametrize("run", ["light", "dark"])
def test_on_screen_only_the_title_the_select_and_the_summary_sit_above_the_rows(run, request):
    first = request.getfixturevalue(run)["first"]
    order = first["order"]
    assert order["title"] < order["select"] < order["summary"] < order["timeline"]
    assert first["titleText"] == "Your journey" and first["reasonLeft"] is False and first["visibleLabels"] == 0
    assert first["summary"]["labels"] == ["Total time", "Transfers", "Walking"]
    assert first["rows"][0]["lines"][0] == "From"


def test_no_chosen_for_you_line_and_no_visible_priority_label_anywhere():
    for name, text in (("index", INDEX), ("copy", COPY), ("guide", GUIDE)):  # the plan names the line only to say it is gone
        assert "Chosen for you" not in text, name
    assert "overview-priority__label" not in INDEX + CSS + GUIDE
    assert 'aria-label="Priority"' in INDEX and "<label" not in INDEX.split('id="overview-priority"', 1)[1].split("</div>", 1)[0]


# ---- the summary card -----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def durations_light(tmp_path_factory):
    return _run(tmp_path_factory, "dur_light", width=360, height=900, durations=True)


@pytest.fixture(scope="module")
def durations_dark(tmp_path_factory):
    return _run(tmp_path_factory, "dur_dark", width=1280, height=900, dark=True, durations=True)


def test_durations_under_an_hour_say_min_and_from_an_hour_say_hr_and_min(durations_light):
    assert durations_light["durations"] == [
        "0" + NB + "min", "1" + NB + "min", "59" + NB + "min", "1" + NB + "hr", "1" + NB + "hr 5" + NB + "min",
        "1" + NB + "hr 59" + NB + "min", "2" + NB + "hr", "3" + NB + "hr 5" + NB + "min"]


@pytest.mark.parametrize("run, theme", [("durations_light", "light"), ("durations_dark", "dark")])
def test_the_summary_colour_follows_the_transfers_with_the_status_tokens(run, theme, request):
    tones = request.getfixturevalue(run)["tones"]
    tokens = tml._theme(theme)
    expected = {"0": ("overview-summary--ok", "--status-live"), "1": ("overview-summary--mid", "--status-uncertain"),
                "2": ("overview-summary--mid", "--status-uncertain"), "3": ("overview-summary--high", "--status-unavailable"),
                "4": ("overview-summary--high", "--status-unavailable")}
    for count, (klass, token) in expected.items():
        seen = tones[count]
        assert klass in seen["cls"] and sum(f"overview-summary--{t}" in seen["cls"] for t in ("ok", "mid", "high")) == 1, (count, seen["cls"])
        assert seen["bar"] == _rgb(tml._hex(tokens, token)), (theme, count)
        assert seen["labels"] == ["Total time", "Transfers", "Walking"] and seen["values"][1] == count  # the numbers and labels always show
    assert tones["0"]["values"][0] == "1" + NB + "hr 10" + NB + "min" and tones["0"]["values"][2] == "1" + NB + "hr 1" + NB + "min"


def test_the_summary_aria_label_reads_the_whole_summary(durations_light):
    tones = durations_light["tones"]
    assert tones["0"]["aria"] == f"Total time 1{NB}hr 10{NB}min, No transfers, walking 1{NB}hr 1{NB}min"
    assert tones["1"]["aria"].endswith(", 1 transfer, walking 1" + NB + "hr 1" + NB + "min")
    assert tones["3"]["aria"] == f"Total time 1{NB}hr 10{NB}min, 3 transfers, walking 1{NB}hr 1{NB}min"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_summary_bar_is_3_to_1_on_the_card_and_the_text_is_readable_on_the_tint(theme):
    tokens = tml._theme(theme)
    card = tml._hex(tokens, "--color-card")
    for token in ("--status-live", "--status-uncertain", "--status-unavailable"):
        accent = tml._hex(tokens, token)
        assert _ratio(accent, card) >= 3, (theme, token)
        tint = "".join(f"{round(int(accent[i:i + 2], 16) * 0.09 + int(card[i:i + 2], 16) * 0.91):02X}" for i in (0, 2, 4))
        assert _ratio(tml._hex(tokens, "--color-ink"), tint) >= 4.5 and _ratio(tml._hex(tokens, "--color-muted"), tint) >= 4.5, (theme, token)


def test_the_summary_card_css_uses_tokens_only():
    block = CSS.split("The summary card under the select", 1)[1].split(".summary-item .dest-tile", 1)[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", block)
    for token in ("--status-live", "--status-uncertain", "--status-unavailable"):
        assert f"var({token})" in block
    assert "border-left: 6px solid var(--summary-accent)" in block


# ---- the start pin and the end flag -------------------------------------------------------------------------


@pytest.mark.parametrize("run, theme", [("light", "light"), ("dark", "dark")])
def test_the_start_is_a_red_pin_and_the_destination_a_green_flag_from_new_tokens(run, theme, request):
    rows = request.getfixturevalue(run)["first"]["rows"]
    tokens = tml._theme(theme)
    start, end = rows[0], rows[-1]
    assert start["lines"][0] == "From" and end["lines"][0] == "Destination"  # the text labels stay
    assert start["icon"]["color"] == _rgb(tml._hex(tokens, "--marker-start")) and end["icon"]["color"] == _rgb(tml._hex(tokens, "--marker-end"))
    assert start["icon"]["bg"] == end["icon"]["bg"] == _rgb(tml._hex(tokens, "--color-secondary"))  # on the icon tile
    assert start["icon"]["svg"] > 0 and end["icon"]["svg"] > 0


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_marker_tokens_are_3_to_1_on_the_tile_and_differ_from_every_status_token(theme):
    tokens = tml._theme(theme)
    tile = tml._hex(tokens, "--color-secondary")
    for name in ("--marker-start", "--marker-end"):
        colour = tml._hex(tokens, name)
        assert _ratio(colour, tile) >= 3 and _ratio(colour, tml._hex(tokens, "--color-card")) >= 3, (theme, name)
        for other, value in tokens.items():
            if re.match(r"--(status-|action-|fill-|map-destination|map-live-bus|color-selected-outline-success)", other):
                resolved = tml._resolve(tokens, value)
                assert resolved.lstrip("#").upper() != colour, (theme, name, other)
    assert tml._hex(tokens, "--marker-start") != tml._hex(tokens, "--marker-end")


def test_the_tokens_are_in_all_four_theme_blocks_and_the_icon_rules_use_them():
    assert THEME.count("--marker-start:") == 4 and THEME.count("--marker-end:") == 4
    assert ".step-node--origin {\n  background: var(--color-secondary);\n  color: var(--marker-start);" in CSS
    assert ".step-node--destination {\n  background: var(--color-secondary);\n  color: var(--marker-end);" in CSS
    assert 'fill=\\"currentColor\\"' in INDEX.split("var FLAG_SVG = ", 1)[1].split("\n", 1)[0]  # a filled flag


def test_the_on_your_way_overview_uses_the_same_icon_rows():
    way = INDEX.split("function renderOnWay()", 1)[1].split("function answerMissed", 1)[0]
    assert 'stepItem("destination", "Destination"' in way
    assert 'stepItem("destination", "Destination"' in INDEX.split("function renderJourneyOverview()", 1)[1].split("function priorityDisabled", 1)[0]


# ---- the chips are gone and the select has a style guide sample ---------------------------------------------


def test_the_chip_code_and_css_that_only_served_the_priority_are_gone():
    assert "syncPriorityChips" not in INDEX and 'role="radio"' not in INDEX.split('id="overview-priority"', 1)[1].split("</div>", 1)[0]
    assert '.arrive-chip[aria-disabled="true"]' not in CSS and "radiogroup" not in INDEX.split('id="overview-priority"', 1)[1][:600]
    assert "function sgChips" not in GUIDE and "Priority chips" not in GUIDE and "Priority chips" not in PLAN


def test_the_style_guide_shows_the_select_in_every_state():
    program = GUIDE.split("function sgSelect(", 1)[1].split("function legsSample", 1)[0] + \
        GUIDE.split("function legsSample", 1)[1].split('document.getElementById("legs-sample-light")', 1)[0]
    for needle in ('class=\\"priority-select\\"', 'sgSelect("fastest", [])', 'sgSelect("least_walking", [])',
                   'sgSelect("fastest", ["least_walking", "mrt_only"])', 'sgSelect("mrt_only", [])', "jo.needsRouteService",
                   "Priority select", "sgSummary(63, 3, 12)", "[120, 3, 12]", "[59, 0, 4]"):
        assert needle in program, needle
    for needle in ("jo.summaryAria", "function sgDuration", "function sgSummary"):
        assert needle in GUIDE, needle
    for needle in ():
        assert needle in program, needle
    block = program.split("Journey overview: the title", 1)[1].split("Priority select: Least walking", 1)[0]
    assert "sgReason" not in block and "<label" not in program.split("function sgSelect(", 1)[0][-10:]
    assert block.index("overview-title") < block.index("sgSelect") < block.index("sgSummary") < block.index("journey-steps")


def test_the_select_css_uses_tokens_only_and_is_44_px():
    block = CSS.split(".priority-select {", 1)[1].split("}", 1)[0]
    assert "min-height: var(--tap-min);" in block and "var(--color-line-strong)" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", CSS.split("The priority is a native select", 1)[1].split("/* Style guide: the route lines", 1)[0])

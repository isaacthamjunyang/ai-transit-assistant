"""The Arrive by card: the main line "Arrive by: {estimate}" in heading size and, muted under it, the gap to the target in
words ("12 mins before target"), in the overview, the on-your-way overview and the new-journey overview. Static checks
read the page, copy.js, the style guide and the plan; the browser checks drive the real page (the target and the estimate
are set directly from the page's own Singapore date, so no test reads the time of day). No live API is called."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
NB = " "
ESC = chr(92) + "u00a0"  # how the page and copy.js spell it in source
OLD = ("Target: Arrive by", "Estimate: Arrive by", "targetLine", "estimateLine", "ARRIVE_TARGET_LINE",
       "ARRIVE_ESTIMATE_LINE", "arriveTargetLine", "arriveEstimateLine", "Arrive about", "In 1 hour ·", "Custom ·")


# ---- words and code -----------------------------------------------------------------------------------------


def test_copy_js_and_the_page_carry_the_same_strings():
    block = COPY.split("arriveLine:", 1)[1].split("gapOnTarget:", 1)[0]
    assert 'arriveLine: "Arrive by: {time}"' in COPY
    assert f'gapMinutes: "{{n}}{ESC}mins"' in COPY and f'gapMinuteOne: "1{ESC}min"' in COPY
    assert f'gapHrMins: "{{h}}{ESC}hr {{m}}{ESC}mins"' in COPY and f'gapHrMinOne: "{{h}}{ESC}hr 1{ESC}min"' in COPY
    assert 'gapBefore: "{amount} before target"' in COPY and 'gapAfter: "{amount} after target"' in COPY
    assert 'gapOnTarget: "On target time"' in COPY and block
    for expected in ('var ARRIVE_LINE = "Arrive by: {time}";',
                     f'var ARRIVE_GAP_MINUTES = "{{n}}{ESC}mins";', f'var ARRIVE_GAP_MINUTE_ONE = "1{ESC}min";',
                     f'var ARRIVE_GAP_HR_MINS = "{{h}}{ESC}hr {{m}}{ESC}mins";',
                     f'var ARRIVE_GAP_HR_MIN_ONE = "{{h}}{ESC}hr 1{ESC}min";',
                     'var ARRIVE_GAP_BEFORE = "{amount} before target";', 'var ARRIVE_GAP_AFTER = "{amount} after target";',
                     'var ARRIVE_ON_TARGET = "On target time";'):
        assert expected in INDEX, expected
    # the whole-hour form reuses the existing duration; the shared durations and every other "minutes" string are untouched
    assert f'durationHr: "{{h}}{ESC}hr"' in COPY and f'durationHrMin: "{{h}}{ESC}hr {{m}}{ESC}min"' in COPY
    assert 'late: "about {minutes} min late"' in COPY and "{n}" + ESC + "minutes" not in COPY
    assert "minutes" not in COPY.split("gapMinutes:", 1)[1].split("gapOnTarget:", 1)[0]


def test_the_old_lines_and_their_strings_and_code_are_gone():
    for name, text in (("copy.js", COPY), ("page", INDEX), ("guide", GUIDE)):
        for old in OLD[:-3]:  # the live page's own sentence ("Arrive about") and the presets live elsewhere
            assert old not in text, (name, old)
    card_code = INDEX.split("function renderArriveCard(prefix, iso) {", 1)[1].split("function renderArrivalViews", 1)[0]
    for old in OLD:
        assert old not in card_code, old
    # nothing else used the two strings or their css: the estimate class now holds the muted gap line
    assert "arriveBy.targetLine" not in GUIDE and "arriveBy.estimateLine" not in GUIDE
    assert "color: var(--color-muted);" in CSS.split(".arrive-box__estimate {", 1)[1].split("}", 1)[0]


def test_the_card_is_fed_by_one_function_in_all_three_places():
    assert 'renderArriveCard("overview", overviewEstimateIso)' in INDEX
    assert 'renderArriveCard("on-way", state.estimateIso)' in INDEX
    assert 'renderArriveCard("new-journey", row.estimated_arrival || null)' in INDEX
    helper = INDEX.split("function arriveGapText(iso) {", 1)[1].split("function renderArriveCard", 1)[0]
    assert "clockMinutes(value)" in helper and "singaporeStamp(new Date(iso))" in helper  # the displayed clock minutes
    assert "Date.UTC(" in INDEX.split("function clockMinutes(stamp) {", 1)[1].split("function arriveGapText", 1)[0]  # midnight lives in the date


def test_the_pill_and_the_edit_link_are_where_they_were():
    card = INDEX.split('<p id="overview-arrive-value"', 1)[1].split("</div>", 1)[0]
    ids = ["overview-arrive-estimate", "overview-arrive-note", "overview-arrive-status"]
    positions = [card.index(f'id="{name}"') for name in ids]
    assert positions == sorted(positions)
    assert 'id="overview-arrive-edit"' in INDEX and "Edit</button>" in INDEX
    for text in ("Arrive-by check: On track", "Arrive-by check: Risk of delay", "Arrive-by check: N/A"):
        assert f'"{text}"' in COPY
    status = INDEX.split("function syncOverviewArrive() {", 1)[1].split("// Screen 6", 1)[0]
    assert "journeyComparison.textContent" in status and "/On track/.test(label)" in status
    assert "badge--track" in status and "badge--risk" in status and "badge--na" in status


def test_the_label_markup_and_css_are_gone_and_each_card_is_a_named_group():
    for name, text in (("page", INDEX), ("guide", GUIDE), ("css", CSS)):
        assert "arrive-box__label" not in text, name
    assert INDEX.count('<div class="arrive-box" role="group" aria-label="Arrive by">') == 3
    assert 'role=\\"group\\" aria-label=\\"" + copy.home.arriveBy' in GUIDE
    gap = CSS.split(".arrive-box__estimate {", 1)[1].split("}", 1)[0]
    assert "font-size: 0.875rem;" in gap and "color: var(--color-muted);" in gap
    for tone, token in (("track", "--status-live"), ("risk", "--status-uncertain"), ("na", "--status-no-history")):
        rule = CSS.split(f".arrive-box__estimate--{tone} {{", 1)[1].split("}", 1)[0]
        assert f"color: var({token});" in rule
        assert f"color: var({token});" in CSS.split(".badge--" + {"track": "track", "risk": "risk", "na": "na"}[tone] + " {", 1)[1].split("}", 1)[0]
    assert 'arriveTone()' in INDEX and "arrive-box__estimate--" in INDEX


def test_the_style_guide_shows_before_after_on_target_hours_midnight_next_day_and_no_target():
    samples = GUIDE.split('<h4>Arrive-by box: before the target', 1)[1].split("sgArriveBoxNoTarget()", 1)[0]
    for needle in ("gapMinutes.replace(\"{n}\", \"12\")", "gapMinuteOne", "gapOnTarget", "gapHrMins",
                   "gapHrMinOne", "across midnight", "copy.arriveBy.tomorrow", "durationHr.replace"):
        assert needle in samples, needle
    assert "No target (the main line only, no label)" in GUIDE
    assert "copy.arriveBy.onTrack" in samples and "copy.arriveBy.risk" in samples


def test_the_plan_describes_the_card_and_the_live_page_keeps_its_sentence():
    for text in ("Arrive by: {time}", "{n} mins before target", "{n} mins after target", "1 min",
                 "{h} hr {m} mins before target", "On target time", "across midnight"):
        assert text in PLAN, text
    assert "Target: Arrive by {time}" not in PLAN
    sentence = INDEX.split("function estimateSentence(estimate, withTarget) {", 1)[1].split("function renderArrivalViews", 1)[0]
    assert '"Arrive about "' in sentence and '"Estimated destination arrival about "' in sentence


# ---- the real page --------------------------------------------------------------------------------------------


def _run(tmp_path_factory, name, **config):
    require_edge()
    builders = {"TRANSIT": stub.bus_only, "BUS": stub.bus_only, "RAIL": stub.bus_only}
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode(builders), rail_table=_table()) as base:
        return run_scenario("arrivecard", base, {"name": name, **config}, timeout=300)["result"]


@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)],
                ids=["360-light", "1280-dark"])
def report(request, tmp_path_factory):
    name, width, height, dark = request.param
    return _run(tmp_path_factory, "card" + name, width=width, height=height, dark=dark)


@pytest.mark.parametrize("case,main,gap", [
    ("before", f"Arrive by: 6:18{NB}PM", "12 mins before target"),
    ("beforeOne", f"Arrive by: 6:29{NB}PM", "1 min before target"),
    ("after", f"Arrive by: 6:35{NB}PM", "5 mins after target"),
    ("afterOne", f"Arrive by: 6:31{NB}PM", "1 min after target"),
    ("onTarget", f"Arrive by: 6:30{NB}PM", "On target time"),
    ("hours", f"Arrive by: 5:25{NB}PM", "1 hr 5 mins before target"),
    ("hoursOneMin", f"Arrive by: 5:29{NB}PM", "1 hr 1 min before target"),
    ("hoursWhole", f"Arrive by: 4:30{NB}PM", "2 hr before target"),
    ("hoursAfter", f"Arrive by: 7:45{NB}PM", "1 hr 15 mins after target"),
    ("acrossMidnight", f"Arrive by: 11:55{NB}PM", "10 mins before target"),
    ("acrossMidnightAfter", f"Arrive by: 12:10{NB}AM (tomorrow)", "15 mins after target"),
    ("nextDay", f"Arrive by: 6:18{NB}PM (tomorrow)", "12 mins before target"),
])
def test_each_wording_on_the_overview_card(report, case, main, gap):
    card = report["cases"][case]
    assert card["label"] is None  # no small label above the main line
    assert card["main"].replace(NB, " ") == main.replace(NB, " "), card
    assert card["gap"].replace(NB, " ") == gap, card
    assert card["order"][:2] == ["overview-arrive-value", "overview-arrive-estimate"]


def test_the_time_keeps_its_no_break_space_and_the_amounts_keep_their_units(report):
    assert report["cases"]["before"]["main"] == f"Arrive by: 6:18{NB}PM"
    assert report["cases"]["before"]["gap"] == f"12{NB}mins before target"
    assert report["cases"]["afterOne"]["gap"] == f"1{NB}min after target"
    assert report["cases"]["hours"]["gap"] == f"1{NB}hr 5{NB}mins before target"
    assert report["cases"]["hoursOneMin"]["gap"] == f"1{NB}hr 1{NB}min before target"
    assert report["cases"]["hoursAfter"]["gap"] == f"1{NB}hr 15{NB}mins after target"
    assert report["cases"]["hoursWhole"]["gap"] == f"2{NB}hr before target"


def test_no_target_shows_only_the_main_line_and_no_estimate_shows_no_lines(report):
    card = report["cases"]["noTarget"]
    assert card["main"] == f"Arrive by: 6:18{NB}PM" and card["gap"] is None and card["status"] is None
    assert card["order"] == ["overview-arrive-value"]
    assert report["cases"]["noEstimate"]["main"] is None and report["cases"]["noEstimate"]["gap"] is None
    assert report["cases"]["neither"]["main"] is None and report["cases"]["neither"]["gap"] is None


def test_the_pill_and_the_edit_link_are_unchanged_below_the_lines(report):
    card = report["cases"]["before"]
    assert card["status"] == "Arrive-by check: On track"
    assert card["order"][-1] == "badge arrive-box__status badge--track" or card["order"][-1] == "overview-arrive-status"
    assert card["order"].index("overview-arrive-estimate") < card["order"].index("overview-arrive-status")
    assert card["editVisible"] is True


def test_the_main_line_is_heading_size_and_the_gap_is_one_step_smaller(report):
    card = report["cases"]["before"]
    assert card["mainSize"] == 18.0 and card["gapSize"] == 14.0  # 1.125 rem and 0.875 rem; the gap was 0.75 rem (12 px)
    assert card["gapSize"] < card["mainSize"]
    assert card["inlineStyles"] == 0 and card["scrollWidth"] <= card["innerWidth"]


def _rgb(text):
    return [int(v) for v in re.findall(r"\d+", text)[:3]]


def _luminance(rgb):
    channels = [v / 255 for v in rgb]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground, background):
    high, low = sorted((_luminance(_rgb(foreground)), _luminance(_rgb(background))), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("case,tone", [("before", "track"), ("onTarget", "track"), ("after", "risk"),
                                       ("afterOne", "risk"), ("notAvailable", "na")])
def test_the_gap_colour_follows_the_pill_state_and_reads_on_the_card(report, case, tone):
    card = report["cases"][case]
    assert f"arrive-box__estimate--{tone}" in card["gapClass"], card["gapClass"]
    assert card["gapColour"] == card["pillColour"], card  # the pill's own text token
    assert _contrast(card["gapColour"], card["boxBackground"]) >= 4.5, (card["gapColour"], card["boxBackground"])
    assert "before target" in (card["gap"] or "") or "after target" in (card["gap"] or "") or card["gap"] == "On target time"


def test_the_three_states_have_three_different_colours(report):
    colours = {report["cases"][name]["gapColour"] for name in ("before", "after", "notAvailable")}
    assert len(colours) == 3
    assert report["cases"]["noTarget"]["gap"] is None  # no target: no gap line at all


def test_the_label_is_gone_and_the_card_still_has_its_icon_edit_link_and_name(report):
    card = report["cases"]["before"]
    assert card["label"] is None and "Arrive by" not in (card["visibleText"] or "").replace("Arrive by:", "")
    assert card["role"] == "group" and card["name"] == "Arrive by"
    assert card["iconShown"] is True and card["editVisible"] is True


def test_the_on_your_way_and_new_journey_cards_show_the_same_two_lines(report):
    main, gap = f"Arrive by: 6:18{NB}PM (tomorrow)", f"12{NB}mins before target"
    other = report["other"]
    for card in ("onWay", "newJourney"):
        assert other["withTarget"][card] == {"main": main, "gap": gap}, card
        assert other["noTarget"][card] == {"main": main, "gap": None}, card


def test_no_old_wording_appears_in_any_case(report):
    for case in report["cases"].values():
        for text in (case["main"] or "", case["gap"] or ""):
            for old in ("Target:", "Estimate:", "Arrive about", "Estimated destination arrival", "In 1 hour", "Custom"):
                assert old not in text, (text, old)

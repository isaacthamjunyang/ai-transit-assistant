"""Page A, standardised: the Arrive by card's gap pill is the check pill's component, the check pill is gone from above the
AI card, the removed lines and strings are absent, the probability card heading is the overview's row (bus and MRT), and
the pace chip, both tiles, the AI card and the sticky button are always there. No live API is called."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
PY = {name: (ROOT / name).read_text(encoding="utf-8") for name in ("reroute.py", "main.py", "explain.py", "rail_arrivals.py")}

THRESHOLD = ("Primary bus target has low catch probability", "improvement threshold")
REMOVED_PAGE_STRINGS = (
    "If you catch this bus", "Train times are scheduled, not live.", "if you leave now and keep walking",
    "if you leave now and walk at your usual pace",
)


def _function(name: str) -> str:
    return INDEX.split(f"function {name}(", 1)[1].split("\n    }\n", 1)[0]


# ---- static -------------------------------------------------------------------------------------------------


def test_the_gap_is_the_check_pill_component_in_all_three_cards():
    for prefix in ("overview", "on-way", "new-journey"):
        assert f'<p id="{prefix}-arrive-estimate" class="badge arrive-box__status badge--na" hidden></p>' in INDEX
    assert 'gap.className = "badge arrive-box__status badge--" + arriveTone();' in INDEX
    assert "arrive-box__estimate" not in INDEX + CSS + GUIDE
    # state colours are the same tokens as the check pill, text-safe on their own tints
    for tone, token in (("track", "--status-live"), ("risk", "--status-uncertain"), ("na", "--status-no-history")):
        assert f"color: var({token});" in CSS.split(f".badge--{tone} {{", 1)[1].split("}", 1)[0]


def test_no_catch_pill_above_the_ai_card_and_no_miss_row_or_on_track_line_on_page_a():
    card = INDEX.split('<section id="ai-explanation"', 1)[1].split("</section>", 1)[0]
    assert "badge" not in card.split('class="ai-card__head"', 1)[0]
    for gone in ('id="ai-badge"', 'id="tile-row"', 'id="tile-status"', 'id="tile-note"', 'id="if-you-miss"', "IF_CATCH_PREFIX",
                 "function renderMiss", "function showMiss(", "latePhrase"):
        assert gone not in INDEX, gone
    for gone in ("ai-card__badge", "tile-status", "leave-tiles__row", "miss-row", "arrive-box__estimate", "catch-card__not-live"):
        assert gone not in CSS, gone
    for text in REMOVED_PAGE_STRINGS:
        assert text not in INDEX, text
    for key in ("ifCatchPrefix", "missLabel", "missWithLate", "missNoSpare", "missWait", "trainMiss", "trainNotLive",
                "captionCurrentPace", "captionUsualPace", "noBetter"):
        assert key not in COPY, key
    assert "notLive:" not in COPY.split("trainPage: {", 1)[1].split("\n  },", 1)[0]


def test_the_on_track_sentence_is_not_drawn_on_page_a():
    tiles = _function("renderLeaveTiles")
    assert "journeyNote" not in tiles and "journeyComparison" not in tiles
    assert 'id="tile-note"' not in INDEX


def test_page_a_card_has_no_subtitle_caption_not_live_or_bus_arrives_label():
    card = INDEX.split('id="arrival-card"', 1)[1].split('id="pace-slot"', 1)[0]
    for gone in ('id="catch-sub', 'id="catch-caption"', "catch-not-live", "catch-card__arrives-label", "Bus arrives", "Train departs"):
        assert gone not in card, gone
    assert 'id="catch-arrives-time"' in card and 'id="catch-line"' in card and 'id="catch-when"' in card
    assert 'id="catch-pill"' in card.split('id="catch-line"', 1)[1].split("</p>", 1)[0]  # the pill is in the heading row
    # the walking-pace button and its card stay as they were
    assert 'id="walk-open"' in card and 'id="catch-pace-line"' in card


def test_the_heading_reuses_the_overview_row_components():
    heading = _function("renderCatchHeading")
    assert "lineRow(leg)" in heading and "busRow(busLeg, null)" in heading
    assert "journey-step--rail-" in heading and "LINE_BADGE_CODES" in heading
    assert "railWhenText(hero)" in heading and "etaParts(hero)" in heading
    rail = _function("railWhenText")
    assert "JO_SCHEDULED_NOW" in rail and "JO_SCHEDULED_IN_ONE" in rail and "JO_SCHEDULED_IN," in rail
    assert 'var JO_SCHEDULED_IN = "Scheduled · In {n}\\u00a0min";' in INDEX
    css = CSS.split(".catch-card__leg {", 1)[1].split(".catch-card__when[hidden]", 1)[0]
    assert "var(--leg-ring, var(--ring-neutral))" in css  # grey for a bus, the line colour from journey-step--rail-xx
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", css)


def test_the_pace_chip_neutral_state_is_in_copy_and_the_page():
    assert 'neutral: {\n      title: "Walking pace"' in COPY.replace("\r\n", "\n")
    assert "detail:" not in COPY.split("pace: {", 1)[1].split("\n  },", 1)[0]
    assert 'neutral: { title: "Walking pace" }' in INDEX
    assert "detail:" not in INDEX.split("var PACE_TEXT = {", 1)[1].split("};", 1)[0]
    assert 'neutral: "badge badge--no-history"' in INDEX


def test_no_threshold_sentence_is_emitted_or_drawn_anywhere():
    for name, text in {**PY, "page": INDEX, "copy.js": COPY, "guide": GUIDE}.items():
        for phrase in THRESHOLD:
            assert phrase not in text, (name, phrase)
    assert "no_better_option" not in PY["reroute.py"] + PY["main.py"] + INDEX
    assert "NO_BETTER_OPTION" not in PY["reroute.py"] and "POST_REROUTE_NO_BETTER" not in PY["reroute.py"]
    # where options were asked for and none exist the page says the one plain sentence
    assert "unlikelyEntry && !hasOptions" in _function("renderPageC") and "NO_OTHER_OPTIONS" in _function("renderPageC")


def test_the_plan_no_longer_carries_the_removed_wording():
    for gone in ("If you catch this bus: ` when", "spare line and Step 9 badge, If you miss it", "`train.trainMiss`",
                 "The pace chip shows only while the action is `leave_now`",
                 "`Primary bus target has low catch probability ({point}%), but no better direct alternative meets the 15%"):
        assert gone not in PLAN, gone
    for needle in ("Scheduled", "Walking pace", "pace chip is on Page A in every", "no no-better-option sentence"):
        assert needle in PLAN, needle


def test_the_style_guide_shows_bus_and_mrt_headings_the_neutral_chip_and_the_pill_gap():
    assert "function sgCatchHead(" in GUIDE and 'sgCatchCard("schedule", 64, 51, 78, undefined, undefined, undefined, "train")' in GUIDE
    assert 'sgPaceChip("neutral")' in GUIDE
    assert 'class=\\"badge badge--" + tone + " arrive-box__status\\"' in GUIDE
    assert "ai-card__badge" not in GUIDE and "miss-row" not in GUIDE


# ---- browser: the real page, bus first -----------------------------------------------------------------------

VIEWPORTS = [("l360", 360, 800, False), ("d1280", 1280, 900, True)]


@pytest.fixture(scope="module", params=VIEWPORTS, ids=["360-light", "1280-dark"])
def states(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    out = {}
    with running_app(tmp_path_factory.mktemp("a" + name), eta_minutes=[10.3]) as base:
        out.update(run_scenario("pageastd", base, {"name": name, "width": width, "height": height, "dark": dark,
                                                    "steps": [["far", 60], ["atStop", 12]]}, timeout=300)["result"])
    with running_app(tmp_path_factory.mktemp("b" + name), eta_minutes=[3.0]) as base:
        out.update({"low": run_scenario("pageastd", base, {"name": name + "low", "width": width, "height": height, "dark": dark,
                                                           "steps": [["low", 1500]]}, timeout=300)["result"]["low"]})
    return out


def _always_there(state, at_stop=False):
    assert state["top"] == "live" and state["pageA"] is True, (state["top"], state["classes"], state["pageCOpen"], state["entryPending"], state["missed"])
    assert state["ai"], "the AI Explanation is on Page A"
    assert state["tileLeave"] is True and state["tileArrival"] is False  # no destination arrival on Page A
    assert state["tileLeaveValue"]
    assert "Estimated destination arrival" not in state["body"] and "Worked out from" not in state["body"]
    assert state["chipHint"] is False and state["aiNote"] is False  # no grey helper text under the chip or the card
    geo = state["geo"]
    tile, tiles = geo["tile"], geo["tiles"]
    assert abs(tile["w"] - tiles["w"]) < 1.5 and abs(tile["x"] - tiles["x"]) < 1.5, geo  # Leave by is the full width
    assert geo["ring"]["w"] >= 96 and abs(geo["ring"]["w"] - geo["ring"]["h"]) < 1  # the ring keeps at least 96 px
    assert geo["ring"]["r"] <= geo["leg"]["x"] + 1, geo  # the heading is at the right of the ring
    assert geo["arrives"]["y"] >= geo["leg"]["b"] - 1 and abs(geo["arrives"]["x"] - geo["leg"]["x"]) < 1.5, geo
    assert state["bar"] == "See bus arrival times"
    if at_stop:
        assert state["tileLeaveValue"] == "At the stop" and state["tileLeaveWalk"] is None
    else:
        assert re.fullmatch(r"\d+ min walk", (state["tileLeaveWalk"] or "").replace(" ", " ")), state["tileLeaveWalk"]
    if at_stop:
        assert state["chip"] is None  # hidden inside 30 m only
    else:
        assert state["chip"], "the pace chip is on Page A"
    assert state["scrollWidth"] <= state["innerWidth"]
    for phrase in THRESHOLD:
        assert phrase not in state["body"]
    assert state["aiBadge"] is False and state["missRow"] is False
    assert "Estimated destination arrival is at or before" not in state["body"]
    assert "If you miss it" not in state["body"] and "If you catch this bus" not in state["body"]


def test_far_from_the_stop_everything_is_there_and_the_heading_is_the_bus_row(states):
    far = states["far"]
    _always_there(far)
    assert far["badgeIsBus"] is True and "18" in far["line"]
    assert re.fullmatch(r"Arriving in \d+ min|Arriving in <1 min|Arriving now", far["when"].replace(" ", " ")), far["when"]
    assert far["pill"] in ("live", "schedule only")
    assert far["hasSub"] is False and far["hasCaption"] is False and far["hasLabel"] is False
    assert re.fullmatch(r"\d{1,2}:\d{2} [AP]M( \(tomorrow\))?", far["arrives"])
    assert "journey-step--rail" not in far["legClass"]


def test_at_the_stop_97_percent_keeps_everything_but_the_chip(states):
    stop = states["atStop"]
    assert stop["atStop"] is True and stop["point"] == 97 and stop["ring"] == "97%"
    _always_there(stop, at_stop=True)


def test_at_a_low_probability_every_element_stays_and_the_unlikely_banner_shows(states):
    low = states["low"]
    assert low["point"] <= 40 and low["band"] == "low", low["point"]
    _always_there(low)
    assert low["banner"] is True


# ---- browser: a train first, the heading is the line row ---------------------------------------------------------
# (the train page's own scenario already reads line, when and the ring colour; see tests/test_train_pages.py)

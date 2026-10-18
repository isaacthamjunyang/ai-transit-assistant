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


def test_the_gap_is_the_check_alert_component_in_all_three_cards():
    for prefix in ("overview", "on-way", "new-journey"):
        assert f'<div id="{prefix}-arrive-estimate" class="alert alert--neutral" hidden>' in INDEX
    assert "setAlertKind(gap, ARRIVE_ALERT_KIND[arriveTone()]);" in INDEX
    assert "arrive-box__estimate" not in INDEX + CSS + GUIDE
    # state colours are the same tokens as the check pill, text-safe on their own tints
    for kind, token in (("success", "--status-live"), ("warning", "--status-uncertain"), ("neutral", "--status-no-history")):
        assert f"--alert-ink: var({token});" in CSS.split(f".alert--{kind} {{", 1)[1].split("}", 1)[0]


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
    card = INDEX.split('id="arrival-card"', 1)[1].split("</section>", 1)[0]
    for gone in ('id="catch-caption"', "catch-not-live", "catch-card__arrives-label", "Bus arrives", "Train departs"):
        assert gone not in card, gone
    assert 'id="catch-arrives-time"' in card and 'id="catch-line"' in card and 'id="catch-to"' in card
    assert 'id="catch-when"' not in card and "Arriving in" not in card and "Scheduled ·" not in card
    # Layout B, top down: the line row, "To {place}", the muted line (a train), the clock time, the pill, the crowding label
    order = [card.index(f'id="{name}"') for name in ("catch-line", "catch-to", "catch-sub", "catch-arrives",
                                                     "catch-pill", "catch-load")]
    assert order == sorted(order), order
    # the button that opens Page W stays; its pace subtitle is gone
    assert 'id="walk-open"' in INDEX and 'id="catch-pace-line"' not in INDEX


def test_the_heading_is_built_from_the_badges_and_the_rows_top_down():
    heading = _function("renderCatchHeading")
    assert "lineBadge(" in heading and "busBadge(" in heading and "JO_TOWARD" in heading
    assert "destinationStopName()" in heading and "busLeg.headsign" in heading  # the destination stop, else the terminus
    assert "JO_CLOCKWISE" in heading and "JO_ANTICLOCKWISE" in heading and "JO_PLATFORM_ONLY" in heading
    assert "trainLineName()" in heading  # the line's name beside its badge
    assert "railWhenText" not in heading and "etaParts" not in heading and "catch-when" not in heading
    assert "journey-step--rail-" in heading and "LINE_BADGE_CODES" in heading
    css = CSS.split(".catch-card__leg {", 1)[1].split(".catch-card__when[hidden]", 1)[0]
    assert "var(--leg-ring, var(--ring-neutral))" in css  # grey for a bus, the line colour from journey-step--rail-xx
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", css)


def test_the_largest_text_is_the_badge_the_place_and_the_clock_and_the_rest_is_smaller():
    def size(selector):
        block = CSS.split(selector + " {", 1)[1].split("}", 1)[0]
        return float(re.search(r"font-size:\s*([0-9.]+)rem", block).group(1))
    # Layout B: the clock time is the largest (26 px), "To {place}" 21 px, the badge 18 px; the rest is smaller
    assert size(".catch-card__copy .catch-card__arrives-time") == 1.625 and size(".catch-card__to") == 1.3125
    assert size(".catch-card__line .line-badge") == 1.125
    assert size(".catch-card__sub-line") < 1.125 and size(".crowd-chip") < 1.125
    # the walk minutes are the second line of the pace alert: the shared alert's meta line, bold like the alert text
    meta = CSS.split(".pace-slot .alert__meta {", 1)[1].split("}", 1)[0]
    assert "font-weight: 700;" in meta and "font-size: 0.9375rem;" in meta  # 15 px, bold


def test_the_leave_by_tile_is_one_line_with_the_label_only_before_a_time():
    tiles = _function("renderLeaveTiles")
    assert "tile-leave-detail" not in INDEX and "leaveMeta" not in tiles
    assert 'id="tile-leave-line"' in INDEX and 'role="group" aria-label="Leave by"' in INDEX
    assert 'tileView.mode === "by"' in tiles and 'var LEAVE_BY_LABEL = "Leave by:";' in INDEX
    assert 'id="pace-walk"' not in INDEX  # built inside the pace card, not a static element beside it
    chip = _function("paceChip")
    assert 'walk.id = "pace-walk";' in chip and 'chip.querySelector(".alert__body").appendChild(walk);' in chip
    assert 'leaveByLabel: "Leave by:"' in COPY and 'paceWalk: "{n}\\u00a0min walk"' in COPY
    assert 'var PACE_WALK_TEXT = "{n}\\u00a0min walk";' in INDEX
    walk = _function("syncPaceWalk")
    assert "lastExplanationPack" in walk and "pack.walk_minutes" in walk and "pack.at_stop" in walk and "slot.hidden" in walk


def test_the_pace_chip_neutral_state_is_in_copy_and_the_page():
    assert 'neutral: {\n      title: "Walking pace"' in COPY.replace("\r\n", "\n")
    assert "detail:" not in COPY.split("pace: {", 1)[1].split("\n  },", 1)[0]
    assert 'neutral: { title: "Walking pace" }' in INDEX
    assert "detail:" not in INDEX.split("var PACE_TEXT = {", 1)[1].split("};", 1)[0]
    assert 'neutral: "neutral"' in INDEX.split("var PACE_ALERT_KIND = {", 1)[1].split("};", 1)[0]


def test_no_threshold_sentence_is_emitted_or_drawn_anywhere():
    for name, text in {**PY, "page": INDEX, "copy.js": COPY, "guide": GUIDE}.items():
        for phrase in THRESHOLD:
            assert phrase not in text, (name, phrase)
    assert "no_better_option" not in PY["reroute.py"] + PY["main.py"] + INDEX
    assert "NO_BETTER_OPTION" not in PY["reroute.py"] and "POST_REROUTE_NO_BETTER" not in PY["reroute.py"]
    # where options were asked for and none exist the page says the one plain sentence
    assert 'noOptionsState() === "missed"' in _function("renderPageC") and "NO_OTHER_OPTIONS" in _function("renderPageC")


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
    assert 'sgAlert("neutral", gap)' in GUIDE
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
    # the heading column, top down, all at the right of the ring: the line row, "To {place}", the clock, the pill
    assert geo["line"]["y"] < geo["to"]["y"] < geo["arrives"]["y"] < geo["pill"]["y"], geo
    assert geo["arrives"]["x"] >= geo["leg"]["x"] and geo["arrives"]["r"] <= geo["card"]["r"] + 1, geo
    assert state["bar"] == "See bus arrival times"
    assert state["tileLeaveName"] == "Leave by"  # the tile's accessible name in every state
    assert "walk" not in state["tileLeaveLine"]  # no walk line inside the tile
    if at_stop:
        # alone, no label; the chip and its walk line are hidden together
        assert state["tileLeaveValue"] == "At the stop" and state["tileLeaveLabelShown"] is False
        assert state["tileLeaveLine"] == "At the stop"
        assert state["tileLeaveWalk"] is None and state["chip"] is None and state["walkLine"] is None
    else:
        assert state["chip"], "the pace chip is on Page A"
        assert re.fullmatch(r"\d+\u00a0min walk", state["walkLine"] or ""), state["walkLine"]
        # inside the pace card: within its box, below the pace label, nothing under the card
        assert geo["paceWalk"]["y"] >= geo["chipBox"]["y"] and geo["paceWalk"]["b"] <= geo["chipBox"]["b"] + 1
        assert geo["paceWalk"]["r"] <= geo["chipBox"]["r"] + 1
        if state["tileLeaveValue"] == "Leave now":
            assert state["tileLeaveLabelShown"] is False and state["tileLeaveLine"] == "Leave now"
        else:
            assert state["tileLeaveLabelShown"] is True
            assert state["tileLeaveLine"].startswith("Leave by: "), state["tileLeaveLine"]
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
    assert far["to"].startswith("To ") and far["direction"] is None  # a bus has no direction row
    assert "Arriving in" not in far["body"] and "Scheduled \u00b7" not in far["body"]
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
    assert low["point"] == 5 and low["band"] == "low", low["point"]
    _always_there(low)
    assert low["banner"] is True


# ---- browser: a train first, the heading is the line row ---------------------------------------------------------
# (the train page's own scenario already reads line, when and the ring colour; see tests/test_train_pages.py)


# ---- the probability card, the banner and the two bottom buttons ------------------------------------------------------------


def test_the_caption_is_gone_everywhere_and_the_ring_is_about_40_percent_of_the_card(states):
    caption = "if you leave now and walk at a normal pace"
    root = Path(__file__).resolve().parents[1]
    for name in ("static/index.html", "static/copy.js", "static/styleguide.html", "PROJECT_PLAN.md", "static/components.css"):
        assert caption not in (root / name).read_text(encoding="utf-8"), name
    assert "catch-card__caption" not in (root / "static" / "components.css").read_text(encoding="utf-8")
    for key in ("far", "atStop", "low"):
        state = states[key]
        assert state["captionAnywhere"] is False and state["hasLabel"] is False, key  # no caption and no "Bus arrives" label
        ring, card = state["geo"]["ring"], state["geo"]["card"]
        assert 96 <= ring["w"] <= 0.42 * (card["w"] - 2 * 16) + 1, (key, ring["w"], card["w"])  # about 40% at 360 px, capped at 7.5rem
        assert state["hasSub"] is False  # no "Arriving in N min" line under the badge on a bus


def test_the_unlikely_banner_is_the_shared_alert_with_just_the_sentence(states):
    low = states["low"]
    assert low["banner"] is True and low["bannerText"] == "Catching this bus is unlikely." and low["bannerIsAlert"] is True
    assert low["bannerExtras"] == 0  # no probability line and no button inside it
    assert "Here are your other options" not in (low["bannerText"] or "")
    for key in ("far", "atStop"):
        assert states[key]["banner"] is False


def test_both_buttons_are_stacked_full_width_in_the_sticky_bar_at_every_probability(states):
    for key in ("far", "atStop", "low"):
        b = states[key]["buttons"]
        assert b["seeText"] == "See bus arrival times" and b["otherShown"] is True and b["otherText"] == "Other bus options", key
        see, other, bar = b["see"], b["other"], b["bar"]
        assert abs(see["w"] - other["w"]) <= 1 and other["top"] >= see["bottom"] - 0.5, key  # full width, stacked
        assert see["h"] >= 44 and other["h"] >= 44, key
        assert bar["h"] <= 0.25 * b["innerHeight"] and bar["bottom"] >= b["innerHeight"] - 1, key  # the sticky bar at the bottom
        assert b["padding"] >= bar["h"], key  # the page leaves room under it: nothing is covered


def test_neither_bottom_button_pulses_and_other_bus_options_is_the_same_blue_with_an_arrow(states):
    for key in ("far", "atStop", "low"):
        b = states[key]["buttons"]
        assert b["pulse"] is False and b["anims"] == 0 and b["otherPulse"] is False and b["otherAnims"] == 0, key  # no pulse on either
        see, other = b["see"], b["other"]
        for field in ("background", "color", "radius", "borderWidth", "weight"):
            assert see[field] == other[field], (key, field)  # the same blue, text colour and radius
        assert other["h"] >= 44 and b["otherArrow"] is True and b["seeArrow"] is True, key
        assert 8 <= b["other"]["top"] - b["see"]["bottom"] <= 12, key  # an 8 to 12 px gap


@pytest.fixture(scope="module")
def other(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("other"), eta_minutes=[10.3]) as base:
        return run_scenario("pageastd", base, {"name": "other", "width": 360, "height": 800, "dark": False,
                                               "steps": [["far", 60]], "openOther": True}, timeout=300)["result"]


def test_other_bus_options_opens_page_c_with_its_own_notice_and_keeps_tracking(other):
    result = other["other"]
    assert result["entry"] == "other" and result["missed"] is False and result["bodyMissed"] is False
    assert result["pageCShown"] is True and result["top"] == "live"  # Page C is a view of the live screen
    assert result["notice"] in ("Here are your other options.", "No other buses or routes are available right now.")
    assert result["tracking"] is True and result["barDrawn"] is False  # tracking goes on; Page C draws no bottom bar
    back = other["afterBack"]  # Back goes to Page A with tracking kept, and asks nothing
    assert back["top"] == "live" and back["pageC"] is False and back["pageA"] is True and back["tracking"] is True
    assert back["dialog"] is False and back["barDrawn"] is True


def test_other_bus_options_is_in_the_blue_class_chain_and_not_in_the_train_bar():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    block = html.split('id="see-arrivals-bar"', 1)[1].split("</div>\n  </div>", 1)[0]
    assert '<div id="other-bus-actions" class="other-bus-actions">' in block
    assert '<button type="button" id="other-bus-options" class="primary primary--icon"><span>Other bus options</span><svg' in block
    assert "pulse-button" not in block  # neither button of the bar pulses
    assert 'document.getElementById("other-bus-actions").hidden = isTrain() || !document.body.classList.contains("is-page-a");' in html
    handler = html.split('getElementById("other-bus-options").addEventListener', 1)[1].split("});", 1)[0]
    assert 'openPageC("other")' in handler and "answerMissed" not in handler and "endedKind" in handler and "isTrain()" in handler
    plan = (root / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    for text in ("`Other bus options`", "`See bus arrival times`", "Catching this bus is unlikely."):
        assert text in plan, text
    assert b"\r\n" in (root / "PROJECT_PLAN.md").read_bytes()


def _rgb_text(value):
    value = value.strip()
    if value.startswith("#"):
        value = value.lstrip("#")
        return "rgb(%d, %d, %d)" % tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    return value


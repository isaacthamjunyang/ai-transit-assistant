"""Screens 7 and 8: catch probability, leave-by tiles, AI card, and the tap-to-switch reroute proposal."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import explain
import reroute

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
COPY = ROOT / "static" / "copy.js"
SGT = timezone(timedelta(hours=8))


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_duplicates_are_gone_and_needed_ids_stay():
    html = _page()
    for gone in ('id="catch-chance-heading"', 'id="primary-bus"', 'id="close-arrivals"', "Can I catch it?",
                 "function appendScore", "function appendHeroPoint", "function appendCatchMeter", "function heroRoute"):
        assert gone not in html
    for kept in ("arrival-card", "arrival-heading", "arrival-status", "arrival-warning", "arrival-list", "arrival-updated",
                 "quality-banner", "stale-status", "location-card", "leave-now-banner", "if-you-miss", "leave-by-section", "journey-comparison", "journey-leave-countdown",
                 "reroute-block", "reroute-card", "reroute-title", "reroute-none", "ai-explanation", "ai-explanation-status",
                 "ai-explanation-text", "notification-panel",
                 "catch-warning", "live-tracking"):
        assert html.count('id="%s"' % kept) == 1, kept
    slot = _between(html, 'id="alert-slot"', 'id="arrival-card"')
    for occupant in ("quality-banner", "stale-status", "location-card", "leave-now-banner", "reroute-block",
                     "catch-warning", "notification-panel"):
        assert 'id="%s"' % occupant in slot


def test_ring_label_always_carries_the_range_with_the_point():
    html = _page()
    text = _between(html, "function probabilityText(chance)", "function setRing")
    assert '"Catch probability: " + chance.point + "% (range " + chance.range_low + "–" + chance.range_high + "%)"' in text
    ring = _between(html, "function setRing(id, chance, emptyText)", "function setPillState")
    assert 'box.setAttribute("aria-label", ringLabel(chance,' in ring  # names the bus, its arrival and the stop
    label = _between(html, "function ringLabel(chance, hero)", "function ")
    assert "a: chance.range_low" in label and "b: chance.range_high" in label  # the range always travels with the point
    assert "{p} percent chance of catching Bus {service}{eta}{at}, range {a} to {b} percent" in html
    assert 'value.setAttribute("stroke-dasharray"' in ring
    assert ".style" not in ring
    card = _between(html, "function renderCatchCard(hero)", "function renderLeaveTiles")
    assert 'typeof chance.range_low === "number" && typeof chance.range_high === "number"' in card
    assert "!displayFrozen && chance" in card
    markup = _between(html, 'id="arrival-card"', "</section>")
    assert 'aria-live="polite"' in _between(html, '<section class="card catch-card" id="arrival-card"', ">")
    assert 'id="catch-ring" class="prob-ring" role="img"' in markup
    assert "if you leave now and walk at a normal pace" in markup


def test_no_new_probability_text_without_its_range():
    html = _page()
    block = _between(html, "// Screen 7: probability card", "function startDemoControls")
    # The ring's centre text is the one exception: setRing sets the range-bearing aria-label beside it,
    # and the card shows "Range: low – high%" next to the ring.
    ring = _between(block, "function setRing(id, chance, emptyText)", "function setPillState")
    assert ring.index('chance.point + "%"') < ring.index("ringLabel(chance")
    block = block.replace(ring, "")
    mini = _between(block, "function buildProbRing(chance)", "function badgePills")
    assert mini.index('chance.point + "%"') > mini.index("probabilityText(chance)")
    block = block.replace(mini, "")
    for match in re.finditer(r'\.point \+ "%', block):
        window = block[match.start(): match.start() + 140]
        assert "range" in window, window


def test_tiles_mirror_existing_values():
    html = _page()
    tiles = _between(html, "function renderLeaveTiles()", "// Screen 8")
    # The Leave by tile reads the leave rule: a clock time or "Leave now", never both (leaveTileView).
    assert "formatClock(lastSuccess.leave_by, true)" not in tiles
    assert "leaveTileView(" in tiles and "trackedAction(lastSuccess)" in tiles and "WAIT_ALERT_TEXT" not in tiles
    assert 'action === "switch_route" || action === "do_not_rely"' in tiles
    assert "formatRange(estimate.arrival_low, estimate.arrival_high)" in tiles
    assert "journey-spare" not in tiles and "tile-spare" not in tiles  # the spare line is gone
    assert "journeyComparison.textContent" in tiles
    assert "journeyNote.textContent" in tiles
    views = _between(html, "function renderArrivalViews(estimate)", "function showMiss")
    assert "lastTileEstimate = " in views
    markup = _between(html, 'id="leave-tiles"', "</section>")
    assert "Estimated arrival" in markup and ">Arrive by<" not in markup


def test_ai_flag_defaults_on_and_the_card_is_never_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_EXPLANATION_ENABLED", raising=False)
    blank = tmp_path / ".env"
    blank.write_text("AI_EXPLANATION_ENABLED=\n", encoding="utf-8")
    assert explain.ai_explanation_enabled(blank) is True
    off = tmp_path / "off.env"
    off.write_text("AI_EXPLANATION_ENABLED=false\n", encoding="utf-8")
    assert explain.ai_explanation_enabled(off) is False
    assert "AI_EXPLANATION_ENABLED=true" in (ROOT / ".env.example").read_text(encoding="utf-8")
    html = _page()
    assert "var AI_EXPLANATION_ENABLED = true;" in html
    begin = _between(html, "function beginExplanation(pack)", "function syncExplanation")
    assert "headline" not in begin and "reasoning" not in begin  # the schema has one field, the clause
    assert 'JSON.stringify({ fact_sheet: pack.fact_sheet, snapshot: pack.snapshot })' in begin
    assert "body.snapshot !== lastExplanationPack.snapshot" in begin  # a reply for an older poll is dropped
    sync = _between(html, "function syncExplanation(body)", "function notifyReroute")
    assert "renderExplanation({ text: pack.text" in sync  # the text is shown on every poll, so the card is never empty
    assert "Probabilities come from the app's own calculation. AI only explains them." in html


def test_reroute_is_a_pending_proposal_until_the_tap():
    html = _page()
    success = _between(html, "function applySuccess(body)", "function applyRouteSwitch")
    # A poll no longer renders a proposal: the compact banner (or Page C) replaces it. The pending notification stays.
    assert "showRerouteProposal" not in html and "renderRerouteProposal" not in html
    assert "notifyPendingReroute(proposal)" in success and "resolveEntry(body)" in success
    assert "applyRouteSwitch" not in success
    # Switch and a row tap only open the new-journey overview; nothing changes until Start journey.
    card_switch = _between(html, "function buildSwitchButton(row)", "function buildOptionCard")
    assert "openNewJourney(row)" in card_switch and "applyRouteSwitch" not in card_switch
    open_fn = _between(html, "function openNewJourney(row)", "function renderNewJourney")
    assert "applyRouteSwitch" not in open_fn and 'pushScreen("newjourney")' in open_fn
    row_fn = _between(html, "function buildOptionRow(row)", "function renderPageC()")
    assert "openNewJourney(row)" in row_fn and "applyRouteSwitch" not in row_fn
    finish = _between(html, "function finishNewJourney(row)", "function startNewJourney")
    assert "applyRouteSwitch(decision)" in finish
    assert finish.index("clearRerouteProposal()") < finish.index("applyRouteSwitch(decision)")
    frozen = _between(html, "function freezeStale()", "function refreshDisplay")
    assert "clearRerouteProposal()" in frozen
    switch = _between(html, "function applyRouteSwitch(decision)", "function highlightBoardingSelection")
    for effect in ("lastRerouteAt = new Date().toISOString()", "pinnedEtaTimestamp", "renderRerouteCard(reroute)",
                   "notifyReroute(reroute)", "clearLeaveNowState()", "startMonitoring(reroute.service_no)"):
        assert effect in switch
    card = _between(html, "function buildOptionCard(kind, row)", "function buildOptionRow")
    assert "buildSwitchButton(row)" in card and "option-merged" in card


def test_pending_wording_for_the_notification_stays_and_the_old_fallback_sentences_are_gone():
    html = _page()
    copy = COPY.read_text(encoding="utf-8")
    for text in ("A better option is available. Open the app to switch.", "Better option — Bus {new_service}",
                 "You're unlikely to catch Bus {service}"):
        assert text in html and text in copy
    for gone in ("Tap Switch to change bus", "Route updated to an alternate service.", "pendingWording", "SWITCHED_ADVICE",
                 "action_advice_text", "actionAdvice"):
        assert gone not in html and gone not in copy, gone
    notify = _between(html, "function notifyPendingReroute(reroute)", "function scoreOf")
    assert "PENDING_NOTIFICATION_TITLE" in notify and "PENDING_NOTIFICATION_BODY" in notify
    assert "new Notification(reroute.notification_title, { body: reroute.notification_body })" in html


def test_option_rows_are_buttons_that_carry_a_range():
    html = _page()
    row = _between(html, "function buildOptionRow(row)", "function renderPageC()")
    assert 'createElement("button")' in row and "alt-row__hit" in row
    assert "CHANCE_TEXT" in row and "CHANCE_RANGE_TEXT" in row  # "{point}% chance" and "(range {low}–{high}%)"
    assert "formatDistance(row.distance_m)" in row and "WALK_TO_TEXT" in row
    assert "AT_YOUR_STOP_TEXT" in row and "REACH_DESTINATION_TEXT" in row and "AFTER_TARGET_TEXT" in row
    assert "Next Bus" not in row
    assert "PACE_TEXT.unlikely.title" in row and "WARN_SVG_SMALL" in row
    shown = _between(html, "function renderPageC()", "function updatePageCUpdated")
    assert "OPTIONS_VISIBLE" in shown and "Show more" in shown and "OTHER_BUSES_HEADING" in shown
    assert "var OPTIONS_VISIBLE = 6;" in html

    class Cache:
        def stop_by_code(self, code):
            return {"Latitude": 1.30, "Longitude": 103.85}

    now = datetime(2026, 10, 1, 18, 0, tzinfo=SGT)
    def cand(service, low, eta_min):
        return {"service_no": service, "stop_code": "1", "stop_name": "A", "point": low + 5, "range_low": low,
                "range_high": low + 10, "eta": now + timedelta(minutes=eta_min), "estimated_arrival": None, "monitored": True}
    winner = cand("7", 55, 2)
    rows = reroute._alternatives(Cache(), [winner, cand("16", 33, 9), cand("36", 40, 12)], winner, False, 1.30, 103.85)
    assert [row["service_no"] for row in rows] == ["36", "16"]
    assert all({"point", "range_low", "range_high", "distance_m"} <= set(row) for row in rows)

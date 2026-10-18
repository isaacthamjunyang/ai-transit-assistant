"""Screens 9 and 10: the in-app Leave now banner and the data-quality warnings. Source checks only."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"
COPY = STATIC / "copy.js"
CSS = STATIC / "components.css"

STALE_HEADING = "LTA data is stale"
STALE_BODY = "Stale data: no catch chance or leave advice until live data returns."
UNAVAILABLE = "No live arrival data. No earlier update."
LOCATION_BODY = "GPS accuracy is {accuracy}. The range is wider and we won't suggest leaving now."


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    head = text.split(start, 1)[1]
    assert end in head, end
    return head.split(end, 1)[0]


def _slot() -> str:
    return _between(_page(), 'id="alert-slot"', 'id="arrival-card"')


def test_there_is_no_in_app_leave_now_banner():
    html = _page()
    for gone in ("leave-now-banner", "leave-now-title", "leave-now-body", "leave-now-details", "leave-now-dismiss", "leave-now-simulated",
                 "showLeaveNowBanner", "hideLeaveNowBanner", "leaveNowStillHolds", "leaveNowBannerBody", "leaveNowBanner ="):
        assert gone not in html, gone
    copy = COPY.read_text(encoding="utf-8")
    assert "leaveNowBanner" not in copy and "viewDetails" not in copy and "bannerProbability" not in copy


def test_the_notification_uses_the_locked_title_and_body_and_fires_once_per_event():
    html = _page()
    deliver = _between(html, "function deliverLeaveNow(busId)", "function fiveMinuteLockKey")
    assert "if (lastNotifiedBusId === busId)" in deliver
    assert deliver.index("if (lastNotifiedBusId === busId)") < deliver.index("showLocalNotification(")
    assert deliver.index("showLocalNotification(") < deliver.index("lastNotifiedBusId = busId")
    assert "notice.title" in deliver and "notice.body" in deliver
    assert "Leave now!" not in html and "Bus 36 arrives soon" not in html


def test_the_notification_follows_the_permission_and_the_same_trigger():
    html = _page()
    deliver = _between(html, "function deliverLeaveNow(busId)", "function fiveMinuteLockKey")
    sync = _between(html, "function syncLeaveNow(body)", "function renderCatchWarning")
    assert "Notification.permission" not in sync
    granted = 'typeof Notification === "function" && Notification.permission === "granted"'
    assert granted in deliver
    assert deliver.index(granted) < deliver.index("showLocalNotification(notice.title, { body: notice.body })")
    assert "body.notification_time" in sync and "chance.range_high < 40" in sync


def test_notification_options_are_unchanged():
    html = _page()
    assert html.count("showLocalNotification(notice.title, { body: notice.body })") == 1
    for call in re.findall(r"new Notification\([^\n]*", html):
        for forbidden in ("actions", "tag", "icon", "badge", "requireInteraction"):
            assert forbidden not in call, call
    for forbidden in ("showNotification(notice", "notificationclick", ".onclick", "actions:", "icon:"):
        if forbidden in ("actions:", "icon:"):
            continue
        assert forbidden not in html, forbidden
    assert html.count("Notification.requestPermission") == 1


def test_nothing_else_depended_on_the_banner():
    html = _page()
    card = html.split('id="arrival-card"', 1)[1].split(">", 1)[0]
    assert 'tabindex="-1"' in card  # the card stays focusable
    quality = _between(html, "function syncQuality()", "function activePlannedLeg")
    assert "LeaveNow" not in quality
    assert "clearLeaveNowTimer()" in _between(html, "function clearLeaveNowState()", "function etaIsMissed")
    assert "lastNotifiedBusId = null" in _between(html, "function clearLeaveNowState()", "function etaIsMissed")




def test_alert_slot_priority_order():
    html = _page()
    slot = _slot()
    ids = ["quality-banner", "stale-status", "location-card", "reroute-block", "catch-warning",
           "notification-panel"]
    positions = [slot.index('id="%s"' % name) for name in ids]
    assert positions == sorted(positions)
    fn = _between(html, "function syncAlertSlot()", "// Screen 8 to 5")
    order = ["reroute-block", "catch-warning", "notification-panel"]
    indexes = [fn.index('byId("%s")' % name) for name in order]
    assert indexes == sorted(indexes)
    assert "var taken = warned;" in fn
    # The location card never takes the slot from the others.
    assert 'byId("location-card")' not in fn.split("var occupants", 1)[1]


def test_stale_layout_hides_the_live_cards_and_shows_the_status_card():
    html = _page()
    css = CSS.read_text(encoding="utf-8")
    block = _between(css, "body.is-data-blocked #arrival-card,", "}")
    for target in ("#pace-slot", "#leave-tiles", "#ai-explanation", "#reroute-block"):
        assert target in block
    assert "#live-tracking" not in block
    status = _between(html, 'id="stale-status"', "</section>")
    for needle in ("bus-tile--hero", 'id="stale-bus-title"', "pill pill--schedule", 'id="stale-arriving"', "alert alert--info", STALE_BODY):
        assert needle in status, needle
    assert "%" not in status
    sync = _between(html, "function syncQuality()", "function activePlannedLeg")
    assert 'classList.toggle("is-data-blocked", state !== "")' in sync
    assert "probabilityText" not in sync
    arriving = _between(html, "function staleArrivingText()", "function locationCardApplies")
    assert "lastSuccess.fetched_at" in arriving and "Date.now()" not in arriving
    assert "STALE_ARRIVING.replace" in arriving


def test_no_probability_string_while_stale_or_unavailable():
    html = _page()
    catch = _between(html, "function renderCatchCard(hero)", "function renderLeaveTiles")
    assert "!displayFrozen && chance" in catch
    unavailable = _between(html, "function showFirstFailure(message)", "function showUpdating")
    assert "renderCatchCard(null)" in unavailable
    banner = _between(html, 'id="quality-banner"', 'id="location-card"')
    assert "%" not in banner.replace(STALE_BODY, "")
    assert "Catch probability" not in banner


def test_stale_counter_and_announcement():
    html = _page()
    banner = _between(html, 'id="quality-banner"', 'id="stale-status"')
    assert '<time id="quality-banner-time"' in banner
    assert 'id="quality-banner-updated" class="alert__meta" aria-live="off"' in banner
    assert "role=" not in html.split('id="quality-banner"', 1)[1].split(">", 1)[0]
    assert 'id="quality-announce" class="visually-hidden" aria-live="polite"' in html
    sync = _between(html, "function syncQuality()", "function activePlannedLeg")
    assert "relativeAge(iso)" in sync
    assert "if (state !== lastQualityState)" in sync
    live = _between(html, "function renderLiveTracking()", 'document.getElementById("live-refresh")')
    assert "syncQuality()" in live  # runs on the one-second display tick, so the time counts up
    age = _between(html, "function relativeAge(iso)", "function hasBusPosition")
    assert 'seconds + " seconds ago"' in age and '" min " + (seconds % 60) + " sec ago"' in age
    assert "updated.hidden = !age" in sync


def test_unavailable_banner_uses_the_existing_text_and_no_time():
    html = _page()
    assert html.count('showFirstFailure("%s")' % UNAVAILABLE) == 2
    assert 'var UNAVAILABLE_TEXT = "%s";' % UNAVAILABLE in html
    sync = _between(html, "function syncQuality()", "function activePlannedLeg")
    assert "STALE_HEADING : UNAVAILABLE_TEXT" in sync
    assert 'iso = state === "stale"' in sync
    assert 'status.hidden = state === ""' in sync
    assert 'var warned = state === "stale" || state === "unavailable"' in sync


def test_location_card_stacks_with_stale_and_uses_the_formatter():
    html = _page()
    sync = _between(html, "function syncQuality()", "function activePlannedLeg")
    assert 'state !== "unavailable" && monitoringActive && locationCardApplies()' in sync
    assert "formatDistance(chance.location_accuracy_m)" in sync  # the accuracy the server saw
    assert 'LOCATION_BODY.replace("{accuracy}", metres)' in sync
    assert 'LOCATION_AGE_BODY.replace("{seconds}", chance.location_age_s)' in sync
    card = html.split('id="location-card"', 1)[1].split(">", 1)[0]
    assert "alert--warning" in card
    rule = _between(html, "function locationCardApplies()", "function syncQuality")
    assert 'chance.data_quality === "location uncertain"' in rule
    assert 'chance.location_reason === "accuracy" || chance.location_reason === "age"' in rule  # neither: no card
    assert html.count("var UNCERTAIN_ACCURACY_M = 100;") == 1


def test_quality_strings_are_approved_and_match_copy():
    html = _page()
    copy = COPY.read_text(encoding="utf-8")
    for text in (STALE_HEADING, STALE_BODY, "Last update: {time}", "Arriving in {minutes} min (estimated)", UNAVAILABLE,
                 "Location uncertain", "GPS accuracy is {accuracy}."):
        assert text in html, text
        assert text in copy, text
    assert LOCATION_BODY in copy
    tail = copy.split("quality: {", 1)[1]
    tail = tail.replace("/* proposed, needs approval */\n      ageBody", "ageBody")  # the age reason is the one new proposed string
    assert "proposed" not in tail.lower()
    assert "needs approval" not in tail.lower()
    assert "{accuracy} m" not in html and "{accuracy} m" not in copy


def test_new_markup_and_styles_use_tokens_only():
    css = CSS.read_text(encoding="utf-8")
    tail = css.split("/* Screens 9 and 10:", 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", tail)
    for name in ("index.html", "styleguide.html"):
        assert 'style="' not in (STATIC / name).read_text(encoding="utf-8")

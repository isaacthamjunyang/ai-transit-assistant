"""Fix refresh, the location reasons, the ring bands, and the two live pages. Source checks plus the Python rule."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from catch_heuristic import UNCERTAIN_ACCURACY_M, UNCERTAIN_AGE_S, is_location_uncertain, score_buses

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 18, 0, tzinfo=SGT)


def _page() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    head = text.split(start, 1)[1]
    assert end in head, end
    return head.split(end, 1)[0]


# ---- location uncertainty

def test_limits_are_unchanged_and_the_rule_is_accuracy_or_age():
    assert UNCERTAIN_ACCURACY_M == 100 and UNCERTAIN_AGE_S == 60.0
    assert is_location_uncertain(55, 3) is False  # a stationary device with a fresh fix
    assert is_location_uncertain(55, 15) is False
    assert is_location_uncertain(101, 3) is True  # accuracy above the limit
    assert is_location_uncertain(55, 61) is True  # a fix that is not refreshed ages out


def _score(age: float, accuracy: float = 55.0, minutes: float = 10.0) -> dict:
    bus = [{"position": "NextBus", "arrival_time": (NOW + timedelta(minutes=minutes)).isoformat(), "monitored": True,
            "origin_code": None, "destination_code": None}]
    return score_buses(
        bus, user_lat=1.3 + 100 / 111_195, user_lon=103.8, accuracy_m=accuracy, stop_lat=1.3, stop_lon=103.8,
        services=[], routes=[], service_no="36", stop_code="1", now=NOW, location_timestamp=NOW.timestamp() - age,
    )[0]["probability"]


def test_a_refreshed_fix_keeps_the_range_narrow_and_a_stale_one_widens_only_the_low_end():
    fresh = _score(age=5, minutes=5)
    aged = _score(age=150, minutes=5)
    assert fresh["data_quality"] == "live" and aged["data_quality"] == "location uncertain"
    assert fresh["point"] == aged["point"]  # the point is not widened by age
    assert fresh["range_high"] == aged["range_high"]
    assert aged["range_low"] < fresh["range_low"] - 40
    assert fresh["range_high"] - fresh["range_low"] < 40


def test_one_fresh_fix_is_requested_per_poll_tick_and_failures_leave_the_age_growing():
    html = _page()
    tick = _between(html, "function armPollTimer(generation)", "// One request per poll tick")
    assert tick.count("refreshLocationFix(generation)") == 1 and tick.count("setInterval(") == 1
    refresh = _between(html, "function refreshLocationFix(generation)", "// The pill, the Last update counter")
    assert refresh.count("getCurrentPosition(") == 1 and "watchPosition" not in refresh
    assert "enableHighAccuracy: true, maximumAge: FIX_MAX_AGE_MS, timeout: FIX_TIMEOUT_MS" in refresh
    assert "var FIX_MAX_AGE_MS = 15000;" in html and "var FIX_TIMEOUT_MS = 10000;" in html
    assert "userLocationTimestamp = Date.now();" in refresh  # a success refreshes the age even for identical coordinates
    failure = refresh.split("function () {", 1)[1]
    assert failure.strip().startswith("return;")  # a failure or timeout changes nothing
    assert "localStorage" not in refresh and "fetch(" not in refresh and "console." not in refresh
    assert html.count("setInterval(") == 3  # the poll and the display tick: no new timer
    request = _between(html, "function requestArrivals(generation)", "function applySuccess")
    assert "getCurrentPosition" not in request


def test_the_card_names_the_reason_the_server_gave():
    html = _page()
    assert "function locationReason()" not in html  # no fall-through to the accuracy wording any more
    card = _between(html, 'var chance = featuredBus(lastSuccess.buses).probability;', "if (state !== lastQualityState)")
    assert 'chance.location_reason === "age"' in card
    assert "LOCATION_AGE_BODY.replace(\"{seconds}\", chance.location_age_s)" in card and "LOCATION_BODY.replace(\"{accuracy}\", metres)" in card
    assert "LOCATION_HEADING" in card
    rule = _between(html, "function locationCardApplies()", "function syncQuality")
    assert 'chance.location_reason === "accuracy" || chance.location_reason === "age"' in rule
    copy = (STATIC / "copy.js").read_text(encoding="utf-8")
    age = "Your location hasn't updated for {seconds} s. We'll show a wider range for the catch probability and won't suggest"
    assert age in html and age in copy
    assert "Your GPS accuracy is {accuracy}. We'll show a wider range for the catch probability" in html
    assert "/* proposed, needs approval */\n      ageBody" in copy


# ---- ring

def _tokens(css: str) -> dict:
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", css))


def _lum(color: str) -> float:
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_ring_has_no_marks_and_uses_band_colours():
    html = _page()
    css = (STATIC / "components.css").read_text(encoding="utf-8")
    guide = (STATIC / "styleguide.html").read_text(encoding="utf-8")
    theme = (STATIC / "theme.css").read_text(encoding="utf-8")
    for text in (html, css, guide, theme):
        assert "prob-ring__mark" not in text and "prob-mark" not in text and "meter__tick" not in text
    assert "RING_MARKS_SVG" not in html
    ring = _between(css, ".prob-ring__track,", ".prob-ring.is-empty .prob-ring__value")
    assert "stroke-width: 10" in ring and "stroke-linecap: round" in ring and "stroke: var(--color-line)" in ring
    for band, token in (("ok", "--prob-ring-ok"), ("mid", "--prob-ring-mid"), ("low", "--prob-ring-low")):
        assert ".prob-ring--%s .prob-ring__value {\n  stroke: var(%s);" % (band, token) in css
    band = _between(html, "var RING_BAND_CLASS", "function setRing")
    assert "ok:" in band and "mid:" in band and "low:" in band
    assert not re.search(r"(40|50)", band)  # the band comes from Python: no probability numbers in the JS mapping
    assert "chance.band" in band and "chance.point" not in band
    assert 'role="img"' in html.split('id="catch-ring"', 1)[1].split(">", 1)[0]
    assert 'aria-live="polite"' in html.split('id="arrival-card"', 1)[1].split(">", 1)[0]
    assert 'box.setAttribute("aria-label", ringLabel(chance,' in html  # names the bus


def test_ring_band_tokens_alias_the_status_tokens_and_pass_three_to_one():
    theme = (STATIC / "theme.css").read_text(encoding="utf-8")
    assert "--prob-ring-ok: var(--status-live);" in theme
    assert "--prob-ring-mid: var(--status-uncertain);" in theme
    assert "--prob-ring-low: var(--status-unavailable);" in theme
    light = theme.split(":root {", 1)[1].split("}", 1)[0]
    dark = theme.split('@media (prefers-color-scheme: dark)', 1)[1]
    light_tokens, dark_tokens = _tokens(light), _tokens(dark)
    for name in ("--status-live", "--status-uncertain", "--status-unavailable"):
        assert _ratio(light_tokens[name], light_tokens["--color-card"]) >= 3.0, name
        assert _ratio(dark_tokens[name], dark_tokens["--color-card"]) >= 3.0, name


# ---- two live pages

def test_start_journey_opens_page_a_and_the_button_opens_page_b():
    html = _page()
    assert 'document.getElementById("start-journey").addEventListener("click"' in html
    start = _between(html, 'document.getElementById("start-journey").addEventListener("click"', "});")
    assert 'pushScreen("live")' in start and 'pushScreen("arrivals")' not in start
    see = _between(html, 'document.getElementById("see-arrivals").addEventListener("click"', "});")
    assert 'pushScreen("arrivals")' in see
    screens = _between(html, "function applyScreen(name)", "function syncHomeButton")
    assert 'classList.toggle("is-page-a", name === "live" && !pageC)' in screens
    assert 'classList.toggle("is-page-b", name === "arrivals")' in screens
    assert 'getElementById("live-tracking").hidden = name !== "arrivals"' in screens
    css = (STATIC / "components.css").read_text(encoding="utf-8")
    block = _between(css, "body.is-page-b #arrival-card,", "}")
    for target in ("#pace-slot", "#leave-tiles", "#if-you-miss", "#ai-explanation", "#stale-status"):
        assert target in block
    assert "See bus arrival times" in html.split('id="see-arrivals-bar"', 1)[1].split("</div>", 1)[0]


def test_back_order_between_the_pages_and_the_overview():
    html = _page()
    helper = _between(html, "function returnsWithoutConfirm()", "function requestBack()")
    assert '"newjourney"' in helper and '"arrivals"' in helper and '"live"' not in helper
    back = _between(html, "function requestBack()", "var pendingLeaveAction")
    assert "monitoringActive && !returnsWithoutConfirm()" in back and "openLeaveDialog()" in back
    pop = _between(html, 'window.addEventListener("popstate"', "try {\n      history.replaceState")
    assert "!returnsWithoutConfirm()" in pop
    assert html.count("setInterval(") == 3  # no second poll or timer for the second page


def test_the_map_is_invalidated_and_fitted_each_time_page_b_opens():
    html = _page()
    screens = _between(html, "function applyScreen(name)", "function syncHomeButton")
    assert screens.index('if (name === "arrivals") {') < screens.index('placeMap(inStops, name === "arrivals", name === "walk")')
    assert "liveUserMoved = false;" in _between(screens, 'if (name === "arrivals") {', "}")
    place = _between(html, "function placeMap(inDestination, inLive, inWalk)", "function placeArriveBy")
    live = _between(place, "if (inLive) {", "return;")
    assert "map.invalidateSize()" in live and "liveFit = { done: false, withBus: false }" in live and "renderLiveTracking()" in live
    fit = _between(html, "function fitLiveView(busPoint, stopPoint)", "function setStatusCell")
    assert "liveFull || liveUserMoved" in fit  # never re-fits after a pan or zoom


def test_question_bar_and_see_arrivals_bar_visibility():
    html = _page()
    sync = _between(html, "function syncCatchBar()", "// Runs on the one-second display tick")
    assert 'showQuestion = running && document.body.classList.contains("is-page-b")' in sync
    assert 'showArrivals = running && (document.body.classList.contains("is-page-a") || document.body.classList.contains("is-page-w"))' in sync
    assert 'qualityState() !== "no-service"' in sync
    assert "isFinite(lastEtaMs)" in sync  # a known arrival time, live or last known
    assert "monitoringActive && !endedKind && !missedMode" in sync  # hidden after Yes, No or an end card
    assert "syncCatchBar()" in _between(html, "function applyScreen(name)", "function syncHomeButton")


def test_yes_and_no_still_end_tracking_and_open_the_right_view():
    html = _page()
    yes = _between(html, "function answerCaught()", "function renderOnWay()")
    assert yes.index("stopTracking()") < yes.index('pushScreen("onway")')
    assert "Watch" not in yes
    no = _between(html, "function answerMissed()", "function showMissedOptions")
    assert no.index("stopTracking()") < no.index('openPageC("missed", missedEpoch)')
    assert "/api/reroute-options?" in _between(html, "function optionsUrl(entry, missedEpoch)", "function canSearchOptions")
    assert "onDemand: true" in _between(html, "function loadPageCOptions()", "function pageCRefreshCooling()")


def test_the_then_bus_line_shows_only_on_the_first_leg_of_a_transfer_route():
    html = _page()
    assert "Then Bus {service} at {stop}" in html
    then = _between(html, 'var then = document.getElementById("live-then");', "var stopPoint")
    assert "leg_index === 1" in then


def test_question_bar_needs_a_known_arrival_time():
    html = _page()
    sync = _between(html, "function syncCatchBar()", "// Runs on the one-second display tick")
    assert "isFinite(lastEtaMs)" in sync and 'qualityState() !== "no-service"' in sync
    assert "monitoringActive && !endedKind && !missedMode" in sync  # hidden after Yes, No and the end card
    reset = _between(html, "function resetTrackingState()", "function planNewJourney")
    assert "lastEtaMs = NaN" in reset  # a new leg starts with no known time
    note = _between(html, "function noteTrackedBus(body)", "function syncCatchBar")
    assert "trackedEtaMs(body)" in note and "lastEtaMs = at" in note  # set from live data, kept while stale or unavailable
    assert "lastEtaMs = NaN" not in note


# ---- the server names the reason (location_reason, location_age_s, location_accuracy_m: additive fields)

def test_the_probability_carries_the_reason_the_age_and_the_accuracy_it_was_scored_with():
    accuracy = _score(age=150, accuracy=22.0)
    assert accuracy["data_quality"] == "location uncertain"
    assert accuracy["location_reason"] == "age" and accuracy["location_age_s"] == 150 and accuracy["location_accuracy_m"] == 22.0
    poor = _score(age=3, accuracy=140.0)
    assert poor["location_reason"] == "accuracy" and poor["location_age_s"] == 3 and poor["location_accuracy_m"] == 140.0
    both = _score(age=150, accuracy=140.0)
    assert both["location_reason"] == "accuracy"  # both apply: the accuracy wording wins, as before


def test_when_neither_applies_there_is_no_reason_and_so_no_card():
    fine = _score(age=5, accuracy=22.0)
    assert fine["data_quality"] == "live" and fine["location_reason"] is None
    assert fine["location_age_s"] == 5 and fine["location_accuracy_m"] == 22.0
    edge = _score(age=60, accuracy=100.0)  # exactly at the limits: not uncertain
    assert edge["data_quality"] == "live" and edge["location_reason"] is None
    without_time = score_buses(
        [{"position": "NextBus", "arrival_time": (NOW + timedelta(minutes=10)).isoformat(), "monitored": True,
          "origin_code": None, "destination_code": None}],
        user_lat=1.3 + 100 / 111_195, user_lon=103.8, accuracy_m=22.0, stop_lat=1.3, stop_lon=103.8,
        services=[], routes=[], service_no="36", stop_code="1", now=NOW,
    )[0]["probability"]
    assert without_time["location_reason"] is None and without_time["location_age_s"] is None


def test_the_reason_is_set_exactly_when_the_location_is_uncertain_and_no_old_field_changed():
    for age, accuracy in ((5, 22), (150, 22), (5, 140), (150, 140), (60, 100), (61, 100), (60, 101)):
        chance = _score(age=age, accuracy=float(accuracy))
        assert (chance["location_reason"] is not None) == (chance["data_quality"] == "location uncertain")
        assert (chance["location_reason"] is not None) == is_location_uncertain(accuracy, age)
    old_keys = {"point", "range_low", "range_high", "slack_seconds", "data_quality", "reliability_label", "is_missed", "band", "pace"}
    assert old_keys <= set(_score(age=5))


def test_the_page_sends_a_fresh_fix_before_the_first_poll_only_when_the_last_fix_is_old():
    html = _page()
    fn = _between(html, "function ensureFreshFix(generation, done)", "function startMonitoring(serviceNo, freshFirst)")
    assert "Date.now() - userLocationTimestamp > FRESH_FIX_MAX_AGE_MS" in fn
    assert "enableHighAccuracy: true, maximumAge: 0, timeout: FRESH_FIX_TIMEOUT_MS" in fn
    assert "var FRESH_FIX_MAX_AGE_MS = 10000;" in html and "var FRESH_FIX_TIMEOUT_MS = 4000;" in html
    assert "setTimeout(finish, FRESH_FIX_TIMEOUT_MS)" in fn  # the poll goes ahead after 4 s whatever the result
    assert "var POLL_MS = 20000;" in html and "var UNCERTAIN_ACCURACY_M = 100;" in html and "var UNCERTAIN_AGE_S = 60;" in html

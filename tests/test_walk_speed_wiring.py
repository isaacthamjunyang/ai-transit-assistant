"""Source-level checks on how the page uses the estimator, and the JS walking-minutes mirror."""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from walk_speed import walk_minutes

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    head = text.split(start, 1)[1]
    assert end in head, end
    return head.split(end, 1)[0]


BLOCK = _between(INDEX, "// Walking speed (static/walk-speed.js).", "// Stops polling, the display tick")


def test_the_page_loads_the_estimator_and_keeps_local_storage_out_of_index_html():
    assert '<script src="walk-speed.js"></script>' in INDEX
    assert INDEX.index('src="walk-speed.js"') < INDEX.index("var AI_EXPLANATION_ENABLED")
    assert "localStorage" not in INDEX and "sessionStorage" not in INDEX
    assert "devicemotion" not in INDEX and "DeviceMotionEvent" not in INDEX  # only walk-speed.js touches the sensor


def test_the_motion_permission_is_asked_only_inside_the_two_start_journey_taps():
    assert INDEX.count(".requestPermission()") == 2  # Notification.requestPermission and the estimator's
    assert INDEX.count("paceEstimator.requestPermission()") == 1
    begin = _between(INDEX, "function beginPaceEstimator() {", "// Two polls in a row")
    assert "paceEstimator.requestPermission()" in begin and "demoModeOn()" in begin
    first = _between(INDEX, 'document.getElementById("start-journey").addEventListener("click"', "pushScreen(\"live\")")
    assert "beginPaceEstimator();" in first and first.index("beginPaceEstimator();") < first.index("selectPlannedRoute")
    second = _between(INDEX, "function startNewJourney() {", "document.getElementById(\"new-journey-start\")")
    assert "beginPaceEstimator();" in second
    assert INDEX.count("beginPaceEstimator()") == 3  # the definition and the two taps
    assert ".then(syncPaceEstimator, syncPaceEstimator)" in begin  # the journey never waits for the answer


def test_the_estimator_follows_the_lifecycle_rules():
    run = _between(BLOCK, "function paceShouldRun() {", "function syncPaceEstimator()")
    for condition in ("paceJourneyActive", "monitoringActive", "endedKind", "missedMode", "onLeg2()", "demoModeOn()",
                      "isLatched()", '"live"', '"arrivals"'):
        assert condition in run, condition
    stop = _between(INDEX, "function stopTracking() {", "// After No, Yes or an end card")
    assert "paceJourneyActive = false;" in stop and "syncPaceEstimator();" in stop  # Yes, No, the end card, a new journey
    assert "paceJourneyActive = false;" in _between(INDEX, "function endMonitoring() {", "function chooseService")  # Back, Leave
    assert "paceJourneyActive = false;" in _between(INDEX, "function exitJourney(keepFields) {", "var arriveError")
    assert "syncPaceEstimator();" in _between(INDEX, "function applyScreen(name) {", "function syncHomeButton")
    assert "syncPaceEstimator();" in _between(INDEX, "function showDemoChrome(enabled) {", "function setArrivalSimulated")
    near = BLOCK.split("function notePaceNearStop(body) {", 1)[1]
    assert "near_stop === true" in near and "onLeg2()" in near


def test_no_new_timers_or_background_apis_in_the_page_wiring():
    assert "setInterval(" not in BLOCK and "setTimeout(" not in BLOCK and "watchPosition" not in BLOCK
    assert "serviceWorker" not in BLOCK and "fetch(" not in BLOCK
    assert INDEX.count("watchPosition(") == 1  # only the existing transfer watch; the estimator owns the other
    assert INDEX.count("setInterval(") == 2  # the existing display tick and poll timer, as before
    assert INDEX.count("getCurrentPosition(") == 2  # the load fix and the per-poll fix, unchanged


def test_the_dead_journey_watch_is_gone():
    assert "geoWatchId" not in INDEX and "stopJourneyWatch" not in INDEX


@pytest.mark.parametrize(
    "endpoint",
    ["/api/arrivals?", "/api/journey-plan?", "/api/route-plan?", "/api/journey?", "/api/destination-stops?", "/api/reroute-options?"],
)
def test_every_scored_request_carries_the_speed_and_unscored_ones_do_not(endpoint):
    start = INDEX.index(endpoint.rstrip("?")) if endpoint != "/api/journey?" else INDEX.index('"/api/journey?dest_lat')
    window = INDEX[start : start + 4500]
    assert "walkSpeedQuery()" in window.split("fetch(", 1)[0] or "walkSpeedQuery()" in window[:2800]


def test_unscored_requests_do_not_send_the_speed():
    for endpoint in ("/api/destinations?", "/api/arrivals/peek?", "/api/reverse-geocode", "/api/explain"):
        for match in re.finditer(re.escape(endpoint), INDEX):
            assert "walkSpeedQuery" not in INDEX[match.start() : match.start() + 400], endpoint


def test_the_page_only_ever_shows_the_servers_value():
    noted = _between(BLOCK, "function noteServerWalkSpeed(body) {", "// A fix from the estimator")
    assert "body.walk_speed_used" in noted and "WALK_SOURCES.indexOf(body.walk_speed_source)" in noted
    assert "paceEstimator" not in noted  # the client's own value is never what the page shows
    assert INDEX.count("noteServerWalkSpeed(") >= 7  # the definition and every scored response


def test_the_watch_fix_may_replace_an_older_per_poll_fix_only():
    take = _between(BLOCK, "function onEstimatorFix(fix) {", "// The estimator runs while")
    assert "fix.t <= userLocationTimestamp" in take and "monitoringActive" in take
    refresh = _between(INDEX, "function refreshLocationFix(generation)", "// The reason the card names")
    assert refresh.count("getCurrentPosition(") == 1 and "watchPosition" not in refresh


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed, so the walking-minutes parity test did not run")
def test_the_js_mirror_matches_the_servers_display_rounding():
    mirror = _between(INDEX, "function walkMinutes(metres) {", "    function setOverviewState")
    body = "function walkMinutes(metres) {" + mirror.rstrip()
    distances = [0, 1, 20, 37, 38, 75, 100, 250, 300, 450, 600, 1200, 3001]
    speeds = [0.5, 0.9, 1.0, 1.1, 1.25, 1.35, 1.4]
    program = (
        "var serverWalkSpeed = 1.25;\n" + body + "\nvar out = [];\n"
        f"var speeds = {json.dumps(speeds)}; var distances = {json.dumps(distances)};\n"
        "speeds.forEach(function (s) { serverWalkSpeed = s; distances.forEach(function (d) { out.push(walkMinutes(d)); }); });\n"
        "console.log(JSON.stringify(out));"
    )
    done = subprocess.run([NODE, "-e", program], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    expected = [walk_minutes(d, s, "display") for s in speeds for d in distances]
    assert got == expected
    assert 0.5 in speeds and 1.4 in speeds and 0 in distances


def test_the_servers_label_and_the_ai_sentence_use_one_rule_for_the_same_distance():
    from destination_stops import _card
    from explain import overview_walk_minutes
    from nearby import walk_minutes as nearby_minutes

    stop = {"BusStopCode": "X", "Description": "X", "Latitude": 1.3, "Longitude": 103.8}
    for speed in (0.5, 1.0, 1.25, 1.4):
        for metres in (0, 20, 100, 250, 450, 600, 1200):
            assert nearby_minutes(metres, speed) == overview_walk_minutes(metres, speed)
            assert _card(stop, metres, speed)["walk_minutes"] == overview_walk_minutes(int(metres + 0.5), speed)
    assert math.isclose(walk_minutes(250, 1.25), 250 / 75)


# ---- Phase 4: what the user sees

COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")

NEW_STRINGS = [
    "if you leave now and keep walking at your current pace",
    "if you leave now and walk at your usual pace",
    "Walking pace: {kmh} km/h · from GPS",
    "Walking pace: {kmh} km/h · from your steps",
    "Walking pace: {kmh} km/h · your usual pace",
    "Walking pace: {kmh} km/h · normal pace",
    "Motion data stays on your phone. Only the walking speed worked out from it is sent. Your location is sent as before.",
    "Motion sensor is off, so your steps are not used.",
]


def test_the_new_strings_are_in_copy_js_and_in_the_page_character_for_character():
    for text in NEW_STRINGS:
        assert text in COPY, text
        assert text in INDEX, text
    assert "if you leave now and walk at a normal pace" in COPY and "if you leave now and walk at a normal pace" in INDEX
    # The three superseded wordings of the overview privacy line, built from pieces so that this file does not
    # itself contain them: the first wording, the second, and the one before the current text.
    lead = "Motion sensor data stays on your phone. "
    superseded = (
        lead + "Your walking speed is used to improve the estimate.",
        lead + "Only your walking speed is sent to improve the estimate.",
        lead + "Only the walking speed worked out from it is sent.",
    )
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    everywhere = COPY + INDEX + GUIDE + plan
    for old in superseded:
        assert old not in everywhere, old
    for fragment in ("Your walking speed is used to improve the estimate", "Only your walking speed is sent to improve"):
        assert fragment not in everywhere, fragment
    current = NEW_STRINGS[6]
    assert current == "Motion data stays on your phone. Only the walking speed worked out from it is sent. Your location is sent as before."
    assert current in plan  # the plan quotes the current line


def test_the_pace_line_is_muted_silent_and_inside_the_probability_card():
    card = _between(INDEX, 'id="arrival-card"', "</section>")
    assert '<p id="catch-pace-line" class="note" aria-live="off"></p>' in card
    assert card.index('id="catch-caption"') < card.index('id="catch-pace-line"')
    for note in ('id="overview-motion-note"', 'id="new-journey-motion-note"'):  # the overview lines: muted, silent
        assert f'<p {note} class="note" aria-live="off"></p>' in INDEX
    start = INDEX.index('<p id="overview-motion-note" class="note" aria-live="off"></p>')
    assert INDEX.index('id="start-journey"') > start and INDEX.index('id="start-journey"') - start < 120
    assert INDEX.index('id="new-journey-start"') > INDEX.index('id="new-journey-motion-note"')


def test_the_menu_keeps_only_appearance_and_back_and_adds_no_row():
    menu = INDEX.split('id="menu-sheet"', 1)[1][:2600]
    assert menu.count('class="menu-row"') == 2
    assert "motion" not in menu.lower()


def test_the_style_guide_shows_every_caption_pace_line_note_and_the_readout_in_both_themes():
    for key in ("captionCurrentPace", "captionUsualPace", "walkPaceGps", "walkPaceSteps", "walkPaceUsual", "walkPaceNormal"):
        assert f"lc.{key}" in GUIDE, key
    for source in ("gps", "cadence", "remembered", "default"):
        assert f'sgWalk("{source}"' in GUIDE, source
    assert "jo.motionPrivacy" in GUIDE and "jo.motionOff" in GUIDE
    assert 'class=\\"pace-debug pace-debug--sample\\"' in GUIDE
    assert 'id="catch-sample-light"' in GUIDE and 'id="catch-sample-dark"' in GUIDE  # catchSample() fills both
    assert "function catchSample()" in GUIDE and "sgWalk(" in GUIDE.split("function catchSample()", 1)[1].split("function ", 1)[0]


def test_no_hex_rgb_hsl_or_inline_style_was_added_outside_the_theme():
    for name in ("walk-speed.js", "components.css", "copy.js", "styleguide.html", "index.html"):
        text = (ROOT / "static" / name).read_text(encoding="utf-8")
        assert 'style="' not in text, name
        if name != "components.css":
            assert not re.search(r"(?<![\w&])#[0-9a-fA-F]{6}\b|rgb\(|hsl\(", text), name
    block = _between((ROOT / "static" / "components.css").read_text(encoding="utf-8"), "/* Developer readout", "/* The style guide shows")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block) and "var(--" in block


def test_pace_guidance_keeps_its_python_rules_and_never_implies_more_than_1_4():
    from config import PACE_MIN_HEADROOM_MPS, WALK_SPEED_MAX_MPS
    from walk_speed import range_speeds

    assert WALK_SPEED_MAX_MPS == 1.4 and PACE_MIN_HEADROOM_MPS == 0.05
    for speed in (1.0, 1.25, 1.35, 1.38, 1.4):
        point, _slow, fast = range_speeds(speed)
        assert fast <= 1.4 and fast >= point
    assert 'title: "Walk faster"' in COPY and 'title: "Walk slower"' in COPY

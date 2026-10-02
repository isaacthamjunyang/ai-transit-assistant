"""Two scenarios after Start journey, the two Page C layouts, the action-driven tile and chip, and the question bar."""

import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explain
import main
import observations
from journey import bus_arrival_window, miss_line
from leave_now import LEAVE_NOW_MARGIN_S, notification_time_from_leave_by
from lta_static import StopAndRouteCache
from main import app
from nearby import EARTH_RADIUS_M

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "components.css").read_text(encoding="utf-8")
THEME = (STATIC / "theme.css").read_text(encoding="utf-8")
COPY = (STATIC / "copy.js").read_text(encoding="utf-8")
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 15, 0, tzinfo=SGT)
LAT, LON = 1.3, 103.8
ORIGIN, DEST = "01011", "99999"


def between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _function(name):
    """The source of one top-level page function."""
    return "function " + name + HTML.split("function " + name, 1)[1].split("\n    function ", 1)[0]


def _run_node(script):
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ---- the scenario decision -------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_decision_boundaries_run_through_the_page_rule():
    script = (
        "var MIN_REAL_CHANCE_RANGE_HIGH = 40;" + _function("isUnlikely") + "\n" +
        "var h = function (high) { return {is_missed: false, probability: {range_high: high}}; };"
        "console.log(JSON.stringify({a: isUnlikely(h(39)), b: isUnlikely(h(40)), c: isUnlikely(h(41)),"
        " none: isUnlikely({is_missed: false, probability: null}), nobus: isUnlikely(null), missed: isUnlikely({is_missed: true, probability: {range_high: 5}})}));"
    )
    got = _run_node(script)
    assert got == {"a": True, "b": False, "c": False, "none": False, "nobus": False, "missed": False}


def test_the_rule_uses_the_existing_forty_constant_and_the_page_receives_it():
    assert "typeof chance.range_high === \"number\" && chance.range_high < MIN_REAL_CHANCE_RANGE_HIGH" in HTML
    assert "var MIN_REAL_CHANCE_RANGE_HIGH = 40;" in HTML
    from config import MIN_REAL_CHANCE_RANGE_HIGH, PAGE_CONSTANTS

    assert PAGE_CONSTANTS["MIN_REAL_CHANCE_RANGE_HIGH"] == MIN_REAL_CHANCE_RANGE_HIGH == 40


def test_start_journey_shows_a_loading_state_then_decides_once():
    start = _function("startMonitoring")
    assert "entryPending = true" in start and "setEntryLoading(true)" in start
    assert 'id="entry-skeleton"' in HTML and 'aria-busy="true"' in HTML.split('id="entry-skeleton"', 1)[1].split(">", 1)[0]
    resolve = _function("resolveEntry")
    assert resolve.index("if (!entryPending)") < resolve.index("entryPending = false")  # once
    # Stale, unavailable, no service and no ETA all settle the decision as scenario 1 (Page A with its layout).
    for name in ("handleEmptyBuses", "showFirstFailure", "freezeStale"):
        assert "resolveEntry(null)" in _function(name), name
    assert "resolveEntry(body)" in _function("applySuccess")
    # The decision is the only automatic way into Page C, and it never navigates afterwards.
    assert HTML.count('openPageC("unlikely")') == 2  # the decision and the banner button
    assert "openPageC(" not in _function("applySuccess") and "openPageC(" not in _function("renderUnlikelyBanner")
    assert "pushScreen" not in resolve and "pushScreen" not in _function("renderUnlikelyBanner")


def test_a_later_change_shows_only_the_compact_banner_and_it_clears():
    banner = _function("renderUnlikelyBanner")
    assert "!entryPending && !pageC && !missedMode && !displayFrozen && isUnlikely(hero)" in banner
    assert "See other buses" in HTML and 'id="unlikely-see"' in HTML
    assert 'addEventListener("click", openPageCFromBanner)' in HTML
    assert "UNLIKELY_BANNER_TITLE" in banner and "probabilityText(hero.probability)" in banner
    order = between(HTML, "var occupants = [", "];")
    ids = re.findall(r'byId\("([a-z-]+)"\)', order)
    assert ids.index("end-card") < ids.index("unlikely-banner") < ids.index("leave-now-banner") < ids.index("reroute-block") < ids.index("catch-warning")
    assert "catch-warning" in HTML and "Tap to enable Leave-Now Alert." in HTML  # the existing banner is untouched


def test_becoming_catchable_on_page_c_hides_the_warning_and_does_not_navigate():
    update = _function("updatePageCCurrent")
    assert 'getElementById("pc-warn").hidden = !(usable && isUnlikely(hero))' in update
    assert "pushScreen" not in update and "closePageC" not in update


# ---- Page C layouts --------------------------------------------------------------------

def test_unlikely_entry_has_the_current_bus_card_first_and_no_page_a_cards():
    page_c = between(HTML, 'id="page-c"', 'id="arrival-card"')
    assert page_c.index('id="reroute-current"') < page_c.index('id="reroute-proposal"') < page_c.index('id="reroute-cards"')
    for text in ("Catching this bus is unlikely. Here are your other options.", "See bus arrival times", 'id="pc-pill"', 'id="pc-ring"'):
        assert text in page_c
    hidden = between(CSS, "body.is-page-c #arrival-card,", "{")
    for needed in ("#pace-slot", "#leave-tiles", "#if-you-miss", "#ai-explanation", "#see-arrivals-bar", "#unlikely-banner", "#catch-warning"):
        assert needed in hidden, needed


def test_missed_entry_has_no_current_bus_card_and_the_banner_leads():
    render = _function("renderPageC")
    assert 'document.getElementById("reroute-current").hidden = !unlikelyEntry' in render
    assert 'pageC.entry === "missed" && !!rerouteNotice' in render
    assert 'rerouteNotice = BUS_LEFT_NOTICE.replace("{service}", service || "")' in _function("answerMissed")
    assert HTML.index('id="reroute-notice"') < HTML.index('id="reroute-cards"')


def test_nothing_eligible_shows_the_current_card_the_no_better_card_and_the_list_without_ai():
    render = _function("renderPageC")
    assert "OTHER_BUSES_HEADING" in render and "noBetterText()" in render
    assert "options.recommended ? ALTERNATIVES_HEADING : OTHER_BUSES_HEADING" in render
    assert "Other buses at your stop" in HTML and "Other buses at your stop" in COPY
    # The AI block belongs to the recommended card only.
    assert "buildOptionExplanation" in _function("buildOptionCard") and "buildOptionExplanation" not in render


def test_every_probability_names_its_bus_and_appears_once_per_option():
    for text in ("Chance to catch Bus {service}", "Chance to catch your Bus {service}", "Chance to catch Bus {service} at {stop}"):
        assert text in HTML and text in COPY, text
    assert "Chance to catch current Bus" not in HTML + COPY
    assert "Arriving in {n} min" in HTML and "Arriving in {n} min" in COPY
    heading = _function("catchHeading")
    assert "CATCH_HEADING_LEG2_TEXT" in heading and "CATCH_HEADING_TEXT" in heading
    assert 'getElementById("catch-title").textContent = catchHeading(false)' in _function("renderCatchCard")
    assert 'getElementById("pc-title").textContent = catchHeading(true)' in _function("updatePageCCurrent")
    assert 'setCatchSub("catch", hero)' in _function("renderCatchCard") and 'setCatchSub("pc", hero)' in _function("updatePageCCurrent")
    assert 'aria-label", ringLabel(chance,' in _function("setRing")
    card = _function("buildOptionCard")
    assert '"Bus " + row.service_no' in card and "Catch probability" not in card and card.count("buildProbRing(row)") == 1
    row = _function("buildOptionRow")
    assert '"Bus " + row.service_no' in row and "CHANCE_TEXT" in row and "Catch probability" not in row.replace("probabilityText(row)", "")
    assert "chance to catch" not in HTML.replace("Chance to catch", "") and "chance to catch\"" not in COPY


def test_slowly_is_absent_everywhere():
    files = list(STATIC.glob("*.html")) + list(STATIC.glob("*.js")) + list(STATIC.glob("*.css")) + [ROOT / "PROJECT_PLAN.md"]
    files += [path for path in ROOT.glob("*.py")]
    for path in files:
        assert "slowly" not in path.read_text(encoding="utf-8").lower(), path.name
    for path in (ROOT / "tests").glob("test_*.py"):
        if path.name != "test_page_c_entry.py":
            assert "slowly" not in path.read_text(encoding="utf-8").lower(), path.name
    assert "Walk slower" in COPY and "Walk slightly slower" in COPY


# ---- the action behind the tile, the chip, the clause and the notification ---------------

ACTION_TABLE = [
    ("wait", dict(reroute=False, quality="live", high=95, leave_by_s=660)),
    ("wait", dict(reroute=False, quality="live", high=95, leave_by_s=61)),
    ("leave_now", dict(reroute=False, quality="live", high=95, leave_by_s=60)),
    ("leave_now", dict(reroute=False, quality="live", high=95, leave_by_s=-30)),
    ("do_not_rely", dict(reroute=False, quality="live", high=39, leave_by_s=660)),
    ("switch_route", dict(reroute=True, quality="live", high=39, leave_by_s=660)),
]


@pytest.mark.parametrize("action,case", ACTION_TABLE)
def test_tile_clause_and_notification_agree_with_the_python_action(action, case):
    got = explain.chosen_action(
        reroute_fired_this_poll=case["reroute"], data_quality=case["quality"], range_high=case["high"], leave_by_seconds=case["leave_by_s"],
    )
    assert got == action
    # The AI clause comes from the same action.
    assert explain.deterministic_advice(action) == explain.ACTION_ADVICE[action]
    # The notification fires at leave-by minus 60 s: exactly when the action turns leave_now.
    leave_by = NOW + timedelta(seconds=case["leave_by_s"])
    due = NOW >= notification_time_from_leave_by(leave_by)
    if case["high"] >= 40 and not case["reroute"]:
        assert due == (action == "leave_now")
    assert LEAVE_NOW_MARGIN_S == 60


def test_the_tile_reads_the_action_and_hides_for_switch_and_do_not_rely():
    tiles = _function("renderLeaveTiles")
    assert 'action === "leave_now"' in tiles and "LEAVE_NOW_TEXT" in tiles
    assert 'action === "wait"' in tiles and "WAIT_ALERT_TEXT" in tiles
    assert 'leaveTile.hidden = action === "switch_route" || action === "do_not_rely"' in tiles
    assert "formatClock(lastSuccess.leave_by" not in tiles
    assert 'var LEAVE_NOW_TEXT = "Leave now";' in HTML and 'var WAIT_ALERT_TEXT = "Wait for Leave By Alert";' in HTML
    assert '"Wait for Leave By Alert"' in COPY and '"Leave now"' in COPY
    assert 'id="tile-leave-label" class="leave-tile__label">Leave by<' in HTML  # the label stays


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_applies_the_same_sixty_second_rule_between_polls():
    script = _function("trackedAction") + "\n" + (
        "var now = Date.now(); var iso = function (s) { return new Date(now + s * 1000).toISOString(); };"
        "console.log(JSON.stringify({wait: trackedAction({chosen_action: 'wait', leave_by: iso(300)}),"
        " edge: trackedAction({chosen_action: 'wait', leave_by: iso(55)}), leave: trackedAction({chosen_action: 'leave_now'}),"
        " switchRoute: trackedAction({chosen_action: 'switch_route', leave_by: iso(5)}), none: trackedAction({})}));"
    )
    assert _run_node(script) == {"wait": "wait", "edge": "leave_now", "leave": "leave_now", "switchRoute": "switch_route", "none": None}


def test_the_pace_chip_shows_only_for_leave_now():
    card = _function("renderCatchCard")
    assert 'trackedAction(lastSuccess) === "leave_now" ? paceChip(paceCategoryFor(chance.pace)) : null' in card


def _poll_client(monkeypatch, tmp_path, high, point, minutes=15):
    stop_lat, stop_lon = north(200)
    dest_lat, dest_lon = north(2000)
    cache = StopAndRouteCache(
        [
            {"BusStopCode": ORIGIN, "Description": "Origin", "RoadName": "Rd", "Latitude": LAT, "Longitude": LON},
            {"BusStopCode": DEST, "Description": "Destination", "RoadName": "Rd", "Latitude": dest_lat, "Longitude": dest_lon},
        ],
        [
            {"ServiceNo": "18", "Direction": 1, "BusStopCode": ORIGIN, "StopSequence": 1, "Distance": 0},
            {"ServiceNo": "18", "Direction": 1, "BusStopCode": DEST, "StopSequence": 5, "Distance": 2},
        ],
        [],
    )
    calls = []

    def fake(stop_code, service_no, **_kwargs):
        now = datetime.now(SGT)
        bus = {
            "position": "NextBus", "arrival_time": (now + timedelta(minutes=minutes)).isoformat(), "is_missed": False, "is_primary": True,
            "monitored": True, "latitude": LAT, "longitude": LON,
            "probability": {"point": point, "range_low": max(0, high - 10), "range_high": high, "slack_seconds": 30, "data_quality": "live", "band": "low"},
        }
        return {"status": "ok", "stop_code": stop_code, "service_no": service_no, "fetched_at": now.isoformat(), "buses": [bus],
                "leave_by": (now + timedelta(minutes=minutes - 4)).isoformat()}

    def fake_stop(stop_code, services, **kwargs):
        return {service: fake(stop_code, service) for service in services}

    real = main.plan_reroute

    def spy(**kwargs):
        calls.append(kwargs["current"]["stop_code"])
        return real(**kwargs)

    monkeypatch.setattr("main.load_static_data", lambda: cache)
    monkeypatch.setattr("main.fetch_arrivals", fake)
    monkeypatch.setattr("main.fetch_stop_arrivals", fake_stop)
    monkeypatch.setattr("main.plan_reroute", spy)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    params = {"stop_code": ORIGIN, "service_no": "18", "lat": LAT, "lon": LON, "accuracy": 12, "destination_stop_code": DEST,
              "dest_lat": dest_lat, "dest_lon": dest_lon, "explanation_rendered": 0}
    return TestClient(app), params, calls


def test_the_reroute_flag_only_skips_work_and_changes_no_decision(tmp_path, monkeypatch):
    client, params, calls = _poll_client(monkeypatch, tmp_path, high=30, point=20)
    with client:
        full = client.get("/api/arrivals", params=params).json()
        skipped = client.get("/api/arrivals", params={**params, "reroute": 0}).json()
        explicit = client.get("/api/arrivals", params={**params, "reroute": 1}).json()
    assert calls == [ORIGIN, ORIGIN]  # evaluated for the plain poll and reroute=1, skipped for reroute=0
    assert "reroute" in full and "reroute" in explicit and "reroute" not in skipped
    for key in ("status", "buses", "chosen_action", "leave_by", "arrival_estimate", "if_you_miss"):
        assert key in skipped, key
    # The probability, the data quality and the action are what they were: the flag cannot hide a warning.
    assert skipped["buses"][0]["probability"] == full["buses"][0]["probability"]
    assert skipped["buses"][0]["probability"]["data_quality"] == "live"
    assert skipped["status"] == full["status"] == "ok"
    assert skipped["chosen_action"] in ("do_not_rely", "switch_route") and full["chosen_action"] in ("do_not_rely", "switch_route")


def test_the_poll_payload_carries_the_python_action(tmp_path, monkeypatch):
    client, params, _ = _poll_client(monkeypatch, tmp_path, high=95, point=92, minutes=15)
    with client:
        wait = client.get("/api/arrivals", params={**params, "reroute": 0}).json()
    assert wait["chosen_action"] == "wait"
    client, params, _ = _poll_client(monkeypatch, tmp_path, high=95, point=92, minutes=4)
    with client:
        leave = client.get("/api/arrivals", params={**params, "reroute": 0}).json()
    assert leave["chosen_action"] == "leave_now"


def test_reroute_options_names_the_entry_and_rejects_others(tmp_path, monkeypatch):
    client, params, _ = _poll_client(monkeypatch, tmp_path, high=30, point=20)
    options = {k: params[k] for k in ("stop_code", "service_no", "lat", "lon", "destination_stop_code", "dest_lat", "dest_lon")}
    options["accuracy"] = 12
    with client:
        better = client.get("/api/reroute-options", params={**options, "entry": "better"}).json()
        missed = client.get("/api/reroute-options", params=options).json()
        bad = client.get("/api/reroute-options", params={**options, "entry": "other"})
    assert better["options"]["entry"] == "better" and missed["options"]["entry"] == "recommended"
    assert bad.status_code == 422


# ---- If you miss it -----------------------------------------------------------------------

def _bus(minutes, *, missed=False, primary=False, monitored=True):
    return {
        "position": "NextBus", "arrival_time": (NOW + timedelta(minutes=minutes)).isoformat(), "is_missed": missed,
        "is_primary": primary, "monitored": monitored, "latitude": LAT, "longitude": LON,
        "probability": None if missed else {"point": 90, "range_low": 80, "range_high": 95, "slack_seconds": 90, "data_quality": "live"},
    }


TERMS = {"board_walk_minutes": 3, "wait_minutes": 4, "ride_minutes": 12, "end_walk_metres": 150}


def test_if_you_miss_uses_the_arrival_after_the_tracked_one_not_the_tracked_one():
    buses = [_bus(3, missed=True), _bus(15, primary=True), _bus(30)]
    tracked = buses[1]
    line = miss_line(NOW, "11", buses, TERMS, None, tracked=tracked)
    assert line["in_minutes"] == 30
    tile = bus_arrival_window(NOW, TERMS, datetime.fromisoformat(tracked["arrival_time"]), live=True)
    assert datetime.fromisoformat(line["estimated_arrival"]) > tile["estimated_arrival"]
    # Without the tracked bus argument the first arrival that is not missed is the tracked one.
    assert miss_line(NOW, "11", buses, TERMS, None)["in_minutes"] == 30
    # Nothing later: the row is hidden.
    assert miss_line(NOW, "11", buses[:2], TERMS, None, tracked=tracked) is None
    assert miss_line(NOW, "11", [_bus(3, missed=True), _bus(15, primary=True)], TERMS, None) is None


def test_if_you_miss_reaches_the_page_through_the_endpoint_helper():
    cache = StopAndRouteCache(
        [{"BusStopCode": ORIGIN, "Description": "Origin", "RoadName": "Rd", "Latitude": LAT, "Longitude": LON},
         {"BusStopCode": DEST, "Description": "Destination", "RoadName": "Rd", "Latitude": north(2000)[0], "Longitude": LON}],
        [{"ServiceNo": "11", "Direction": 1, "BusStopCode": ORIGIN, "StopSequence": 1, "Distance": 0},
         {"ServiceNo": "11", "Direction": 1, "BusStopCode": DEST, "StopSequence": 5, "Distance": 2}],
        [],
    )
    buses = [_bus(3, missed=True), _bus(15, primary=True), _bus(30)]
    payload = {"buses": buses}
    dest_lat, dest_lon = north(2000)
    main._attach_arrival_estimate(
        payload, cache=cache, now=NOW, user_lat=LAT, user_lon=LON, dest_lat=dest_lat, dest_lon=dest_lon,
        destination_stop_code=DEST, boarding_stop_code=ORIGIN, service_no="11", arrive_by=None, route_type=None,
        leg_index=None, leg1_ride_minutes=None, leg2_ride_minutes=None, leg1_direction=None,
    )
    assert payload["if_you_miss"]["in_minutes"] == 30
    assert payload["if_you_miss"]["estimated_arrival"] > payload["arrival_estimate"]["estimated_arrival"]


# ---- question bar colours ----------------------------------------------------------------

def _luminance(hex_value):
    r, g, b = [int(hex_value.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channel = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_yes_and_no_use_status_tokens_with_four_and_a_half_to_one_text_in_both_themes():
    values = {}
    for name in ("action-yes", "action-no", "action-ink"):
        found = re.findall(rf"--{name}: (#[0-9A-Fa-f]{{6}});", THEME)
        assert len(found) == 4, name  # light, dark media, light explicit, dark explicit
        values[name] = found
    for yes, no, ink in zip(values["action-yes"], values["action-no"], values["action-ink"]):
        assert _ratio(yes, ink) >= 4.5 and _ratio(no, ink) >= 4.5
    assert 'class="primary action-yes"' in HTML and 'class="secondary action-no"' in HTML
    assert "M5 12.5l4.5 4.5L19 7.5" in HTML.split('id="catch-yes"', 1)[1].split("</button>", 1)[0]  # check icon
    assert "M6 6l12 12M18 6L6 18" in HTML.split('id="catch-no"', 1)[1].split("</button>", 1)[0]  # X icon
    assert "background: var(--action-yes)" in CSS and "background: var(--action-no)" in CSS
    assert "min-height: var(--tap-min)" in between(CSS, ".catch-bar__actions button {", "}")
    focus = between(CSS, ".catch-bar__actions .action-yes:focus-visible,", "}")
    assert "outline: 2px solid var(--color-focus)" in focus  # blue: different from the green and red fills


# ---- refresh, Back and the leave confirm -----------------------------------------------

def test_the_refresh_uses_the_existing_cooldown_demo_rule_and_adds_no_timer():
    block = between(HTML, "    var pageC = null;", "    function syncRerouteBlock()")
    assert "MANUAL_REFRESH_MIN_SECONDS * 1000" in block and "demoModeOn()" in block
    assert 'setAttribute("aria-disabled", blocked ? "true" : "false")' in block and 'classList.toggle("is-spinning"' in block
    assert "setInterval" not in block and "setTimeout" not in block
    assert "syncPageCRefresh();" in between(HTML, "function refreshDisplay(generation)", "function clearPrimaryBus")  # the existing tick
    assert 'aria-label="Refresh other buses"' in HTML and "Refresh other buses" in COPY
    assert "@media (prefers-reduced-motion: no-preference) {\n  .refresh-button.is-spinning .icon" in CSS
    assert 'id="reroute-updated"' in HTML and 'var UPDATED_TEXT = "Updated {time}";' in HTML


def test_back_keeps_the_confirm_while_polling_and_skips_it_after_no():
    back = _function("requestBack")
    assert "monitoringActive && !returnsWithoutConfirm()" in back and "openLeaveDialog()" in back
    missed = _function("answerMissed")
    assert missed.index("stopTracking()") < missed.index('openPageC("missed", missedEpoch)')  # polling is off: no confirm
    assert "monitoringActive = false" in _function("stopTracking")
    # Page C is a view of the live screen: Back from it uses the live-screen history entry, so it returns to the overview.
    assert 'pushScreen("reroute")' not in HTML
    # Page B opened from Page C returns to Page C without a confirm.
    assert 'return top === "newjourney" || top === "arrivals";' in HTML


def test_polls_while_page_c_is_open_ask_the_server_to_skip_the_reroute_evaluation():
    request = _function("requestArrivals")
    assert 'pageC && pageC.entry === "unlikely"' in request and '"&reroute=0"' in request


def test_a_switch_from_page_c_decides_again_for_the_new_bus():
    assert "entryPending = true" in _function("startMonitoring")  # applyRouteSwitch calls startMonitoring
    assert "closePageC()" in _function("finishNewJourney")
    assert "startMonitoring(reroute.service_no)" in _function("applyRouteSwitch")


# ---- the probability heading, the muted line and the ring label ---------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_muted_line_and_the_ring_label_follow_the_agreed_wording():
    script = (
        'var ARRIVING_IN_TEXT = "Arriving in {n} min", ARRIVING_SOON_TEXT = "Arriving in <1 min", ARRIVING_NOW_TEXT = "Arriving now";'
        'var RING_LABEL_TEXT = "{p} percent chance of catching Bus {service}{eta}{at}, range {a} to {b} percent";'
        'var RING_ETA_TEXT = " arriving in {n} minutes", RING_ETA_SOON_TEXT = " arriving in under 1 minute", RING_ETA_NOW_TEXT = " arriving now", RING_AT_TEXT = " at {stop}";'
        "var selectedService = '11'; var selectedBoardingStop = {description: 'Tanjong Rhu Stn Exit 2', stop_code: '90041'};"
        + _function("fillText") + "\n" + _function("boardingStopName") + "\n" + _function("etaParts") + "\n" + _function("ringLabel") + "\n"
        + "var at = function (s) { return {arrival_time: new Date(Date.now() + s * 1000).toISOString(), is_missed: false}; };"
        "var chance = {point: 92, range_low: 80, range_high: 95};"
        "console.log(JSON.stringify({min15: etaParts(at(900)).line, soon: etaParts(at(45)).line, now: etaParts(at(10)).line, none: etaParts({is_missed: false}),"
        " missed: etaParts({is_missed: true, arrival_time: at(60).arrival_time}),"
        " label: ringLabel(chance, at(900)), noEta: ringLabel(chance, null), nowLabel: ringLabel(chance, at(10))}));"
    )
    got = _run_node(script)
    assert got["min15"] == "Arriving in 15 min" and got["soon"] == "Arriving in <1 min" and got["now"] == "Arriving now"
    assert got["none"] is None and got["missed"] is None
    assert got["label"] == "92 percent chance of catching Bus 11 arriving in 15 minutes at Tanjong Rhu Stn Exit 2, range 80 to 95 percent"
    assert got["noEta"] == "92 percent chance of catching Bus 11 at Tanjong Rhu Stn Exit 2, range 80 to 95 percent"
    assert got["nowLabel"] == "92 percent chance of catching Bus 11 arriving now at Tanjong Rhu Stn Exit 2, range 80 to 95 percent"


def test_the_stop_line_truncates_on_one_line_with_the_full_name_in_a_title_and_leg_2_shows_minutes_only():
    sub = _function("setCatchSub")
    assert 'var stop = onLeg2() ? "" : boardingStopName();' in sub
    assert 'stopEl.setAttribute("title", stop)' in sub
    assert "sepEl.hidden = !(eta && stop)" in sub and 'document.getElementById(prefix + "-sub").hidden = !(eta || stop)' in sub
    rule = between(CSS, ".catch-card__sub {", "}")
    assert "white-space: nowrap" in rule and "min-width: 0" in rule
    stop = between(CSS, ".catch-card__stop {", "}")
    assert "overflow: hidden" in stop and "text-overflow: ellipsis" in stop and "min-width: 0" in stop
    assert "flex: 0 0 auto" in between(CSS, ".catch-card__eta,", "}")
    for prefix in ("catch", "pc"):
        assert f'id="{prefix}-sub-stop"' in HTML and f'id="{prefix}-sub-eta"' in HTML
    assert "Arriving in {n} min" in COPY and "Chance to catch your Bus {service}" in COPY
    assert 'ringLabel: "{p} percent chance of catching Bus {service}{eta}{at}, range {a} to {b} percent"' in COPY


def test_the_pill_shares_a_row_with_the_heading_and_the_heading_wraps_instead_of_overlapping():
    assert "position: absolute" not in between(CSS, ".catch-card__pill {", "}")
    head = between(CSS, ".catch-card__head {", "}")
    assert "display: flex" in head and "justify-content: space-between" in head
    assert "min-width: 0" in between(CSS, ".catch-card__heading {", "}")  # the heading shrinks and wraps beside the pill
    for prefix in ("catch", "pc"):
        after = HTML.split(f'id="{prefix}-title"', 1)[1].split('<div class="catch-card__row">', 1)[0]
        assert after.index(f'id="{prefix}-pill"') < after.index(f'id="{prefix}-sub"')  # head row (title, pill), then the muted line


def test_no_old_heading_remains_in_the_repo():
    for path in list(STATIC.glob("*")) + [ROOT / "PROJECT_PLAN.md"] + list((ROOT / "tests").glob("test_*.py")):
        if path.suffix in (".html", ".js", ".css", ".md", ".py") and path.name != "test_page_c_entry.py":
            assert "Chance to catch current Bus" not in path.read_text(encoding="utf-8"), path.name

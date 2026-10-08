"""Page W, "Walk to your stop": navigation, state machine, parity with the server, map, watch, ring and trend.

The browser part drives the real page in headless Edge with a fake location API (tests/js/scenarios/walkpage.mjs); the
pure helpers (walkStateOf, walkTrendNext, walkMinutesOf, haversineMetres) also run in node against the server's numbers.
"""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from nearby import haversine_m
from walk_speed import walk_minutes

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
NB = "\u00a0"


def _between(text, start, end):
    return start + text.split(start, 1)[1].split(end, 1)[0]


PAGE_W = _between(INDEX, "// ---- Page W:", "// Screen 8:")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("walk"), eta_minutes=[10.3]) as base:
        return run_scenario("walkpage", base, {})["result"]


def _node(program):
    done = subprocess.run([NODE, "-e", program], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout)


def _helpers():
    """The page's pure helpers, cut out of the page source by name."""
    source = "var WALK_ONWAY_METRES = 5; var WALK_ONWAY_WINDOW_MS = 10000; var WALK_TREND_STEP = 2;\n"
    for name in ("walkMinutesOf", "walkStateOf", "walkTrendNext", "walkWhyOf", "walkProgressOf"):
        start = PAGE_W.index("function " + name + "(")
        end = PAGE_W.index("\n    }\n", start) + len("\n    }\n")
        source += PAGE_W[start:end]
    return source


# ---- navigation

def test_page_a_has_the_button_row_and_the_pace_line_is_its_subtitle(report):
    page = report["pageA"]
    assert "See current location and walking pace" in page["row"]
    assert page["sub"] == "Walking pace: 4.5 km/h · normal pace"  # the same pace line as before, now the muted subtitle
    assert page["caption"] == "if you leave now and walk at a normal pace"  # the caption under the ring stays
    assert page["cardLines"] == 0 and page["top"] == "live"  # no pace line under the caption any more


def test_a_to_w_to_b_and_back(report):
    assert report["open"]["top"] == "walk" and report["open"]["stack"] == ["home", "journey", "live", "walk"]
    assert report["open"]["pageW"] is True and report["open"]["pageA"] is False and report["open"]["walkHidden"] is False
    assert report["open"]["title"] == "Walk to your stop" and report["open"]["bar"] is True  # the sticky button shows
    assert report["pageB"]["top"] == "arrivals" and report["pageB"]["stack"][-2:] == ["walk", "arrivals"]
    assert report["backToW"]["top"] == "walk" and report["backToW"]["pageW"] is True  # Back returns to where you came from
    assert report["backToA"]["top"] == "live" and report["backToA"]["pageA"] is True
    assert report["dialogOpen"] is False  # Back from Page W keeps the journey running, with no leave dialog


# ---- the state machine

def test_approaching_not_moving_moving_away_arrived_checking_and_waiting(report):
    assert report["approaching"] == ["Checking your movement…", "Checking your movement…", "On your way"]
    assert report["notMoving"] == ["Checking your movement…", "Checking your movement…", "Not moving"]
    assert report["movingAway"] == ["Checking your movement…", "Moving away from the stop"]
    assert report["arrived"]["state"] == "Arrived at the stop" and report["nearStopFlag"] is True  # the server's flag decides
    assert report["arrived"]["progress"] == 100
    assert report["noFixText"] == "Waiting for your location…"
    assert report["open"]["distance"] == "300" + NB + "m to the stop" and report["open"]["minutes"] == "about 4" + NB + "min walk"


@needs_node
@pytest.mark.parametrize("drop, seconds, expected", [
    (4.9, 10, "still"), (5.0, 10, "onway"), (5.0, 9.9, "checking"), (30, 10.1, "onway"), (0, 12, "still"),
    (-4.9, 12, "still"), (-5.0, 10, "away"), (-20, 12, "away"), (-20, 9.9, "checking"), (-5.0, 9.9, "checking"),
])
def test_the_movement_rule_is_5_m_over_10_s_and_checking_before_that(drop, seconds, expected):
    program = _helpers() + (
        f"var samples = [{{t: 0, d: 300}}, {{t: {seconds * 1000}, d: {300 - drop}}}];"
        "console.log(JSON.stringify(walkStateOf(true, false, samples, 99999)));"
    )
    assert _node(program) == expected


@needs_node
def test_waiting_arrived_and_the_empty_history():
    program = _helpers() + (
        "console.log(JSON.stringify([walkStateOf(false, false, [], 0), walkStateOf(true, true, [{t:0,d:900},{t:20000,d:100}], 0),"
        " walkStateOf(true, false, [], 0), walkStateOf(true, false, [{t:0,d:50}], 0)]));"
    )
    assert _node(program) == ["waiting", "arrived", "checking", "checking"]  # no history: checking, not "Not moving"


@needs_node
def test_the_arrived_state_is_the_servers_flag_not_the_distance():
    program = _helpers() + "console.log(JSON.stringify([walkStateOf(true, false, [{t:0,d:3},{t:20000,d:2}], 0), walkStateOf(true, true, [{t:0,d:300},{t:20000,d:300}], 0)]));"
    assert _node(program) == ["still", "arrived"]  # 2 m from the stop is not "arrived" until the server says near_stop


# ---- the numbers: distance and minutes agree with the server

@needs_node
def test_walking_minutes_match_the_servers_display_rounding_over_a_table():
    distances = list(range(0, 3001, 7)) + [29.9, 30, 30.1, 74.9, 75, 75.1, 187.4, 187.5, 187.6, 1999.5, 2250]
    speeds = [round(0.5 + 0.05 * i, 2) for i in range(19)] + [1.25, 1.1, 1.4, 0.77]
    program = _helpers() + (
        f"var d = {json.dumps(distances)}, s = {json.dumps(speeds)}, out = [];"
        "d.forEach(function (m) { s.forEach(function (v) { out.push(walkMinutesOf(m, v)); }); });"
        "console.log(JSON.stringify(out));"
    )
    got = _node(program)
    expected = [walk_minutes(m, v, "display") for m in distances for v in speeds]
    bad = [(i, g, x) for i, (g, x) in enumerate(zip(got, expected)) if g != x]
    assert len(got) == len(expected) > 1500 and not bad, bad[:3]
    assert "Math.max(1, Math.round(metres / speed / 60))" in PAGE_W  # the same rule as the server's display mode


@needs_node
def test_the_page_distance_is_the_servers_haversine():
    code = _between(INDEX, "function haversineMetres(lat1, lon1, lat2, lon2) {", "function exitJourney")
    code = code.split("\n    function exitJourney", 1)[0]
    pairs = [(1.3, 103.8, 1.3027, 103.8), (1.3521, 103.8198, 1.2966, 103.8520), (1.3, 103.8, 1.3, 103.8), (1.4, 103.7, 1.2, 103.9)]
    program = code + f"\nvar p = {json.dumps(pairs)};console.log(JSON.stringify(p.map(function (a) {{ return haversineMetres(a[0], a[1], a[2], a[3]); }})));"
    got = _node(program)
    for (a, b, c, d), value in zip(pairs, got):
        assert abs(value - haversine_m(a, b, c, d)) < 0.5, (a, b, c, d, value)


# ---- the map

def test_the_map_has_the_markers_the_line_and_the_accuracy_circle(report):
    opened = report["open"]
    assert opened["mapInSlot"] and opened["you"] == 1 and opened["stop"] == 1 and opened["line"] == 1 and opened["accuracy"] == 1
    assert "walk-line" in PAGE_W and "className: \"walk-line\"" in PAGE_W  # a CSS class, no routing service
    assert not re.search(r"routing|osrm|directions|valhalla", PAGE_W, re.I)


def test_the_marker_moves_without_re_fitting_after_a_pan_and_recentre_refits(report):
    fitted, panned, after, recentred = report["fitted"], report["panned"], report["afterPan"], report["recentred"]
    assert panned["center"] == [1.32, 103.82] and panned["zoom"] == 14  # the user panned and zoomed
    assert after["youLatLng"] != panned["youLatLng"]  # the marker moved to the new fix
    assert after["center"] == panned["center"] and after["zoom"] == panned["zoom"]  # and the map was not re-fitted
    assert recentred["center"] != after["center"] and recentred["zoom"] != after["zoom"]  # Recentre fits both markers again
    assert fitted["zoom"] == 17 or fitted["zoom"] >= 16


def test_the_direction_wedge_needs_a_heading_and_a_speed_above_half_a_metre_per_second(report):
    assert report["wedgeMoving"] is False  # heading 180 at 1.3 m/s: shown
    assert report["wedgeNoHeading"] is True and report["wedgeSlow"] is True
    assert "WALK_HEADING_MIN_SPEED = 0.5" in PAGE_W


def test_the_accuracy_circle_is_capped_and_the_uncertain_card_shows(report):
    poor = report["poorAccuracy"]
    assert poor["accuracy"] == 150 and poor["radius"] <= poor["cap"] + 0.01 and poor["radius"] > 1  # large but never the whole map
    assert poor["card"] is True and poor["cardTitle"] == "Location uncertain"  # the existing card, in the shared alert strip


@needs_node
def test_the_marker_transition_is_at_most_a_second_and_off_for_reduced_motion():
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    assert re.search(r"\.walk-map \.leaflet-marker-icon\.walk-you \{[^}]*transition: transform 1s linear;", css)
    reduced = css.split("@media (prefers-reduced-motion: reduce) {\n  .walk-map .leaflet-marker-icon.walk-you {", 1)[1].split("}", 1)[0]
    assert "transition: none;" in reduced


# ---- the watch and the rescore

def test_the_pages_own_watch_runs_only_while_open_visible_and_not_fed_by_the_estimator(report):
    assert report["open"]["ownWatch"] is False and report["open"]["watching"] == 1 and report["open"]["estimatorRunning"] is True
    own = report["watchOwn"]
    assert own["own"] is True and own["watching"] == 1 and own["estimator"] is False
    assert own["options"] == {"enableHighAccuracy": True, "maximumAge": 0}  # high accuracy
    assert report["watchHidden"] == {"own": False, "watching": 0}  # a hidden page stops it
    assert report["watchShown"] == {"own": True, "watching": 1}


def test_the_watch_and_the_rescore_stop_on_back_and_at_the_end_of_tracking(report):
    assert report["pageB"]["ownWatch"] is False  # leaving for Page B
    assert report["backToA"]["ownWatch"] is False
    assert report["beforeEnd"] == {"own": True, "timer": True}
    assert report["afterEnd"] == {"own": False, "timer": False, "watching": 0}


def test_the_rescore_runs_about_every_5_seconds_only_while_open_and_visible(report):
    assert len(report["rescoreUrls"]) == 1 and report["rescoreSecondCall"] == 1  # a second call within 5 s sends nothing
    assert report["rescoreWhileHidden"] == 0 and report["timerWhileHidden"] is False and report["timerWhenVisible"] is True
    url = report["rescoreUrls"][0]
    for name in ("stop_code=", "service_no=", "lat=", "lon=", "accuracy=", "location_timestamp="):
        assert name in url  # the poll's own parameter names
    assert "WALK_RESCORE_MS = 5000" in PAGE_W


def test_no_storage_no_logging_and_no_new_request_carries_the_position(report):
    assert "localStorage" not in INDEX and "sessionStorage" not in INDEX and "indexedDB" not in INDEX
    assert report["storageKeys"] == []
    assert "console." not in PAGE_W and "sendBeacon" not in PAGE_W and "XMLHttpRequest" not in PAGE_W
    assert PAGE_W.count("fetch(") == 1 and 'var url = "/api/rescore?stop_code="' in PAGE_W  # the rescore is its only request
    since = report["requestsAll"][report["requestsBefore"]:]
    carrying = {re.match(r"/[^?]*", url).group(0) for url in since if re.search(r"[?&](lat|lon|user_lat|user_lon)=", url)}
    assert carrying <= {"/api/arrivals", "/api/rescore"}, carrying  # the poll and the rescore only
    assert "walkChanceSource" in PAGE_W and not re.search(r"(Storage|document\.cookie|history\.replaceState)", PAGE_W)


# ---- the ring and the trend follow the server's values

def test_the_ring_is_the_servers_point_and_the_bus_arrival_time_replaces_the_range(report):
    chance = report["chance"]
    assert report["open"]["ring"] == f"{chance['point']}%"
    # the range is still in the server's numbers (the decisions use it) but it is not displayed on Page W
    assert isinstance(chance["low"], int) and isinstance(chance["high"], int) and chance["low"] <= chance["point"] <= chance["high"]
    assert report["open"]["rangeElement"] is False and "Range" not in report["open"]["cardText"] and "range" not in report["open"]["cardText"]
    assert str(chance["low"]) + " – " + str(chance["high"]) not in report["open"]["cardText"]
    # at the right of the ring: the muted label and the bus arrival clock time, 12-hour with a no-break space
    assert report["open"]["arrivesHidden"] is False and report["open"]["arrives"] == chance["clock"]
    assert re.fullmatch(r"\d{1,2}:\d\d (AM|PM)", report["open"]["arrives"]), report["open"]["arrives"]
    assert "Bus arrives" in report["open"]["cardText"]
    assert report["open"]["heading"] == "Chance to catch Bus 18"
    assert 'role="img"' in INDEX.split('id="walk-ring"', 1)[1].split(">", 1)[0]  # the ring is an image with an aria-label
    assert '<section class="card catch-card walk-chance" aria-live="polite"' in INDEX  # and announced politely
    assert "Math.exp" not in PAGE_W and "sigmoid" not in PAGE_W.lower()  # no scoring on the phone


TREND_BY_STATE = {  # (trend, state) -> the line
    ("rising", "onway"): "Rising as you get closer", ("rising", "away"): "Rising", ("rising", "still"): "Rising",
    ("falling", "onway"): "Falling as time passes", ("falling", "away"): "Falling as you move away",
    ("falling", "still"): "Falling as time passes",
}


@pytest.mark.parametrize("state", ["onway", "away", "still"])
def test_the_trend_shows_only_after_a_change_of_2_points_or_more_and_follows_the_state(report, state):
    seq = report["trendSeq"][state]
    assert [row["ring"] for row in seq] == ["60%", "61%", "64%", "64%", "64%", "60%"]  # the ring follows each server value
    assert [row["state"] for row in seq] == [{"onway": "On your way", "away": "Moving away from the stop", "still": "Not moving"}[state]] * 6
    assert [row["hidden"] for row in seq] == [True, True, False, False, False, False]
    assert [row["trend"] for row in seq] == [
        "", "", TREND_BY_STATE[("rising", state)], TREND_BY_STATE[("rising", state)], "Steady", TREND_BY_STATE[("falling", state)]]
    assert all("Range" not in row["cardText"] and "–" not in row["cardText"] for row in seq)  # no range text on the card


@needs_node
def test_the_trend_key_is_chosen_from_the_trend_and_the_state():
    program = _helpers() + _trend_key() + (
        "var out = {}; ['rising', 'falling', 'steady', null].forEach(function (t) { ['onway', 'away', 'still', 'checking', 'arrived', 'waiting'].forEach(function (s) { out[t + '|' + s] = walkTrendKey(t, s); }); });"
        "console.log(JSON.stringify(out));"
    )
    got = _node(program)
    assert got["rising|onway"] == "risingCloser" and got["falling|away"] == "fallingAway"
    for state in ("away", "still", "checking", "arrived", "waiting"):
        assert got[f"rising|{state}"] == "rising"
    for state in ("onway", "still", "checking", "arrived", "waiting"):
        assert got[f"falling|{state}"] == "falling"
    assert all(got[f"steady|{s}"] == "steady" for s in ("onway", "away", "still")) and got["null|onway"] == ""


def _trend_key():
    start = PAGE_W.index("function walkTrendKey(")
    return PAGE_W[start: PAGE_W.index("\n    }\n", start) + len("\n    }\n")]


@needs_node
def test_the_trend_rule_in_isolation():
    program = _helpers() + (
        "var s = {anchor: null, text: null, calm: 0}, out = [];"
        "[50, 50, 51, 52, 52, 52, 49, 49, 49, 55].forEach(function (p) { s = walkTrendNext(s, p); out.push(s.text); });"
        "console.log(JSON.stringify(out));"
    )
    assert _node(program) == [None, None, None, "rising", "rising", "steady", "falling", "falling", "steady", "rising"]


# ---- Sensor details

def test_sensor_details_is_closed_by_default_and_reads_the_estimator_state(report):
    assert report["sensorsClosed"]["sensorsOpen"] is False
    opened = report["sensorsOpen"]
    assert opened["open"] is True and opened["expanded"] == "true"
    pace, gps, accuracy, cadence, step, samples = opened["rows"]
    assert pace == "4.5" + NB + "km/h · average pace"  # the server's speed and its source, in plain words
    assert gps == "4.7" + NB + "km/h" and accuracy == "8" + NB + "m"
    assert cadence == "114"  # 1.9 steps per second: a stride-doubled cadence is shown exactly like a normal one
    assert step == "0.72" + NB + "m" and samples == "4"
    assert opened["why"] == "Not walking yet" and opened["whyHidden"] is False  # no measured speed: one why line


@needs_node
def test_the_why_line_and_the_source_words():
    program = _helpers() + (
        "console.log(JSON.stringify([walkWhyOf(true, false, {latched: false}), walkWhyOf(false, true, {latched: false}),"
        " walkWhyOf(false, false, {latched: true}), walkWhyOf(false, false, {permission: 'denied'}),"
        " walkWhyOf(false, false, {permission: 'granted', latched: false}), walkWhyOf(false, false, null),"
        " walkWhyOf(true, true, {latched: false}), walkWhyOf(true, false, {latched: true})]));"
    )
    # near the stop wins even with a held, measured speed: nothing is measured now
    assert _node(program) == ["", "nearStop", "nearStop", "noPermission", "notWalking", "noPermission", "nearStop", "nearStop"]
    for words in ("from GPS", "from your steps", "your usual pace", "average pace"):
        assert f'"{words}"' in PAGE_W
    assert "stride" not in PAGE_W.lower()  # a stride-doubled cadence has no special display


def test_demo_mode_shows_the_simulated_tag(report):
    assert report["simulatedOff"] is True and report["simulatedOn"] is True


def test_stale_data_keeps_the_layout_with_an_unavailable_ring(report):
    assert report["staleRing"]["ring"] == "Unavailable" and report["staleRing"]["arrivesHidden"] is True and report["staleRing"]["arrives"] == ""


# ---- the strings: page and copy.js agree

def test_the_page_strings_are_in_copy_js():
    esc = chr(92) + "u00a0"
    for text in ("See current location and walking pace", "Walk to your stop", "{distance} to the stop", "about {n}" + esc + "min walk",
                 "On your way", "Not moving", "Arrived at the stop", "Waiting for your location…",
                 "Recentre map", "Sensor details", "Moving away from the stop", "Checking your movement…", "Rising as you get closer", "Falling as you move away", "Steady",
                 "from GPS", "from your steps", "your usual pace", "average pace", "Not walking yet", "No motion permission",
                 "Near the stop", "Walking pace", "GPS speed", "GPS accuracy", "Steps per minute", "Step length", "Learned samples"):
        assert f'"{text}"' in COPY, text
    for text in ("Walk to your stop", "{distance} to the stop", "On your way", "Not moving", "Arrived at the stop",
                 "Moving away from the stop", "Checking your movement…",
                 "Waiting for your location…", "Rising as you get closer", "Falling as you move away", "Steady",
                 "Not walking yet", "No motion permission", "Near the stop", "from GPS", "from your steps", "your usual pace",
                 "average pace", "about {n}" + esc + "min walk"):
        assert f'"{text}"' in INDEX, text
    for label in ("Sensor details", "Walking pace", "GPS speed", "GPS accuracy", "Steps per minute", "Step length", "Learned samples",
                  "Recentre map", "See current location and walking pace"):
        assert label in INDEX, label


# ---- Sensor details in every speed case (open panel)

@pytest.fixture(scope="module")
def sensors(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("sensors"), eta_minutes=[10.3]) as base:
        return run_scenario("walksensors", base, {})["result"]


def test_sensor_details_for_a_speed_measured_from_gps(sensors):
    case = sensors["cases"]["gps"]
    assert case["open"] is True and case["expanded"] == "true"
    assert case["rows"] == ["4.7" + NB + "km/h · from GPS", "4.7" + NB + "km/h", "8" + NB + "m", "108", "0.72" + NB + "m", "4"]
    assert case["whyHidden"] is True and case["why"] == ""  # a measured speed has no why line


def test_sensor_details_for_a_speed_from_your_steps_and_a_stride_doubled_cadence_reads_the_same_way(sensors):
    cadence = sensors["cadence"]
    assert cadence["normalPick"] == "ok" and cadence["stridePick"] == "stride_doubled"  # the real estimator's two picks
    steps, stride = sensors["cases"]["steps"], sensors["cases"]["stridesteps"]
    assert steps["rows"][0] == "4.3" + NB + "km/h · from your steps" and steps["rows"][3] == str(round(cadence["normal"] * 60))
    assert stride["rows"][0].endswith(" · from your steps")  # exactly like a normal cadence: the same words
    assert stride["rows"][3] == str(round(cadence["stride"] * 60)) == "120"  # the doubled value, shown as a number of steps
    assert steps["whyHidden"] is True and stride["whyHidden"] is True
    assert steps["rows"][1] == "—" and stride["rows"][1] == "—"  # no GPS speed in these two cases


@pytest.mark.parametrize("name, why", [("notwalking", "Not walking yet"), ("nopermission", "No motion permission")])
def test_sensor_details_with_no_speed_measured_gives_one_why_line(sensors, name, why):
    case = sensors["cases"][name]
    assert case["why"] == why and case["whyHidden"] is False
    assert case["rows"][0] == "4.5" + NB + "km/h · average pace"
    assert case["rows"][4] == "0.70" + NB + "m" and case["rows"][5] == "0"  # no samples: the starting step length


def test_near_the_stop_after_the_real_latch_the_pace_keeps_its_measured_value_and_source(sensors):
    before, after = sensors["beforeLatch"], sensors["afterLatch"]
    assert before["status"]["running"] is True and before["source"] == "gps" and before["why"] == "" and before["whyHidden"] is True
    assert after["status"]["latched"] is True and after["status"]["running"] is False  # the estimator stopped near the stop
    assert after["pollValue"] == before["pollValue"] == {"speed": 1.2, "source": "gps"}  # the last smoothed speed is still sent
    assert after["query"] == "&walk_speed=1.2&walk_speed_source=gps"
    assert after["source"] == "gps" and after["used"] == 1.2  # the server keeps answering with the measured source
    assert after["rows"][0] == "4.3" + NB + "km/h · from GPS"  # not "average pace"
    assert after["why"] == "Near the stop" and after["whyHidden"] is False  # nothing is measured now


def test_the_why_line_is_directly_under_the_title_in_body_text_with_an_icon_and_is_silent(sensors):
    cases = [sensors["cases"][n] for n in ("notwalking", "nopermission")] + [sensors["afterLatch"]]
    for case in cases:
        assert case["whyIsFirstInPanel"] is True and case["whyBeforeRows"] is True, case
        assert case["whyFont"] == case["bodyFont"] and case["whyFont"] > case["captionFont"], case  # body text, not caption size
        assert case["whyIcon"] is True and case["whySilent"] is True, case
    assert 'id="walk-sensor-why" class="walk-sensors__why" hidden>' in INDEX and "aria-live" not in INDEX.split('id="walk-sensor-why"', 1)[1].split("</p>", 1)[0]


def test_with_no_learned_samples_the_step_length_is_the_starting_value(sensors):
    assert sensors["fresh"]["rows"][4] == "0.70" + NB + "m" and sensors["fresh"]["rows"][5] == "0"  # a real fresh estimator
    assert sensors["afterLatch"]["rows"][4] == "0.70" + NB + "m" and sensors["afterLatch"]["rows"][5] == "0"


@needs_node
def test_a_stored_length_without_a_stored_count_cannot_show_0_72_with_0_samples():
    program = (
        "var W = require(" + json.dumps(str(ROOT / "static" / "walk-speed.js")) + ");"
        "var stored = function (v) { return { getItem: function () { return JSON.stringify(v); }, setItem: function () {} }; };"
        "var out = { prior: W.CONSTANTS.STEP_LEN_PRIOR, none: W.loadStep(null), zero: W.loadStep(stored({ length: 0.72, count: 0, savedAt: 1 })),"
        " one: W.loadStep(stored({ length: 0.72, count: 1, savedAt: 1 })), fresh: W.createEstimator({ storage: null }).snapshot() };"
        "console.log(JSON.stringify({ prior: out.prior, none: out.none, zero: out.zero, one: out.one, length: out.fresh.stepLength, count: out.fresh.stepCount }));"
    )
    got = _node(program)
    assert got["prior"] == 0.70 and got["none"] == {"length": 0.7, "count": 0} and got["zero"] == {"length": 0.7, "count": 0}
    assert got["one"] == {"length": 0.72, "count": 1}  # 0.72 only ever appears with at least one sample
    assert got["length"] == 0.70 and got["count"] == 0



# ---- the straight-line line is gone; the progress fill is the success token

def test_the_straight_line_line_is_gone_everywhere():
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    guide = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
    for text in (INDEX, COPY, css, guide):
        assert "straight-line distance" not in text and "straightLine" not in text and "walk-status__note" not in text


def test_the_progress_fill_uses_the_success_ring_token():
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    block = css.split(".walk-progress::-webkit-progress-value", 1)[1].split("}", 1)[0]
    assert "var(--prob-ring-ok)" in block
    assert css.split(".walk-progress::-moz-progress-bar", 1)[1].split("}", 1)[0].count("var(--prob-ring-ok)") == 1

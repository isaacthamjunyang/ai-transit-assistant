"""The On your way screen: one per-leg layout for a bus and a train, the progress ticks and the "Next:" line (schedule
only), and the "Get off" alert (the phone's position, read and compared on the phone only).

The browser tests drive the real page in headless Edge against the real app, a stubbed OneMap and a rail table
(tests/onemap_stub.py). The page clock is skewed with Date.now() so the schedule is walked through without waiting; no
live API is called."""

import json
import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
NB = chr(0xA0)


def _pairs(block: str) -> dict:
    return dict(re.findall(r'^\s*(\w+): "((?:[^"\\]|\\.)*)",?$', block, flags=re.M))


# ---- words: copy.js and the page say the same ---------------------------------------------------------------------


COPY_WAY = _pairs(COPY.split("  onWay: {", 1)[1].split("\n  },", 1)[0])
PAGE_WAY = _pairs(INDEX.split("var ON_WAY_TEXT = {", 1)[1].split("\n    };", 1)[0])


def test_the_on_way_words_are_copy_js_character_for_character():
    assert COPY_WAY == PAGE_WAY and len(COPY_WAY) == 10


def test_the_spec_words_are_exact():
    assert COPY_WAY["nextGetOff"] == "Next: Get off at {place}"
    assert COPY_WAY["nextWalk"] == "Next: Walk {n}\\u00a0min to {place}"
    assert COPY_WAY["getOffBus"] == "Get off next stop: {place}"
    assert COPY_WAY["getOffTrain"] == "Get off at {station}"
    assert COPY_WAY["openNote"] == "Works while this page is open."
    assert "never sent, stored or logged" in COPY_WAY["privacy"] and "this phone" in COPY_WAY["privacy"]


def test_the_markup_words_match_copy_js():
    assert COPY_WAY["privacy"] in INDEX.split('id="on-way-privacy"', 1)[1].split("</p>", 1)[0]
    assert COPY_WAY["openNote"] in INDEX.split('id="on-way-open-note"', 1)[1].split("</p>", 1)[0]
    assert 'id="on-way-alert-dismiss" class="secondary">' + COPY_WAY["dismiss"] + "<" in INDEX


def test_the_new_code_uses_no_colour_and_no_inline_style():
    region = INDEX.split('// ---- "On your way": every route', 1)[1].split("// No, for a train: the left text", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", region) and ".style." not in region
    css = CSS.split(".journey-step--leg-done {", 1)[1].split(".on-way-alert .secondary {", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", css) and "style=" not in css
    on_way_html = INDEX.split('<section id="on-way"', 1)[1].split("</section>", 1)[0]
    assert "style=" not in on_way_html


def test_the_old_four_row_bus_layout_is_gone():
    region = INDEX.split("function renderOnWay() {", 1)[1].split("function onWayRidingIndex", 1)[0]
    for old in ('"Boarding stop"', '"Bus service"', '"Transfer stop"', '"Destination stop"', "renderTrainOnWay"):
        assert old not in region, old
    assert "renderTrainOnWay" not in INDEX


def test_the_question_follows_the_tracked_first_leg_each_time_the_bar_syncs():
    sync = INDEX.split("function syncCatchBar() {", 1)[1].split("function tickTracking", 1)[0]
    assert 'isTrain() ? TRAIN_PAGE.question : CATCH_QUESTION_BUS' in sync
    assert 'say("catch-bar-title"' not in INDEX
    assert 'var CATCH_QUESTION_BUS = "Did you catch the bus?";' in INDEX
    assert COPY.count('question: "Did you catch the bus?"') == 1 and COPY.count('question: "Did you catch the train?"') == 1


def test_the_position_is_never_stored_or_given_to_request_state():
    region = INDEX.split("function readOnWayPosition(now) {", 1)[1].split("function stopOnWayReading", 1)[0]
    assert INDEX.count("setInterval(") == 3  # the page's three timers: this screen adds none
    for forbidden in ("userLat", "userLon", "localStorage", "sessionStorage", "fetch(", "sendBeacon", "XMLHttpRequest",
                      "console.", "encodeURIComponent", "watchPosition"):
        assert forbidden not in region, forbidden
    check = INDEX.split("function checkOnWayAlert(now) {", 1)[1].split("// The progress runs on", 1)[0]
    for forbidden in ("userLat", "fetch(", "sendBeacon", "localStorage", "console."):
        assert forbidden not in check, forbidden


def test_the_plan_states_the_progress_the_alert_and_the_privacy_rule():
    for text in ("**On your way progress and the Get off alert.**", "Next: Get off at {place}", "Get off next stop: {place}",
                 "Works while this page is open.", "400 m", "2 minutes", "never sent, stored or logged"):
        assert text in PLAN, text


def test_the_style_guide_shows_the_on_way_legs_the_next_line_and_the_alert_in_both_themes():
    section = GUIDE.split('id="legs-heading"', 1)[1].split("</section>", 1)[0]
    assert "onWayLegsSample" in GUIDE and "on-way-sample-light" in section and "on-way-sample-dark" in section
    sample = GUIDE.split("function onWayLegsSample()", 1)[1]
    assert "on-way-next" in sample and "journey-step--leg-done" in sample and "on-way-alert" in sample


# ---- the page in a browser ----------------------------------------------------------------------------------------


def _run(tmp_path_factory, name, builder, lta_status=200, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode({"TRANSIT": builder}), rail_table=_table(),
                     lta_status=lta_status) as base:
        return run_scenario("onway", base, {"name": name, **config}, timeout=360)["result"]


def _flat(text: str) -> str:
    return (text or "").replace(NB, " ")


def _kinds(rows) -> list:
    return [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in rows]


WALK_TO_DEST = r"Next: Walk \d+ min to Destination"

# (minutes from planning, steps ticked, the row that is "On board" or None, the Next line)
BUS_BUS_BUS = [
    (0, 0, 0, r"Next: Get off at .*"),
    (14.5, 1, None, r"Next: Walk \d+ min to .*"),
    (16.5, 2, None, r"Next: Board Bus 36 at .*"),
    (21, 2, 2, r"Next: Get off at .*"),
    (30.5, 3, None, r"Next: Walk \d+ min to .*"),
    (32.5, 4, None, r"Next: Board Bus 77 at .*"),
    (37, 4, 4, r"Next: Get off at .*"),
    (46.5, 5, None, WALK_TO_DEST),
    (49, 6, None, None),
]
BUS_TRAIN = [
    (0, 0, 0, r"Next: Get off at .*"),
    (14.5, 1, None, r"Next: Walk \d+ min to .* \(NS17\)"),
    (16.5, 2, None, r"Next: Board the North-South Line train at .* \(NS17\)"),
    (21, 2, 2, r"Next: Get off at .* \(NS26\)"),
    (30.5, 3, None, WALK_TO_DEST),
    (33, 4, None, None),
]
TRAIN_TRAIN = [
    (0, 0, 0, r"Next: Get off at .* \(NS26\)"),
    (20.5, 1, None, r"Next: Walk \d+ min to .* \(EW14\)"),
    (22.5, 2, None, r"Next: Board the East-West Line train at .* \(EW14\)"),
    (27, 2, 2, r"Next: Get off at .* \(EW15\)"),
    (34.5, 3, None, WALK_TO_DEST),
    (37, 4, None, None),
]


@pytest.fixture(scope="module")
def bus_bus(tmp_path_factory):
    return _run(tmp_path_factory, "busbus", stub.bus_chain, mode="progress", width=390, height=844, bus=True,
                stages=[row[0] for row in BUS_BUS_BUS])


@pytest.fixture(scope="module")
def bus_train(tmp_path_factory):
    return _run(tmp_path_factory, "bustrain", stub.bus_rail, mode="progress", width=390, height=844, bus=True,
                stages=[row[0] for row in BUS_TRAIN])


@pytest.fixture(scope="module")
def train_train(tmp_path_factory):
    return _run(tmp_path_factory, "traintrain", stub.train_transfer, lta_status=500, mode="progress", width=390,
                height=844, stages=[row[0] for row in TRAIN_TRAIN])


def _check_progress(run, kinds, plan):
    t0 = run["t0"]
    assert t0["screen"] == "onway" and t0["title"] == "On your way" and t0["planNew"] and t0["arrive"]
    assert _kinds(t0["rows"]) == kinds, _kinds(t0["rows"])
    first = t0["rows"][0]
    assert "journey-step--leg" in first["cls"] and first["bar"] is True and first["nodes"] == 2
    assert "On board" in first["text"] and re.search(r"\d+ stops? · \d+ min", _flat(first["text"]))
    assert not any(row["done"] for row in t0["rows"])
    assert run["timerRuns"] is True and len(run["stages"]) == len(plan)
    for (minutes, ticked, on_board, expected), snap in zip(plan, run["stages"]):
        label = f"at +{minutes} min"
        done = [row["done"] for row in snap["rows"]]
        assert done[:ticked] == [True] * ticked and not any(done[ticked:]), (label, done)
        for index, row in enumerate(snap["rows"]):
            if index < ticked and "journey-step--leg" in row["cls"]:
                assert "journey-step--leg-done" in row["cls"] and "On board" not in row["text"], (label, index)
            assert ("On board" in row["text"]) == (index == on_board), (label, index, row["text"])
        if expected is None:
            assert snap["next"] is None and snap["over"] is True and snap["timer"] is False, label
            assert snap["reading"] is False and snap["screen"] == "onway", label
        else:
            assert re.fullmatch(expected, _flat(snap["next"])), (label, snap["next"])
            assert snap["over"] is False and snap["timer"] is True and snap["reading"] is True, label
        assert snap["scrollWidth"] <= snap["innerWidth"], label


def test_progress_and_next_lines_for_bus_then_bus(bus_bus):
    _check_progress(bus_bus, ["bus", "walk", "bus", "walk", "bus", "walk", "destination"], BUS_BUS_BUS)
    assert [row["badge"] for row in bus_bus["t0"]["rows"] if row["badge"]] == ["Bus 18", "Bus 36", "Bus 77"] \
        or [row["badge"].replace("Bus ", "") for row in bus_bus["t0"]["rows"] if row["badge"]] == ["18", "36", "77"]


def test_progress_and_next_lines_for_bus_then_train(bus_train):
    _check_progress(bus_train, ["bus", "walk", "rail", "walk", "destination"], BUS_TRAIN)
    assert bus_train["t0"]["rows"][2]["badge"] == "NS"


def test_progress_and_next_lines_for_train_then_train(train_train):
    _check_progress(train_train, ["rail", "walk", "rail", "walk", "destination"], TRAIN_TRAIN)
    assert train_train["t0"]["rows"][0]["badge"] == "NS" and train_train["t0"]["rows"][2]["badge"] == "EW"


@pytest.fixture(scope="module")
def alert_bus(tmp_path_factory):
    return _run(tmp_path_factory, "alertbus", stub.bus_chain, mode="alert", width=390, height=844, bus=True,
                second=True, notify="default")


@pytest.fixture(scope="module")
def alert_train(tmp_path_factory):
    return _run(tmp_path_factory, "alerttrain", stub.train_transfer, lta_status=500, mode="alert", width=390, height=844,
                second=True, notify="granted")


def test_the_alert_fires_once_at_399_m_and_not_at_401_m_for_a_bus(alert_bus):
    r = alert_bus
    assert r["t0"]["alert"] is None and r["t0"]["reading"] is True
    assert r["at401"]["alert"] is None and r["at401"]["notes"] == []
    assert re.fullmatch(r"Get off next stop: .*", _flat(r["at399"]["alert"])), r["at399"]["alert"]
    assert r["at399"]["alertVisible"] is True
    assert r["again"]["alert"] == r["at399"]["alert"]
    assert r["dismissed"]["alert"] is None
    assert r["afterDismiss"]["alert"] is None  # once per leg: closer still, and it does not come back
    # permission was not granted: no browser notification, and the page never asked
    assert r["at399"]["notes"] == [] and r["afterDismiss"]["asked"] == 0
    # the next leg gets its own alert, with the same 401 / 399 rule
    assert r["second401"]["alert"] is None
    assert re.fullmatch(r"Get off next stop: .*", _flat(r["second399"]["alert"])), r["second399"]["alert"]


def test_the_alert_for_a_train_says_get_off_at_the_station_and_notifies_only_when_granted(alert_train):
    r = alert_train
    assert r["at401"]["alert"] is None and r["at401"]["notes"] == []
    assert re.fullmatch(r"Get off at .* \(NS26\)", _flat(r["at399"]["alert"])), r["at399"]["alert"]
    assert r["at399"]["notes"] == [r["at399"]["alert"]] and r["afterDismiss"]["notes"] == r["at399"]["notes"]
    assert r["afterDismiss"]["asked"] == 0
    assert r["second401"]["alert"] is None
    assert re.fullmatch(r"Get off at .* \(EW15\)", _flat(r["second399"]["alert"])), r["second399"]["alert"]
    assert len(r["second399"]["notes"]) == 2


def test_the_screen_reads_the_position_with_getcurrentposition_and_opens_no_watch(alert_bus):
    # the reads of this screen are the ones with a 5 s maximum age (the other calls in the log are the walking pages');
    # none of them is a watch
    mine = [o for o in alert_bus["readOptions"] if o and o.get("maximumAge") == 5000]
    assert mine and all(o["high"] is True and o["timeout"] == 10000 for o in mine)
    assert alert_bus["t0"]["watching"] == 0 and alert_bus["at399"]["watching"] == 0  # no watch is open on this screen


@pytest.fixture(scope="module")
def fallback(tmp_path_factory):
    return _run(tmp_path_factory, "fallback", stub.bus_chain, mode="fallback", width=390, height=844, bus=True)


def test_without_a_position_the_alert_falls_back_to_two_minutes_before_the_planned_arrival(fallback):
    r = fallback
    assert r["noFix"]["alert"] is None and r["noFix"]["reading"] is True
    assert r["at150"]["alert"] is None
    assert re.fullmatch(r"Get off next stop: .*", _flat(r["at119"]["alert"])), r["at119"]["alert"]
    # a usable position wins over the clock; a poor one (500 m) is no position
    assert r["farFixEarly"]["alert"] is None and r["farFix"]["alert"] is None
    assert _flat(r["poorFix"]["alert"]).startswith("Get off next stop: ")


@pytest.fixture(scope="module")
def privacy(tmp_path_factory):
    return _run(tmp_path_factory, "privacy", stub.bus_only, mode="privacy", width=390, height=844, bus=True)


def test_no_request_beacon_or_xhr_after_yes_carries_a_coordinate(privacy):
    sentinels = []
    for point in privacy["pushed"]:
        for value in (point["lat"], point["lon"]):
            sentinels.append(repr(value))
            sentinels.append(f"{value:.4f}")
            sentinels.append(f"{value:.5f}")
    sent = privacy["after"]["sent"]
    for entry in sent:
        blob = (entry["url"] + " " + entry["body"])
        for needle in sentinels:
            assert needle not in blob, (needle, entry)
        assert not re.search(r"[?&](lat|lon|latitude|longitude|accuracy)=", entry["url"]), entry
    assert not any(re.search(r"[?&](lat|lon)=", url) for url in privacy["after"]["requests"])
    # the page's own request state never took the alert's position
    assert privacy["after"]["userLat"] == privacy["before"]["userLat"] and privacy["after"]["userLon"] == privacy["before"]["userLon"]
    for place in ("local", "session", "cookie", "href"):
        for needle in sentinels:
            assert needle not in privacy["stores"][place], (place, needle)


def test_the_privacy_and_open_page_lines_show_while_the_position_is_read(privacy):
    layout = privacy["layout"]
    assert layout["reading"] is True
    assert layout["privacy"] == COPY_WAY["privacy"] and layout["open"] == "Works while this page is open."
    assert privacy["final"]["reading"] is False and privacy["final"]["privacy"] is None and privacy["final"]["open"] is None


def test_the_caught_leg_uses_the_per_leg_layout_for_a_bus(privacy):
    rows = privacy["layout"]["rows"]
    assert _kinds(rows) == ["bus", "walk", "destination"], _kinds(rows)
    first = rows[0]
    text = _flat(first["text"])
    assert "journey-step--leg" in first["cls"] and first["bar"] and first["nodes"] == 2
    assert first["badge"] == "Bus 18" or first["badge"].endswith("18")
    assert "To Destination" in text and "On board" in text and re.search(r"\d+ stops · \d+ min", text)
    assert len(first["titles"]) == 2  # the boarding stop and the alighting stop, each with its code
    all_text = " ".join(row["text"] for row in rows)
    for old in ("Boarding stop", "Bus service", "Destination stop", "Transfer stop"):
        assert old not in all_text
    assert privacy["layout"]["title"] == "On your way" and privacy["layout"]["planNew"] and privacy["layout"]["arrive"]


@pytest.fixture(scope="module")
def ends(tmp_path_factory):
    return _run(tmp_path_factory, "ends", stub.bus_only, mode="ends", width=390, height=844, bus=True)


@pytest.mark.parametrize("which", ["planNew", "hidden", "pagehide", "end", "back"])
def test_the_watch_and_the_tick_stop_on_each_end_condition(ends, which):
    run = ends["runs"][which]
    assert run["start"]["reading"] is True and run["start"]["timer"] is True
    assert run["end"]["reading"] is False and run["end"]["timer"] is False and run["end"]["alert"] is None
    assert run["end"]["privacy"] is None
    assert run["end"]["reads"] == run["readsAtEnd"]  # a late tick and a late fix read nothing


def test_a_hidden_page_stops_and_a_shown_page_resumes(ends):
    run = ends["runs"]["hidden"]
    assert run["whileHidden"]["reading"] is False and run["whileHidden"]["timer"] is False
    assert run["shownAgain"]["reading"] is True and run["shownAgain"]["timer"] is True


def test_leaving_the_page_and_the_planned_end_are_final(ends):
    assert ends["runs"]["pagehide"]["end"]["over"] is True
    assert ends["runs"]["end"]["end"]["over"] is True
    assert ends["runs"]["end"]["end"]["next"] is None
    assert ends["runs"]["planNew"]["end"]["screen"] == "home" and ends["runs"]["back"]["end"]["screen"] == "home"


def test_demo_mode_reads_no_position_and_shows_no_alert(ends):
    run = ends["runs"]["demo"]
    assert run["start"]["reading"] is False and run["start"]["privacy"] is None and run["start"]["open"] is None
    assert run["demoPush"]["alert"] is None and run["demoClock"]["alert"] is None
    # no position was read from the Yes tap to the end of the run
    assert run["demoPush"]["reads"] == run["start"]["reads"] == run["demoClock"]["reads"] == run["end"]["reads"]
    assert run["demoClock"]["reading"] is False


@pytest.fixture(scope="module", params=[
    ("l360", stub.bus_chain, 360, 800, False, True), ("d360", stub.train_transfer, 360, 800, True, False),
    ("l1280", stub.train_transfer, 1280, 900, False, False), ("d1280", stub.bus_chain, 1280, 900, True, True)],
    ids=["360-light-bus", "360-dark-train", "1280-light-train", "1280-dark-bus"])
def layout(request, tmp_path_factory):
    name, builder, width, height, dark, bus = request.param
    return _run(tmp_path_factory, "layout" + name, builder, lta_status=200 if bus else 500, mode="layout", width=width,
                height=height, dark=dark, bus=bus)


def test_the_on_way_layout_has_no_overflow_and_the_alert_has_an_icon_and_a_label(layout):
    for key in ("t0", "alert", "ticked"):
        assert layout[key]["scrollWidth"] <= layout[key]["innerWidth"], key
    assert layout["alert"]["alertVisible"] is True and layout["alert"]["alert"].startswith("Get off")
    assert layout["colors"]["hasIcon"] is True and layout["colors"]["iconW"] > 0 and layout["colors"]["text"] is True
    assert layout["colors"]["color"] != layout["colors"]["bg"]
    assert layout["ticked"]["rows"][0]["done"] is True
    assert layout["t0"]["next"] and layout["t0"]["next"].startswith("Next: ")


@pytest.fixture(scope="module")
def no_plan(tmp_path_factory):
    return _run(tmp_path_factory, "noplan", stub.bus_only, mode="noplan", width=390, height=844, bus=True)


def test_a_yes_with_no_plan_shows_the_minimal_leg_and_nothing_that_needs_an_end_stop(no_plan):
    r = no_plan
    assert r["noPlan"] == {"plan": None, "itinerary": None}  # really no plan and no itinerary
    first = r["firstRow"]
    assert "journey-step--bus" in first["cls"] and "journey-step--leg" in first["cls"]
    assert first["nodes"] == 1 and first["bar"] is False  # a start marker only: no end marker, no bar
    assert first["titles"] == ["Origin"]
    assert first["badge"].replace("Bus ", "") == "18"
    assert "On board" in first["text"] and "To " not in first["text"] and "stop" not in first["text"].replace("Origin", "")
    rows = r["t0"]["rows"]
    assert rows[-1]["cls"].startswith("journey-step journey-step--destination") and "Destination" in rows[-1]["text"]
    assert r["t0"]["title"] == "On your way" and r["t0"]["planNew"] and r["t0"]["arrive"]


def test_a_yes_with_no_plan_has_no_next_line_no_alert_and_reads_no_location(no_plan):
    r = no_plan
    for key in ("t0", "later"):
        assert r[key]["next"] is None and r[key]["alert"] is None and r[key]["alertVisible"] is False
        assert r[key]["reading"] is False and r[key]["privacy"] is None and r[key]["open"] is None
        assert r[key]["notes"] == []
    assert r["reads1"] == r["reads0"]  # no getCurrentPosition from the Yes tap to the end of the run
    assert r["later"]["watching"] == 0 or r["later"]["watching"] == r["t0"]["watching"]
    assert not any(re.search(r"[?&](lat|lon)=", entry) for entry in r["sentAfter"])

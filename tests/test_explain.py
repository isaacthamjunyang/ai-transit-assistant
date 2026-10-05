"""The three-sentence explanation. Fixtures only: these tests do not call OpenAI."""

import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explain
from explain import (
    ACTION_ADVICE,
    EXPLANATION_SCHEMA,
    FACT_SHEET_KEYS,
    GUARANTEE_PHRASES,
    TEMPERATURE,
    TIMEOUT_SECONDS,
    UNSAFE_PHRASES,
    advice_is_valid,
    REASON_CODES,
    build_numbers,
    clause_text,
    format_clock,
    format_distance,
    format_kmh,
    lead_text,
    parse_fact_sheet,
    reason_code_for,
    snapshot_key,
    build_poll_explanation,
    chosen_action,
    compose_text,
    explanation_request,
    handle_explain_request,
    interpret_explanation,
    model_name,
    overview_walk_minutes,
    produce_explanation,
    read_openai_api_key,
    reset_explanation_gate,
    sentence_one,
    sentence_two,
    tile_minutes,
)
from main import app

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
CTX = {"band": "ok", "uncertain": False}


@pytest.fixture(autouse=True)
def _block_live_openai(monkeypatch):
    reset_explanation_gate()

    def forbid(fact_sheet, api_key, request):
        raise AssertionError("live OpenAI call")

    monkeypatch.setattr(explain, "_openai_complete", forbid)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    yield
    reset_explanation_gate()


def sheet(bus=10, walk=3, action="wait", *, leave_in=600, source="gps", speed=1.25, distance=300.0):
    """The numbers of sentences one and two. They stay on the server."""
    return build_numbers(
        bus_minutes=bus, walk_minutes=walk, chosen_action=action, distance_m=distance, walk_speed_used=speed,
        walk_speed_source=source, leave_by=(NOW + timedelta(seconds=leave_in)).isoformat(), now=NOW,
    )


def msheet(action="wait", reason="LEAVE_BY"):
    """What the model may see: a reason code and the action."""
    return {"reason_code": reason, "chosen_action": action}


def accepted(advice="wait for your leave-by alert"):
    return {"advice": advice}


# ---- the numbers come from the tile and the overview functions

def _iso(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


@pytest.mark.parametrize("seconds, minutes", [(643, 11), (600, 10), (629, 10), (630, 11), (89, 1), (90, 2), (60, 1), (59, 0), (31, 0), (30, 0), (0, 0), (-40, 0)])
def test_bus_minutes_use_the_tile_rounding(seconds, minutes):
    assert tile_minutes(_iso(seconds), NOW) == minutes


def test_the_tile_rounding_is_the_javascript_function():
    html = INDEX.read_text(encoding="utf-8")
    tile = html.split("function countdownLabel(iso)", 1)[1].split("function formatTime", 1)[0]
    assert "seconds <= 30" in tile and "seconds < 60" in tile and "Math.round(seconds / 60)" in tile
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    body = "function countdownLabel(iso)" + tile
    code = (
        "Date.now=function(){return 0};\n" + body.rstrip() + "\n"
        "var out=[];[643,600,629,630,89,90,60,59,31,30,0,-40].forEach(function(s){out.push(countdownLabel(new Date(s*1000).toISOString()));});"
        "console.log(JSON.stringify(out));"
    )
    result = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=20)
    labels = json.loads(result.stdout)
    expected = []
    for seconds in (643, 600, 629, 630, 89, 90, 60, 59, 31, 30, 0, -40):
        minutes = tile_minutes(_iso(seconds), NOW)
        expected.append("Due" if seconds <= 30 else "<1 min" if minutes == 0 else f"{minutes} min")
    assert labels == expected


def test_walk_minutes_use_the_overview_rounding():
    assert overview_walk_minutes(0) == 1 and overview_walk_minutes(20) == 1  # never zero, as on the overview
    assert overview_walk_minutes(225) == 3 and overview_walk_minutes(262) == 3 and overview_walk_minutes(263) == 4
    html = INDEX.read_text(encoding="utf-8")
    assert "Math.max(1, Math.round(metres / serverWalkSpeed / 60))" in html


def test_the_example_from_the_prompt():
    # 643 s shows 11 on the tile, so the text says 11 (the tile's rounding wins).
    fact = sheet(bus=tile_minutes(_iso(643), NOW), walk=3)
    text = compose_text(fact, ACTION_ADVICE["wait"], **CTX)
    assert text == ("The bus is 11 minutes away. You are 300\u00a0m from the stop and walking at about 4.5\u00a0km/h, "
                    "so you should leave by 2:10\u00a0PM. It is advisable to wait for your leave-by alert.")
    ten = compose_text(sheet(bus=10, walk=3), ACTION_ADVICE["wait"], **CTX)
    assert ten.startswith("The bus is 10 minutes away. You are 300\u00a0m from the stop")


# ---- sentences one and two, every variant

def test_sentence_one_variants():
    assert sentence_one(10) == "The bus is 10 minutes away."
    assert sentence_one(1) == "The bus is 1 minute away."
    assert sentence_one(0) == "The bus is arriving now."


@pytest.mark.parametrize("source, speed, middle", [
    ("gps", 1.25, "and walking at about 4.5\u00a0km/h, so you should leave by 2:10\u00a0PM."),
    ("cadence", 1.0, "and walking at about 3.6\u00a0km/h, so you should leave by 2:10\u00a0PM."),
    ("remembered", 1.1, "and walking at your usual speed of 4.0\u00a0km/h, so you should leave by 2:10\u00a0PM."),
    ("default", 1.25, "and, at an average walking speed of 4.5\u00a0km/h, you should leave by 2:10\u00a0PM."),
])
def test_sentence_two_leave_by_for_every_speed_source(source, speed, middle):
    text = sentence_two(sheet(10, 3, source=source, speed=speed), band="ok", uncertain=False)
    assert text == f"You are 300\u00a0m from the stop {middle}"


@pytest.mark.parametrize("source, speed, middle", [
    ("gps", 1.25, "and walking at about 4.5\u00a0km/h, so you should leave now."),
    ("cadence", 1.4, "and walking at about 5.0\u00a0km/h, so you should leave now."),
    ("remembered", 1.1, "and walking at your usual speed of 4.0\u00a0km/h, so you should leave now."),
    ("default", 1.25, "and, at an average walking speed of 4.5\u00a0km/h, you should leave now."),
])
def test_sentence_two_leave_now_for_every_speed_source(source, speed, middle):
    for seconds in (60, 30, 0, -1, -600):
        text = sentence_two(sheet(10, 3, source=source, speed=speed, leave_in=seconds), band="ok", uncertain=False)
        assert text == f"You are 300\u00a0m from the stop {middle}", seconds


def test_sentence_two_unlikely_for_a_low_band_or_switch_or_do_not_rely():
    expected = "You are 300\u00a0m from the stop, but catching this bus is unlikely."
    assert sentence_two(sheet(10, 3), band="low", uncertain=False) == expected
    assert sentence_two(sheet(10, 3, "switch_route"), band="ok", uncertain=False) == expected
    assert sentence_two(sheet(10, 3, "do_not_rely"), band="ok", uncertain=False) == expected
    # no uncertain-location sentence after the unlikely sentence, and the time is not mentioned
    assert sentence_two(sheet(10, 3), band="low", uncertain=True) == expected
    assert sentence_two(sheet(2, 5, "do_not_rely", leave_in=0), band="low", uncertain=True) == expected


def test_sentence_two_adds_the_uncertain_location_sentence_after_leave_by_and_after_leave_now():
    by = sentence_two(sheet(10, 3), band="ok", uncertain=True)
    assert by.endswith("so you should leave by 2:10\u00a0PM. Your location is uncertain, so leave a little earlier than that to be safe.")
    now = sentence_two(sheet(10, 3, leave_in=60), band="ok", uncertain=True)
    assert now.endswith("so you should leave now. Your location is uncertain, so the walking time may be off.")


def test_distance_and_clock_formats():
    assert format_distance(0) == "0\u00a0m" and format_distance(999.4) == "999\u00a0m" and format_distance(0.5) == "1\u00a0m"
    assert format_distance(999.5) == "1\u00a0km" and format_distance(1000) == "1\u00a0km"
    assert format_distance(1249) == "1.2\u00a0km" and format_distance(1250) == "1.3\u00a0km" and format_distance(2000) == "2\u00a0km"
    assert format_clock(NOW + timedelta(minutes=10), NOW) == "2:10\u00a0PM"
    assert format_clock(NOW.replace(hour=0, minute=5), NOW) == "12:05\u00a0AM"
    assert format_clock(NOW.replace(hour=12, minute=0), NOW) == "12:00\u00a0PM"
    assert format_clock(NOW + timedelta(hours=10), NOW) == "12:00\u00a0AM (tomorrow)"
    assert format_kmh(1.25) == "4.5" and format_kmh(1.4) == "5.0" and format_kmh(0.5) == "1.8"


def test_variant_priority_first_match_wins():
    # unlikely (low band, switch, do-not-rely), then leave now or leave by with the uncertain sentence after it.
    assert "unlikely" in sentence_two(sheet(2, 5, "do_not_rely"), band="ok", uncertain=False)
    assert "leave now" in sentence_two(sheet(2, 5, leave_in=0), band="mid", uncertain=False)
    assert "leave by" in sentence_two(sheet(2, 5, leave_in=61), band="mid", uncertain=False)
    assert "unlikely" in sentence_two(sheet(2, 5), band="low", uncertain=True)


def test_copy_templates_match_python():
    copy = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
    page = INDEX.read_text(encoding="utf-8")
    texts = ["The bus is arriving now.", "The bus is {e} minutes away.", "The bus is 1 minute away.",
             "It is advisable to {advice}.", explain.S2_UNLIKELY, explain.S2_UNCERTAIN_BY, explain.S2_UNCERTAIN_NOW]
    texts += list(explain.S2_LEAVE_BY.values()) + list(explain.S2_LEAVE_NOW.values())
    escape = chr(92) + "u00a0"  # copy.js and the page spell the no-break space as an escape in their source
    for text in texts:
        assert text.replace("\u00a0", escape) in copy, text
    for text in [explain.S2_UNLIKELY, explain.S2_UNCERTAIN_BY, explain.S2_UNCERTAIN_NOW, explain.S1_ARRIVING_NOW]:
        assert text in page, text  # the page mirror carries the same wording
    for text in list(explain.S2_LEAVE_BY.values()) + list(explain.S2_LEAVE_NOW.values()):
        assert text.replace("\u00a0", escape) in page, text
    for clause in ACTION_ADVICE.values():
        assert clause in copy
    for old in ("Given the walking time", "you may not reach the stop", "to get to the bus stop", "Wait for Leave By Alert"):
        assert old not in copy and old not in page, old


# ---- no heading, no probability, no seconds, no spare

ALL_CASES = [(e, w, a, band, unc) for e in (0, 1, 2, 10) for w in (1, 3, 12) for a in explain.ACTIONS
             for band in ("ok", "mid", "low", None) for unc in (False, True)]


def test_no_explanation_has_a_heading_probability_seconds_or_spare():
    for e, w, action, band, unc in ALL_CASES:
        for leave_in in (600, 30):
            numbers = sheet(e, w, action, leave_in=leave_in)
            text = compose_text(numbers, ACTION_ADVICE[action], band=band, uncertain=unc)
            sentences = re.split(r"\. ", text)
            assert len(sentences) in (3, 4), text  # three; four only when the uncertain sentence is added
            assert "\n" not in text and "%" not in text
            lowered = text.lower()
            for banned in ("second", "spare", "probability", "chance", "range", "slack", "headline"):
                assert banned not in lowered, (banned, text)
            first, rest = text.split(". ", 1)
            assert re.findall(r"\d+", first) == ([str(e)] if e >= 1 else []), text
            for piece in (format_distance(numbers["distance_m"]), format_kmh(numbers["walk_speed_used"]), numbers["time_text"]):
                rest = rest.replace(piece, "", 1)
            assert not re.search(r"\d", rest), (rest, text)  # every digit is a placeholder value
            assert text.endswith(".") and text.split(". ")[-1].startswith("It is advisable to ")


# ---- the model's clause

@pytest.mark.parametrize("action", explain.ACTIONS)
def test_the_fixed_clause_is_valid_for_its_own_action(action):
    assert advice_is_valid(ACTION_ADVICE[action], action)


@pytest.mark.parametrize("advice, action", [
    ("wait for your alert before leaving", "wait"),
    ("leave now and walk steadily to the stop", "leave_now"),
    ("switch to another bus", "switch_route"),
    ("not rely only on this estimate", "do_not_rely"),
    ("take the next bus instead and change at the stop", "switch_route"),
])
def test_good_advice_is_accepted(advice, action):
    assert advice_is_valid(advice, action)


@pytest.mark.parametrize("advice, action", [
    ("wait for the bus in 5 minutes", "wait"),                       # digits
    ("wait for your alert for 30 seconds", "wait"),                  # a word about seconds
    ("Wait for your leave-by alert", "wait"),                        # capital letter
    ("wait for your leave-by alert.", "wait"),                       # final full stop
    ("leave now and walk to the bus stop", "wait"),                  # contradicts the action
    ("wait for the next bus", "leave_now"),                          # contradicts the action
    ("walk to the stop", "switch_route"),                            # does not say to switch
    ("check the timetable", "do_not_rely"),                          # does not say not to rely
    ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen", "wait"),  # over 15 words
    ("run to the bus stop", "leave_now"),                            # unsafe
    ("you will make it so wait", "wait"),                            # guarantee
    ("", "wait"),
    (None, "wait"),
])
def test_bad_advice_is_rejected(advice, action):
    assert advice_is_valid(advice, action) is False


@pytest.mark.parametrize("phrase", UNSAFE_PHRASES)
def test_every_unsafe_phrase_is_rejected(phrase):
    assert advice_is_valid(f"wait and {phrase} to the stop", "wait") is False


@pytest.mark.parametrize("phrase", GUARANTEE_PHRASES)
def test_guaranteed_arrival_phrases_are_rejected(phrase):
    assert advice_is_valid(f"wait because {phrase}", "wait") is False


def test_a_bad_model_clause_falls_back_and_never_carries_numbers():
    fact = msheet("wait")
    for bad in ("wait for the bus in 7 minutes", "leave now and run", "Wait for your leave-by alert."):
        view = interpret_explanation({"status": 200, "body": {"advice": bad}}, fact)
        assert view["source"] == "fallback"
        assert view["advice"] == ACTION_ADVICE["wait"]
        assert view["clause"] == "It is advisable to wait for your leave-by alert."
        assert "text" not in view  # the model path knows no minutes, so it cannot produce sentences one and two
    good = interpret_explanation({"status": 200, "body": json.dumps({"advice": "wait for your alert before leaving"})}, fact)
    assert good["source"] == "model" and good["clause"] == "It is advisable to wait for your alert before leaving."
    assert not re.search(r"\d", good["clause"])


@pytest.mark.parametrize("raw", [
    {"status": 500, "body": None},
    {"status": 200, "body": "not json"},
    {"status": 200, "body": {}},
    {"status": 200, "body": {"advice": "wait for your leave-by alert", "headline": "x"}},
    {"status": 200, "body": {"headline": "x", "reasoning": "y", "leave_advice": "wait", "cited_low": 1, "cited_high": 2}},
])
def test_failures_and_extra_fields_use_the_fixed_clause(raw):
    view = interpret_explanation(raw, msheet())
    assert view["source"] == "fallback" and view["advice"] == ACTION_ADVICE["wait"]


def test_timeout_and_missing_key_use_the_fixed_clause():
    def slow(fact, request):
        raise TimeoutError

    assert produce_explanation(msheet(), complete=slow, api_key="sk-x")["source"] == "fallback"
    assert produce_explanation(msheet(), complete=lambda f, r: {"status": 200, "body": accepted()}, api_key="")["source"] == "fallback"


# ---- the fact sheet and the request

def test_the_fact_sheet_is_a_reason_code_and_the_action_and_no_number_at_all():
    fact = msheet("wait", "LEAVE_BY")
    assert tuple(fact) == FACT_SHEET_KEYS == ("reason_code", "chosen_action")
    assert REASON_CODES == ("UNLIKELY", "LOCATION_UNCERTAIN", "LEAVE_NOW", "LEAVE_BY")
    assert parse_fact_sheet(fact) == fact
    request = explanation_request(fact)
    user = json.loads(request["messages"][1]["content"])
    assert user == fact
    assert not re.search(r"\d", request["messages"][1]["content"]), "a digit reached the model as data"
    assert re.findall(r"\d+", request["messages"][0]["content"]) == ["15"]  # only the word limit in the instructions
    blob = json.dumps(request).lower()
    for marker in ("minutes", "slack", "range_low", "range_high", "\"point\"", "latitude", "longitude", "stop_code", "service_no"):
        assert marker not in blob
    assert EXPLANATION_SCHEMA["required"] == ["advice"] and list(EXPLANATION_SCHEMA["properties"]) == ["advice"]
    assert EXPLANATION_SCHEMA["additionalProperties"] is False


def test_every_poll_pack_sends_the_model_nothing_but_the_reason_code_and_the_action():
    pack = _poll(_payload(643))
    assert set(pack["fact_sheet"]) == {"reason_code", "chosen_action"}
    assert pack["fact_sheet"]["reason_code"] in REASON_CODES
    assert not re.search(r"\d", json.dumps(pack["fact_sheet"]))


def test_the_reason_code_is_the_sentence_two_variant():
    assert reason_code_for(sheet(10, 3), band="ok", uncertain=True) == "LOCATION_UNCERTAIN"
    assert reason_code_for(sheet(10, 3, leave_in=0), band="ok", uncertain=True) == "LOCATION_UNCERTAIN"
    assert reason_code_for(sheet(10, 3), band="low", uncertain=False) == "UNLIKELY"
    assert reason_code_for(sheet(10, 3), band="low", uncertain=True) == "UNLIKELY"  # unlikely comes first
    assert reason_code_for(sheet(10, 3, "switch_route"), band="ok", uncertain=False) == "UNLIKELY"
    assert reason_code_for(sheet(10, 3, "do_not_rely"), band="ok", uncertain=False) == "UNLIKELY"
    assert reason_code_for(sheet(3, 3, leave_in=60), band="ok", uncertain=False) == "LEAVE_NOW"
    assert reason_code_for(sheet(10, 3, leave_in=61), band="mid", uncertain=False) == "LEAVE_BY"
    assert reason_code_for(sheet(10, 3, leave_in=-5), band="mid", uncertain=False) == "LEAVE_NOW"


def test_python_action_precedence():
    assert chosen_action(reroute_fired_this_poll=True, data_quality="stale", range_high=10, leave_by_seconds=0) == "switch_route"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="stale", range_high=90, leave_by_seconds=10) == "do_not_rely"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="live", range_high=39, leave_by_seconds=120) == "do_not_rely"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="location uncertain", range_high=40, leave_by_seconds=60) == "leave_now"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="live", range_high=40, leave_by_seconds=61) == "wait"


def test_model_configuration():
    assert model_name() == "gpt-4o-mini"
    assert TEMPERATURE == 0.2 and TIMEOUT_SECONDS == 3
    request = explanation_request(msheet())
    assert request["model"] == "gpt-4o-mini" and request["store"] is False
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"] == EXPLANATION_SCHEMA
    system = request["messages"][0]["content"].lower()
    assert "headline" not in system and "range" not in system and "probability" not in system


def test_model_name_can_be_swapped_from_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini-2024-07-18")
    assert explanation_request(msheet())["model"] == "gpt-4o-mini-2024-07-18"


# ---- the poll: text rebuilt every time, the clause cached by action

class _Cache:
    def stop_by_code(self, code):
        return {"Latitude": 1.3, "Longitude": 103.8}


def _payload(eta_seconds, *, band="ok", quality="live", leave_in=600, high=80):
    return {
        "leave_by": (NOW + timedelta(seconds=leave_in)).isoformat(),
        "buses": [{"position": "NextBus", "arrival_time": _iso(eta_seconds), "is_primary": True, "is_missed": False,
                   "probability": {"point": 60, "range_low": 50, "range_high": high, "data_quality": quality, "band": band}}],
    }


def _poll(payload, **overrides):
    args = dict(now=NOW, cache=_Cache(), user_lat=1.3 + 225 / 111_195, user_lon=103.8, stop_code="1", explained_action=None,
                explained_advice=None, in_flight=False, reroute_fired=False)
    args.update(overrides)
    return build_poll_explanation(payload, **args)


def test_the_poll_text_uses_this_polls_numbers_and_the_fixed_clause_until_the_model_answers():
    first = _poll(_payload(643))
    assert first["text"].startswith("The bus is 11 minutes away. You are 225\u00a0m from the stop and, at an average walking speed of 4.5\u00a0km/h, you should leave by 2:10\u00a0PM.")
    assert first["text"].endswith("It is advisable to wait for your leave-by alert.")
    assert first["call"] is True and first["action"] == "wait"
    later = _poll(_payload(583))  # 20 s later: the minutes change, the text follows
    assert later["text"].startswith("The bus is 10 minutes away.")


def test_the_cached_clause_is_reused_only_for_the_same_action_and_must_still_be_valid():
    advice = "wait for your alert before leaving"
    same = _poll(_payload(600), explained_action="wait", explained_advice=advice)
    assert same["text"].endswith(f"It is advisable to {advice}.") and same["call"] is False
    changed = _poll(_payload(600, leave_in=30), explained_action="wait", explained_advice=advice)
    assert changed["action"] == "leave_now" and changed["text"].endswith("leave now and walk to the bus stop.") and changed["call"] is True
    tampered = _poll(_payload(600), explained_action="wait", explained_advice="leave now, in 5 minutes")
    assert tampered["text"].endswith("wait for your leave-by alert.") and tampered["call"] is True
    busy = _poll(_payload(600), in_flight=True)
    assert busy["call"] is False and busy["pending"] is True


def test_context_chooses_the_sentence_two_variant_and_the_model_never_sees_it():
    low = _poll(_payload(600, band="low", high=30))
    assert "catching this bus is unlikely" in low["text"] and low["action"] == "do_not_rely"
    unc = _poll(_payload(600, quality="location uncertain"))
    assert "Your location is uncertain" in unc["text"]
    assert unc["fact_sheet"] == {"reason_code": "LOCATION_UNCERTAIN", "chosen_action": unc["action"]}
    stale = _poll(_payload(600, quality="stale"))
    assert stale["call"] is False  # no model call for stale or unavailable data


def _three_buses(reroute=True):
    """Arrivals at 2, 22 and 40 minutes. The tile shows the 2-minute bus. A reroute to the 22-minute bus fires."""
    buses = []
    for index, minutes in enumerate((2, 22, 40)):
        buses.append({"position": ("NextBus", "NextBus2", "NextBus3")[index], "arrival_time": _iso(minutes * 60),
                      "is_primary": index == 0, "is_missed": False,
                      "probability": {"point": 60, "range_low": 50, "range_high": 80, "data_quality": "live", "band": "ok"}})
    payload = {"service_no": "36", "leave_by": (NOW + timedelta(seconds=600)).isoformat(), "buses": buses}
    if reroute:
        payload["reroute"] = {
            "winner_score": {"point": 63, "range_low": 55, "range_high": 70, "data_quality": "live"},
            "reroute": {"arrival_time": _iso(22 * 60), "stop": {"distance_m": 150}}}
    return payload


def test_a_reroute_describes_the_tracked_bus_with_the_switch_wording_never_the_winner():
    pack = _poll(_three_buses(), reroute_fired=True)
    assert pack["action"] == "switch_route"
    assert pack["text"].startswith("The bus is 2 minutes away. You are 225\u00a0m from the stop, but catching this bus is unlikely.")
    assert "22 minutes" not in pack["text"] and "40 minutes" not in pack["text"]
    assert pack["text"].endswith("It is advisable to switch to another bus.")
    assert pack["arrival_time"] == _iso(120)
    # With no reroute the same 2-minute bus is described (the bug: the winner's 22 minutes leaked in).
    plain = _poll(_three_buses(reroute=False))
    assert plain["text"].startswith("The bus is 2 minutes away.") and plain["action"] == "wait"


def test_after_a_missed_arrival_the_text_follows_the_new_tracked_bus():
    payload = _three_buses(reroute=False)
    payload["buses"][0].update({"arrival_time": _iso(-45), "is_missed": True, "is_primary": False, "probability": None})
    payload["buses"][1]["is_primary"] = True
    pack = _poll(payload)
    assert pack["text"].startswith("The bus is 22 minutes away.") and pack["arrival_time"] == _iso(22 * 60)
    for bus in payload["buses"]:
        bus["is_missed"], bus["is_primary"] = True, False
    assert _poll(payload) is None  # nothing tracked: no explanation (the page clears the card)


def test_the_page_minutes_equal_the_tile_minutes_for_every_variant():
    # The sentence-one number is the tile's number (tile_minutes) in every case of the variant table.
    for e, w, action, band, unc in ALL_CASES:
        numbers = sheet(e, w, action)
        lead = lead_text(numbers, band=band, uncertain=unc)
        expected_one = "The bus is arriving now." if e < 1 else f"The bus is {e} minute{'s' if e != 1 else ''} away."
        assert lead.startswith(expected_one), lead
    for seconds in (-40, 0, 30, 31, 59, 60, 89, 90, 600, 629, 630, 1320):
        e = tile_minutes(_iso(seconds), NOW)
        pack = _poll(_payload(seconds))
        if pack is not None:
            numbers = build_numbers(
                bus_minutes=e, walk_minutes=pack["walk_minutes"], chosen_action=pack["action"], distance_m=pack["distance_m"],
                walk_speed_used=pack["walk_speed_used"], walk_speed_source=pack["walk_speed_source"],
                leave_by=pack["leave_by"], now=NOW)
            assert pack["text"].startswith(lead_text(numbers, band=pack["band"], uncertain=pack["uncertain"])), seconds


def test_the_pack_carries_the_snapshot_key_of_its_bus_and_poll():
    pack = _poll(_payload(600), stop_code="1")
    assert pack["snapshot"] == snapshot_key("1", "", _iso(600), NOW)
    later = build_poll_explanation(_payload(600), now=NOW + timedelta(seconds=20), cache=_Cache(), user_lat=1.3 + 225 / 111_195,
                                   user_lon=103.8, stop_code="1", explained_action=None, explained_advice=None,
                                   in_flight=False, reroute_fired=False)
    assert later["snapshot"] != pack["snapshot"]


# ---- endpoint, key, scope

def test_explain_endpoint_returns_the_clause_and_the_snapshot_and_hides_the_key(monkeypatch):
    secret = "sk-endpoint-secret"
    calls = []
    key = "36|01011|2026-09-29T14:02:00+08:00|2026-09-29T14:00:00+08:00"

    def fake_complete(fact_sheet, api_key, request):
        calls.append(api_key)
        status_code, queued = handle_explain_request({"fact_sheet": msheet("wait", "LEAVE_NOW"), "snapshot": "later"})
        assert status_code == 200 and queued["queued"] is True and queued["snapshot"] == "later"
        return {"status": 200, "body": json.dumps(accepted())}

    monkeypatch.setattr(explain, "_openai_complete", fake_complete)
    monkeypatch.setattr(explain, "read_openai_api_key", lambda: secret)
    status, payload = handle_explain_request({"fact_sheet": msheet("wait"), "snapshot": key})
    assert status == 200 and payload["source"] == "model" and payload["action"] == "wait"
    assert payload["snapshot"] == key  # every reply carries the key of the request it answers
    assert payload["clause"] == "It is advisable to wait for your leave-by alert." and "text" not in payload
    assert payload["pending_fact_sheet"]["reason_code"] == "LEAVE_NOW"
    assert secret not in json.dumps(payload) and calls == [secret]
    reset_explanation_gate()
    with TestClient(app) as client:
        response = client.post("/api/explain", json={"fact_sheet": msheet(), "snapshot": key})
    assert response.status_code == 200 and secret not in response.text and response.json()["snapshot"] == key


def test_explain_endpoint_rejects_bad_spatial_or_numeric_sheets_and_a_missing_snapshot():
    body = msheet()
    body["latitude"] = 1.3
    assert handle_explain_request({"fact_sheet": body, "snapshot": "k"})[0] == 422
    numeric = dict(msheet(), bus_minutes=10)
    assert handle_explain_request({"fact_sheet": numeric, "snapshot": "k"})[0] == 422
    assert handle_explain_request({"fact_sheet": msheet("wait", "NOT_A_CODE"), "snapshot": "k"})[0] == 422
    assert handle_explain_request({"fact_sheet": msheet()})[0] == 422  # no snapshot key
    assert handle_explain_request({"fact_sheet": msheet(), "snapshot": "bad key with spaces"})[0] == 422
    assert handle_explain_request({"point": 1})[0] == 422


def test_api_key_never_reaches_the_browser_logs_or_disk(tmp_path, capsys, caplog, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    secret = "sk-unit-test-secret"
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    assert read_openai_api_key(env_file) == secret
    captured = capsys.readouterr()
    assert secret not in captured.out and secret not in captured.err
    assert "OPENAI_API_KEY" not in INDEX.read_text(encoding="utf-8")
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    seen = {}

    def transport(fact, request):
        seen["request"] = request
        return {"status": 200, "body": accepted()}

    with caplog.at_level(0):
        result = produce_explanation(msheet(), complete=transport, api_key=secret)
    assert secret not in caplog.text + json.dumps(seen) + json.dumps(result)
    source = (ROOT / "explain.py").read_text(encoding="utf-8")
    for banned in ("sqlite3", "record_observation", "write_text", "logging"):
        assert banned not in source

    def boom(*args, **kwargs):
        raise AssertionError("explanation persistence")

    monkeypatch.setattr(sqlite3, "connect", boom)
    monkeypatch.setattr(Path, "write_text", boom)
    produce_explanation(msheet(), complete=transport, api_key=secret)


def test_the_model_is_not_asked_to_choose_or_rank_stops():
    request = explanation_request(msheet())
    raw_user = request["messages"][1]["content"].lower()
    for marker in ("latitude", "longitude", "stop_code", "busstop", "coordinate", "service_no"):
        assert marker not in raw_user
    assert "tools" not in request and "functions" not in request
    for name in ("catch_heuristic.py", "journey.py", "leave_now.py", "arrivals.py", "reroute.py", "destination_stops.py",
                 "nearby.py", "onemap.py", "observations.py", "main.py", "static/index.html"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "chat.completions" not in text and "OpenAI(" not in text and "api.openai.com" not in text


def test_openai_sdk_is_installed_and_pinned():
    import openai

    assert openai.__version__ == "3.20.0"
    assert "openai==3.20.0" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


# ---- the model's clause keeps its strict checks: the relaxed checks above are for the Python-built sentences only

FIFTEEN = "wait for your alert " + " ".join(["before"] * 11)  # 4 + 11 = 15 words
SIXTEEN = FIFTEEN + " now"


@pytest.mark.parametrize("label, advice", [
    ("a colon", "wait: for your leave-by alert"),
    ("a colon only", "wait for your leave-by alert:"),
    ("a clock time", "wait until 10:03 for your alert"),
    ("a clock time in words and digits", "wait for your alert at 10:03"),
    ("a single digit", "wait for 1 alert"),
    ("digits", "wait for the bus in 7 minutes"),
    ("a newline", "wait for your\nleave-by alert"),
    ("a newline then a sentence", "wait for your alert\nIt is advisable to leave"),
    ("a carriage return", "wait for your\rleave-by alert"),
    ("a tab", "wait for your\tleave-by alert"),
    ("16 words", SIXTEEN),
])
def test_the_models_clause_is_rejected_for_a_colon_a_digit_a_clock_time_a_newline_or_over_15_words(label, advice):
    assert len(SIXTEEN.split()) == 16 and len(FIFTEEN.split()) == 15
    assert advice_is_valid(advice, "wait") is False, label
    view = interpret_explanation({"status": 200, "body": {"advice": advice}}, msheet("wait"))
    assert view["source"] == "fallback" and view["advice"] == ACTION_ADVICE["wait"], label


def test_a_clause_of_exactly_15_words_is_still_accepted():
    assert advice_is_valid(FIFTEEN, "wait") is True


def test_the_relaxed_checks_cover_the_python_sentences_and_never_the_models_clause():
    # The Python-built text may hold a colon (a clock time such as 2:10\u00a0PM) and four sentences ...
    numbers = sheet(10, 3, leave_in=600)
    text = compose_text(numbers, ACTION_ADVICE["wait"], band="ok", uncertain=True)
    assert ":" in text and len(re.split(r"\. ", text)) == 4
    # ... but the same characters are refused in the model's clause, whatever the text around it allows.
    assert advice_is_valid("wait until 2:10\u00a0PM", "wait") is False
    assert advice_is_valid("wait for your alert. It is advisable to wait", "wait") is False

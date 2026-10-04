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
    build_fact_sheet,
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


def sheet(bus=10, walk=3, action="wait"):
    return build_fact_sheet(bus_minutes=bus, walk_minutes=walk, chosen_action=action)


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
    assert text == ("The bus is 11 minutes away. Given the walking time is only 3 minutes, you have 8 minutes to get to the bus stop. "
                    "It is advisable to wait for your leave-by alert.")
    ten = compose_text(sheet(bus=10, walk=3), ACTION_ADVICE["wait"], **CTX)
    assert ten.startswith("The bus is 10 minutes away. Given the walking time is only 3 minutes, you have 7 minutes")


# ---- sentences one and two, every variant

def test_sentence_one_variants():
    assert sentence_one(10) == "The bus is 10 minutes away."
    assert sentence_one(1) == "The bus is 1 minute away."
    assert sentence_one(0) == "The bus is arriving now."


def test_sentence_two_default_singular_and_plural():
    assert sentence_two(sheet(10, 3), band="ok", uncertain=False) == \
        "Given the walking time is only 3 minutes, you have 7 minutes to get to the bus stop."
    assert sentence_two(sheet(5, 4), band="ok", uncertain=False) == \
        "Given the walking time is only 4 minutes, you have 1 minute to get to the bus stop."
    assert sentence_two(sheet(6, 1), band="ok", uncertain=False) == \
        "Given the walking time is only 1 minute, you have 5 minutes to get to the bus stop."


def test_sentence_two_may_not_reach_when_walking_takes_as_long_as_the_bus():
    assert sentence_two(sheet(3, 3), band="ok", uncertain=False) == \
        "Given the walking time is 3 minutes, you may not reach the stop before the bus."
    assert sentence_two(sheet(2, 5), band="mid", uncertain=False) == \
        "Given the walking time is 5 minutes, you may not reach the stop before the bus."
    assert sentence_two(sheet(0, 1), band="ok", uncertain=False).endswith("before the bus.")


def test_sentence_two_unlikely_for_a_low_band_or_switch_or_do_not_rely():
    expected = "Given the walking time is 3 minutes, catching this bus is unlikely."
    assert sentence_two(sheet(10, 3), band="low", uncertain=False) == expected
    assert sentence_two(sheet(10, 3, "switch_route"), band="ok", uncertain=False) == expected
    assert sentence_two(sheet(10, 3, "do_not_rely"), band="ok", uncertain=False) == expected


def test_sentence_two_location_uncertain_wins():
    expected = "Your location is uncertain, so the walking time may be off."
    assert sentence_two(sheet(10, 3), band="low", uncertain=True) == expected
    assert sentence_two(sheet(2, 5, "do_not_rely"), band="low", uncertain=True) == expected


def test_variant_priority_first_match_wins():
    # uncertain, then low band or switch or do-not-rely, then may-not-reach, then the default.
    assert "unlikely" in sentence_two(sheet(2, 5, "do_not_rely"), band="ok", uncertain=False)
    assert "may not reach" in sentence_two(sheet(2, 5), band="mid", uncertain=False)


def test_copy_templates_match_python():
    copy = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
    for text in ("The bus is arriving now.", "The bus is {e} minutes away.", "The bus is 1 minute away.",
                 "Given the walking time is only {w} minutes, you have {t} minutes to get to the bus stop.",
                 "Given the walking time is {w} minutes, you may not reach the stop before the bus.",
                 "Given the walking time is {w} minutes, catching this bus is unlikely.",
                 "Your location is uncertain, so the walking time may be off.",
                 "It is advisable to {advice}."):
        assert text in copy, text
    for clause in ACTION_ADVICE.values():
        assert clause in copy


# ---- no heading, no probability, no seconds, no spare

ALL_CASES = [(e, w, a, band, unc) for e in (0, 1, 2, 10) for w in (1, 3, 12) for a in explain.ACTIONS
             for band in ("ok", "mid", "low", None) for unc in (False, True)]


def test_no_explanation_has_a_heading_probability_seconds_or_spare():
    for e, w, action, band, unc in ALL_CASES:
        text = compose_text(sheet(e, w, action), ACTION_ADVICE[action], band=band, uncertain=unc)
        assert len(re.findall(r"[.]", text)) == 3, text  # exactly three sentences
        assert "\n" not in text and ":" not in text and "%" not in text
        lowered = text.lower()
        for banned in ("second", "spare", "probability", "chance", "range", "slack", "headline"):
            assert banned not in lowered, (banned, text)
        digits = re.findall(r"\d+", text)
        allowed = {str(e), str(w), str(e - w), "1"}
        assert all(d in allowed or int(d) in (e, w, e - w) for d in digits), text
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


def test_a_bad_model_clause_falls_back_and_the_numbers_cannot_change():
    fact = sheet(10, 3, "wait")
    for bad in ("wait for the bus in 7 minutes", "leave now and run", "Wait for your leave-by alert."):
        view = interpret_explanation({"status": 200, "body": {"advice": bad}}, fact, CTX)
        assert view["source"] == "fallback"
        assert view["advice"] == ACTION_ADVICE["wait"]
        assert view["text"].startswith("The bus is 10 minutes away. Given the walking time is only 3 minutes, you have 7 minutes")
    good = interpret_explanation({"status": 200, "body": json.dumps({"advice": "wait for your alert before leaving"})}, fact, CTX)
    assert good["source"] == "model" and good["text"].endswith("It is advisable to wait for your alert before leaving.")
    assert good["text"].split(" It is advisable")[0] == compose_text(fact, ACTION_ADVICE["wait"], **CTX).split(" It is advisable")[0]


@pytest.mark.parametrize("raw", [
    {"status": 500, "body": None},
    {"status": 200, "body": "not json"},
    {"status": 200, "body": {}},
    {"status": 200, "body": {"advice": "wait for your leave-by alert", "headline": "x"}},
    {"status": 200, "body": {"headline": "x", "reasoning": "y", "leave_advice": "wait", "cited_low": 1, "cited_high": 2}},
])
def test_failures_and_extra_fields_use_the_fixed_clause(raw):
    view = interpret_explanation(raw, sheet(), CTX)
    assert view["source"] == "fallback" and view["advice"] == ACTION_ADVICE["wait"]


def test_timeout_and_missing_key_use_the_fixed_clause():
    def slow(fact, request):
        raise TimeoutError

    assert produce_explanation(sheet(), CTX, complete=slow, api_key="sk-x")["source"] == "fallback"
    assert produce_explanation(sheet(), CTX, complete=lambda f, r: {"status": 200, "body": accepted()}, api_key="")["source"] == "fallback"


# ---- the fact sheet and the request

def test_the_fact_sheet_is_whole_minutes_and_the_action_only():
    fact = sheet(10, 3, "wait")
    assert tuple(fact) == FACT_SHEET_KEYS
    assert set(fact) == {"bus_minutes", "walk_minutes", "minutes_before_leaving", "chosen_action"}
    assert fact["minutes_before_leaving"] == fact["bus_minutes"] - fact["walk_minutes"]
    for forbidden in ("slack", "second", "point", "range", "probability", "quality", "monitored", "spare", "arrive", "target"):
        assert not any(forbidden in key for key in fact)
    request = explanation_request(fact)
    user = json.loads(request["messages"][1]["content"])
    assert set(user) == set(FACT_SHEET_KEYS)
    blob = json.dumps(request).lower()
    for marker in ("slack", "range_low", "range_high", "\"point\"", "latitude", "longitude", "stop_code", "service_no"):
        assert marker not in blob
    assert EXPLANATION_SCHEMA["required"] == ["advice"] and list(EXPLANATION_SCHEMA["properties"]) == ["advice"]
    assert EXPLANATION_SCHEMA["additionalProperties"] is False


def test_python_action_precedence():
    assert chosen_action(reroute_fired_this_poll=True, data_quality="stale", range_high=10, leave_by_seconds=0) == "switch_route"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="stale", range_high=90, leave_by_seconds=10) == "do_not_rely"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="live", range_high=39, leave_by_seconds=120) == "do_not_rely"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="location uncertain", range_high=40, leave_by_seconds=60) == "leave_now"
    assert chosen_action(reroute_fired_this_poll=False, data_quality="live", range_high=40, leave_by_seconds=61) == "wait"


def test_model_configuration():
    assert model_name() == "gpt-4o-mini"
    assert TEMPERATURE == 0.2 and TIMEOUT_SECONDS == 3
    request = explanation_request(sheet())
    assert request["model"] == "gpt-4o-mini" and request["store"] is False
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"] == EXPLANATION_SCHEMA
    system = request["messages"][0]["content"].lower()
    assert "headline" not in system and "range" not in system and "probability" not in system


def test_model_name_can_be_swapped_from_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini-2024-07-18")
    assert explanation_request(sheet())["model"] == "gpt-4o-mini-2024-07-18"


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
    assert first["text"].startswith("The bus is 11 minutes away. Given the walking time is only 3 minutes, you have 8 minutes")
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
    assert set(unc["fact_sheet"]) == set(FACT_SHEET_KEYS) and "band" not in unc["fact_sheet"]
    stale = _poll(_payload(600, quality="stale"))
    assert stale["call"] is False  # no model call for stale or unavailable data


def test_a_reroute_uses_the_winners_numbers():
    payload = {"leave_by": None, "buses": [], "reroute": {
        "winner_score": {"point": 63, "range_low": 55, "range_high": 70, "data_quality": "live"},
        "reroute": {"arrival_time": _iso(300), "stop": {"distance_m": 150}}}}
    pack = _poll(payload, reroute_fired=True)
    assert pack["action"] == "switch_route"
    assert pack["text"].startswith("The bus is 5 minutes away. Given the walking time is 2 minutes, catching this bus is unlikely.")
    assert pack["text"].endswith("It is advisable to switch to another bus.")


# ---- endpoint, key, scope

def test_explain_endpoint_returns_the_assembled_text_and_hides_the_key(monkeypatch):
    secret = "sk-endpoint-secret"
    calls = []

    def fake_complete(fact_sheet, api_key, request):
        calls.append(api_key)
        status_code, queued = handle_explain_request({"fact_sheet": sheet(8, 2, "wait"), "context": CTX})
        assert status_code == 200 and queued["queued"] is True
        return {"status": 200, "body": json.dumps(accepted())}

    monkeypatch.setattr(explain, "_openai_complete", fake_complete)
    monkeypatch.setattr(explain, "read_openai_api_key", lambda: secret)
    status, payload = handle_explain_request({"fact_sheet": sheet(10, 3, "wait"), "context": CTX})
    assert status == 200 and payload["source"] == "model" and payload["action"] == "wait"
    assert payload["text"].startswith("The bus is 10 minutes away.") and payload["text"].endswith("wait for your leave-by alert.")
    assert payload["pending_fact_sheet"]["bus_minutes"] == 8
    assert secret not in json.dumps(payload) and calls == [secret]
    reset_explanation_gate()
    with TestClient(app) as client:
        response = client.post("/api/explain", json={"fact_sheet": sheet(), "context": CTX})
    assert response.status_code == 200 and secret not in response.text


def test_explain_endpoint_rejects_bad_or_spatial_sheets():
    body = sheet()
    body["latitude"] = 1.3
    assert handle_explain_request({"fact_sheet": body})[0] == 422
    inconsistent = sheet()
    inconsistent["minutes_before_leaving"] += 1
    assert handle_explain_request({"fact_sheet": inconsistent})[0] == 422
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
        result = produce_explanation(sheet(), CTX, complete=transport, api_key=secret)
    assert secret not in caplog.text + json.dumps(seen) + json.dumps(result)
    source = (ROOT / "explain.py").read_text(encoding="utf-8")
    for banned in ("sqlite3", "record_observation", "write_text", "logging"):
        assert banned not in source

    def boom(*args, **kwargs):
        raise AssertionError("explanation persistence")

    monkeypatch.setattr(sqlite3, "connect", boom)
    monkeypatch.setattr(Path, "write_text", boom)
    produce_explanation(sheet(), CTX, complete=transport, api_key=secret)


def test_the_model_is_not_asked_to_choose_or_rank_stops():
    request = explanation_request(sheet())
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

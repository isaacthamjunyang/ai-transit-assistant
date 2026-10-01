"""Step 12 explanation layer. Fixtures only — these tests do not call OpenAI."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explain
from explain import (
    ACTION_ADVICE,
    ALLOWED_QUALITY,
    EXPLANATION_SCHEMA,
    FACT_SHEET_KEYS,
    GUARANTEE_PHRASES,
    TEMPERATURE,
    TIMEOUT_SECONDS,
    UNSAFE_PHRASES,
    ExplanationGate,
    build_fact_sheet,
    build_poll_explanation,
    chosen_action,
    classify_poll,
    explanation_request,
    fallback_text,
    handle_explain_request,
    model_name,
    poll_explanation_requests,
    produce_explanation,
    read_openai_api_key,
    reset_explanation_gate,
    trigger_due,
    complete_explanation_request,
)
from main import app

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)


@pytest.fixture(autouse=True)
def _block_live_openai(monkeypatch):
    reset_explanation_gate()

    def forbid(fact_sheet, api_key, request):
        raise AssertionError("live OpenAI call")

    monkeypatch.setattr(explain, "_openai_complete", forbid)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    yield
    reset_explanation_gate()


def sheet(**overrides):
    base = {
        "point": 74,
        "range_low": 65,
        "range_high": 82,
        "slack_seconds": 180,
        "walk_minutes": 4,
        "monitored": True,
        "data_quality": "live",
        "chosen_action": "wait",
    }
    base.update(overrides)
    return base


def accepted(fact):
    return {
        "headline": "About the quoted range at a normal walking pace.",
        "reasoning": "The leave-by clock still fits this walk.",
        "leave_advice": fact["chosen_action"],
        "cited_low": fact["range_low"],
        "cited_high": fact["range_high"],
    }


def transport_returning(body, status=200):
    def transport(fact, request):
        return {"status": status, "body": body if body is None or not isinstance(body, dict) else dict(body)}

    return transport


def exact_fallback(fact):
    advice = ACTION_ADVICE[fact["chosen_action"]]
    return (
        f"Catch probability: {fact['point']}% "
        f"(range {fact['range_low']}\u2013{fact['range_high']}%). "
        f"{advice}"
    )


class _Cache:
    def stop_by_code(self, code):
        return {"Latitude": 1.3002, "Longitude": 103.8002, "stop_code": code}


def _bus(**probability):
    chance = {
        "point": 74,
        "range_low": 65,
        "range_high": 82,
        "slack_seconds": 180,
        "data_quality": "live",
    }
    chance.update(probability)
    return {
        "is_primary": True,
        "is_missed": False,
        "monitored": True,
        "probability": chance,
    }


def _payload(bus=None, leave_by="2026-09-29T14:30:00+08:00", reroute=None):
    payload = {
        "buses": [_bus() if bus is None else bus],
        "leave_by": leave_by,
    }
    if reroute is not None:
        payload["reroute"] = reroute
    return payload


def test_first_valid_score_triggers():
    pack = build_poll_explanation(
        _payload(),
        now=NOW,
        cache=_Cache(),
        user_lat=1.3,
        user_lon=103.8,
        stop_code="01011",
        rendered=False,
        last_low=None,
        last_high=None,
        in_flight=False,
        reroute_fired=False,
    )
    assert pack["call"] is True
    assert pack["fact_sheet"]["data_quality"] == "live"
    assert trigger_due(sheet(), rendered=False, last_low=65, last_high=82) is True


def test_range_low_change_of_exactly_10_triggers():
    current = sheet(range_low=75)
    assert trigger_due(current, rendered=True, last_low=65, last_high=82) is True


def test_range_high_change_of_exactly_10_triggers():
    current = sheet(range_high=92)
    assert trigger_due(current, rendered=True, last_low=65, last_high=82) is True


@pytest.mark.parametrize(
    ("low", "high"),
    [(55, 82), (75, 82), (65, 72), (65, 92)],
)
def test_band_changes_in_either_direction_trigger(low, high):
    current = sheet(range_low=low, range_high=high)
    assert trigger_due(current, rendered=True, last_low=65, last_high=82) is True


def test_change_below_10_does_not_trigger():
    current = sheet(point=99, range_low=74, range_high=91)
    assert trigger_due(current, rendered=True, last_low=65, last_high=82) is False
    same_width = sheet(range_low=70, range_high=80)
    assert trigger_due(same_width, rendered=True, last_low=65, last_high=82) is False


def test_band_compares_with_the_last_rendered_explanation():
    rendered_low, rendered_high = 40, 55
    requested_low, requested_high = 70, 90
    current = sheet(range_low=72, range_high=88)
    assert trigger_due(current, rendered=True, last_low=rendered_low, last_high=rendered_high) is True
    assert trigger_due(current, rendered=True, last_low=requested_low, last_high=requested_high) is False


def test_band_change_and_reroute_make_one_post_reroute_request():
    pre = sheet(point=45, range_low=40, range_high=50, chosen_action="wait")
    post = sheet(point=80, range_low=70, range_high=85, chosen_action="switch_route")
    requests = poll_explanation_requests(
        pre,
        post,
        reroute_fired=True,
        rendered=True,
        last_low=40,
        last_high=50,
        in_flight=False,
    )
    assert requests == [post]
    assert requests[0]["chosen_action"] == "switch_route"
    pack = build_poll_explanation(
        _payload(
            reroute={
                "switched": True,
                "winner_score": {
                    "point": 80,
                    "range_low": 70,
                    "range_high": 85,
                    "slack_seconds": 40,
                    "monitored": True,
                    "data_quality": "live",
                    "walk_minutes": 6,
                },
            }
        ),
        now=NOW,
        cache=_Cache(),
        user_lat=1.3,
        user_lon=103.8,
        stop_code="01011",
        rendered=True,
        last_low=40,
        last_high=50,
        in_flight=False,
        reroute_fired=True,
    )
    assert pack["call"] is True
    assert pack["fact_sheet"]["chosen_action"] == "switch_route"
    assert pack["fact_sheet"]["range_low"] == 70
    assert pack["fact_sheet"]["walk_minutes"] == 6
    assert pack["fact_sheet"]["point"] == 80


def test_no_second_simultaneous_request():
    gate = ExplanationGate()
    calls = []

    def transport(fact, request):
        calls.append(fact["point"])
        assert gate.begin(sheet(point=8, range_low=20, range_high=30)) == "queued"
        return {"status": 200, "body": accepted(fact)}

    assert gate.begin(sheet(point=1)) == "start"
    produce_explanation(sheet(point=1), complete=transport, api_key="sk-test")
    assert calls == [1]
    assert gate.explanation_request_in_flight is True


def test_latest_pending_fact_sheet_is_retained_and_processed_after_completion():
    gate = ExplanationGate()
    first = sheet(point=1, range_low=10, range_high=20)
    middle = sheet(point=2, range_low=30, range_high=40)
    latest = sheet(point=3, range_low=50, range_high=60)
    assert gate.begin(first) == "start"
    assert gate.begin(middle) == "queued"
    assert gate.begin(latest) == "queued"
    assert gate.pending == latest
    calls = []

    def transport(fact, request):
        calls.append(fact["point"])
        return {"status": 200, "body": accepted(fact)}

    result, pending = complete_explanation_request(gate, first, complete=transport, api_key="sk-test")
    assert result["source"] == "model"
    assert gate.explanation_request_in_flight is False
    assert pending == latest
    assert gate.begin(pending) == "start"
    complete_explanation_request(gate, pending, complete=transport, api_key="sk-test")
    assert calls == [1, 3]


def test_timeout_clears_in_flight_before_pending_is_processed():
    gate = ExplanationGate()
    order = []

    def transport(fact, request):
        order.append("call")
        raise TimeoutError("longer than 3 seconds")

    first = sheet(point=1, range_low=10, range_high=20)
    latest = sheet(point=2, range_low=40, range_high=55)
    gate.begin(first)
    gate.begin(latest)
    result, pending = complete_explanation_request(gate, first, complete=transport, api_key="sk-test")
    order.append(("released", gate.explanation_request_in_flight))
    assert result["source"] == "fallback"
    assert result["headline"] == exact_fallback(first)
    assert pending == latest
    assert order == ["call", ("released", False)]
    assert gate.begin(pending) == "start"


@pytest.mark.parametrize("quality", ["live", "schedule", "location uncertain"])
def test_allowed_data_quality_can_call(quality):
    fact = sheet(data_quality=quality)
    pack = classify_poll(fact, rendered=False, last_low=None, last_high=None, in_flight=False)
    assert pack["call"] is True
    assert quality in ALLOWED_QUALITY
    seen = []

    def transport(current, request):
        seen.append(current["data_quality"])
        return {"status": 200, "body": accepted(current)}

    result = produce_explanation(fact, complete=transport, api_key="sk-test")
    assert seen == [quality]
    assert result["source"] == "model"


@pytest.mark.parametrize("quality", ["stale", "unavailable"])
def test_stale_or_unavailable_skips_openai_and_uses_fallback(quality):
    fact = sheet(data_quality=quality, chosen_action="do_not_rely")
    seen = []
    pack = classify_poll(fact, rendered=False, last_low=None, last_high=None, in_flight=False)
    assert pack["call"] is False
    assert pack["replace_with_fallback"] is True
    assert pack["fallback"] == exact_fallback(fact)
    result = produce_explanation(fact, complete=lambda *args: seen.append(args), api_key="sk-test")
    assert seen == []
    assert result["source"] == "fallback"
    assert result["headline"] == exact_fallback(fact)


def test_fact_sheet_has_exact_python_keys_and_no_spatial_selection():
    built = build_fact_sheet(
        point=74,
        range_low=65,
        range_high=82,
        slack_seconds=180,
        walk_minutes=4,
        monitored=True,
        data_quality="live",
        chosen_action="wait",
    )
    assert tuple(built) == FACT_SHEET_KEYS
    assert built == sheet()
    blob = json.dumps(built).lower()
    for marker in ("latitude", "longitude", "stop_code", "coordinate", "bus stop"):
        assert marker not in blob
    request = explanation_request(built)
    user = json.loads(request["messages"][1]["content"])
    assert user == built
    assert "tools" not in request
    assert "functions" not in request


def test_python_action_precedence():
    assert chosen_action(
        reroute_fired_this_poll=True,
        data_quality="stale",
        range_high=10,
        leave_by_seconds=0,
    ) == "switch_route"
    assert chosen_action(
        reroute_fired_this_poll=False,
        data_quality="stale",
        range_high=90,
        leave_by_seconds=10,
    ) == "do_not_rely"
    assert chosen_action(
        reroute_fired_this_poll=False,
        data_quality="unavailable",
        range_high=90,
        leave_by_seconds=120,
    ) == "do_not_rely"
    assert chosen_action(
        reroute_fired_this_poll=False,
        data_quality="live",
        range_high=39,
        leave_by_seconds=120,
    ) == "do_not_rely"
    assert chosen_action(
        reroute_fired_this_poll=False,
        data_quality="location uncertain",
        range_high=40,
        leave_by_seconds=60,
    ) == "leave_now"
    assert chosen_action(
        reroute_fired_this_poll=False,
        data_quality="live",
        range_high=40,
        leave_by_seconds=61,
    ) == "wait"


@pytest.mark.parametrize("action", ["wait", "leave_now", "switch_route", "do_not_rely"])
def test_matching_leave_advice_is_accepted(action):
    fact = sheet(chosen_action=action)
    result = produce_explanation(
        fact,
        complete=transport_returning(accepted(fact)),
        api_key="sk-test",
    )
    assert result["source"] == "model"
    assert result["leave_advice"] == action
    assert result["headline"] == accepted(fact)["headline"]


def test_leave_advice_mismatch_is_rejected():
    fact = sheet(chosen_action="leave_now")
    body = accepted(fact)
    body["leave_advice"] = "wait"
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "fallback"
    assert result["headline"] == exact_fallback(fact)
    assert result["leave_advice"] == "leave_now"


def test_missing_field_is_rejected():
    fact = sheet()
    body = accepted(fact)
    del body["reasoning"]
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "fallback"
    assert result["headline"] == exact_fallback(fact)


def test_extra_field_is_rejected():
    fact = sheet()
    body = accepted(fact)
    body["note"] = "extra"
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "fallback"


def test_malformed_field_type_is_rejected():
    fact = sheet()
    body = accepted(fact)
    body["headline"] = 12
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "fallback"
    assert result["headline"] == exact_fallback(fact)


def test_exact_range_match_is_accepted():
    fact = sheet()
    result = produce_explanation(fact, complete=transport_returning(accepted(fact)), api_key="sk-test")
    assert result["source"] == "model"
    assert result["reasoning"] == accepted(fact)["reasoning"]


def test_low_mismatch_is_rejected():
    fact = sheet()
    body = accepted(fact)
    body["cited_low"] = fact["range_low"] + 1
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["headline"] == exact_fallback(fact)


def test_high_mismatch_is_rejected():
    fact = sheet()
    body = accepted(fact)
    body["cited_high"] = fact["range_high"] - 1
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["headline"] == exact_fallback(fact)


@pytest.mark.parametrize("bad", ["65", 65.0, True])
def test_non_integer_cited_value_is_rejected(bad):
    fact = sheet()
    body = accepted(fact)
    body["cited_low"] = bad
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "fallback"
    assert "65.0" not in result["headline"]


@pytest.mark.parametrize("phrase", UNSAFE_PHRASES)
def test_every_unsafe_phrase_is_rejected(phrase):
    fact = sheet()
    body = accepted(fact)
    body["headline"] = f"Please {phrase.upper()} now."
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "fallback"
    assert phrase.lower() not in result["headline"].lower()
    assert result["headline"] == exact_fallback(fact)


def test_unsafe_phrase_in_reasoning_is_rejected():
    fact = sheet()
    body = accepted(fact)
    body["reasoning"] = "You should sprint the last part."
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["headline"] == exact_fallback(fact)


def test_runtime_is_not_an_unsafe_word():
    fact = sheet()
    body = accepted(fact)
    body["headline"] = "The runtime of this walk is a normal pace."
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "model"


@pytest.mark.parametrize("phrase", GUARANTEE_PHRASES)
def test_guaranteed_arrival_phrases_are_rejected(phrase):
    fact = sheet()
    body = accepted(fact)
    body["reasoning"] = f"Note: {phrase}."
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["source"] == "fallback"
    assert result["headline"] == exact_fallback(fact)


@pytest.mark.parametrize("action", ["wait", "leave_now", "switch_route", "do_not_rely"])
def test_exact_fallback_sentence_for_each_action(action):
    fact = sheet(chosen_action=action, point=74, range_low=65, range_high=82)
    text = fallback_text(fact)
    assert text == exact_fallback(fact)
    assert f"{fact['range_low']}\u2013{fact['range_high']}" in text
    assert f"{fact['range_low']}-{fact['range_high']}" not in text
    assert text.endswith(ACTION_ADVICE[action])
    assert not text.endswith("..")


def test_timeout_http_missing_key_and_malformed_use_the_python_fallback():
    fact = sheet()
    expected = exact_fallback(fact)

    def timed_out(current, request):
        raise TimeoutError("longer than 3 seconds")

    assert produce_explanation(fact, complete=timed_out, api_key="sk-test")["headline"] == expected
    assert produce_explanation(fact, complete=transport_returning("ok", status=500), api_key="sk-test")["headline"] == expected
    assert produce_explanation(fact, complete=transport_returning(accepted(fact), status=201), api_key="sk-test")["headline"] == expected

    def fail_if_called(current, request):
        raise AssertionError("called without a key")

    assert produce_explanation(fact, complete=fail_if_called, api_key="")["headline"] == expected
    assert produce_explanation(fact, complete=transport_returning("not-json"), api_key="sk-test")["headline"] == expected
    assert produce_explanation(fact, complete=transport_returning([1, 2]), api_key="sk-test")["headline"] == expected
    assert produce_explanation(fact, complete=transport_returning(None), api_key="sk-test")["headline"] == expected

    def explode(current, request):
        raise RuntimeError("schema parser failed")

    assert produce_explanation(fact, complete=explode, api_key="sk-test")["headline"] == expected


def test_rejected_model_numbers_never_enter_the_fallback():
    fact = sheet()
    body = accepted(fact)
    body["cited_low"] = 1
    body["cited_high"] = 2
    body["headline"] = "99% if you run"
    result = produce_explanation(fact, complete=transport_returning(body), api_key="sk-test")
    assert result["headline"] == exact_fallback(fact)
    assert "99" not in result["headline"]


def test_model_configuration_and_schema():
    assert model_name() == "gpt-4o-mini"
    assert TEMPERATURE == 0.2
    assert TIMEOUT_SECONDS == 3
    assert EXPLANATION_SCHEMA["additionalProperties"] is False
    assert EXPLANATION_SCHEMA["required"] == [
        "headline",
        "reasoning",
        "leave_advice",
        "cited_low",
        "cited_high",
    ]
    request = explanation_request(sheet())
    assert request["model"] == "gpt-4o-mini"
    assert request["temperature"] == 0.2
    assert request["timeout"] == 3
    assert request["store"] is False
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"] == EXPLANATION_SCHEMA


def test_model_name_can_be_swapped_from_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini-2024-07-18")
    assert model_name() == "gpt-4o-mini-2024-07-18"
    assert explanation_request(sheet())["model"] == "gpt-4o-mini-2024-07-18"


def test_explanation_card_placement_and_updating_state():
    html = INDEX.read_text(encoding="utf-8")
    assert html.index('id="arrival-list"') < html.index('id="ai-explanation"') < html.index('id="notification-panel"')
    assert "AI Explanation" not in html
    assert "Why this catch chance" not in html
    updating = html.split("function showExplanationUpdating", 1)[1].split("function ", 1)[0]
    assert updating.count("● Updating explanation...") == 1
    assert "aiExplanationHeadline" not in updating
    assert "aiExplanationReasoning" not in updating
    assert "aiExplanationAdvice" not in updating
    begin = html.split("function beginExplanation", 1)[1].split("function syncExplanation", 1)[0]
    assert begin.index("showExplanationUpdating") < begin.index('fetch("/api/explain"')
    assert 'aiExplanationHeadline.textContent = ""' not in begin
    assert begin.index("if (explanationInFlight)") < begin.index("explanationInFlight = true")
    assert "pendingExplanation = pack" in begin
    assert begin.index("explanationInFlight = false") < begin.index("beginExplanation(next)")
    render = html.split("function renderExplanation", 1)[1].split("function ", 1)[0]
    assert "aiExplanationHeadline" in render
    assert "aiExplanationReasoning" in render
    assert "aiExplanationAdvice" in render
    stored = html.split("function showStoredExplanationFallback", 1)[1].split("function ", 1)[0]
    assert "renderExplanation" in stored
    assert "lastExplanationPack.fallback" in stored
    success = html.split("function applySuccess", 1)[1].split("function applyRouteSwitch", 1)[0]
    assert success.index("syncExplanation(body)") < success.index("applyRouteSwitch")
    confirm = html.split('confirmDestinationStop.addEventListener("click"', 1)[1].split("function clearLeaveNowTimer", 1)[0]
    assert "resetExplanationState()" in confirm
    assert "OPENAI_API_KEY" not in html
    assert "api.openai.com" not in html
    assert "alert(" not in begin
    assert html.count("setInterval(") == 2


def test_api_key_never_reaches_the_browser_logs_or_disk(tmp_path, capsys, caplog, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    secret = "sk-unit-test-secret"
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    assert read_openai_api_key(env_file) == secret
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "OPENAI_API_KEY" not in INDEX.read_text(encoding="utf-8")
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    seen = {}

    def transport(fact, request):
        seen["request"] = request
        return {"status": 200, "body": accepted(fact)}

    with caplog.at_level(0):
        result = produce_explanation(sheet(), complete=transport, api_key=secret)
    blob = caplog.text + json.dumps(seen) + json.dumps(result)
    assert secret not in blob
    source = (ROOT / "explain.py").read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "record_observation" not in source
    assert "write_text" not in source
    assert "logging" not in source
    assert secret not in source

    def boom(*args, **kwargs):
        raise AssertionError("explanation persistence")

    monkeypatch.setattr(sqlite3, "connect", boom)
    monkeypatch.setattr(Path, "write_text", boom)
    produce_explanation(sheet(), complete=transport, api_key=secret)


def test_explain_endpoint_hides_the_key_and_queues_a_second_request(monkeypatch):
    secret = "sk-endpoint-secret"
    calls = []

    def fake_complete(fact_sheet, api_key, request):
        calls.append(api_key)
        status_code, queued = handle_explain_request(sheet(point=2, range_low=20, range_high=30))
        assert status_code == 200
        assert queued["queued"] is True
        return {"status": 200, "body": json.dumps(accepted(fact_sheet))}

    monkeypatch.setattr(explain, "_openai_complete", fake_complete)
    monkeypatch.setattr(explain, "read_openai_api_key", lambda: secret)
    status, payload = handle_explain_request(sheet())
    assert status == 200
    assert payload["source"] == "model"
    assert payload["pending_fact_sheet"]["point"] == 2
    assert secret not in json.dumps(payload)
    assert calls == [secret]
    reset_explanation_gate()
    with TestClient(app) as client:
        response = client.post("/api/explain", json=sheet())
    assert response.status_code == 200
    assert secret not in response.text
    assert "sqlite" not in response.text.lower()


def test_explain_endpoint_rejects_a_spatial_fact_sheet():
    body = sheet()
    body["latitude"] = 1.3
    status, payload = handle_explain_request(body)
    assert status == 422
    assert "latitude" not in json.dumps(payload)


def test_explainer_is_not_asked_to_choose_or_rank_stops():
    fact = sheet()
    request = explanation_request(fact)
    user = json.loads(request["messages"][1]["content"])
    assert set(user) == set(FACT_SHEET_KEYS)
    raw_user = request["messages"][1]["content"].lower()
    for marker in ("latitude", "longitude", "stop_code", "busstop", "coordinate", "service_no"):
        assert marker not in raw_user
    system = request["messages"][0]["content"].lower()
    assert "choose the best stop" not in system
    assert "select a bus stop" not in system
    assert "rank the stops" not in system
    assert "tools" not in request
    assert "functions" not in request
    called = []

    def transport(current, payload):
        called.append(payload)
        return {"status": 200, "body": accepted(current)}

    produce_explanation(fact, complete=transport, api_key="sk-test")
    assert len(called) == 1
    assert "tools" not in called[0]
    for name in (
        "catch_heuristic.py",
        "journey.py",
        "leave_now.py",
        "arrivals.py",
        "reroute.py",
        "destination_stops.py",
        "nearby.py",
        "onemap.py",
        "observations.py",
        "main.py",
        "static/index.html",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "chat.completions" not in text
        assert "OpenAI(" not in text
        assert "api.openai.com" not in text


def test_step_13_demo_mode_is_not_implemented():
    for name in ("explain.py", "main.py", "static/index.html"):
        assert "DEMO_MODE" not in (ROOT / name).read_text(encoding="utf-8")


def test_openai_sdk_is_installed_and_pinned():
    import openai

    assert openai.__version__ == "3.20.0"
    assert "openai==3.20.0" in (ROOT / "requirements.txt").read_text(encoding="utf-8")

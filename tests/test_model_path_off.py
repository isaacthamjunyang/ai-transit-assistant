"""The model path is off by default: both endpoints answer 503 and never build a client or read the key.

Demo Mode with scenario 12 is the one exception: the endpoints take the simulated reply (still through the real
validators), again with no client and no key. Every test here replaces the OpenAI class and read_openai_api_key
with ones that fail when used.
"""

import pytest
from fastapi.testclient import TestClient

import demo
import explain
import lta_static
from explain import reset_explanation_gate
from main import app

SNAPSHOT = "36|01011|2026-09-29T14:02:00+08:00|2026-09-29T14:00:00+08:00"
EXPLAIN_BODY = {"fact_sheet": {"reason_code": "LEAVE_BY", "chosen_action": "wait"}, "snapshot": SNAPSHOT}
OPTION_BODY = {"fact_sheet": {"reason_code": "HIGHEST_CHANCE", "chosen_action": "switch_route"}, "service_no": "11"}


@pytest.fixture(autouse=True)
def _guarded(monkeypatch, tmp_path):
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(lta_static, "ENV_PATH", env)
    monkeypatch.setattr(explain, "ENV_PATH", env)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("AI_EXPLANATION_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    demo.reset_to_live()
    reset_explanation_gate()
    constructed, key_reads = [], []

    class NeverBuilt:
        def __init__(self, *args, **kwargs):
            constructed.append(1)
            raise AssertionError("an OpenAI client was built")

    def never_read(*args, **kwargs):
        key_reads.append(1)
        raise AssertionError("the OpenAI key was read")

    monkeypatch.setattr("openai.OpenAI", NeverBuilt)
    monkeypatch.setattr(explain, "read_openai_api_key", never_read)
    yield constructed, key_reads
    demo.reset_to_live()
    reset_explanation_gate()


def test_normal_mode_both_endpoints_answer_503_disabled_and_touch_neither_client_nor_key(_guarded):
    constructed, key_reads = _guarded
    with TestClient(app) as client:
        for path, body in (("/api/explain", EXPLAIN_BODY), ("/api/explain-option", OPTION_BODY)):
            reply = client.post(path, json=body)
            assert reply.status_code == 503 and reply.json() == {"status": "disabled"}, path
    assert constructed == [] and key_reads == []


def test_a_body_that_is_not_a_json_object_is_still_422_before_the_handler(_guarded):
    with TestClient(app) as client:
        for path in ("/api/explain", "/api/explain-option"):
            assert client.post(path, json=["not", "an", "object"]).status_code == 422, path


def test_the_flag_defaults_to_off_when_unset_or_blank(tmp_path):
    assert explain.ai_explanation_enabled(tmp_path / "missing.env") is False
    blank = tmp_path / "blank.env"
    blank.write_text("AI_EXPLANATION_ENABLED=\n", encoding="utf-8")
    assert explain.ai_explanation_enabled(blank) is False


def test_the_pack_says_model_enabled_false_in_normal_mode_and_true_with_the_flag(monkeypatch):
    assert explain.model_path_enabled() is False
    monkeypatch.setenv("AI_EXPLANATION_ENABLED", "true")
    assert explain.model_path_enabled() is True


def test_demo_scenario_12_gives_unsafe_contradictory_and_timeout_through_the_real_validators(monkeypatch, _guarded):
    constructed, key_reads = _guarded
    monkeypatch.setenv("DEMO_MODE", "true")
    seen = []
    real_interpret = explain.interpret_explanation

    def spy(raw, fact_sheet):
        seen.append(raw)
        return real_interpret(raw, fact_sheet)

    monkeypatch.setattr(explain, "interpret_explanation", spy)
    fixed = explain.ACTION_ADVICE["wait"]
    with TestClient(app) as client:
        replies = []
        for _ in range(3):  # unsafe, contradictory, timeout: the scenario cycles
            demo.run_scenario(demo.OPENAI_GUARD)
            reply = client.post("/api/explain", json=EXPLAIN_BODY)
            assert reply.status_code == 200, reply.text
            replies.append(reply.json())
        option = client.post("/api/explain-option", json=OPTION_BODY)
        assert option.status_code == 200 and option.json()["source"] == "fallback"
    assert len(seen) == 2  # the first two replies reached the validators; the third timed out
    assert explain.contains_unsafe(seen[0]["body"]["advice"]) and not explain.advice_is_valid(seen[0]["body"]["advice"], "wait")
    assert not explain.advice_is_valid(seen[1]["body"]["advice"], "wait")  # digits and a promise
    for body in replies:
        assert body["source"] == "fallback" and body["advice"] == fixed
        assert body["snapshot"] == SNAPSHOT
    assert constructed == [] and key_reads == []


def test_demo_mode_without_scenario_12_is_still_disabled(monkeypatch, _guarded):
    monkeypatch.setenv("DEMO_MODE", "true")
    with TestClient(app) as client:
        assert client.post("/api/explain", json=EXPLAIN_BODY).status_code == 503

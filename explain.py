"""OpenAI explanation layer.

OpenAI receives only an already-computed numerical fact sheet from Python.
The fact sheet contains no prompt instructions or API capabilities to select,
resolve, rank, or modify coordinates or bus stops. All spatial resolution and
journey calculations remain strictly inside Python.
"""

import json
import os
import re
from datetime import datetime

from journey import parse_journey_time
from lta_static import ENV_PATH, _read_env_value
from nearby import haversine_m, walk_minutes

DEFAULT_MODEL = "gpt-4o-mini"
TEMPERATURE = 0.2
TIMEOUT_SECONDS = 3

FACT_SHEET_KEYS = (
    "point",
    "range_low",
    "range_high",
    "slack_seconds",
    "walk_minutes",
    "monitored",
    "data_quality",
    "chosen_action",
)
ACTIONS = ("wait", "leave_now", "switch_route", "do_not_rely")
ALLOWED_QUALITY = ("live", "schedule", "location uncertain")
RESPONSE_FIELDS = ("headline", "reasoning", "leave_advice", "cited_low", "cited_high")

EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "reasoning": {"type": "string"},
        "leave_advice": {
            "type": "string",
            "enum": ["wait", "leave_now", "switch_route", "do_not_rely"],
        },
        "cited_low": {"type": "integer"},
        "cited_high": {"type": "integer"},
    },
    "required": ["headline", "reasoning", "leave_advice", "cited_low", "cited_high"],
    "additionalProperties": False,
}

ACTION_ADVICE = {
    "wait": "Wait for your leave-by alert.",
    "leave_now": "Leave now to walk to the bus stop.",
    "switch_route": "Route updated to an alternate service.",
    "do_not_rely": "Data uncertain; do not rely solely on this estimate.",
}

UNSAFE_PHRASES = (
    "run",
    "running",
    "sprint",
    "sprinting",
    "dash",
    "dashing",
    "hurry",
    "hurrying",
    "jaywalk",
    "jaywalking",
    "cross against",
    "ignore light",
    "ignore traffic",
)

GUARANTEE_PHRASES = (
    "you'll make it",
    "you will make it",
    "definitely make it",
    "definitely catch",
    "guaranteed",
    "100% guarantee",
    "certain to catch",
    "impossible to miss",
)

SYSTEM_PROMPT = (
    "OpenAI receives only an already-computed numerical fact sheet from Python. "
    "The fact sheet contains no prompt instructions or API capabilities to select, "
    "resolve, rank, or modify coordinates or bus stops. All spatial resolution and "
    "journey calculations remain strictly inside Python. "
    "Explain the fact sheet in plain language. "
    "Set cited_low to range_low and cited_high to range_high. "
    "Set leave_advice to chosen_action. "
    "Recommend only a normal walking pace."
)

_UNSAFE_PATTERNS = tuple(
    re.compile(r"\b" + r"\s+".join(re.escape(part) for part in phrase.split(" ")) + r"\b", re.IGNORECASE)
    for phrase in UNSAFE_PHRASES
)


class ExplanationGate:
    """One in-flight explanation, plus the latest pending fact sheet only."""

    def __init__(self) -> None:
        self.explanation_request_in_flight = False
        self.pending: dict | None = None

    def begin(self, fact_sheet: dict) -> str:
        if fact_sheet.get("data_quality") not in ALLOWED_QUALITY:
            return "skip"
        if self.explanation_request_in_flight:
            self.pending = {key: fact_sheet[key] for key in FACT_SHEET_KEYS}
            return "queued"
        self.explanation_request_in_flight = True
        return "start"

    def finish(self) -> dict | None:
        self.explanation_request_in_flight = False
        pending = self.pending
        self.pending = None
        return pending


EXPLANATION_GATE = ExplanationGate()


def reset_explanation_gate() -> None:
    EXPLANATION_GATE.explanation_request_in_flight = False
    EXPLANATION_GATE.pending = None


def read_openai_api_key(env_path=None) -> str:
    path = ENV_PATH if env_path is None else env_path
    from_file = _read_env_value(path, "OPENAI_API_KEY")
    if from_file:
        return from_file
    return os.environ.get("OPENAI_API_KEY", "").strip()


def model_name() -> str:
    configured = os.environ.get("OPENAI_MODEL", "").strip()
    return configured or DEFAULT_MODEL


def ai_explanation_enabled(env_path=None) -> bool:
    """Page and server switch for the explanation card. Default off."""
    path = ENV_PATH if env_path is None else env_path
    raw = _read_env_value(path, "AI_EXPLANATION_ENABLED")
    if not raw:
        raw = os.environ.get("AI_EXPLANATION_ENABLED", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def chosen_action(
    *,
    reroute_fired_this_poll: bool,
    data_quality: str,
    range_high: int,
    leave_by_seconds: float,
) -> str:
    if reroute_fired_this_poll:
        action = "switch_route"
    elif data_quality in ("stale", "unavailable") or range_high < 40:
        action = "do_not_rely"
    elif leave_by_seconds <= 60:
        action = "leave_now"
    else:
        action = "wait"
    return action


def seconds_until_leave_by(leave_by_iso: str | None, now: datetime) -> float:
    """A missing leave-by stays above 60 so the action else-branch is wait."""
    if not isinstance(leave_by_iso, str) or not leave_by_iso.strip():
        return 61
    try:
        leave_by = parse_journey_time(leave_by_iso)
    except ValueError:
        return 61
    return (leave_by - now).total_seconds()


def fallback_text(fact_sheet: dict) -> str:
    advice = ACTION_ADVICE[fact_sheet["chosen_action"]]
    return (
        f"Catch probability: {fact_sheet['point']}% "
        f"(range {fact_sheet['range_low']}\u2013{fact_sheet['range_high']}%). "
        f"{advice}"
    )


def build_fact_sheet(
    *,
    point: int,
    range_low: int,
    range_high: int,
    slack_seconds: int,
    walk_minutes: int,
    monitored: bool,
    data_quality: str,
    chosen_action: str,
) -> dict:
    sheet = {
        "point": point,
        "range_low": range_low,
        "range_high": range_high,
        "slack_seconds": slack_seconds,
        "walk_minutes": walk_minutes,
        "monitored": monitored,
        "data_quality": data_quality,
        "chosen_action": chosen_action,
    }
    if tuple(sheet) != FACT_SHEET_KEYS:
        raise ValueError("Fact sheet keys are fixed.")
    for key in ("point", "range_low", "range_high", "slack_seconds", "walk_minutes"):
        if type(sheet[key]) is not int:
            raise ValueError("Fact sheet numbers must be integers.")
    if type(sheet["monitored"]) is not bool or sheet["chosen_action"] not in ACTIONS:
        raise ValueError("Fact sheet state is invalid.")
    if not isinstance(sheet["data_quality"], str) or not sheet["data_quality"]:
        raise ValueError("Fact sheet data quality is invalid.")
    return sheet


def trigger_due(
    fact_sheet: dict,
    *,
    rendered: bool,
    last_low: int | None,
    last_high: int | None,
) -> bool:
    if not rendered or type(last_low) is not int or type(last_high) is not int:
        return True
    low_shift = abs(fact_sheet["range_low"] - last_low)
    high_shift = abs(fact_sheet["range_high"] - last_high)
    return low_shift >= 10 or high_shift >= 10


def classify_poll(
    fact_sheet: dict,
    *,
    rendered: bool,
    last_low: int | None,
    last_high: int | None,
    in_flight: bool,
) -> dict:
    pack = {
        "fact_sheet": fact_sheet,
        "fallback": fallback_text(fact_sheet),
        "call": False,
        "pending": False,
        "replace_with_fallback": False,
    }
    if fact_sheet["data_quality"] not in ALLOWED_QUALITY:
        pack["replace_with_fallback"] = True
        return pack
    if not trigger_due(fact_sheet, rendered=rendered, last_low=last_low, last_high=last_high):
        return pack
    if in_flight:
        pack["pending"] = True
        return pack
    pack["call"] = True
    return pack


def poll_explanation_requests(
    pre_sheet: dict,
    post_sheet: dict,
    *,
    reroute_fired: bool,
    rendered: bool,
    last_low: int | None,
    last_high: int | None,
    in_flight: bool,
) -> list[dict]:
    """One poll yields at most one request. A reroute uses the post-reroute sheet."""
    sheet = post_sheet if reroute_fired else pre_sheet
    pack = classify_poll(
        sheet,
        rendered=rendered,
        last_low=last_low,
        last_high=last_high,
        in_flight=in_flight,
    )
    if pack["call"]:
        return [pack["fact_sheet"]]
    return []


def boarding_walk_minutes(cache, stop_code: str, user_lat: float | None, user_lon: float | None) -> int | None:
    if cache is None or user_lat is None or user_lon is None:
        return None
    stop = cache.stop_by_code(stop_code)
    if not isinstance(stop, dict):
        return None
    lat = stop.get("Latitude")
    lon = stop.get("Longitude")
    if type(lat) not in (int, float) or type(lon) not in (int, float):
        return None
    return walk_minutes(haversine_m(float(user_lat), float(user_lon), float(lat), float(lon)))


def build_poll_explanation(
    payload: dict,
    *,
    now: datetime,
    cache,
    user_lat: float | None,
    user_lon: float | None,
    stop_code: str,
    rendered: bool,
    last_low: int | None,
    last_high: int | None,
    in_flight: bool,
    reroute_fired: bool,
) -> dict | None:
    if reroute_fired:
        score = _winner_fields(payload)
        if score is None:
            return None
        point = score.get("point")
        low = score.get("range_low")
        high = score.get("range_high")
        slack = score.get("slack_seconds")
        monitored = score.get("monitored")
        quality = score.get("data_quality")
        minutes = score.get("walk_minutes")
    else:
        bus = _scored_journey_bus(payload.get("buses") or [])
        chance = bus.get("probability") if isinstance(bus, dict) else None
        if not isinstance(chance, dict):
            return None
        point = chance.get("point")
        low = chance.get("range_low")
        high = chance.get("range_high")
        slack = chance.get("slack_seconds")
        monitored = bus.get("monitored")
        quality = chance.get("data_quality")
        minutes = boarding_walk_minutes(cache, stop_code, user_lat, user_lon)
    if (
        type(point) is not int
        or type(low) is not int
        or type(high) is not int
        or type(slack) is not int
        or type(minutes) is not int
        or type(monitored) is not bool
        or not isinstance(quality, str)
    ):
        return None
    action = chosen_action(
        reroute_fired_this_poll=reroute_fired,
        data_quality=quality,
        range_high=high,
        leave_by_seconds=seconds_until_leave_by(payload.get("leave_by"), now),
    )
    sheet = build_fact_sheet(
        point=point,
        range_low=low,
        range_high=high,
        slack_seconds=slack,
        walk_minutes=minutes,
        monitored=monitored,
        data_quality=quality,
        chosen_action=action,
    )
    return classify_poll(
        sheet,
        rendered=rendered,
        last_low=last_low,
        last_high=last_high,
        in_flight=in_flight,
    )


def explanation_messages(fact_sheet: dict) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(fact_sheet, separators=(",", ":"))},
    ]


def explanation_request(fact_sheet: dict) -> dict:
    return {
        "model": model_name(),
        "temperature": TEMPERATURE,
        "timeout": TIMEOUT_SECONDS,
        "store": False,
        "messages": explanation_messages(fact_sheet),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "bus_catch_explanation",
                "strict": True,
                "schema": EXPLANATION_SCHEMA,
            },
        },
    }


def _openai_demo_active() -> bool:
    import demo

    return demo.explanation_is_simulated()


def produce_explanation(fact_sheet: dict, *, complete=None, api_key: str | None = None) -> dict:
    if fact_sheet["data_quality"] not in ALLOWED_QUALITY:
        return fallback_view(fact_sheet)
    key = read_openai_api_key() if api_key is None else api_key
    demo_supplies_result = complete is None and _openai_demo_active()
    if not key and not demo_supplies_result:
        return fallback_view(fact_sheet)
    request = explanation_request(fact_sheet)
    try:
        if complete is None:
            raw = _openai_complete(fact_sheet, key or "", request)
        else:
            raw = complete(fact_sheet, request)
    except TimeoutError:
        return fallback_view(fact_sheet)
    except AssertionError:
        raise
    except Exception:
        return fallback_view(fact_sheet)
    return interpret_explanation(raw, fact_sheet)


def complete_explanation_request(gate: ExplanationGate, fact_sheet: dict, **kwargs) -> tuple[dict, dict | None]:
    try:
        result = produce_explanation(fact_sheet, **kwargs)
    except TimeoutError:
        result = fallback_view(fact_sheet)
    except AssertionError:
        raise
    except Exception:
        result = fallback_view(fact_sheet)
    pending = gate.finish()
    return result, pending


def handle_explain_request(body: dict) -> tuple[int, dict]:
    sheet = parse_fact_sheet(body)
    if sheet is None:
        return 422, {"detail": "Fact sheet is invalid."}
    if sheet["data_quality"] not in ALLOWED_QUALITY:
        view = fallback_view(sheet)
        view["status"] = "ok"
        return 200, view
    kind = EXPLANATION_GATE.begin(sheet)
    if kind == "queued":
        return 200, {"status": "ok", "queued": True, "source": "queued"}
    result, pending = complete_explanation_request(EXPLANATION_GATE, sheet)
    payload = dict(result)
    payload["status"] = "ok"
    payload["pending_fact_sheet"] = pending
    return 200, payload


def parse_fact_sheet(body: dict) -> dict | None:
    if not isinstance(body, dict) or set(body) != set(FACT_SHEET_KEYS):
        return None
    for key in ("point", "range_low", "range_high", "slack_seconds", "walk_minutes"):
        if type(body[key]) is not int:
            return None
    if type(body["monitored"]) is not bool or body["chosen_action"] not in ACTIONS:
        return None
    if not isinstance(body["data_quality"], str) or not body["data_quality"]:
        return None
    return {key: body[key] for key in FACT_SHEET_KEYS}


def fallback_view(fact_sheet: dict) -> dict:
    text = fallback_text(fact_sheet)
    return {
        "source": "fallback",
        "headline": text,
        "reasoning": "",
        "leave_advice": fact_sheet["chosen_action"],
        "fallback": text,
        "queued": False,
    }


def interpret_explanation(raw: dict, fact_sheet: dict) -> dict:
    if not isinstance(raw, dict) or raw.get("status", 200) != 200:
        return fallback_view(fact_sheet)
    parsed = _parse_body(raw.get("body"))
    if not _schema_ok(parsed):
        return fallback_view(fact_sheet)
    if parsed["cited_low"] != fact_sheet["range_low"] or parsed["cited_high"] != fact_sheet["range_high"]:
        return fallback_view(fact_sheet)
    if parsed["leave_advice"] != fact_sheet["chosen_action"]:
        return fallback_view(fact_sheet)
    if contains_unsafe(parsed["headline"], parsed["reasoning"]):
        return fallback_view(fact_sheet)
    if contains_guarantee(parsed["headline"], parsed["reasoning"]):
        return fallback_view(fact_sheet)
    return {
        "source": "model",
        "headline": parsed["headline"],
        "reasoning": parsed["reasoning"],
        "leave_advice": parsed["leave_advice"],
        "fallback": fallback_text(fact_sheet),
        "queued": False,
    }


def contains_unsafe(headline: str, reasoning: str) -> bool:
    text = f"{headline}\n{reasoning}"
    return any(pattern.search(text) for pattern in _UNSAFE_PATTERNS)


def contains_guarantee(headline: str, reasoning: str) -> bool:
    text = f"{headline}\n{reasoning}".lower().replace("\u2019", "'").replace("\u2018", "'")
    return any(phrase in text for phrase in GUARANTEE_PHRASES)


def _schema_ok(parsed: dict | None) -> bool:
    if not isinstance(parsed, dict) or set(parsed) != set(RESPONSE_FIELDS):
        return False
    if not isinstance(parsed["headline"], str) or not isinstance(parsed["reasoning"], str):
        return False
    if parsed["leave_advice"] not in ACTIONS:
        return False
    if type(parsed["cited_low"]) is not int or type(parsed["cited_high"]) is not int:
        return False
    return True


def _parse_body(body: object) -> dict | None:
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _openai_complete(fact_sheet: dict, api_key: str, request: dict) -> dict:
    import demo

    simulated = demo.simulated_openai_result(fact_sheet)
    if simulated is not None:
        if simulated.get("timeout") is True:
            raise TimeoutError("explanation timed out")
        return {"status": simulated["status"], "body": simulated["body"]}
    from openai import APIStatusError, APITimeoutError, OpenAI

    client = OpenAI(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=0)
    try:
        completion = client.chat.completions.create(
            model=request["model"],
            temperature=request["temperature"],
            messages=request["messages"],
            response_format=request["response_format"],
            store=False,
            timeout=request["timeout"],
        )
    except APITimeoutError as exc:
        raise TimeoutError("explanation timed out") from exc
    except APIStatusError as exc:
        return {"status": int(exc.status_code), "body": None}
    content = completion.choices[0].message.content
    return {"status": 200, "body": content}


def _scored_journey_bus(buses: list) -> dict | None:
    active = None
    primary = None
    for bus in buses:
        if not isinstance(bus, dict) or bus.get("is_missed"):
            continue
        if bus.get("is_active_target") and active is None:
            active = bus
        elif bus.get("is_primary") and primary is None:
            primary = bus
    return active if active is not None else primary


def _winner_fields(payload: dict) -> dict | None:
    decision = payload.get("reroute")
    if not isinstance(decision, dict):
        return None
    score = decision.get("winner_score")
    if not isinstance(score, dict):
        return None
    return score

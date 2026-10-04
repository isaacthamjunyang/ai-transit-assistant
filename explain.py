"""The AI Explanation card.

The text has exactly three sentences. Python computes every number and writes sentences one and two from a fixed
template, in the same poll response and from the same numbers as the arrival tile and the catch card, for the bus
the tile shows. The model's only job is the clause that completes "It is advisable to ...", and Python falls back
to a fixed clause for the action whenever the model is missing, slow, or rejected. OpenAI receives the action and
a reason code from a closed set and nothing else: no minutes, no probability, no range, no seconds, no
coordinates, no stops.
"""

import json
import math
import os
import re
from datetime import datetime

from journey import parse_journey_time
from lta_static import ENV_PATH, _read_env_value
from config import WALK_SPEED_DEFAULT_MPS
from nearby import haversine_m
from walk_speed import walk_minutes

DEFAULT_MODEL = "gpt-4o-mini"
TEMPERATURE = 0.2
TIMEOUT_SECONDS = 3

# What the model may see: a reason code and the action. No number at all.
FACT_SHEET_KEYS = ("reason_code", "chosen_action")
REASON_CODES = ("LOCATION_UNCERTAIN", "UNLIKELY", "MAY_NOT_REACH", "TIME_TO_SPARE")
ACTIONS = ("wait", "leave_now", "switch_route", "do_not_rely")
ALLOWED_QUALITY = ("live", "schedule", "location uncertain")
RESPONSE_FIELDS = ("advice",)
MAX_ADVICE_WORDS = 15

EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {"advice": {"type": "string"}},
    "required": ["advice"],
    "additionalProperties": False,
}

# Sentence three, when the model does not supply a usable clause. Python decides the advice.
ACTION_ADVICE = {
    "wait": "wait for your leave-by alert",
    "leave_now": "leave now and walk to the bus stop",
    "switch_route": "switch to another bus",
    "do_not_rely": "not rely only on this estimate",
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

# The clause has to agree with the action Python chose.
_FORBIDDEN_FOR_ACTION = {
    "wait": re.compile(r"\b(leave now|go now|set off|head off|head out|walk now|leave immediately)\b"),
    "leave_now": re.compile(r"\b(wait|hold off|stay put)\b"),
    "switch_route": re.compile(r"\b(leave now|wait for)\b"),
    "do_not_rely": re.compile(r"\b(leave now|go now|walk now)\b"),
}
_REQUIRED_FOR_ACTION = {
    "switch_route": re.compile(r"\b(switch|change|another bus|different bus|other bus)\b"),
    "do_not_rely": re.compile(r"\b(not rely|don't rely|do not rely|not depend|avoid relying|not count on)\b"),
}
_SECONDS_WORDS = re.compile(r"\b(sec|secs|second|seconds)\b", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You finish one sentence for a bus app: \"It is advisable to ...\". "
    "You receive reason_code and chosen_action. reason_code is one of LOCATION_UNCERTAIN, UNLIKELY, "
    "MAY_NOT_REACH, TIME_TO_SPARE; you never see a number. "
    "Return JSON with one field, advice: the words that complete the sentence, in lower case, at most 15 words, "
    "with no digits, no full stop, and no word about seconds. "
    "The advice must agree with chosen_action: wait means wait for the leave-by alert, leave_now means leave now "
    "and walk to the bus stop, switch_route means switch to another bus, do_not_rely means not rely only on the "
    "estimate. Recommend only a normal walking pace. Never promise that the bus will be caught."
)

_UNSAFE_PATTERNS = tuple(
    re.compile(r"\b" + r"\s+".join(re.escape(part) for part in phrase.split(" ")) + r"\b", re.IGNORECASE)
    for phrase in UNSAFE_PHRASES
)


class ExplanationGate:
    """One in-flight advice request, plus the latest pending fact sheet only."""

    def __init__(self) -> None:
        self.explanation_request_in_flight = False
        self.pending: dict | None = None

    def begin(self, fact_sheet: dict) -> str:
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
    """Page and server switch for the explanation card. Default on; only an explicit false-like value turns it off."""
    path = ENV_PATH if env_path is None else env_path
    raw = _read_env_value(path, "AI_EXPLANATION_ENABLED")
    if not raw:
        raw = os.environ.get("AI_EXPLANATION_ENABLED", "")
    text = raw.strip().lower()
    if not text:
        return True
    return text in {"1", "true", "yes", "on"}


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


# ---- the numbers: the same functions and rounding the page uses ----

def round_half_up(value: float) -> int:
    """JavaScript Math.round for the values used here."""
    return int(math.floor(value + 0.5))


def tile_minutes(arrival_iso: str | None, now: datetime) -> int | None:
    """Whole minutes the arrival tile shows. 0 stands for "Due" (30 s or less) and "<1 min"."""
    if not isinstance(arrival_iso, str) or not arrival_iso.strip():
        return None
    try:
        eta = parse_journey_time(arrival_iso)
    except ValueError:
        return None
    seconds = round_half_up((eta - now).total_seconds())
    if seconds < 60:
        return 0
    return round_half_up(seconds / 60)


def overview_walk_minutes(distance_m: float, walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> int:
    """Whole minutes the journey overview shows for a walk: at least 1."""
    return walk_minutes(distance_m, walk_speed_m_s, "display")


def boarding_walk_minutes(
    cache, stop_code: str, user_lat: float | None, user_lon: float | None, walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS
) -> int | None:
    if cache is None or user_lat is None or user_lon is None:
        return None
    stop = cache.stop_by_code(stop_code)
    if not isinstance(stop, dict):
        return None
    lat = stop.get("Latitude")
    lon = stop.get("Longitude")
    if type(lat) not in (int, float) or type(lon) not in (int, float):
        return None
    return overview_walk_minutes(
        haversine_m(float(user_lat), float(user_lon), float(lat), float(lon)), walk_speed_m_s
    )


def minutes_text(count: int) -> str:
    return "1 minute" if count == 1 else f"{count} minutes"


# Every field of the poll's explanation pack that the page reads. The page keeps a MIRROR of tile_minutes,
# sentence_one and sentence_two (static/index.html: explanationMinutes, explanationLead) so it can redraw sentences
# one and two every second from the tile's own minutes. Any change to the templates or the variant rules here must
# change that mirror too. Tests that pin the two: tests/test_explanation_consistency.py
# (test_the_page_mirror_equals_python_on_the_boundary_grid, ..._on_3000_seeded_random_cases,
# ..._on_every_minute_and_walk_pair_in_range, test_the_page_reads_exactly_the_pack_fields_the_server_lists) and tests/test_walk_speed_page.py
# (test_real_poll_payloads_render_the_same_sentences_as_the_pack).
PAGE_PACK_FIELDS = (
    "snapshot", "fact_sheet", "text", "clause", "action", "arrival_time", "walk_minutes", "band", "uncertain",
    "call", "pending",
)


def build_numbers(*, bus_minutes: int, walk_minutes: int, chosen_action: str) -> dict:
    """The numbers of sentences one and two. They stay on the server and are never sent to the model."""
    numbers = {
        "bus_minutes": bus_minutes,
        "walk_minutes": walk_minutes,
        "minutes_before_leaving": bus_minutes - walk_minutes,
        "chosen_action": chosen_action,
    }
    for key in ("bus_minutes", "walk_minutes", "minutes_before_leaving"):
        if type(numbers[key]) is not int:
            raise ValueError("Explanation numbers must be integers.")
    if numbers["chosen_action"] not in ACTIONS:
        raise ValueError("Explanation action is invalid.")
    return numbers


def sentence_one(bus_minutes: int) -> str:
    if bus_minutes < 1:
        return "The bus is arriving now."
    return f"The bus is {minutes_text(bus_minutes)} away."


def sentence_two(numbers: dict, *, band: str | None, uncertain: bool) -> str:
    """First match wins: location uncertain, low band or switch or do-not-rely, may not reach, then the default."""
    e = numbers["bus_minutes"]
    w = numbers["walk_minutes"]
    t = numbers["minutes_before_leaving"]
    lead = f"Given the walking time is {minutes_text(w)}"
    if uncertain:
        return "Your location is uncertain, so the walking time may be off."
    if band == "low" or numbers["chosen_action"] in ("switch_route", "do_not_rely"):
        return f"{lead}, catching this bus is unlikely."
    if w >= e:
        return f"{lead}, you may not reach the stop before the bus."
    return f"Given the walking time is only {minutes_text(w)}, you have {minutes_text(t)} to get to the bus stop."


def reason_code_for(numbers: dict, *, band: str | None, uncertain: bool) -> str:
    """The sentence-two variant as a code: the only thing about the numbers the model is told."""
    if uncertain:
        return "LOCATION_UNCERTAIN"
    if band == "low" or numbers["chosen_action"] in ("switch_route", "do_not_rely"):
        return "UNLIKELY"
    if numbers["walk_minutes"] >= numbers["bus_minutes"]:
        return "MAY_NOT_REACH"
    return "TIME_TO_SPARE"


def lead_text(numbers: dict, *, band: str | None, uncertain: bool) -> str:
    """Sentences one and two."""
    return sentence_one(numbers["bus_minutes"]) + " " + sentence_two(numbers, band=band, uncertain=uncertain)


def clause_text(advice: str) -> str:
    """Sentence three."""
    return f"It is advisable to {advice}."


def compose_text(numbers: dict, advice: str, *, band: str | None, uncertain: bool) -> str:
    return lead_text(numbers, band=band, uncertain=uncertain) + " " + clause_text(advice)


# ---- the model's clause ----

def advice_is_valid(advice: object, action: str) -> bool:
    """Every check the clause has to pass. Any failure means the fixed clause is used."""
    if not isinstance(advice, str) or action not in ACTIONS:
        return False
    text = advice.strip()
    if not text or text != advice:
        return False
    if re.search(r"\d", text) or text.endswith(".") or text != text.lower():
        return False
    if len(text.split()) > MAX_ADVICE_WORDS or _SECONDS_WORDS.search(text):
        return False
    if contains_unsafe(text) or contains_guarantee(text):
        return False
    if _FORBIDDEN_FOR_ACTION[action].search(text):
        return False
    required = _REQUIRED_FOR_ACTION.get(action)
    if required is not None and not required.search(text):
        return False
    return True


def contains_unsafe(text: str) -> bool:
    return any(pattern.search(text) for pattern in _UNSAFE_PATTERNS)


def contains_guarantee(text: str) -> bool:
    lowered = text.lower().replace("’", "'").replace("‘", "'")
    return any(phrase in lowered for phrase in GUARANTEE_PHRASES)


def deterministic_advice(action: str) -> str:
    return ACTION_ADVICE[action]


def parse_fact_sheet(body: dict) -> dict | None:
    if not isinstance(body, dict) or set(body) != set(FACT_SHEET_KEYS):
        return None
    if body["reason_code"] not in REASON_CODES or body["chosen_action"] not in ACTIONS:
        return None
    return {key: body[key] for key in FACT_SHEET_KEYS}


def parse_snapshot(value: object) -> str | None:
    """The key of the poll an explanation belongs to: bus id plus poll time. Echoed back, never interpreted."""
    if isinstance(value, str) and 0 < len(value) <= 200 and re.fullmatch(r"[\w|:.+\-]+", value):
        return value
    return None


def explanation_messages(fact_sheet: dict) -> list[dict]:
    visible = {key: fact_sheet[key] for key in FACT_SHEET_KEYS}
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(visible, separators=(",", ":"))},
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
            "json_schema": {"name": "bus_catch_advice", "strict": True, "schema": EXPLANATION_SCHEMA},
        },
    }


def _openai_demo_active() -> bool:
    import demo

    return demo.explanation_is_simulated()


def advice_view(fact_sheet: dict, advice: str, source: str) -> dict:
    return {
        "source": source,
        "advice": advice,
        "clause": clause_text(advice),
        "action": fact_sheet["chosen_action"],
        "reason_code": fact_sheet["reason_code"],
        "queued": False,
    }


def fallback_view(fact_sheet: dict) -> dict:
    return advice_view(fact_sheet, deterministic_advice(fact_sheet["chosen_action"]), "fallback")


def produce_explanation(fact_sheet: dict, *, complete=None, api_key: str | None = None) -> dict:
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
    """The request is {fact_sheet: {reason_code, chosen_action}, snapshot}. The snapshot is echoed so the page can
    drop a reply that belongs to an older poll."""
    if not isinstance(body, dict):
        return 422, {"detail": "Fact sheet is invalid."}
    sheet = parse_fact_sheet(body.get("fact_sheet"))
    snapshot = parse_snapshot(body.get("snapshot"))
    if sheet is None or snapshot is None:
        return 422, {"detail": "Fact sheet is invalid."}
    kind = EXPLANATION_GATE.begin(sheet)
    if kind == "queued":
        return 200, {"status": "ok", "queued": True, "source": "queued", "snapshot": snapshot}
    result, pending = complete_explanation_request(EXPLANATION_GATE, sheet)
    payload = dict(result)
    payload["status"] = "ok"
    payload["snapshot"] = snapshot
    payload["pending_fact_sheet"] = pending
    return 200, payload


def interpret_explanation(raw: dict, fact_sheet: dict) -> dict:
    if not isinstance(raw, dict) or raw.get("status", 200) != 200:
        return fallback_view(fact_sheet)
    parsed = _parse_body(raw.get("body"))
    if not isinstance(parsed, dict) or set(parsed) != set(RESPONSE_FIELDS):
        return fallback_view(fact_sheet)
    advice = parsed["advice"]
    if not advice_is_valid(advice, fact_sheet["chosen_action"]):
        return fallback_view(fact_sheet)
    return advice_view(fact_sheet, advice, "model")


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


# ---- the poll: sentences one and two are rebuilt from the tracked bus's numbers every time ----

def snapshot_key(stop_code: str, service_no: str, arrival_iso: str | None, poll_time: datetime) -> str:
    """Bus id plus poll time: identifies the one poll an explanation belongs to."""
    arrival = (arrival_iso or "none").replace(" ", "")
    return f"{service_no}|{stop_code}|{arrival}|{poll_time.isoformat()}"


def build_poll_explanation(
    payload: dict,
    *,
    now: datetime,
    cache,
    user_lat: float | None,
    user_lon: float | None,
    stop_code: str,
    explained_action: str | None,
    explained_advice: str | None,
    in_flight: bool,
    reroute_fired: bool,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict | None:
    """The card's text for this poll, plus whether a model clause is needed for the action.

    The card always describes the tracked bus, the one the arrival tile and the catch card show. A reroute that
    fires only changes the action to switch_route (and with it the wording); it never brings in the minutes
    of the better bus. Sentences one and two use this poll's numbers. Only the clause is cached, keyed by the
    action: it is reused while the action is unchanged and replaced by the fixed clause until the model's clause
    for a new action arrives. The pack carries what the page needs to redraw sentences one and two from the
    tile's own minutes every second (arrival time, walk minutes, band, uncertain flag), and the snapshot key.
    """
    bus = _scored_journey_bus(payload.get("buses") or [])
    chance = bus.get("probability") if isinstance(bus, dict) else None
    if not isinstance(chance, dict):
        return None
    quality = chance.get("data_quality")
    high = chance.get("range_high")
    band = chance.get("band")
    arrival = bus.get("arrival_time")
    walk = boarding_walk_minutes(cache, stop_code, user_lat, user_lon, walk_speed_m_s)
    bus_minutes = tile_minutes(arrival, now)
    if (
        bus_minutes is None
        or type(walk) is not int
        or type(high) is not int
        or not isinstance(quality, str)
    ):
        return None
    action = chosen_action(
        reroute_fired_this_poll=reroute_fired,
        data_quality=quality,
        range_high=high,
        leave_by_seconds=seconds_until_leave_by(payload.get("leave_by"), now),
    )
    numbers = build_numbers(bus_minutes=bus_minutes, walk_minutes=walk, chosen_action=action)
    band = band if band in ("ok", "mid", "low") else None
    uncertain = quality == "location uncertain"
    reason = reason_code_for(numbers, band=band, uncertain=uncertain)
    sheet = {"reason_code": reason, "chosen_action": action}
    cached = explained_advice if explained_action == action and advice_is_valid(explained_advice, action) else None
    advice = cached if cached is not None else deterministic_advice(action)
    needs_model = quality in ALLOWED_QUALITY and cached is None
    return {
        "snapshot": snapshot_key(stop_code, str(payload.get("service_no") or ""), arrival, now),
        "fact_sheet": sheet,
        "text": compose_text(numbers, advice, band=band, uncertain=uncertain),
        "clause": clause_text(advice),
        "action": action,
        "reason_code": reason,
        "arrival_time": arrival,
        "walk_minutes": walk,
        "band": band,
        "uncertain": uncertain,
        "call": needs_model and not in_flight,
        "pending": needs_model and in_flight,
    }


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


# ---- Page C: the recommended option's explanation ----
# Its own small fact sheet: the reason code and the action only. No number, probability, range,
# coordinate or stop. The advice clause goes through the same advice_is_valid as Page A.

OPTION_REASON_CODES = ("FASTEST_RUSHING", "HIGHEST_CHANCE_ON_TIME", "HIGHEST_CHANCE", "SHORTER_WALK", "NONE_BY_TARGET")
OPTION_FACT_SHEET_KEYS = ("reason_code", "chosen_action")
OPTION_ACTION = "switch_route"

OPTION_SYSTEM_PROMPT = (
    "You finish one sentence for a bus app: \"It is advisable to ...\". "
    "You receive reason_code (why one bus is recommended) and chosen_action. "
    "Return JSON with one field, advice: the words that complete the sentence, in lower case, at most 15 words, "
    "with no digits, no full stop, and no word about seconds. "
    "chosen_action is switch_route, so the advice means switch to the recommended bus. "
    "Recommend only a normal walking pace. Never promise that the bus will be caught."
)


def is_option_reason_code(code: object) -> bool:
    return isinstance(code, str) and code in OPTION_REASON_CODES


def build_option_fact_sheet(reason_code: str) -> dict:
    if not is_option_reason_code(reason_code):
        raise ValueError("Reason code is invalid.")
    return {"reason_code": reason_code, "chosen_action": OPTION_ACTION}


def parse_option_fact_sheet(body: object) -> dict | None:
    if not isinstance(body, dict) or set(body) != set(OPTION_FACT_SHEET_KEYS):
        return None
    if not is_option_reason_code(body["reason_code"]) or body["chosen_action"] != OPTION_ACTION:
        return None
    return {key: body[key] for key in OPTION_FACT_SHEET_KEYS}


def compose_option_text(reason_code: str, service: str, advice: str) -> str:
    """Two sentences: the fixed reason sentence for the code, then the advice clause."""
    from recommend import reason_text

    return f"{reason_text(reason_code, service)} It is advisable to {advice}."


def option_explanation_messages(fact_sheet: dict) -> list[dict]:
    visible = {key: fact_sheet[key] for key in OPTION_FACT_SHEET_KEYS}
    return [
        {"role": "system", "content": OPTION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(visible, separators=(",", ":"))},
    ]


def option_explanation_request(fact_sheet: dict) -> dict:
    return {
        "model": model_name(),
        "temperature": TEMPERATURE,
        "timeout": TIMEOUT_SECONDS,
        "store": False,
        "messages": option_explanation_messages(fact_sheet),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "bus_option_advice", "strict": True, "schema": EXPLANATION_SCHEMA},
        },
    }


def produce_option_advice(fact_sheet: dict, *, complete=None, api_key: str | None = None) -> dict:
    """{"advice", "source"}: the model's clause when valid, otherwise the fixed clause."""
    fixed = {"advice": deterministic_advice(OPTION_ACTION), "source": "fallback"}
    key = read_openai_api_key() if api_key is None else api_key
    if not key and complete is None:
        return fixed
    request = option_explanation_request(fact_sheet)
    try:
        if complete is None:
            raw = _openai_option_complete(key or "", request)
        else:
            raw = complete(fact_sheet, request)
    except AssertionError:
        raise
    except Exception:
        return fixed
    if not isinstance(raw, dict) or raw.get("status", 200) != 200:
        return fixed
    parsed = _parse_body(raw.get("body"))
    if not isinstance(parsed, dict) or set(parsed) != set(RESPONSE_FIELDS):
        return fixed
    if not advice_is_valid(parsed["advice"], OPTION_ACTION):
        return fixed
    return {"advice": parsed["advice"], "source": "model"}


def _openai_option_complete(api_key: str, request: dict) -> dict:
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
    return {"status": 200, "body": completion.choices[0].message.content}


def handle_option_explain_request(body: dict, *, complete=None) -> tuple[int, dict]:
    """The Page C clause. The service number is only used here to assemble the final text."""
    if not isinstance(body, dict):
        return 422, {"detail": "Fact sheet is invalid."}
    sheet = parse_option_fact_sheet(body.get("fact_sheet"))
    service = body.get("service_no")
    if sheet is None or not isinstance(service, str) or not re.fullmatch(r"[0-9A-Za-z]{1,6}", service.strip()):
        return 422, {"detail": "Fact sheet is invalid."}
    result = produce_option_advice(sheet, complete=complete)
    return 200, {
        "status": "ok",
        "source": result["source"],
        "advice": result["advice"],
        "action": OPTION_ACTION,
        "reason_code": sheet["reason_code"],
        "text": compose_option_text(sheet["reason_code"], service.strip(), result["advice"]),
    }

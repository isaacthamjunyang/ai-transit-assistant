"""Judge-facing demo fixtures.

Demo mode is on only when DEMO_MODE is exactly true. A scenario replaces
one provider input. CatchHeuristic, reroute, journey, and the explanation
guardrails still produce the result.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from nearby import haversine_m

LTA_TIMEOUT = "LTA API Timeout / Proxy Error"
STALE_POLL = "Stale Data Poll"
SCHEDULE_ONLY = "Schedule-Only / Monitored = 0"
GPS_PENALTY = "GPS Fix/Age Penalty"
REROUTE = "Auto-Reroute Opportunity"
ONEMAP_FAILURE = "OneMap Zero Results / API Error"
OPENAI_GUARD = "Unsafe / Contradictory OpenAI Output"

SCENARIOS = (
    LTA_TIMEOUT,
    STALE_POLL,
    SCHEDULE_ONLY,
    GPS_PENALTY,
    REROUTE,
    ONEMAP_FAILURE,
    OPENAI_GUARD,
)

STALE_FIXTURE_AGE_S = 121
GPS_ACCURACY_M = 150.0
GPS_AGE_S = 90.0
OPENAI_DEMO_ELAPSED_S = 4.0
_OPENAI_CYCLE = ("unsafe", "contradictory", "timeout")
_LTA_SCRIPTS = (LTA_TIMEOUT, STALE_POLL, SCHEDULE_ONLY, REROUTE)


class _DemoState:
    def __init__(self) -> None:
        self.scenario: str | None = None
        self.onemap_outcome: str | None = None
        self.openai_outcome: str | None = None
        self.primary: tuple[str, str] | None = None


_state = _DemoState()


def _file_setting(path: Path, name: str) -> str | None:
    """The raw .env value, or None when that name is not in the file.

    The value is kept exactly. Quotes and surrounding spaces are not removed.
    """
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        body = raw_line
        if body.lstrip().startswith("export "):
            body = body.lstrip()[len("export ") :]
        if "=" not in body:
            continue
        key, value = body.split("=", 1)
        if key.strip() != name:
            continue
        return value
    return None


def demo_enabled(env_path: Path | None = None) -> bool:
    """True only for the exact value true. Every other value is live mode."""
    import lta_static

    path = lta_static.ENV_PATH if env_path is None else env_path
    file_value = _file_setting(path, "DEMO_MODE")
    if file_value is not None:
        return file_value == "true"
    return os.environ.get("DEMO_MODE") == "true"


def public_status() -> dict:
    enabled = demo_enabled()
    outcome = None
    if enabled and _state.scenario == ONEMAP_FAILURE:
        outcome = _state.onemap_outcome
    elif enabled and _state.scenario == OPENAI_GUARD:
        outcome = _state.openai_outcome
    return {
        "enabled": enabled,
        "scenarios": list(SCENARIOS) if enabled else [],
        "active": _state.scenario if enabled else None,
        "outcome": outcome,
    }


def run_scenario(name: str) -> bool:
    if not demo_enabled() or name not in SCENARIOS:
        return False
    if _state.scenario != name:
        _clear()
        _state.scenario = name
        if name == ONEMAP_FAILURE:
            _state.onemap_outcome = "zero"
        elif name == OPENAI_GUARD:
            _state.openai_outcome = "unsafe"
    elif name == ONEMAP_FAILURE:
        _state.onemap_outcome = "error" if _state.onemap_outcome == "zero" else "zero"
    elif name == OPENAI_GUARD:
        current = _state.openai_outcome or "unsafe"
        _state.openai_outcome = _OPENAI_CYCLE[(_OPENAI_CYCLE.index(current) + 1) % 3]
    _state.primary = None
    return True


def reset_to_live() -> None:
    """Drop the active fixture. Demo mode itself stays an environment setting."""
    _clear()


def _clear() -> None:
    _state.scenario = None
    _state.onemap_outcome = None
    _state.openai_outcome = None
    _state.primary = None


def begin_arrival_poll(stop_code: str, service_no: str) -> None:
    if demo_enabled() and _state.scenario == REROUTE:
        _state.primary = (stop_code, service_no)


def lta_script_active() -> bool:
    return demo_enabled() and _state.scenario in _LTA_SCRIPTS


def timeout_is_active() -> bool:
    return demo_enabled() and _state.scenario == LTA_TIMEOUT


def arrival_is_simulated() -> bool:
    return demo_enabled() and _state.scenario in (
        STALE_POLL,
        SCHEDULE_ONLY,
        GPS_PENALTY,
        REROUTE,
    )


def scoring_location(
    accuracy: float | None,
    location_timestamp: float | None,
    now: datetime,
) -> tuple[float | None, float | None]:
    """GPS scenario only. A supplied fix becomes accuracy 150 m and age 90 s."""
    if not demo_enabled() or _state.scenario != GPS_PENALTY or accuracy is None:
        return accuracy, location_timestamp
    return GPS_ACCURACY_M, now.timestamp() - GPS_AGE_S


def simulated_lta_response(
    stop_code: str,
    service_no: str,
    now: datetime,
    user_lat: float | None,
    user_lon: float | None,
    cache,
) -> httpx.Response | None:
    """A stand-in BusArrival response, or None when this poll stays live."""
    if not lta_script_active():
        return None
    if _state.scenario == LTA_TIMEOUT:
        raise httpx.TimeoutException("simulated timeout")
    if _state.scenario == SCHEDULE_ONLY:
        distance = _distance(cache, stop_code, user_lat, user_lon)
        eta = _iso(now, 160 + distance / 1.4 + 45)
        body = _services(service_no, [("NextBus", _bus(eta, 0))])
        return httpx.Response(200, json=body)
    if _state.scenario == REROUTE:
        poor = _state.primary in (None, (stop_code, service_no))
        if _state.primary is None:
            _state.primary = (stop_code, service_no)
        return httpx.Response(200, json=_reroute_body(stop_code, service_no, now, user_lat, user_lon, cache, poor))
    eta = _iso(now, 8 * 60)
    return httpx.Response(200, json=_services(service_no, [("NextBus", _bus(eta, 1))]))


def apply_stale(payload: dict, now: datetime) -> bool:
    if not demo_enabled() or _state.scenario != STALE_POLL:
        return False
    payload["fetched_at"] = _iso(now, -STALE_FIXTURE_AGE_S)
    payload["leave_now"] = None
    payload["demo_stale"] = True
    payload["simulated"] = True
    payload.pop("reroute", None)
    return True


def simulated_reverse_geocode() -> dict | None:
    """Same OneMap-failure switch as place search. None leaves reverse geocoding live."""
    if not demo_enabled() or _state.scenario != ONEMAP_FAILURE:
        return None
    if _state.onemap_outcome == "error":
        return {"unavailable": True}
    return {"unavailable": False, "name": ""}


def simulated_destination(query: str) -> dict | None:
    if not demo_enabled() or _state.scenario != ONEMAP_FAILURE:
        return None
    if _state.onemap_outcome == "error":
        return {"unavailable": True, "query": query}
    return {"unavailable": False, "query": query}


def destination_is_simulated() -> bool:
    return demo_enabled() and _state.scenario == ONEMAP_FAILURE


def simulated_openai_result(fact_sheet: dict) -> dict | None:
    """A fake model body, or a timeout marker. None leaves OpenAI live."""
    if not demo_enabled() or _state.scenario != OPENAI_GUARD:
        return None
    outcome = _state.openai_outcome or "unsafe"
    if outcome == "timeout":
        if OPENAI_DEMO_ELAPSED_S > 3:
            return {"timeout": True}
        return {"timeout": True}
    if outcome == "unsafe":
        # Unsafe wording: the clause is rejected and the fixed clause is shown.
        body = {"advice": "run for this bus"}
    else:
        # Digits and a promise, whatever the action: rejected as well.
        body = {"advice": "leave now, you will make it in 5 minutes"}
    return {"timeout": False, "status": 200, "body": body}


def explanation_is_simulated() -> bool:
    return demo_enabled() and _state.scenario == OPENAI_GUARD


def _reroute_body(stop_code, service_no, now, user_lat, user_lon, cache, poor: bool) -> dict:
    distance = _distance(cache, stop_code, user_lat, user_lon)
    if poor:
        soon = 20 + distance / 1.4 + 45
        later = 180 + distance / 1.1 + 45 + 8
        buses = [
            ("NextBus", _bus(_iso(now, soon), 1)),
            ("NextBus2", _bus(_iso(now, later), 1)),
        ]
    else:
        later = 180 + distance / 1.1 + 45 + 8
        buses = [("NextBus", _bus(_iso(now, later), 1))]
    return _services(service_no, buses)


def _distance(cache, stop_code: str, user_lat, user_lon) -> float:
    if cache is None or not isinstance(user_lat, (int, float)) or not isinstance(user_lon, (int, float)):
        return 80.0
    stop = cache.stop_by_code(stop_code)
    if not isinstance(stop, dict):
        return 80.0
    lat = stop.get("Latitude")
    lon = stop.get("Longitude")
    if isinstance(lat, bool) or isinstance(lon, bool):
        return 80.0
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return 80.0
    return haversine_m(float(user_lat), float(user_lon), float(lat), float(lon))


def _services(service_no: str, buses: list[tuple[str, dict]]) -> dict:
    item = {"ServiceNo": service_no}
    for position, bus in buses:
        item[position] = bus
    return {"Services": [item]}


def _bus(eta: str, monitored: int) -> dict:
    return {
        "EstimatedArrival": eta,
        "Monitored": monitored,
        "Latitude": "",
        "Longitude": "",
        "OriginCode": "",
        "DestinationCode": "",
    }


def _iso(now: datetime, seconds: float) -> str:
    value = now + timedelta(seconds=seconds)
    if value.tzinfo is None:
        value = value.replace(tzinfo=now.tzinfo)
    return value.replace(microsecond=0).isoformat()

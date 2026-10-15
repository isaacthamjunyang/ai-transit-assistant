"""Train service alerts (LTA DataMall guide 2.11, TrainServiceAlerts).

Response fields as the guide's Annex C shows them: value.Status (1 normal or minor delays, 2 disrupted or major delays),
value.AffectedSegments[] (Line, Direction, Stations, FreePublicBus, FreeMRTShuttle, MRTShuttleDirection) and
value.Message[] (Content, CreatedDate). The messages are not keyed by line, so a message belongs to a line when its text
names the line's LTA code (for example "NEL - Additional travelling time ...").

The server asks LTA at most once every 60 seconds for everyone. Nothing about the user is sent (no position, no
coordinates, no identity): the request has no parameters. Any failure, a missing key and Demo Mode all return no alerts,
silently. The alerts are display only: they never reach ranking, probability or reroute.
"""

import re
import threading
import time

import httpx

import demo
from lta_static import BASE_URL, read_account_key

ALERTS_URL = f"{BASE_URL}/TrainServiceAlerts"
CACHE_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 5.0
MAX_MESSAGE_CHARS = 600
MAX_ALERTS = 12

# The guide's line codes, and the short codes the app uses everywhere else (copy.js lineNames).
LINE_CODES = {
    "EWL": "EW", "NSL": "NS", "NEL": "NE", "CCL": "CC", "DTL": "DT", "TEL": "TE", "BPL": "BP", "STL": "SK", "PTL": "PG",
}

DISRUPTED = "disrupted"
MINOR = "minor"

_lock = threading.Lock()
_cache: dict = {"at": None, "alerts": []}


def clear_cache() -> None:
    with _lock:
        _cache["at"] = None
        _cache["alerts"] = []


def _clean(text: object) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", text)).strip()[:MAX_MESSAGE_CHARS]


def parse_alerts(payload: object) -> list[dict]:
    """The alerts of one TrainServiceAlerts answer: [{"line": "NS", "status": "disrupted"|"minor", "message": str}].

    Status 2 is disrupted. Status 1 with an affected segment is the guide's minor delay; Status 1 with none is normal
    service, so nothing is returned. A line the guide does not list is dropped. Anything malformed returns []."""
    if not isinstance(payload, dict):
        return []
    value = payload.get("value")
    if isinstance(value, list) and value and isinstance(value[0], dict):
        value = value[0]
    if not isinstance(value, dict):
        return []
    segments = value.get("AffectedSegments")
    if not isinstance(segments, list) or not segments:
        return []
    status = DISRUPTED if value.get("Status") == 2 else MINOR
    messages = []
    raw_messages = value.get("Message")
    for item in raw_messages if isinstance(raw_messages, list) else []:
        text = _clean(item.get("Content")) if isinstance(item, dict) else ""
        if text:
            messages.append(text)
    found: dict[str, dict] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        lta_code = str(segment.get("Line", "")).strip().upper()
        short = LINE_CODES.get(lta_code)
        if short is None or short in found:
            continue
        own = [text for text in messages if re.search(rf"\b{lta_code}\b", text) or re.search(rf"\b{short}\b", text)]
        message = own[0] if own else ""
        found[short] = {"line": short, "status": status, "message": message}
        if len(found) >= MAX_ALERTS:
            break
    return list(found.values())


def _fetch(client: httpx.Client | None, account_key: str) -> list[dict]:
    headers = {"AccountKey": account_key}
    if client is None:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as owned:
            response = owned.get(ALERTS_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    else:
        response = client.get(ALERTS_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        return []
    try:
        return parse_alerts(response.json())
    except ValueError:
        return []


def current_alerts(client: httpx.Client | None = None, account_key: str | None = None, now: float | None = None) -> list[dict]:
    """The active alerts, from the 60 s shared cache. Never raises. Empty in Demo Mode and on any failure."""
    try:
        if demo.demo_enabled():
            return []
        moment = time.monotonic() if now is None else now
        with _lock:
            at = _cache["at"]
            if at is not None and 0 <= moment - at < CACHE_SECONDS:
                return list(_cache["alerts"])
        key = read_account_key() if account_key is None else account_key.strip()
        if not key:
            alerts: list[dict] = []
        else:
            alerts = _fetch(client, key)
        with _lock:
            _cache["at"] = moment
            _cache["alerts"] = alerts
        return list(alerts)
    except Exception:  # a display-only extra: it must never break a page
        return []

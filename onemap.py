"""OneMap place search.

The browser never calls OneMap. Tokens stay in memory for this process
and are not written to disk, logs, or API responses.
"""

import math
import os
import time
from pathlib import Path

import httpx

import demo

from lta_static import ENV_PATH, _read_env_value

SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
TOKEN_URL = "https://www.onemap.gov.sg/api/auth/post/getToken"
ONEMAP_TIMEOUT_SECONDS = 8


class DestinationUnavailable(Exception):
    """OneMap could not be used. Status is unavailable."""

    def __init__(self) -> None:
        super().__init__("Destination search unavailable")
        self.status = "unavailable"


class OneMapSession:
    """In-memory token. expiry is None when the token has no known expiry."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.expiry: float | None = None
        self.manual_rejected: bool = False


def read_onemap_credentials(env_path: Path | None = None) -> tuple[str, str, str]:
    """Return ONEMAP_TOKEN, ONEMAP_EMAIL, and ONEMAP_PASSWORD."""
    path = ENV_PATH if env_path is None else env_path

    def value(name: str) -> str:
        from_file = _read_env_value(path, name)
        if from_file:
            return from_file
        return os.environ.get(name, "").strip()

    return value("ONEMAP_TOKEN"), value("ONEMAP_EMAIL"), value("ONEMAP_PASSWORD")


def parse_expiry_timestamp(value: object) -> float:
    """OneMap expiry_timestamp as UNIX seconds."""
    if isinstance(value, bool) or value is None:
        raise ValueError("expiry_timestamp is not a UNIX time.")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise ValueError("expiry_timestamp is not a UNIX time.") from exc
    else:
        raise ValueError("expiry_timestamp is not a UNIX time.")
    if not math.isfinite(number) or number <= 0:
        raise ValueError("expiry_timestamp is not a UNIX time.")
    return number


def search_destinations(
    query: str,
    *,
    session: OneMapSession,
    client: httpx.Client,
    token: str = "",
    email: str = "",
    password: str = "",
    now: float | None = None,
) -> dict:
    """Search page 1. At most two search calls, and only after an auth failure."""
    text = query.strip()
    simulated = demo.simulated_destination(text)
    if simulated is not None:
        if simulated.get("unavailable"):
            raise DestinationUnavailable
        return {"status": "ok", "query": text, "results": [], "simulated": True}
    moment = time.time() if now is None else now
    manual = token.strip()
    mail = email.strip()
    secret = password.strip()
    refreshed = False
    for _attempt in range(2):
        current = _usable_token(session, manual, moment)
        if current is None:
            if refreshed or not mail or not secret:
                raise DestinationUnavailable
            _generate_token(session, client, mail, secret)
            refreshed = True
            current = _usable_token(session, manual, moment)
            if current is None:
                raise DestinationUnavailable
        try:
            payload = _search_once(client, current, text)
        except _AuthRejected:
            _invalidate(session)
            if refreshed or not mail or not secret:
                raise DestinationUnavailable
            _generate_token(session, client, mail, secret)
            refreshed = True
            continue
        if session.token != current:
            session.token = current
            session.expiry = None
        return _normalize(payload, text)
    raise DestinationUnavailable


def _usable_token(session: OneMapSession, manual: str, now: float) -> str | None:
    if session.token:
        if session.expiry is None or now < session.expiry:
            return session.token
        session.token = None
        session.expiry = None
    if manual and not session.manual_rejected:
        return manual
    return None


def _invalidate(session: OneMapSession) -> None:
    session.token = None
    session.expiry = None
    session.manual_rejected = True


def _generate_token(
    session: OneMapSession,
    client: httpx.Client,
    email: str,
    password: str,
) -> None:
    try:
        response = client.post(
            TOKEN_URL,
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=ONEMAP_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise DestinationUnavailable from exc
    except httpx.HTTPError as exc:
        raise DestinationUnavailable from exc
    if response.status_code != 200:
        raise DestinationUnavailable
    try:
        payload = response.json()
    except ValueError as exc:
        raise DestinationUnavailable from exc
    if not isinstance(payload, dict):
        raise DestinationUnavailable
    access = payload.get("access_token")
    if not isinstance(access, str) or not access.strip():
        raise DestinationUnavailable
    try:
        expiry = parse_expiry_timestamp(payload.get("expiry_timestamp"))
    except ValueError as exc:
        raise DestinationUnavailable from exc
    session.token = access.strip()
    session.expiry = expiry
    session.manual_rejected = True


def _search_once(client: httpx.Client, token: str, query: str) -> dict:
    try:
        response = client.get(
            SEARCH_URL,
            params={
                "searchVal": query,
                "returnGeom": "Y",
                "getAddrDetails": "Y",
                "pageNum": 1,
            },
            headers={"Authorization": token},
            timeout=ONEMAP_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise DestinationUnavailable from exc
    except httpx.HTTPError as exc:
        raise DestinationUnavailable from exc
    if response.status_code == 401 or _body_is_auth_error(response):
        raise _AuthRejected
    if response.status_code != 200:
        raise DestinationUnavailable
    try:
        payload = response.json()
    except ValueError as exc:
        raise DestinationUnavailable from exc
    if not isinstance(payload, dict):
        raise DestinationUnavailable
    if _error_text(payload) and not _is_auth_message(_error_text(payload)):
        raise DestinationUnavailable
    return payload


def _body_is_auth_error(response: httpx.Response) -> bool:
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    return _is_auth_message(_error_text(payload))


def _error_text(payload: dict) -> str:
    error = payload.get("error")
    if isinstance(error, str):
        return error.strip()
    return ""


def _is_auth_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    mentions_auth = "token" in lowered or "auth" in lowered or "unauthor" in lowered
    mentions_failure = any(
        word in lowered for word in ("invalid", "expired", "missing", "fail", "unauthor")
    )
    return mentions_auth and mentions_failure


class _AuthRejected(Exception):
    """The current token was rejected. The caller may refresh once."""


def _normalize(payload: dict, query: str) -> dict:
    found = payload.get("found")
    results = payload.get("results", None)
    if found in (0, "0") or results == []:
        return {"status": "ok", "query": query, "results": []}
    if not isinstance(results, list):
        raise DestinationUnavailable
    valid = []
    for item in results:
        place = _place(item)
        if place is not None:
            valid.append(place)
    return {"status": "ok", "query": query, "results": valid}


def _place(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    latitude = _coordinate(item.get("LATITUDE"))
    longitude = _coordinate(item.get("LONGITUDE"))
    if latitude is None or longitude is None:
        return None
    label = _text(item.get("BUILDING")) or _text(item.get("SEARCHVAL")) or _text(item.get("ADDRESS"))
    address = _text(item.get("ADDRESS"))
    if not address:
        address = " ".join(
            part
            for part in (
                _text(item.get("BLK_NO")),
                _text(item.get("ROAD_NAME")),
                _text(item.get("BUILDING")),
                _text(item.get("POSTAL")),
            )
            if part
        )
    postal = _text(item.get("POSTAL"))
    return {
        "id": "|".join((label, postal, repr(latitude), repr(longitude))),
        "label": label,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
    }


def _coordinate(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number):
        return None
    return number


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""

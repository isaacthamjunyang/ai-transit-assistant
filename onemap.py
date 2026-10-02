"""OneMap place search.

The browser never calls OneMap. Tokens stay in memory for this process
and are not written to disk, logs, or API responses.
"""

import math
import os
import re
import time
from pathlib import Path

import httpx

import demo

from lta_static import ENV_PATH, _read_env_value

SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
REVERSE_URL = "https://www.onemap.gov.sg/api/public/revgeocode"
TOKEN_URL = "https://www.onemap.gov.sg/api/auth/post/getToken"
ONEMAP_TIMEOUT_SECONDS = 8
REVERSE_TIMEOUT_SECONDS = 3
_REVERSE_CACHE: dict[tuple[float, float], dict] = {}
_SINGAPORE = re.compile(r"\bSINGAPORE\b", re.IGNORECASE)
_POSTAL = re.compile(r"\b\d{6}\b")
_SPACES = re.compile(r"\s+")


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


def clear_reverse_cache() -> None:
    _REVERSE_CACHE.clear()


ACRONYM_ALLOWLIST = frozenset({
    "NUS", "NTU", "SMU", "SUTD", "SIT", "SUSS", "SIM", "NIE", "ITE",
    "MRT", "LRT", "HDB", "CBD", "JC", "RC", "CC",
    "PIE", "CTE", "ECP", "TPE", "SLE", "KPE", "MCE", "AYE", "BKE", "KJE",
    "PSA", "IMM", "OCBC", "DBS", "UOB", "NEA", "URA", "LTA",
})
ABBREVIATION_MAP = {
    "BLK": "Blk",
    "ST": "St",
    "RD": "Rd",
    "AVE": "Ave",
    "DR": "Dr",
    "MT": "Mt",
    "BT": "Bt",
    "JLN": "Jln",
    "LOR": "Lor",
    "KG": "Kg",
    "CTR": "Ctr",
    "OPP": "Opp",
    "NTH": "Nth",
    "STH": "Sth",
}
SMALL_WORDS = frozenset({"for", "of", "and", "the", "at", "to", "in", "on", "by"})
_NESTED_PARENS = re.compile(r"\(([^()]*)\(([^()]*)\)([^()]*)\)")
_PLACE_TOKEN = re.compile(
    r"\([A-Za-z]{2,6}\)"
    r"|[@&]"
    r"|[A-Za-z0-9#]+(?:'[A-Za-z0-9]+)*(?:[/-][A-Za-z0-9#]+(?:'[A-Za-z0-9]+)*)*\.?"
)


def format_place_name(text: str) -> str:
    """Display casing for an all-caps OneMap name. Mixed case is left as written."""
    if not isinstance(text, str):
        return ""
    if re.search(r"[a-z]", text):
        return text
    collapsed = _collapse_nested_parens(text.strip())
    return _case_caps(collapsed)


def format_display_address(
    address: str = "",
    *,
    name: str = "",
    block: str = "",
    road: str = "",
    postal: str = "",
) -> str:
    """A display address. Structured fields win; otherwise the string is parsed."""
    block_text = block.strip()
    road_text = road.strip()
    postal_text = postal.strip()
    if block_text or road_text or postal_text:
        street_raw = " ".join(part for part in (block_text, road_text) if part)
        street = format_place_name(street_raw) if street_raw else ""
        street = _strip_repeated_name(street, name).strip(" ,")
        if street and postal_text:
            return f"{street}, Singapore {postal_text}"
        if postal_text:
            return f"Singapore {postal_text}"
        return street
    return _parse_address_string(address, name)


def _collapse_nested_parens(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _NESTED_PARENS.sub(r"\1(\2)\3", text)
    return _SPACES.sub(" ", text).strip()


def _case_caps(text: str) -> str:
    first = True
    pieces = []
    cursor = 0
    for match in _PLACE_TOKEN.finditer(text):
        pieces.append(text[cursor:match.start()])
        token, first = _format_token(match.group(0), first)
        pieces.append(token)
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def _format_token(token: str, first: bool) -> tuple[str, bool]:
    if token in {"@", "&"}:
        return token, first
    if re.fullmatch(r"\([A-Za-z]{2,6}\)", token):
        return "(" + token[1:-1].upper() + ")", False
    if re.search(r"\d", token):
        return token, False
    dot = "." if token.endswith(".") else ""
    core = token[:-1] if dot else token
    cased = []
    word_is_first = first
    for part in re.split(r"([/-])", core):
        if part in {"/", "-"}:
            cased.append(part)
            continue
        cased.append(_format_word(part, word_is_first))
        word_is_first = False
    return "".join(cased) + dot, False


def _format_word(word: str, first: bool) -> str:
    if not word:
        return word
    key = word.upper()
    if key in ABBREVIATION_MAP:
        return ABBREVIATION_MAP[key]
    if key in ACRONYM_ALLOWLIST:
        return key
    if "'" in word:
        bits = word.split("'")
        cased_bits = []
        for index, bit in enumerate(bits):
            if index > 0 and bit.upper() == "S" and len(bit) == 1:
                cased_bits.append("s")
            else:
                cased_bits.append(_title_piece(bit))
        text = "'".join(cased_bits)
    else:
        text = _title_piece(word)
    if not first and text.lower() in SMALL_WORDS:
        return text.lower()
    return text


def _title_piece(bit: str) -> str:
    if not bit:
        return bit
    if bit.upper() in ACRONYM_ALLOWLIST:
        return bit.upper()
    return bit[:1].upper() + bit[1:].lower()


def _strip_repeated_name(text: str, name: str) -> str:
    if not text or not name or not name.strip():
        return text
    result = text
    seen = set()
    for candidate in (name.strip(), _collapse_nested_parens(name.strip()), format_place_name(name)):
        if not candidate or candidate in seen or len(candidate) < 2:
            continue
        seen.add(candidate)
        result = re.sub(re.escape(candidate), " ", result, flags=re.IGNORECASE)
    result = _SPACES.sub(" ", result)
    result = re.sub(r"\s*,\s*", ", ", result)
    result = re.sub(r"(?:,\s*){2,}", ", ", result)
    return result.strip(" ,")


def _parse_address_string(address: str, name: str) -> str:
    text = _strip_repeated_name(address.strip(), name)
    if text and not re.search(r"[a-z]", text):
        text = _collapse_nested_parens(text)
    postal = ""
    match = _POSTAL.search(text)
    if match:
        postal = match.group(0)
        text = text[:match.start()] + text[match.end():]
    text = _SINGAPORE.sub(" ", text)
    text = _SPACES.sub(" ", text).strip(" ,")
    street = format_place_name(text) if text else ""
    street = _strip_repeated_name(street, name).strip(" ,")
    if street and postal:
        return f"{street}, Singapore {postal}"
    if postal:
        return f"Singapore {postal}"
    return street


def reverse_geocode(
    lat: float,
    lon: float,
    *,
    session: OneMapSession,
    client: httpx.Client,
    token: str = "",
    email: str = "",
    password: str = "",
    now: float | None = None,
) -> dict:
    """One place name for a rounded point. Never includes the coordinates."""
    simulated = demo.simulated_reverse_geocode()
    if simulated is not None:
        if simulated.get("unavailable"):
            return _place_payload("", simulated=True)
        return _place_payload(str(simulated.get("name") or ""), simulated=True)
    try:
        rounded_lat = round(float(lat), 4)
        rounded_lon = round(float(lon), 4)
    except (TypeError, ValueError):
        return _place_payload("")
    if not math.isfinite(rounded_lat) or not math.isfinite(rounded_lon):
        return _place_payload("")
    key = (rounded_lat, rounded_lon)
    cached = _REVERSE_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    moment = time.time() if now is None else now
    manual = token.strip()
    mail = email.strip()
    secret = password.strip()
    refreshed = False
    payload = None
    for _attempt in range(2):
        current = _usable_token(session, manual, moment)
        if current is None:
            if refreshed or not mail or not secret:
                return _place_payload("")
            try:
                _generate_token(session, client, mail, secret)
            except DestinationUnavailable:
                return _place_payload("")
            refreshed = True
            current = _usable_token(session, manual, moment)
            if current is None:
                return _place_payload("")
        try:
            payload = _reverse_once(client, current, rounded_lat, rounded_lon)
        except _AuthRejected:
            _invalidate(session)
            if refreshed or not mail or not secret:
                return _place_payload("")
            try:
                _generate_token(session, client, mail, secret)
            except DestinationUnavailable:
                return _place_payload("")
            refreshed = True
            continue
        except DestinationUnavailable:
            return _place_payload("")
        if session.token != current:
            session.token = current
            session.expiry = None
        break
    if payload is None:
        return _place_payload("")
    result = _place_payload(_label_from_reverse(payload))
    if result["full_name"]:
        _REVERSE_CACHE[key] = dict(result)
    return result


def _place_payload(raw: str, simulated: bool = False) -> dict:
    original = raw.strip() if isinstance(raw, str) else ""
    display = format_place_name(original) if original else ""
    body = {"status": "ok", "name": original, "display_name": display, "full_name": display}
    if simulated:
        body["simulated"] = True
    return body


def _label_from_reverse(payload: dict) -> str:
    rows = payload.get("GeocodeInfo")
    if not isinstance(rows, list):
        return ""
    for item in rows:
        if not isinstance(item, dict):
            continue
        building = _usable_part(item.get("BUILDINGNAME"))
        road = _usable_part(item.get("ROAD"))
        if building or road:
            return building or road
    return ""


def _usable_part(value: object) -> str:
    text = _text(value)
    if text.upper() in {"NIL", "NULL", "NONE", "NA", "N/A"}:
        return ""
    return text


def _reverse_once(client: httpx.Client, token: str, lat: float, lon: float) -> dict:
    try:
        response = client.get(
            REVERSE_URL,
            params={
                "location": f"{lat:.4f},{lon:.4f}",
                "buffer": 40,
                "addressType": "All",
            },
            headers={"Authorization": token},
            timeout=REVERSE_TIMEOUT_SECONDS,
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
    return payload


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
    block = _usable_part(item.get("BLK_NO"))
    road = _usable_part(item.get("ROAD_NAME"))
    postal = _text(item.get("POSTAL"))
    label = _text(item.get("BUILDING")) or _text(item.get("SEARCHVAL")) or _text(item.get("ADDRESS"))
    address = _text(item.get("ADDRESS"))
    if not address:
        address = " ".join(
            part
            for part in (
                block,
                road,
                _text(item.get("BUILDING")),
                postal,
            )
            if part
        )
    return {
        "id": "|".join((label, postal, repr(latitude), repr(longitude))),
        "label": label,
        "label_display": format_place_name(label),
        "address": address,
        "address_display": format_display_address(
            address,
            name=label,
            block=block,
            road=road,
            postal=postal,
        ),
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

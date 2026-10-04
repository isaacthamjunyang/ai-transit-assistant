"""Live LTA BusArrival for one stop and one service.

The browser calls our API. This module calls DataMall, normalizes
timestamps, and asks CatchHeuristic for a probability when the user's
location was supplied. It does not log observations.
"""

import copy
import math
import time
from datetime import datetime, timedelta, timezone

import httpx

import demo
from catch_heuristic import score_buses
from config import WALK_SPEED_DEFAULT_MPS
from journey import leave_by_for_buses
from leave_now import leave_now_notice, notification_time_iso
from lta_static import BASE_URL, REQUEST_TIMEOUT_SECONDS, StopAndRouteCache, read_account_key

SGT = timezone(timedelta(hours=8))
BUS_POSITIONS = ("NextBus", "NextBus2", "NextBus3")
PEEK_HANDOFF_SECONDS = 20
_peek_handoff: dict[tuple[str, str], tuple[float, dict]] = {}


class ArrivalUnavailable(Exception):
    """A live arrival poll could not be used. Status is unavailable."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.status = "unavailable"


def fetch_arrivals(
    stop_code: str,
    service_no: str,
    client: httpx.Client | None = None,
    account_key: str | None = None,
    now: datetime | None = None,
    user_lat: float | None = None,
    user_lon: float | None = None,
    accuracy: float | None = None,
    location_timestamp: float | None = None,
    cache: StopAndRouteCache | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict:
    key = read_account_key() if account_key is None else account_key.strip()
    if not key:
        raise ArrivalUnavailable(
            "Live arrival data is unavailable: LTA_ACCOUNT_KEY is missing."
        )
    moment = now if now is not None else datetime.now(SGT)
    handed = None if demo.lta_script_active() else _take_peek(stop_code, service_no)
    if handed is not None:
        result = handed
    elif demo.lta_script_active():
        result = _fetch(
            None,
            key,
            stop_code,
            service_no,
            moment,
            user_lat=user_lat,
            user_lon=user_lon,
            cache=cache,
        )
    elif client is None:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as owned:
            result = _fetch(owned, key, stop_code, service_no, moment)
    else:
        result = _fetch(client, key, stop_code, service_no, moment)
    result["buses"] = _with_probability(
        result["buses"],
        stop_code=stop_code,
        service_no=service_no,
        user_lat=user_lat,
        user_lon=user_lon,
        accuracy=accuracy,
        location_timestamp=location_timestamp,
        cache=cache,
        now=moment,
        walk_speed_m_s=walk_speed_m_s,
    )
    result["leave_by"] = leave_by_for_buses(
        result["buses"],
        stop_code=stop_code,
        user_lat=user_lat,
        user_lon=user_lon,
        cache=cache,
        now=moment,
        walk_speed_m_s=walk_speed_m_s,
    )
    result["notification_time"] = notification_time_iso(result["leave_by"])
    result["leave_now"] = leave_now_notice(
        result["buses"],
        service_no=service_no,
        stop_code=stop_code,
        stop_name=_boarding_stop_name(cache, stop_code),
        leave_by_iso=result["leave_by"],
        notification_time=result["notification_time"],
        arrival_status="ok",
    )
    return result


def fetch_stop_arrivals(
    stop_code: str,
    wanted_services: list[str],
    client: httpx.Client | None = None,
    account_key: str | None = None,
    now: datetime | None = None,
    user_lat: float | None = None,
    user_lon: float | None = None,
    accuracy: float | None = None,
    location_timestamp: float | None = None,
    cache: StopAndRouteCache | None = None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> dict[str, dict]:
    """Every wanted service at one stop from a single BusArrival call with ServiceNo omitted.

    LTA returns all the services at the stop when ServiceNo is left out. Each wanted service
    comes back shaped and scored like fetch_arrivals (status, stop_code, service_no,
    fetched_at, buses with probability), through the same parser and scoring. In Demo Mode
    the provider interception supplies each service, so no network call is made.
    """
    key = read_account_key() if account_key is None else account_key.strip()
    if not key:
        raise ArrivalUnavailable("Live arrival data is unavailable: LTA_ACCOUNT_KEY is missing.")
    moment = now if now is not None else datetime.now(SGT)
    wanted = [str(service).strip() for service in wanted_services if str(service).strip()]
    results: dict[str, dict] = {}
    if demo.lta_script_active():
        for service in wanted:
            results[service] = _fetch(None, key, stop_code, service, moment, user_lat=user_lat, user_lon=user_lon, cache=cache)
    else:
        if client is None:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as owned:
                payload = _fetch_stop_payload(owned, key, stop_code)
        else:
            payload = _fetch_stop_payload(client, key, stop_code)
        for service in wanted:
            results[service] = {
                "status": "ok",
                "stop_code": stop_code,
                "service_no": service,
                "fetched_at": _as_sgt_iso(moment),
                "buses": _buses_from_payload(payload, service),
            }
    for service, result in results.items():
        result["buses"] = _with_probability(
            result["buses"],
            stop_code=stop_code,
            service_no=service,
            user_lat=user_lat,
            user_lon=user_lon,
            accuracy=accuracy,
            location_timestamp=location_timestamp,
            cache=cache,
            now=moment,
            walk_speed_m_s=walk_speed_m_s,
        )
    return results


def _fetch_stop_payload(client: httpx.Client, account_key: str, stop_code: str) -> dict:
    try:
        response = client.get(
            f"{BASE_URL}/v3/BusArrival",
            params={"BusStopCode": stop_code},
            headers={"AccountKey": account_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise ArrivalUnavailable("Live arrival data is unavailable: request timed out.") from exc
    except httpx.HTTPError as exc:
        raise ArrivalUnavailable("Live arrival data is unavailable: request failed.") from exc
    if response.status_code != 200:
        raise ArrivalUnavailable(f"Live arrival data is unavailable: HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ArrivalUnavailable("Live arrival data is unavailable: response was not valid JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("Services"), list):
        raise ArrivalUnavailable("Live arrival data is unavailable: response did not contain services.")
    return payload


def peek_arrivals(stop_code: str, service_no: str, account_key: str | None = None) -> dict:
    """One raw arrival lookup for the journey overview.

    Same provider call as monitoring, so Demo Mode interception applies. No probability,
    no leave-by, no notification, no logging. The result is handed to the first
    monitoring fetch for the same stop and service if that comes within 20 seconds,
    so pressing Start does not repeat the call.
    """
    key = read_account_key() if account_key is None else account_key.strip()
    if not key:
        raise ArrivalUnavailable(
            "Live arrival data is unavailable: LTA_ACCOUNT_KEY is missing."
        )
    moment = datetime.now(SGT)
    if demo.lta_script_active():
        return _fetch(None, key, stop_code, service_no, moment)
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as owned:
        result = _fetch(owned, key, stop_code, service_no, moment)
    _peek_handoff[(stop_code, service_no)] = (time.monotonic(), copy.deepcopy(result))
    return result


def _take_peek(stop_code: str, service_no: str) -> dict | None:
    entry = _peek_handoff.pop((stop_code, service_no), None)
    if entry is None:
        return None
    stored_at, result = entry
    if time.monotonic() - stored_at >= PEEK_HANDOFF_SECONDS:
        return None
    return result


def _fetch(
    client: httpx.Client | None,
    account_key: str,
    stop_code: str,
    service_no: str,
    now: datetime | None,
    user_lat: float | None = None,
    user_lon: float | None = None,
    cache=None,
) -> dict:
    try:
        response = demo.simulated_lta_response(
            stop_code,
            service_no,
            now if now is not None else datetime.now(SGT),
            user_lat,
            user_lon,
            cache,
        )
        if response is None:
            response = client.get(
                f"{BASE_URL}/v3/BusArrival",
                params={"BusStopCode": stop_code, "ServiceNo": service_no},
                headers={"AccountKey": account_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
    except httpx.TimeoutException as exc:
        raise ArrivalUnavailable("Live arrival data is unavailable: request timed out.") from exc
    except httpx.HTTPError as exc:
        raise ArrivalUnavailable("Live arrival data is unavailable: request failed.") from exc
    if response.status_code != 200:
        raise ArrivalUnavailable(
            f"Live arrival data is unavailable: HTTP {response.status_code}."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ArrivalUnavailable(
            "Live arrival data is unavailable: response was not valid JSON."
        ) from exc
    buses = _buses_from_payload(payload, service_no)
    fetched = now if now is not None else datetime.now(SGT)
    return {
        "status": "ok",
        "stop_code": stop_code,
        "service_no": service_no,
        "fetched_at": _as_sgt_iso(fetched),
        "buses": buses,
    }


def _buses_from_payload(payload: object, service_no: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("Services"), list):
        raise ArrivalUnavailable(
            "Live arrival data is unavailable: response did not contain services."
        )
    service = None
    for item in payload["Services"]:
        if isinstance(item, dict) and str(item.get("ServiceNo", "")).strip() == service_no:
            service = item
            break
    if service is None:
        return []
    buses = []
    for position in BUS_POSITIONS:
        bus = _normalize_bus(service.get(position), position)
        if bus is not None:
            buses.append(bus)
    return buses


def _normalize_bus(raw: object, position: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    arrival = normalize_timestamp(raw.get("EstimatedArrival"))
    if arrival is None:
        return None
    return {
        "position": position,
        "arrival_time": arrival,
        "monitored": raw.get("Monitored") == 1 or raw.get("Monitored") == "1",
        "latitude": _coordinate(raw.get("Latitude")),
        "longitude": _coordinate(raw.get("Longitude")),
        "origin_code": _text_code(raw.get("OriginCode")),
        "destination_code": _text_code(raw.get("DestinationCode")),
    }


def _with_probability(
    buses: list[dict],
    *,
    stop_code: str,
    service_no: str,
    user_lat: float | None,
    user_lon: float | None,
    accuracy: float | None,
    location_timestamp: float | None,
    cache: StopAndRouteCache | None,
    now: datetime,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> list[dict]:
    stop = cache.stop_by_code(stop_code) if cache is not None else None
    stop_lat = stop.get("Latitude") if isinstance(stop, dict) else None
    stop_lon = stop.get("Longitude") if isinstance(stop, dict) else None
    services = cache.services if cache is not None else []
    routes = cache.routes if cache is not None else []
    return score_buses(
        buses,
        user_lat=user_lat,
        user_lon=user_lon,
        accuracy_m=accuracy,
        location_timestamp=location_timestamp,
        stop_lat=stop_lat if isinstance(stop_lat, (int, float)) else None,
        stop_lon=stop_lon if isinstance(stop_lon, (int, float)) else None,
        services=services,
        routes=routes,
        service_no=service_no,
        stop_code=stop_code,
        now=now,
        walk_speed_m_s=walk_speed_m_s,
    )


def _boarding_stop_name(cache: StopAndRouteCache | None, stop_code: str) -> str:
    if cache is None:
        return ""
    stop = cache.stop_by_code(stop_code)
    if not isinstance(stop, dict):
        return ""
    name = stop.get("Description")
    if isinstance(name, str):
        return name.strip()
    return ""


def _text_code(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def normalize_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_sgt_iso(parsed)


def _as_sgt_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SGT)
    else:
        value = value.astimezone(SGT)
    return value.replace(microsecond=0).isoformat()


def _coordinate(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number == 0:
        return None
    return number

"""Local cache of static LTA BusStops, BusRoutes, and BusServices.

Startup uses a valid cache when one is already on disk and does not
download again. The first boot, with no valid cache, downloads all three
datasets. Lookup and headway reads use the cache only.
"""

import json
import logging
import os
from pathlib import Path

import httpx

BASE_URL = "https://datamall2.mytransport.sg/ltaodataservice"
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 15

CACHE_DIR = Path(__file__).resolve().parent / "cache"
STOPS_FILENAME = "bus_stops.json"
ROUTES_FILENAME = "bus_routes.json"
SERVICES_FILENAME = "bus_services.json"
ENV_PATH = Path(__file__).resolve().parent / ".env"

STATIC_CACHE_WARNING = (
    "Using cached static LTA bus stops and routes. "
    "Current static LTA updates were not fetched. "
    "This is cached static data, not a live bus arrival."
)

logger = logging.getLogger("uvicorn.error")


class StaticDataUnavailable(Exception):
    """Static stops and routes cannot be loaded. Status is unavailable."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.status = "unavailable"


class StopAndRouteCache:
    """Stops and routes kept in memory for later steps.

    Stop names are the LTA Description field. Lookup does not call LTA.
    """

    def __init__(
        self,
        stops: list[dict],
        routes: list[dict],
        services: list[dict] | None = None,
    ) -> None:
        self.stops = stops
        self.routes = routes
        self.services = [] if services is None else services
        self._by_code = {stop["BusStopCode"]: stop for stop in stops}

    def stop_by_code(self, code: str) -> dict | None:
        return self._by_code.get(code)

    def stops_by_name(self, query: str) -> list[dict]:
        needle = query.casefold()
        return [
            stop
            for stop in self.stops
            if needle in str(stop.get("Description", "")).casefold()
        ]


def cache_is_available(cache_dir: Path | None = None) -> bool:
    return load_cache(cache_dir) is not None


def load_cache(cache_dir: Path | None = None) -> StopAndRouteCache | None:
    directory = _directory(cache_dir)
    stops_path = directory / STOPS_FILENAME
    routes_path = directory / ROUTES_FILENAME
    services_path = directory / SERVICES_FILENAME
    if not stops_path.is_file() or not routes_path.is_file() or not services_path.is_file():
        return None
    try:
        stops = json.loads(stops_path.read_text(encoding="utf-8"))
        routes = json.loads(routes_path.read_text(encoding="utf-8"))
        services = json.loads(services_path.read_text(encoding="utf-8"))
        _validate_stops(stops)
        _validate_routes(routes)
        _validate_services(services)
    except (OSError, UnicodeError, json.JSONDecodeError, StaticDataUnavailable):
        return None
    return StopAndRouteCache(stops, routes, services)


def write_cache(
    cache_dir: Path,
    stops: list[dict],
    routes: list[dict],
    services: list[dict] | None = None,
) -> None:
    stored_services = [] if services is None else services
    _validate_stops(stops)
    _validate_routes(routes)
    _validate_services(stored_services)
    directory = _directory(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write(directory / STOPS_FILENAME, stops)
    _atomic_write(directory / ROUTES_FILENAME, routes)
    _atomic_write(directory / SERVICES_FILENAME, stored_services)


def fetch_paged(client: httpx.Client, dataset: str, account_key: str) -> list[dict]:
    """Download one static dataset, following $skip until the last page."""
    records: list[dict] = []
    skip = 0
    while True:
        page = _fetch_page(client, dataset, account_key, skip)
        if not page:
            break
        records.extend(page)
        if len(page) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
    if not records:
        raise StaticDataUnavailable(
            f"LTA static data is unavailable: {dataset} returned no records."
        )
    return records


def load_static_data(
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
    account_key: str | None = None,
) -> StopAndRouteCache:
    """Load a valid cache, or download one on first boot.

    A valid cache is used as-is. A failed download never replaces it.
    With no valid cache, a failed download raises StaticDataUnavailable
    and does not write a cache file.
    """
    directory = _directory(cache_dir)
    cached = load_cache(directory)
    if cached is not None:
        logger.warning(STATIC_CACHE_WARNING)
        return cached
    try:
        return _download_and_store(directory, client, account_key)
    except StaticDataUnavailable as exc:
        logger.error("%s", exc)
        raise


def read_account_key(env_path: Path | None = None) -> str:
    """Return LTA_ACCOUNT_KEY from .env, then from the process environment."""
    path = ENV_PATH if env_path is None else env_path
    from_file = _read_env_value(path, "LTA_ACCOUNT_KEY")
    if from_file:
        return from_file
    return os.environ.get("LTA_ACCOUNT_KEY", "").strip()


def _download_and_store(
    cache_dir: Path,
    client: httpx.Client | None,
    account_key: str | None,
) -> StopAndRouteCache:
    key = _resolve_account_key(account_key)
    if client is not None:
        return _download_with_client(cache_dir, client, key)
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as owned:
        return _download_with_client(cache_dir, owned, key)


def _download_with_client(
    cache_dir: Path, client: httpx.Client, account_key: str
) -> StopAndRouteCache:
    stops = fetch_paged(client, "BusStops", account_key)
    _validate_stops(stops)
    routes = fetch_paged(client, "BusRoutes", account_key)
    _validate_routes(routes)
    services = fetch_paged(client, "BusServices", account_key)
    _validate_services(services)
    write_cache(cache_dir, stops, routes, services)
    return StopAndRouteCache(stops, routes, services)


def _fetch_page(
    client: httpx.Client, dataset: str, account_key: str, skip: int
) -> list[dict]:
    try:
        response = client.get(
            f"{BASE_URL}/{dataset}",
            params={"$skip": skip},
            headers={"AccountKey": account_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise StaticDataUnavailable(
            f"LTA static data is unavailable: {dataset} request timed out."
        ) from exc
    except httpx.HTTPError as exc:
        raise StaticDataUnavailable(
            f"LTA static data is unavailable: {dataset} request failed."
        ) from exc
    if response.status_code != 200:
        raise StaticDataUnavailable(
            f"LTA static data is unavailable: {dataset} returned HTTP {response.status_code}."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise StaticDataUnavailable(
            f"LTA static data is unavailable: {dataset} response was not valid JSON."
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        raise StaticDataUnavailable(
            f"LTA static data is unavailable: {dataset} response did not contain a record list."
        )
    page = payload["value"]
    if any(not isinstance(record, dict) for record in page):
        raise StaticDataUnavailable(
            f"LTA static data is unavailable: {dataset} response records were not objects."
        )
    return page


def _resolve_account_key(account_key: str | None) -> str:
    key = read_account_key() if account_key is None else account_key.strip()
    if not key:
        raise StaticDataUnavailable(
            "LTA static data is unavailable: LTA_ACCOUNT_KEY is missing and no local cache exists."
        )
    return key


def _validate_stops(records: object) -> None:
    if not isinstance(records, list) or not records:
        raise StaticDataUnavailable(
            "LTA static data is unavailable: BusStops dataset is empty or invalid."
        )
    for record in records:
        if not _stop_is_usable(record):
            raise StaticDataUnavailable(
                "LTA static data is unavailable: BusStops records are missing required fields."
            )


def _validate_routes(records: object) -> None:
    if not isinstance(records, list) or not records:
        raise StaticDataUnavailable(
            "LTA static data is unavailable: BusRoutes dataset is empty or invalid."
        )
    for record in records:
        if not _route_is_usable(record):
            raise StaticDataUnavailable(
                "LTA static data is unavailable: BusRoutes records are missing required fields."
            )


def _stop_is_usable(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        _non_empty_text(record.get("BusStopCode"))
        and isinstance(record.get("Description"), str)
        and _is_number(record.get("Latitude"))
        and _is_number(record.get("Longitude"))
    )


def _validate_services(records: object) -> None:
    if not isinstance(records, list):
        raise StaticDataUnavailable(
            "LTA static data is unavailable: BusServices dataset is invalid."
        )
    for record in records:
        if not _service_is_usable(record):
            raise StaticDataUnavailable(
                "LTA static data is unavailable: BusServices records are missing required fields."
            )


def _service_is_usable(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    return _non_empty_text(record.get("ServiceNo")) and _is_int(record.get("Direction"))


def _route_is_usable(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        _non_empty_text(record.get("ServiceNo"))
        and _is_int(record.get("Direction"))
        and _is_int(record.get("StopSequence"))
        and _non_empty_text(record.get("BusStopCode"))
        and _is_number(record.get("Distance"))
    )


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _atomic_write(path: Path, records: list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(records, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
        raise StaticDataUnavailable(
            "LTA static data is unavailable: the local cache could not be written."
        ) from exc


def _read_env_value(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        return value.strip().strip('"').strip("'")
    return ""


def _directory(cache_dir: Path | None) -> Path:
    return CACHE_DIR if cache_dir is None else cache_dir

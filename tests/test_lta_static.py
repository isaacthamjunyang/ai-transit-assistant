"""Fixture tests for the LTA static cache. These tests do not call LTA."""

import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import lta_static
from lta_static import (
    PAGE_SIZE,
    STATIC_CACHE_WARNING,
    StaticDataUnavailable,
    fetch_paged,
    load_cache,
    load_static_data,
    write_cache,
)
from main import app

ACCOUNT_KEY = "test-account-key"


def _stop(code: str, description: str, **extra) -> dict:
    record = {
        "BusStopCode": code,
        "RoadName": "Orchard Rd",
        "Description": description,
        "Latitude": 1.3,
        "Longitude": 103.8,
    }
    record.update(extra)
    return record


def _route(
    service: str,
    direction: int,
    sequence: int,
    code: str,
    distance: float,
    **extra,
) -> dict:
    record = {
        "ServiceNo": service,
        "Operator": "SBST",
        "Direction": direction,
        "StopSequence": sequence,
        "BusStopCode": code,
        "Distance": distance,
        "WD_FirstBus": "0500",
        "WD_LastBus": "2300",
    }
    record.update(extra)
    return record


def _sample_stops() -> list[dict]:
    return [
        _stop("09022", "Orchard Stn/Tang Plaza"),
        _stop("09048", "Orchard Blvd"),
        _stop("08138", "Somerset Stn"),
        _stop("08122", "Bef Somerset"),
        _stop("01012", "Hotel Grand Pacific"),
    ]


def _sample_routes() -> list[dict]:
    return [
        _route("10", 1, 1, "09022", 0),
        _route("10", 1, 2, "09048", 0.4),
        _route("65", 2, 1, "08138", 0),
    ]


def _sample_services() -> list[dict]:
    return [
        {
            "ServiceNo": "10",
            "Operator": "SBST",
            "Direction": 1,
            "OriginCode": "09022",
            "DestinationCode": "01012",
            "AM_Peak_Freq": "12-15",
            "AM_Offpeak_Freq": "08-12",
            "PM_Peak_Freq": "12-15",
            "PM_Offpeak_Freq": "10-15",
        }
    ]


def _pages(records: list[dict]) -> dict[int, list[dict]]:
    pages = {
        skip: records[skip : skip + PAGE_SIZE]
        for skip in range(0, len(records), PAGE_SIZE)
    }
    if records and len(records) % PAGE_SIZE == 0:
        pages[len(records)] = []
    if not records:
        pages[0] = []
    return pages


def _client_for(
    stops: list[dict],
    routes: list[dict],
    seen: dict | None = None,
    services: list[dict] | None = None,
):
    pages_by_dataset = {
        "BusStops": _pages(stops),
        "BusRoutes": _pages(routes),
        "BusServices": _pages(_sample_services() if services is None else services),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["AccountKey"] == ACCOUNT_KEY
        assert ACCOUNT_KEY not in str(request.url)
        dataset = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        skip = int(request.url.params["$skip"])
        if seen is not None:
            seen.setdefault(dataset, []).append(skip)
        pages = pages_by_dataset.get(dataset)
        if pages is None or skip not in pages:
            return httpx.Response(500, text="unexpected skip")
        return httpx.Response(
            200,
            json={"odata.metadata": "fixture", "value": pages[skip]},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _forbid_live_client(*args, **kwargs):
    raise AssertionError("live HTTP client should not be created")


def test_bus_stops_pagination_combines_pages(tmp_path: Path):
    stops = [_stop(f"{index:05d}", f"Stop {index}") for index in range(PAGE_SIZE * 2 + 3)]
    routes = _sample_routes()
    seen: dict[str, list[int]] = {}
    with _client_for(stops, routes, seen) as client:
        loaded = load_static_data(
            cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
        )
    assert seen["BusStops"] == [0, PAGE_SIZE, PAGE_SIZE * 2]
    assert [stop["BusStopCode"] for stop in loaded.stops] == [
        stop["BusStopCode"] for stop in stops
    ]
    assert loaded.stops[0]["RoadName"] == "Orchard Rd"


def test_full_page_requests_the_following_skip():
    stops = [_stop(f"{index:05d}", f"Stop {index}") for index in range(PAGE_SIZE)]
    seen: dict[str, list[int]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["$skip"])
        seen.setdefault("BusStops", []).append(skip)
        page = stops if skip == 0 else []
        return httpx.Response(200, json={"value": page})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = fetch_paged(client, "BusStops", ACCOUNT_KEY)
    assert seen["BusStops"] == [0, PAGE_SIZE]
    assert len(records) == PAGE_SIZE


def test_bus_routes_pagination_combines_pages(tmp_path: Path):
    stops = _sample_stops()
    routes = [
        _route("10", 1, index + 1, f"{index:05d}", index / 10)
        for index in range(PAGE_SIZE + 2)
    ]
    seen: dict[str, list[int]] = {}
    with _client_for(stops, routes, seen) as client:
        loaded = load_static_data(
            cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
        )
    assert seen["BusRoutes"] == [0, PAGE_SIZE]
    assert len(loaded.routes) == PAGE_SIZE + 2
    assert loaded.routes[0]["ServiceNo"] == "10"
    assert loaded.routes[0]["Direction"] == 1
    assert loaded.routes[0]["StopSequence"] == 1
    assert loaded.routes[0]["Distance"] == 0
    assert loaded.routes[-1]["StopSequence"] == PAGE_SIZE + 2


def test_download_writes_json_cache(tmp_path: Path):
    stops = _sample_stops()
    routes = _sample_routes()
    with _client_for(stops, routes) as client:
        load_static_data(cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY)
    stored_stops = json.loads((tmp_path / "bus_stops.json").read_text(encoding="utf-8"))
    stored_routes = json.loads((tmp_path / "bus_routes.json").read_text(encoding="utf-8"))
    stored_services = json.loads((tmp_path / "bus_services.json").read_text(encoding="utf-8"))
    assert stored_stops == stops
    assert stored_routes == routes
    assert stored_routes[1]["Distance"] == 0.4
    assert stored_services == _sample_services()
    assert stored_services[0]["Direction"] == 1
    assert stored_services[0]["AM_Peak_Freq"] == "12-15"


def test_load_cache_reads_valid_json(tmp_path: Path):
    stops = _sample_stops()
    routes = _sample_routes()
    write_cache(tmp_path, stops, routes)
    loaded = load_cache(tmp_path)
    assert loaded is not None
    assert loaded.stops == stops
    assert loaded.routes == routes
    assert loaded.routes[0]["BusStopCode"] == "09022"
    assert loaded.services == []


def test_existing_cache_is_used_when_lta_fails(tmp_path: Path, caplog, monkeypatch):
    stops = _sample_stops()
    routes = _sample_routes()
    write_cache(tmp_path, stops, routes)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
    }
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500, text="down")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(httpx, "Client", _forbid_live_client)
        with caplog.at_level(logging.WARNING):
            loaded = load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert calls == []
    assert loaded.stop_by_code("01012")["Description"] == "Hotel Grand Pacific"
    assert STATIC_CACHE_WARNING in caplog.text
    assert "live bus arrival" in caplog.text
    assert ACCOUNT_KEY not in caplog.text
    after = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert after == before


def test_first_boot_failure_does_not_invent_a_cache(tmp_path: Path, caplog, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503, text="down")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(httpx, "Client", _forbid_live_client)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(StaticDataUnavailable) as caught:
                load_static_data(
                    cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
                )
    assert caught.value.status == "unavailable"
    assert "unavailable" in str(caught.value)
    assert calls == ["/ltaodataservice/BusStops"]
    assert list(tmp_path.iterdir()) == []
    assert ACCOUNT_KEY not in caplog.text


def test_missing_account_key_does_not_call_lta_or_write_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lta_static, "read_account_key", lambda: "")
    monkeypatch.setattr(httpx, "Client", _forbid_live_client)
    with pytest.raises(StaticDataUnavailable) as caught:
        load_static_data(cache_dir=tmp_path, account_key=None)
    assert caught.value.status == "unavailable"
    assert list(tmp_path.iterdir()) == []


def test_stop_code_lookup_is_exact(tmp_path: Path, monkeypatch):
    write_cache(tmp_path, _sample_stops(), _sample_routes())
    monkeypatch.setattr(httpx, "Client", _forbid_live_client)
    loaded = load_static_data(cache_dir=tmp_path, account_key=ACCOUNT_KEY)
    found = loaded.stop_by_code("09022")
    assert found is not None
    assert found["Description"] == "Orchard Stn/Tang Plaza"
    assert found["Latitude"] == 1.3
    assert found["Longitude"] == 103.8
    assert loaded.stop_by_code("99999") is None
    assert loaded.stop_by_code("9022") is None


def test_stop_name_lookup_is_case_insensitive_and_partial(tmp_path: Path, monkeypatch):
    write_cache(tmp_path, _sample_stops(), _sample_routes())
    monkeypatch.setattr(httpx, "Client", _forbid_live_client)
    loaded = load_static_data(cache_dir=tmp_path, account_key=ACCOUNT_KEY)
    orchard = loaded.stops_by_name("orchard")
    somerset = loaded.stops_by_name("SOMERSET")
    assert [stop["Description"] for stop in orchard] == [
        "Orchard Stn/Tang Plaza",
        "Orchard Blvd",
    ]
    assert [stop["Description"] for stop in somerset] == [
        "Somerset Stn",
        "Bef Somerset",
    ]
    assert loaded.stops_by_name("hotel grand")[0]["BusStopCode"] == "01012"
    assert loaded.stops_by_name("no such stop") == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="down"),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"value": []}),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"value": "nope"}),
        httpx.Response(200, json={"value": [1]}),
        httpx.Response(
            200,
            json={
                "value": [
                    {
                        "BusStopCode": "01012",
                        "Description": "Hotel Grand Pacific",
                        "Longitude": 103.8,
                    }
                ]
            },
        ),
    ],
)
def test_invalid_stop_responses_are_not_cached(tmp_path: Path, response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StaticDataUnavailable) as caught:
            load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert caught.value.status == "unavailable"
    assert list(tmp_path.iterdir()) == []


def test_timeout_is_not_cached(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StaticDataUnavailable) as caught:
            load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert "timed out" in str(caught.value)
    assert list(tmp_path.iterdir()) == []


def test_failed_second_page_does_not_write_a_partial_cache(tmp_path: Path):
    full_page = [_stop(f"{index:05d}", f"Stop {index}") for index in range(PAGE_SIZE)]

    def handler(request: httpx.Request) -> httpx.Response:
        dataset = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        skip = int(request.url.params["$skip"])
        if dataset == "BusStops" and skip == 0:
            return httpx.Response(200, json={"value": full_page})
        return httpx.Response(500, text="down")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StaticDataUnavailable):
            load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert list(tmp_path.iterdir()) == []


def test_routes_failure_does_not_keep_a_stops_file(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        dataset = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        if dataset == "BusStops":
            return httpx.Response(200, json={"value": _sample_stops()})
        return httpx.Response(200, json={"value": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StaticDataUnavailable):
            load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert list(tmp_path.iterdir()) == []


def test_cache_write_failure_leaves_no_valid_cache(tmp_path: Path, monkeypatch):
    original = Path.write_text

    def fail_write(self: Path, *args, **kwargs):
        if self.parent == tmp_path:
            raise OSError("disk full")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write)
    with _client_for(_sample_stops(), _sample_routes()) as client:
        with pytest.raises(StaticDataUnavailable) as caught:
            load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert caught.value.status == "unavailable"
    assert list(tmp_path.rglob("*.json")) == []


def test_unreadable_cache_is_not_replaced_when_download_fails(tmp_path: Path):
    stops_path = tmp_path / "bus_stops.json"
    routes_path = tmp_path / "bus_routes.json"
    stops_path.write_text("{", encoding="utf-8")
    routes_path.write_text("{", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StaticDataUnavailable):
            load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert stops_path.read_text(encoding="utf-8") == "{"
    assert routes_path.read_text(encoding="utf-8") == "{"


def test_home_page_still_loads_from_cache(tmp_path: Path, monkeypatch):
    write_cache(tmp_path, _sample_stops(), _sample_routes())
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(httpx, "Client", _forbid_live_client)
    with TestClient(app) as client:
        response = client.get("/")
        spec = client.get("/openapi.json")
    assert response.status_code == 200
    assert "Bus Catch Assistant" in response.text
    assert "Orchard Stn/Tang Plaza" not in response.text
    assert set(spec.json()["paths"]) == {
        "/",
        "/theme.css",
        "/components.css",
        "/theme-boot.js",
        "/format-distance.js",
        "/place-icons.js",
        "/sw.js",
        "/api/stops/nearby",
        "/api/arrivals",
        "/api/destinations",
        "/api/reverse-geocode",
        "/api/destination-stops",
        "/api/journey",
        "/api/journey-plan",
        "/api/arrivals/peek",
        "/api/route-plan",
        "/api/reroute-options",
        "/api/explain",
        "/api/demo",
        "/api/demo/run",
        "/api/demo/reset",
        "/api/explain-option",
    }


def test_app_startup_fails_when_cache_and_key_are_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(lta_static, "read_account_key", lambda: "")
    monkeypatch.setattr(httpx, "Client", _forbid_live_client)
    with pytest.raises(StaticDataUnavailable) as caught:
        with TestClient(app):
            pass
    assert caught.value.status == "unavailable"
    assert list(tmp_path.iterdir()) == []


def test_services_failure_does_not_fabricate_frequencies(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        dataset = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        if dataset == "BusStops":
            return httpx.Response(200, json={"value": _sample_stops()})
        if dataset == "BusRoutes":
            return httpx.Response(200, json={"value": _sample_routes()})
        return httpx.Response(500, text="down")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StaticDataUnavailable):
            load_static_data(
                cache_dir=tmp_path, client=client, account_key=ACCOUNT_KEY
            )
    assert list(tmp_path.iterdir()) == []


def test_cache_without_services_file_is_incomplete(tmp_path: Path):
    write_cache(tmp_path, _sample_stops(), _sample_routes(), _sample_services())
    (tmp_path / "bus_services.json").unlink()
    assert load_cache(tmp_path) is None

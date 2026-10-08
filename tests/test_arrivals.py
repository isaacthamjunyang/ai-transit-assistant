"""Live arrival normalization. Fixtures only — these tests do not call LTA."""

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import arrivals
import lta_static
from arrivals import SGT, fetch_arrivals, normalize_timestamp
from lta_static import write_cache
from main import app

ACCOUNT_KEY = "test-account-key"
FETCHED = datetime(2026, 9, 29, 14, 54, 20, tzinfo=SGT)


def _bus(
    arrival: str,
    monitored: int,
    latitude: str = "",
    longitude: str = "",
    load: str = "SEA",
) -> dict:
    return {
        "EstimatedArrival": arrival,
        "Latitude": latitude,
        "Longitude": longitude,
        "VisitNumber": "1",
        "Load": load,
        "Monitored": monitored,
    }


def _payload() -> dict:
    return {
        "BusStopCode": "08057",
        "Services": [
            {
                "ServiceNo": "36",
                "Operator": "SBST",
                "NextBus": _bus(
                    "2026-09-29T14:58:00+08:00",
                    1,
                    "1.2985",
                    "103.8441",
                ),
                "NextBus2": _bus(
                    "2026-09-29T15:07:00+08:00",
                    1,
                    "1.2912",
                    "103.8502",
                ),
                "NextBus3": _bus("2026-09-29T15:19:00+08:00", 0, "0", "0"),
            }
        ],
    }


def _client(payload=None, status: int = 200, raw: bytes | None = None, error=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["AccountKey"] == ACCOUNT_KEY
        assert ACCOUNT_KEY not in str(request.url)
        assert request.url.params["BusStopCode"] == "08057"
        assert request.url.params["ServiceNo"] == "36"
        assert request.url.path.endswith("/v3/BusArrival")
        if error is not None:
            raise error
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=payload if payload is not None else _payload())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_normalizes_three_buses_and_monitored_independently():
    with _client() as client:
        result = fetch_arrivals(
            "08057", "36", client=client, account_key=ACCOUNT_KEY, now=FETCHED
        )
    assert result["status"] == "ok"
    assert result["stop_code"] == "08057"
    assert result["service_no"] == "36"
    assert result["fetched_at"] == "2026-09-29T14:54:20+08:00"
    assert [bus["position"] for bus in result["buses"]] == [
        "NextBus",
        "NextBus2",
        "NextBus3",
    ]
    assert [bus["monitored"] for bus in result["buses"]] == [True, True, False]
    assert result["buses"][0]["latitude"] == pytest.approx(1.2985)
    assert result["buses"][0]["longitude"] == pytest.approx(103.8441)
    assert result["buses"][1]["latitude"] == pytest.approx(1.2912)
    assert result["buses"][2]["latitude"] is None
    assert result["buses"][2]["longitude"] is None
    assert "Load" not in str(result)
    assert ACCOUNT_KEY not in str(result)


def test_timestamps_are_iso_with_singapore_offset():
    assert normalize_timestamp("2026-09-29T14:58:00+08:00") == "2026-09-29T14:58:00+08:00"
    assert normalize_timestamp("2026-09-29T14:58:00") == "2026-09-29T14:58:00+08:00"
    assert normalize_timestamp("2026-09-29T06:58:00Z") == "2026-09-29T14:58:00+08:00"
    assert normalize_timestamp("") is None
    assert normalize_timestamp("not-a-time") is None


def test_bus_without_arrival_time_is_omitted():
    payload = _payload()
    payload["Services"][0]["NextBus2"]["EstimatedArrival"] = ""
    payload["Services"][0]["NextBus3"] = {"EstimatedArrival": None, "Monitored": 1}
    with _client(payload) as client:
        result = fetch_arrivals(
            "08057", "36", client=client, account_key=ACCOUNT_KEY, now=FETCHED
        )
    assert [bus["position"] for bus in result["buses"]] == ["NextBus"]
    assert all(bus["arrival_time"] for bus in result["buses"])
    assert "null" not in str(result["buses"]).lower() or result["buses"][0]["latitude"] is not None


def test_http_ok_with_no_buses_is_an_empty_arrival_not_a_failed_poll(tmp_path, monkeypatch):
    _prime_endpoint(tmp_path, monkeypatch, payload={"BusStopCode": "08057", "Services": []})
    with TestClient(app) as client:
        response = client.get(
            "/api/arrivals",
            params={
                "stop_code": "08057",
                "service_no": "36",
                "lat": 1.3001,
                "lon": 103.8001,
                "accuracy": 18,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["buses"] == []
    assert body["leave_by"] is None
    assert body["leave_now"]["eligible"] is False
    assert "reroute" not in body
    assert "probability" not in response.text
    assert "arrival_time" not in response.text
    html = (lta_static.ENV_PATH.parent / "static" / "index.html").read_text(encoding="utf-8")
    branch = html.split("if (!result.body.buses.length)", 1)[1].split("var fetchedAt", 1)[0]
    assert "handleEmptyBuses(result.body)" in branch
    assert "handlePollFailure" not in branch
    empty = html.split("function handleEmptyBuses(body)", 1)[1].split("function showFirstFailure", 1)[0]
    assert 'arrivalWarning.textContent = "No buses currently in service at this stop."' in empty
    assert "No previous successful update." not in empty
    assert "handlePollFailure" not in empty
    assert "syncLeaveNow" not in empty
    assert "applyRouteSwitch" not in empty
    assert "appendScore" not in empty
    failure = html.split("function handlePollFailure()", 1)[1].split("function handleEmptyBuses", 1)[0]
    assert 'showFirstFailure("No live arrival data available. No previous successful update.")' in failure


def test_no_valid_buses_returns_an_empty_list_without_a_fake_eta():
    payload = _payload()
    for name in ("NextBus", "NextBus2", "NextBus3"):
        payload["Services"][0][name]["EstimatedArrival"] = ""
    with _client(payload) as client:
        result = fetch_arrivals(
            "08057", "36", client=client, account_key=ACCOUNT_KEY, now=FETCHED
        )
    assert result["status"] == "ok"
    assert result["buses"] == []
    assert result["fetched_at"] == "2026-09-29T14:54:20+08:00"


def test_fetched_at_is_the_backend_fetch_time_not_the_bus_time():
    later = FETCHED + timedelta(minutes=30)
    with _client() as client:
        result = fetch_arrivals(
            "08057", "36", client=client, account_key=ACCOUNT_KEY, now=later
        )
    assert result["fetched_at"] == "2026-09-29T15:24:20+08:00"
    assert result["fetched_at"] != result["buses"][0]["arrival_time"]


@pytest.mark.parametrize(
    "status",
    [401, 500, 503],
)
def test_http_errors_do_not_become_arrivals(status: int):
    with _client(status=status, payload={"Services": []}) as client:
        with pytest.raises(arrivals.ArrivalUnavailable) as caught:
            fetch_arrivals("08057", "36", client=client, account_key=ACCOUNT_KEY)
    assert caught.value.status == "unavailable"
    assert ACCOUNT_KEY not in str(caught.value)


def test_timeout_is_unavailable():
    with _client(error=httpx.ReadTimeout("timed out")) as client:
        with pytest.raises(arrivals.ArrivalUnavailable) as caught:
            fetch_arrivals("08057", "36", client=client, account_key=ACCOUNT_KEY)
    assert "timed out" in str(caught.value)


@pytest.mark.parametrize(
    "raw",
    [b"not-json", b"{}", b'{"Services":"nope"}'],
)
def test_malformed_responses_are_unavailable(raw: bytes):
    with _client(raw=raw) as client:
        with pytest.raises(arrivals.ArrivalUnavailable):
            fetch_arrivals("08057", "36", client=client, account_key=ACCOUNT_KEY)


def test_missing_account_key_does_not_call_lta(monkeypatch):
    monkeypatch.setattr(arrivals, "read_account_key", lambda: "")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("LTA was called")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(arrivals.ArrivalUnavailable):
            fetch_arrivals("08057", "36", client=client, account_key=None)


def _minimal_cache(tmp_path):
    write_cache(
        tmp_path,
        [
            {
                "BusStopCode": "08057",
                "RoadName": "Orchard Rd",
                "Description": "Dhoby Ghaut Stn",
                "Latitude": 1.3,
                "Longitude": 103.8,
            }
        ],
        [
            {
                "ServiceNo": "36",
                "Operator": "SBST",
                "Direction": 1,
                "StopSequence": 1,
                "BusStopCode": "08057",
                "Distance": 0,
            }
        ],
    )


def test_endpoint_calls_bus_arrival_and_hides_the_key(tmp_path, monkeypatch):
    _minimal_cache(tmp_path)
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: ACCOUNT_KEY)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["stop"] = request.url.params["BusStopCode"]
        seen["service"] = request.url.params["ServiceNo"]
        seen["key"] = request.headers["AccountKey"]
        return httpx.Response(200, json=_payload())

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", PatchedClient)
    with TestClient(app) as client:
        response = client.get(
            "/api/arrivals", params={"stop_code": "08057", "service_no": "36"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["buses"][0]["position"] == "NextBus"
    assert seen["path"].endswith("/v3/BusArrival")
    assert seen["stop"] == "08057"
    assert seen["service"] == "36"
    assert seen["key"] == ACCOUNT_KEY
    assert ACCOUNT_KEY not in response.text
    assert "AccountKey" not in response.text


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"stop_code": "08057"},
        {"service_no": "36"},
        {"stop_code": " ", "service_no": "36"},
        {"stop_code": "08057", "service_no": " "},
    ],
)
def test_arrival_parameters_are_required(tmp_path, monkeypatch, params):
    _minimal_cache(tmp_path)
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: "")
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LTA was called")),
    )
    with TestClient(app) as client:
        response = client.get("/api/arrivals", params=params)
    assert response.status_code == 422
    assert ACCOUNT_KEY not in response.text
    assert "buses" not in response.text


class _FrozenDateTime(datetime):
    clock = datetime(2026, 9, 29, 14, 54, 20, tzinfo=SGT)

    @classmethod
    def now(cls, tz=None):
        return cls.clock


def _prime_endpoint(tmp_path, monkeypatch, payload=None, services=None):
    _minimal_cache(tmp_path)
    if services is not None:
        services_path = tmp_path / "bus_services.json"
        services_path.write_text(__import__("json").dumps(services), encoding="utf-8")
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: ACCOUNT_KEY)
    monkeypatch.setattr(arrivals, "datetime", _FrozenDateTime)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v3/BusArrival")
        assert "AccountKey" in request.headers
        return httpx.Response(200, json=payload if payload is not None else _payload())

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", PatchedClient)


def test_arrivals_without_location_keep_probability_null(tmp_path, monkeypatch):
    _prime_endpoint(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get(
            "/api/arrivals", params={"stop_code": "08057", "service_no": "36"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["buses"][0]["latitude"] == pytest.approx(1.2985)
    assert all(bus["probability"] is None for bus in body["buses"])
    assert body["buses"][0]["is_missed"] is False
    assert body["buses"][0]["is_primary"] is True
    assert "sqlite" not in response.text.lower()
    assert ACCOUNT_KEY not in response.text


def test_arrivals_with_location_score_each_bus(tmp_path, monkeypatch):
    _prime_endpoint(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get(
            "/api/arrivals",
            params={
                "stop_code": "08057",
                "service_no": "36",
                "lat": 1.3005,  # 55 m away: not at the stop (under 30 m)
                "lon": 103.8001,
                "accuracy": 18,
            },
        )
    body = response.json()
    chances = [bus["probability"] for bus in body["buses"]]
    assert all(chance is not None for chance in chances)
    assert chances[0]["point"] != chances[1]["point"]
    assert chances[0]["data_quality"] == "live"
    assert chances[2]["data_quality"] == "schedule"
    assert chances[2]["range_high"] <= 60
    assert chances[2]["point"] <= 60
    assert chances[0]["reliability_label"] == "no historical reliability yet"
    assert chances[0]["is_missed"] is False
    assert body["buses"][0]["is_primary"] is True
    assert {"point", "range_low", "range_high", "slack_seconds", "data_quality"} <= set(
        chances[0]
    )
    assert ACCOUNT_KEY not in response.text
    assert "Load" not in response.text


def test_arrivals_mark_a_missed_bus_without_a_probability(tmp_path, monkeypatch):
    _FrozenDateTime.clock = datetime(2026, 9, 29, 15, 0, 0, tzinfo=SGT)
    try:
        _prime_endpoint(tmp_path, monkeypatch)
        with TestClient(app) as client:
            response = client.get(
                "/api/arrivals",
                params={
                    "stop_code": "08057",
                    "service_no": "36",
                    "lat": 1.3001,
                    "lon": 103.8001,
                    "accuracy": 18,
                },
            )
        buses = response.json()["buses"]
        assert buses[0]["position"] == "NextBus"
        assert buses[0]["is_missed"] is True
        assert buses[0]["probability"] is None
        assert buses[0]["is_primary"] is False
        assert buses[1]["is_missed"] is False
        assert buses[1]["is_primary"] is True
        assert buses[1]["probability"] is not None
    finally:
        _FrozenDateTime.clock = datetime(2026, 9, 29, 14, 54, 20, tzinfo=SGT)


def test_uncertain_gps_keeps_the_point_and_widens_the_low_end(tmp_path, monkeypatch):
    _prime_endpoint(tmp_path, monkeypatch)
    params = {
        "stop_code": "08057",
        "service_no": "36",
        "lat": 1.301,
        "lon": 103.801,
    }
    with TestClient(app) as client:
        tight = client.get("/api/arrivals", params={**params, "accuracy": 20}).json()
        wide = client.get("/api/arrivals", params={**params, "accuracy": 180}).json()
    tight_bus = tight["buses"][0]["probability"]
    wide_bus = wide["buses"][0]["probability"]
    assert wide_bus["point"] == tight_bus["point"]
    assert wide_bus["range_low"] < tight_bus["range_low"]
    assert wide_bus["data_quality"] == "location uncertain"
    assert tight_bus["data_quality"] == "live"


def test_location_timestamp_is_optional_and_an_old_fix_is_uncertain(tmp_path, monkeypatch):
    _prime_endpoint(tmp_path, monkeypatch)
    clock = _FrozenDateTime.clock.timestamp()
    params = {
        "stop_code": "08057",
        "service_no": "36",
        "lat": 1.3005,  # 55 m away: not at the stop (under 30 m)
        "lon": 103.8001,
        "accuracy": 18,
    }
    with TestClient(app) as client:
        missing = client.get("/api/arrivals", params=params)
        fresh = client.get(
            "/api/arrivals", params={**params, "location_timestamp": clock - 10}
        )
        old_seconds = client.get(
            "/api/arrivals", params={**params, "location_timestamp": clock - 61}
        )
        old_millis = client.get(
            "/api/arrivals",
            params={**params, "location_timestamp": (clock - 61) * 1000},
        )
        stamp_only = client.get(
            "/api/arrivals",
            params={
                "stop_code": "08057",
                "service_no": "36",
                "location_timestamp": clock - 10,
            },
        )
    assert missing.status_code == 200
    assert fresh.status_code == 200
    fresh_chance = fresh.json()["buses"][0]["probability"]
    missing_chance = missing.json()["buses"][0]["probability"]
    assert fresh_chance is not None
    assert missing_chance["point"] == fresh_chance["point"]
    assert missing_chance["data_quality"] == "live"
    assert fresh_chance["data_quality"] == "live"
    assert {
        "point",
        "range_low",
        "range_high",
        "slack_seconds",
        "data_quality",
        "reliability_label",
        "is_missed",
    } <= set(fresh_chance)
    old_chance = old_seconds.json()["buses"][0]["probability"]
    assert old_chance["data_quality"] == "location uncertain"
    assert old_chance["point"] == fresh_chance["point"]
    assert old_chance["range_high"] == fresh_chance["range_high"]
    assert old_chance["range_low"] < fresh_chance["range_low"]
    millis_chance = old_millis.json()["buses"][0]["probability"]
    assert millis_chance["data_quality"] == "location uncertain"
    assert millis_chance["point"] == old_chance["point"]
    assert millis_chance["range_low"] == old_chance["range_low"]
    assert millis_chance["range_high"] == old_chance["range_high"]
    assert stamp_only.status_code == 200
    assert stamp_only.json()["buses"][0]["probability"] is None
    assert ACCOUNT_KEY not in old_seconds.text


@pytest.mark.parametrize("stamp", ["NaN", "Infinity", "-inf", "-1", "not-a-time"])
def test_invalid_location_timestamp_is_rejected(tmp_path, monkeypatch, stamp):
    _minimal_cache(tmp_path)
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: ACCOUNT_KEY)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LTA was called")),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/arrivals",
            params={
                "stop_code": "08057",
                "service_no": "36",
                "lat": 1.3,
                "lon": 103.8,
                "accuracy": 10,
                "location_timestamp": stamp,
            },
        )
    assert response.status_code == 422
    assert ACCOUNT_KEY not in response.text
    assert "point" not in response.text


def test_unavailable_arrival_does_not_invent_a_probability(tmp_path, monkeypatch):
    _minimal_cache(tmp_path)
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: ACCOUNT_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", PatchedClient)
    with TestClient(app) as client:
        response = client.get(
            "/api/arrivals",
            params={
                "stop_code": "08057",
                "service_no": "36",
                "lat": 1.3,
                "lon": 103.8,
                "accuracy": 10,
            },
        )
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "probability" not in response.text
    assert "point" not in response.text

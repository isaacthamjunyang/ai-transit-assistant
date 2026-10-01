"""OneMap destination search. Fixtures only — these tests do not call OneMap."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import lta_static
import main
import onemap
from lta_static import write_cache
from main import app
from onemap import (
    DestinationUnavailable,
    OneMapSession,
    parse_expiry_timestamp,
    search_destinations,
)

MANUAL = "manual-token"
FRESH = "fresh-token"
EMAIL = "person@example.com"
PASSWORD = "example-password"


def _place(name, address, lat, lon, postal="018956"):
    return {
        "SEARCHVAL": name,
        "BLK_NO": "10",
        "ROAD_NAME": "BAYFRONT AVENUE",
        "BUILDING": name,
        "ADDRESS": address,
        "POSTAL": postal,
        "LATITUDE": lat,
        "LONGITUDE": lon,
    }


def _search_body(*places, found=None):
    body = {"results": list(places)}
    if found is None:
        body["found"] = len(places)
    else:
        body["found"] = found
    return body


def _ok(*places, found=None):
    return httpx.Response(200, json=_search_body(*places, found=found))


MARINA = _place("MARINA BAY SANDS", "10 BAYFRONT AVENUE SINGAPORE 018956", "1.2834", "103.8607")
ORCHARD = _place("ORCHARD ROAD", "ORCHARD ROAD SINGAPORE 238858", "1.3048", "103.8318", "238858")


class _Script:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert "datamall" not in str(request.url)
        assert "openai" not in str(request.url)
        assert "developers.onemap" not in str(request.url)
        if not self.steps:
            raise AssertionError("unexpected OneMap call")
        step = self.steps.pop(0)
        return step(request)


def _client(script: _Script) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(script))


def _search(script, *, token=MANUAL, email=EMAIL, password=PASSWORD, session=None, now=1_700_000_000):
    with _client(script) as client:
        return search_destinations(
            "Marina Bay Sands",
            session=OneMapSession() if session is None else session,
            client=client,
            token=token,
            email=email,
            password=password,
            now=now,
        )


def _paths(script: _Script) -> list[str]:
    return [request.url.path for request in script.calls]


def _token_response(request: httpx.Request) -> httpx.Response:
    assert request.method == "POST"
    assert request.url.path.endswith("/getToken")
    body = json.loads(request.content)
    assert body == {"email": EMAIL, "password": PASSWORD}
    assert request.headers.get("Authorization") in (None, "")
    return httpx.Response(
        200,
        json={"access_token": FRESH, "expiry_timestamp": "2000000000"},
    )


def _assert_search(request: httpx.Request, token: str) -> None:
    assert request.method == "GET"
    assert request.url.path.endswith("/elastic/search")
    assert request.url.params["searchVal"] == "Marina Bay Sands"
    assert request.url.params["returnGeom"] == "Y"
    assert request.url.params["getAddrDetails"] == "Y"
    assert request.url.params["pageNum"] == "1"
    assert request.headers["Authorization"] == token
    assert not request.headers["Authorization"].startswith("Bearer")
    assert "pageNum=2" not in str(request.url)


def test_manual_token_is_used_without_generating_another():
    script = _Script([lambda request: (_assert_search(request, MANUAL), _ok(MARINA))[1]])

    result = _search(script, email=EMAIL, password=PASSWORD)
    assert result["status"] == "ok"
    assert result["results"][0]["label"] == "MARINA BAY SANDS"
    assert result["results"][0]["latitude"] == pytest.approx(1.2834)
    assert result["results"][0]["longitude"] == pytest.approx(103.8607)
    assert _paths(script) == ["/api/common/elastic/search"]
    assert MANUAL not in json.dumps(result)
    assert PASSWORD not in json.dumps(result)


@pytest.mark.parametrize(
    "message",
    [
        "Authentication token missing",
        "Authentication token expired",
        "Invalid authentication token",
    ],
)
def test_http_200_auth_error_refreshes_once_and_retries_the_search(message):
    script = _Script(
        [
            lambda request: (_assert_search(request, MANUAL), httpx.Response(200, json={"error": message}))[1],
            _token_response,
            lambda request: (_assert_search(request, FRESH), _ok(MARINA, ORCHARD))[1],
        ]
    )
    session = OneMapSession()
    result = _search(script, session=session)
    assert [place["label"] for place in result["results"]] == ["MARINA BAY SANDS", "ORCHARD ROAD"]
    assert _paths(script) == [
        "/api/common/elastic/search",
        "/api/auth/post/getToken",
        "/api/common/elastic/search",
    ]
    assert session.token == FRESH
    assert session.expiry == pytest.approx(2000000000)
    assert FRESH not in json.dumps(result)


def test_invalid_manual_token_without_credentials_is_unavailable():
    script = _Script(
        [
            lambda request: httpx.Response(200, json={"error": "Invalid authentication token"}),
        ]
    )
    with pytest.raises(DestinationUnavailable):
        _search(script, email="", password="")
    assert _paths(script) == ["/api/common/elastic/search"]


def test_email_password_obtains_a_token_before_the_search():
    script = _Script(
        [
            _token_response,
            lambda request: (_assert_search(request, FRESH), _ok(MARINA))[1],
        ]
    )
    session = OneMapSession()
    result = _search(script, token="", session=session)
    assert result["results"][0]["address"] == "10 BAYFRONT AVENUE SINGAPORE 018956"
    assert _paths(script) == ["/api/auth/post/getToken", "/api/common/elastic/search"]
    assert session.token == FRESH


def test_missing_token_and_credentials_does_not_call_onemap():
    script = _Script([])
    with pytest.raises(DestinationUnavailable):
        _search(script, token="", email="", password="")
    assert script.calls == []


def test_expired_generated_token_is_replaced_before_search():
    script = _Script(
        [
            _token_response,
            lambda request: (_assert_search(request, FRESH), _ok(MARINA))[1],
        ]
    )
    session = OneMapSession()
    session.token = "stale-token"
    session.expiry = 1_000
    session.manual_rejected = True
    _search(script, token=MANUAL, session=session, now=1_000)
    assert _paths(script) == ["/api/auth/post/getToken", "/api/common/elastic/search"]
    assert all(request.headers.get("Authorization") != "stale-token" for request in script.calls)


def test_unexpired_generated_token_is_reused():
    script = _Script([lambda request: (_assert_search(request, "cached-token"), _ok(MARINA))[1]])
    session = OneMapSession()
    session.token = "cached-token"
    session.expiry = 1_800_000_000
    session.manual_rejected = True
    _search(script, session=session, now=1_700_000_000)
    assert _paths(script) == ["/api/common/elastic/search"]


def test_expiry_timestamp_parses_unix_seconds():
    assert parse_expiry_timestamp("1700000000") == pytest.approx(1700000000)
    assert parse_expiry_timestamp(1700000000) == pytest.approx(1700000000)
    with pytest.raises(ValueError):
        parse_expiry_timestamp("tomorrow")
    with pytest.raises(ValueError):
        parse_expiry_timestamp(-1)


def test_token_is_not_written_to_disk(tmp_path, monkeypatch):
    script = _Script([lambda request: _ok(MARINA)])
    session = OneMapSession()
    monkeypatch.chdir(tmp_path)
    _search(script, session=session)
    assert session.token == MANUAL
    assert list(tmp_path.iterdir()) == []
    source = Path(onemap.__file__).read_text(encoding="utf-8").lower()
    assert "sqlite" not in source
    assert "write_text" not in source


def test_refreshed_token_rejected_again_does_not_loop():
    script = _Script(
        [
            lambda request: httpx.Response(401, json={"error": "Invalid authentication token"}),
            _token_response,
            lambda request: httpx.Response(200, json={"error": "Authentication token expired"}),
        ]
    )
    with pytest.raises(DestinationUnavailable):
        _search(script)
    assert _paths(script) == [
        "/api/common/elastic/search",
        "/api/auth/post/getToken",
        "/api/common/elastic/search",
    ]


def test_non_auth_error_is_not_refreshed():
    script = _Script(
        [lambda request: httpx.Response(200, json={"error": "service temporarily unavailable"})]
    )
    with pytest.raises(DestinationUnavailable):
        _search(script)
    assert _paths(script) == ["/api/common/elastic/search"]


def test_zero_results_and_invalid_coordinates_are_filtered():
    blank = _place("BLANK", "SOMEWHERE", " ", "103.8")
    missing_lat = _place("NO LAT", "SOMEWHERE", None, "103.8")
    missing_lon = dict(MARINA)
    missing_lon.pop("LONGITUDE")
    words = _place("WORDS", "SOMEWHERE", "north", "east")
    script = _Script(
        [
            lambda request: _ok(blank, missing_lat, missing_lon, words, MARINA, found=5),
        ]
    )
    result = _search(script)
    assert result["query"] == "Marina Bay Sands"
    assert [place["label"] for place in result["results"]] == ["MARINA BAY SANDS"]
    assert "LATITUDE" not in json.dumps(result)


def test_found_zero_and_empty_results_are_successful_matches():
    for body in ({"found": 0, "results": [MARINA]}, {"found": 1, "results": []}):
        script = _Script([lambda request, payload=body: httpx.Response(200, json=payload)])
        result = _search(script)
        assert result == {"status": "ok", "query": "Marina Bay Sands", "results": []}


def test_all_valid_page_one_results_are_returned_once():
    places = [
        _place(f"PLACE {index}", f"ADDRESS {index}", f"1.{index}", f"103.{index}", str(index))
        for index in range(10)
    ]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["pageNum"])
        _assert_search(request, MANUAL)
        return _ok(*places)

    script = _Script([handler])
    result = _search(script)
    assert len(result["results"]) == 10
    assert seen == ["1"]
    assert len(script.calls) == 1


def test_query_is_trimmed_before_the_search():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["searchVal"] == "NUS"
        return _ok(_place("NUS", "KENT RIDGE", "1.2966", "103.7764"))

    script = _Script([handler])
    with _client(script) as client:
        result = search_destinations(
            "  NUS  ",
            session=OneMapSession(),
            client=client,
            token=MANUAL,
            email="",
            password="",
            now=1_700_000_000,
        )
    assert result["query"] == "NUS"
    assert len(script.calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        lambda request: (_ for _ in ()).throw(httpx.TimeoutException("timed out")),
        lambda request: httpx.Response(403, text="forbidden"),
        lambda request: httpx.Response(429, text="slow down"),
        lambda request: httpx.Response(500, text="down"),
        lambda request: httpx.Response(200, content=b"{"),
        lambda request: httpx.Response(200, json={"found": 2}),
    ],
)
def test_transport_and_malformed_failures_do_not_retry(failure):
    script = _Script([failure])
    with pytest.raises(DestinationUnavailable):
        _search(script)
    assert len(script.calls) == 1
    assert not any(path.endswith("/getToken") for path in _paths(script))


def _prime(tmp_path, monkeypatch, script, credentials):
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
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(main, "read_onemap_credentials", lambda: credentials)
    transport = httpx.MockTransport(script)

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", PatchedClient)


def test_endpoint_returns_page_one_places(tmp_path, monkeypatch):
    script = _Script([lambda request: (_assert_search(request, MANUAL), _ok(MARINA))[1]])
    _prime(tmp_path, monkeypatch, script, (MANUAL, "", ""))
    with TestClient(app) as client:
        response = client.get("/api/destinations", params={"q": "Marina Bay Sands"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["results"][0]["label"] == "MARINA BAY SANDS"
    assert "stop_code" not in response.text
    assert "probability" not in response.text
    assert MANUAL not in response.text
    assert PASSWORD not in response.text


@pytest.mark.parametrize("params", [{}, {"q": "   "}])
def test_empty_destination_query_does_not_call_onemap(tmp_path, monkeypatch, params):
    script = _Script([])
    _prime(tmp_path, monkeypatch, script, (MANUAL, EMAIL, PASSWORD))
    with TestClient(app) as client:
        response = client.get("/api/destinations", params=params)
    assert response.status_code == 400
    assert response.json()["detail"] == "Enter a destination."
    assert script.calls == []


def test_endpoint_unavailable_hides_credentials(tmp_path, monkeypatch):
    script = _Script([lambda request: httpx.Response(429, text="slow down")])
    _prime(tmp_path, monkeypatch, script, (MANUAL, EMAIL, PASSWORD))
    with TestClient(app) as client:
        response = client.get("/api/destinations", params={"q": "NUS"})
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["detail"] == "Destination search unavailable"
    assert MANUAL not in response.text
    assert EMAIL not in response.text
    assert PASSWORD not in response.text
    assert len(script.calls) == 1

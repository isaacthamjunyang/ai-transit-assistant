"""One BusArrival call with ServiceNo omitted returns every wanted service at the stop."""

import inspect
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import arrivals
from arrivals import ArrivalUnavailable, fetch_arrivals, fetch_stop_arrivals

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 18, 0, tzinfo=SGT)


def _bus(minutes):
    return {"EstimatedArrival": (NOW + timedelta(minutes=minutes)).isoformat(), "Monitored": 1, "Latitude": "1.3", "Longitude": "103.8"}


PAYLOAD = {"BusStopCode": "90041", "Services": [
    {"ServiceNo": "11", "NextBus": _bus(2), "NextBus2": _bus(10), "NextBus3": {}},
    {"ServiceNo": "7", "NextBus": _bus(5), "NextBus2": {}, "NextBus3": {}},
    {"ServiceNo": "99", "NextBus": _bus(1), "NextBus2": {}, "NextBus3": {}},
]}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_one_call_without_service_no_returns_every_wanted_service():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=PAYLOAD)

    result = fetch_stop_arrivals("90041", ["11", "7", "5"], client=_client(handler), account_key="key", now=NOW,
                                 user_lat=1.3, user_lon=103.8, accuracy=10)
    assert len(seen) == 1 and seen[0] == {"BusStopCode": "90041"}  # ServiceNo is omitted: one call, not one per service
    assert set(result) == {"11", "7", "5"}
    assert [bus["position"] for bus in result["11"]["buses"]] == ["NextBus", "NextBus2"]
    assert len(result["7"]["buses"]) == 1 and result["5"]["buses"] == []  # a service not listed has no buses
    assert result["11"]["status"] == "ok" and result["11"]["stop_code"] == "90041" and result["11"]["service_no"] == "11"
    assert all("99" not in key for key in result)  # only the wanted services


def test_failures_raise_the_same_unavailable_error():
    for response in (httpx.Response(500), httpx.Response(200, text="not json"), httpx.Response(200, json={"no": "services"})):
        with pytest.raises(ArrivalUnavailable):
            fetch_stop_arrivals("90041", ["11"], client=_client(lambda request, r=response: r), account_key="key", now=NOW)

    def boom(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ArrivalUnavailable):
        fetch_stop_arrivals("90041", ["11"], client=_client(boom), account_key="key", now=NOW)
    with pytest.raises(ArrivalUnavailable):
        fetch_stop_arrivals("90041", ["11"], account_key=" ", now=NOW)


def test_fetch_arrivals_is_unchanged_and_still_names_a_service():
    params = inspect.signature(fetch_arrivals).parameters
    assert list(params)[:2] == ["stop_code", "service_no"]
    source = inspect.getsource(arrivals._fetch)
    assert '"ServiceNo": service_no' in source


def test_demo_mode_uses_the_provider_interception(monkeypatch):
    calls = []

    def fake_fetch(client, key, stop, service, now, **kwargs):
        calls.append(service)
        return {"status": "ok", "stop_code": stop, "service_no": service, "fetched_at": now.isoformat(), "buses": []}

    monkeypatch.setattr(arrivals.demo, "lta_script_active", lambda: True)
    monkeypatch.setattr(arrivals, "_fetch", fake_fetch)
    result = fetch_stop_arrivals("90041", ["11", "7"], account_key="key", now=NOW)
    assert calls == ["11", "7"] and set(result) == {"11", "7"}  # no network: the Demo layer answers each service

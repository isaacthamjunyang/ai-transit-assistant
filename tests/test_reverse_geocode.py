"""OneMap reverse geocoding. Fixtures only — these tests do not call OneMap."""

import inspect
import logging

import httpx

import onemap
from onemap import DestinationUnavailable, OneMapSession, reverse_geocode


def _info(building="", road=""):
    return {
        "GeocodeInfo": [
            {
                "BUILDINGNAME": building,
                "ROAD": road,
                "POSTALCODE": "436886",
            }
        ]
    }


def _lookup(script, lat=1.320156, lon=103.89174):
    onemap.clear_reverse_cache()
    with httpx.Client(transport=httpx.MockTransport(script)) as client:
        return reverse_geocode(
            lat,
            lon,
            session=OneMapSession(),
            client=client,
            token="manual-token",
        )


def test_building_name_is_preferred_and_cleaned():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["location"] == "1.3202,103.8917"
        return httpx.Response(200, json=_info("TANJONG RHU VIEW", "TANJONG RHU ROAD"))

    body = _lookup(handler)
    assert body["name"] == "TANJONG RHU VIEW"
    assert body["display_name"] == "Tanjong Rhu View"
    assert body["full_name"] == "Tanjong Rhu View"
    assert "lat" not in body
    assert "lon" not in body


def test_road_is_used_when_the_building_is_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_info("NIL", "TANJONG RHU ROAD"))

    body = _lookup(handler)
    assert body["name"] == "TANJONG RHU ROAD"
    assert body["display_name"] == "Tanjong Rhu Road"
    assert body["full_name"] == "Tanjong Rhu Road"


def test_long_names_keep_the_original_and_a_formatted_display():
    raw = "A VERY LONG BUILDING NAME INDEED"
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_info(raw, "SHORT ROAD"))

    body = _lookup(handler)
    assert body["name"] == raw
    assert body["display_name"] == "A Very Long Building Name Indeed"
    assert body["full_name"] == body["display_name"]


def test_coordinates_are_rounded_before_the_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["location"] = request.url.params["location"]
        return httpx.Response(200, json=_info("BLOCK", "ROAD"))

    _lookup(handler, 1.320156, 103.89174)
    assert seen["location"] == "1.3202,103.8917"
    assert "1.320156" not in seen["location"]
    assert "103.89174" not in seen["location"]


def test_timeout_returns_an_empty_name():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    body = _lookup(handler)
    assert body == {"status": "ok", "name": "", "display_name": "", "full_name": ""}


def test_reverse_geocode_does_not_log_coordinates_or_use_sqlite(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_info("LIBRARY", "VICTORIA STREET"))

    _lookup(handler, 1.2965123, 103.8522456)
    logged = " ".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith("httpx") and not record.name.startswith("httpcore")
    )
    assert "1.2965123" not in logged
    assert "103.8522456" not in logged
    source = inspect.getsource(reverse_geocode)
    route = inspect.getsource(__import__("main").reverse_geocode_place)
    combined = source + route
    assert "sqlite" not in combined.lower()
    assert "print(" not in combined
    assert "logging" not in combined

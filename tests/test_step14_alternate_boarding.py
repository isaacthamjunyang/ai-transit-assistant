"""Nearby boarding-stop fallback when the chosen stop has no static route."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from lta_static import StopAndRouteCache
from route_plan import NO_FEASIBLE_MESSAGE, suggest_alternate_boarding

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=SGT)
LAT = 1.3
LON = 103.8
DEST = "99999"
INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


def _stop(code: str, name: str, north_m: float = 0) -> dict:
    return {
        "BusStopCode": code,
        "Description": name,
        "RoadName": "Rd",
        "Latitude": LAT + (north_m / 111_000),
        "Longitude": LON,
    }


def _hop(service: str, code: str, sequence: int, distance: float) -> dict:
    return {
        "ServiceNo": service,
        "Direction": 1,
        "BusStopCode": code,
        "StopSequence": sequence,
        "Distance": distance,
    }


def _plan(routes, stops, origin, alternates):
    cache = StopAndRouteCache(stops, routes, [])
    return suggest_alternate_boarding(
        cache, origin, DEST, LAT, LON, LAT, LON, alternates, now=NOW
    )


def test_a_valid_selected_stop_does_not_recommend_another():
    body = _plan(
        [_hop("11", "GOOD", 1, 0), _hop("11", DEST, 2, 1.8)],
        [_stop("GOOD", "Good Stop"), _stop(DEST, "Dest")],
        "GOOD",
        ["GOOD", "OTHER"],
    )
    assert body["route_status"] == "ok"
    assert "alternate_stop" not in body


def test_nearby_stop_is_recommended_without_live_scoring():
    body = _plan(
        [
            _hop("11", "GOOD", 1, 0),
            _hop("11", DEST, 2, 1.8),
            _hop("99", "SLOW", 1, 0),
            _hop("99", DEST, 2, 12),
        ],
        [
            _stop("BAD", "Bad Stop"),
            _stop("GOOD", "Tanjong Rhu", 197),
            _stop("SLOW", "Slow Stop", 50),
            _stop(DEST, "Waterplace", 400),
        ],
        "BAD",
        ["BAD", "GOOD", "SLOW"],
    )
    assert body["route_status"] == "alternate_boarding"
    assert body["message"] == "A route is available from a nearby stop."
    assert body["alternate_stop"]["stop_code"] == "GOOD"
    assert body["alternate_stop"]["services"] == ["11"]
    assert body["alternate_stop"]["route_type"] == "direct"
    assert body["alternate_stop"]["generalized_time_minutes"] < 90
    assert body["options"] == []
    source = Path(__file__).resolve().parents[1].joinpath("route_plan.py").read_text(encoding="utf-8")
    assert "fetch_arrivals" not in source
    assert "score_buses" not in source


def test_over_budget_and_no_link_stay_no_feasible():
    over = _plan(
        [_hop("11", "GOOD", 1, 0), _hop("11", DEST, 2, 40)],
        [_stop("BAD", "Bad"), _stop("GOOD", "Good", 100), _stop(DEST, "Dest", 200)],
        "BAD",
        ["GOOD"],
    )
    assert over["route_status"] == "no_feasible_route"
    assert over["message"] == NO_FEASIBLE_MESSAGE
    none = _plan(
        [],
        [_stop("BAD", "Bad"), _stop("GOOD", "Good"), _stop(DEST, "Dest")],
        "BAD",
        ["GOOD"],
    )
    assert none["route_status"] == "no_feasible_route"


def test_page_selection_and_map_and_explicit_stop_choice():
    html = INDEX.read_text(encoding="utf-8")
    css = (INDEX.parent / "components.css").read_text(encoding="utf-8")
    selected = css.split(".dest-stop-row.is-selected,", 1)[1].split("}", 1)[0]
    assert "0 0 0 2px var(--color-selected-outline)" in selected
    assert html.count('L.map("map"') == 1
    # The boarding-stop screen is gone: the map moves into the live screen and is resized there.
    place = html.split("function placeMap(inDestination, inLive)", 1)[1].split("function placeArriveBy", 1)[0]
    assert "map.invalidateSize()" in place
    assert "Use This Stop" not in html
    assert 'id="boarding-stage"' not in html
    assert html.count("setInterval(") == 2

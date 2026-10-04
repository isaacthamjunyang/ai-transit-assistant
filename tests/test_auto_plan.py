"""Auto-planned journey: the app picks the boarding stop and the route. Fixtures only; no live APIs."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import arrivals
import journey_plan
from journey_plan import (
    NO_ROUTE,
    NO_TARGET,
    TARGET_MET,
    TARGET_MISSED,
    pick_journey_option,
    service_number_key,
)

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
COPY = ROOT / "static" / "copy.js"
CSS = ROOT / "static" / "components.css"
STYLEGUIDE = ROOT / "static" / "styleguide.html"
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 18, 0, tzinfo=SGT)


def _option(minutes, transfers=0, walk=100, services=("36",), arrival_min=None):
    return {
        "generalized_time_minutes": minutes,
        "transfers": transfers,
        "boarding_walk_m": walk,
        "total_route_km": 5.0,
        "legs": [{"service_no": service, "direction": 1} for service in services],
        "estimated_arrival": None if arrival_min is None else NOW + timedelta(minutes=arrival_min),
    }


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


# The selection rule (pure function).

def test_target_met_by_the_second_option():
    first = _option(30, transfers=0, arrival_min=30)
    second = _option(35, transfers=1, services=("14", "106"), arrival_min=25)
    picked = pick_journey_option([second, first], NOW + timedelta(minutes=28))
    assert picked["reason"] == TARGET_MET
    assert picked["option"] is second
    assert picked["ordered"] == [first, second]


def test_no_option_meets_the_target_takes_the_first_in_order():
    first = _option(30, arrival_min=30)
    second = _option(40, arrival_min=40)
    picked = pick_journey_option([second, first], NOW + timedelta(minutes=10))
    assert picked["reason"] == TARGET_MISSED
    assert picked["option"] is first


def test_no_target_takes_the_first_in_order():
    first = _option(22)
    second = _option(30)
    picked = pick_journey_option([second, first], None)
    assert picked["reason"] == NO_TARGET
    assert picked["option"] is first


def test_ties_break_by_transfers_then_walk_then_lowest_service():
    transfer = _option(30, transfers=1, walk=50, services=("2", "3"))
    far = _option(30, transfers=0, walk=300, services=("1",))
    near_high = _option(30, transfers=0, walk=120, services=("106",))
    near_low = _option(30, transfers=0, walk=120, services=("36",))
    picked = pick_journey_option([transfer, far, near_high, near_low], None)
    assert picked["ordered"] == [near_low, near_high, far, transfer]
    assert picked["option"] is near_low
    assert service_number_key("14") < service_number_key("14e") < service_number_key("36") < service_number_key("106")


def test_no_options():
    picked = pick_journey_option([], NOW)
    assert picked == {"option": None, "reason": NO_ROUTE, "ordered": []}


def test_plan_journey_uses_every_candidate_stop_and_the_existing_pathfinder(monkeypatch):
    calls = []
    stops = [
        {"stop_code": "A", "description": "Stop A", "distance_m": 80, "latitude": 1.30, "longitude": 103.85},
        {"stop_code": "B", "description": "Stop B", "distance_m": 300, "latitude": 1.30, "longitude": 103.85},
    ]

    def fake_plan(cache, code, destination, *args, **kwargs):
        calls.append(code)
        minutes = 25 if code == "B" else 31
        leg = {"service_no": "36" if code == "B" else "7", "direction": 1, "boarding_stop_code": code,
               "boarding_stop_name": code, "alighting_stop_code": destination, "ride_minutes": 10, "stops": []}
        return {"route_status": "ok", "options": [{
            "route_type": "direct", "legs": [leg], "transfers": 0, "transfer_distance_m": 0.0,
            "transfer_stop_code": None, "generalized_time_minutes": minutes, "total_route_km": 3.0,
            "transfer_penalty_minutes": 0, "label": "Fastest Route",
        }]}

    monkeypatch.setattr(journey_plan, "nearby_boarding_stops", lambda *args, **kwargs: stops)
    monkeypatch.setattr(journey_plan, "plan_route", fake_plan)
    monkeypatch.setattr(journey_plan, "build_journey", lambda *args, **kwargs: {"arrival_point": None})
    body = journey_plan.plan_journey(
        object(), user_lat=1.3, user_lon=103.85, destination_stop_code="D", dest_lat=1.29, dest_lon=103.86, now=NOW
    )
    assert calls == ["A", "B"]
    assert body["reason"] == NO_TARGET
    assert body["option"]["legs"][0]["boarding_stop_code"] == "B"
    assert body["boarding_stop"]["stop_code"] == "B"
    assert "estimated_arrival" not in body["option"]


def test_plan_journey_without_routes_is_no_route(monkeypatch):
    monkeypatch.setattr(journey_plan, "nearby_boarding_stops", lambda *args, **kwargs: [])
    body = journey_plan.plan_journey(
        object(), user_lat=1.3, user_lon=103.85, destination_stop_code="D", dest_lat=1.29, dest_lon=103.86, now=NOW
    )
    assert body["route_status"] == "no_feasible_route"
    assert body["option"] is None


def test_planner_makes_no_live_arrival_calls():
    source = (ROOT / "journey_plan.py").read_text(encoding="utf-8")
    assert "fetch_arrivals" not in source
    assert "BusArrival" not in source
    assert "httpx" not in source


# The single overview lookup and its handoff to Start.

def test_peek_is_handed_to_the_first_monitoring_fetch_within_20_seconds(monkeypatch):
    fetched = []

    def fake_fetch(client, key, stop_code, service_no, now, **kwargs):
        fetched.append((stop_code, service_no))
        return {"status": "ok", "stop_code": stop_code, "service_no": service_no, "fetched_at": "2026-10-01T18:00:00+08:00", "buses": []}

    monkeypatch.setattr(arrivals, "_fetch", fake_fetch)
    monkeypatch.setattr(arrivals.demo, "lta_script_active", lambda: False)
    arrivals._peek_handoff.clear()
    arrivals.peek_arrivals("04121", "36", account_key="k")
    arrivals.fetch_arrivals("04121", "36", account_key="k")
    assert fetched == [("04121", "36")]
    arrivals.fetch_arrivals("04121", "36", account_key="k")
    assert len(fetched) == 2


def test_peek_handoff_expires_after_20_seconds(monkeypatch):
    fetched = []
    monkeypatch.setattr(arrivals, "_fetch", lambda *args, **kwargs: fetched.append(1) or {"buses": [], "fetched_at": "x"})
    monkeypatch.setattr(arrivals.demo, "lta_script_active", lambda: False)
    arrivals._peek_handoff.clear()
    arrivals._peek_handoff[("1", "2")] = (arrivals.time.monotonic() - 21, {"buses": [], "fetched_at": "x"})
    arrivals.fetch_arrivals("1", "2", account_key="k")
    assert fetched == [1]


# The page.

def test_back_arrow_is_gone_everywhere():
    for path in (INDEX, COPY, CSS, STYLEGUIDE):
        text = path.read_text(encoding="utf-8")
        assert "search-back" not in text
        assert "backToSearch" not in text
        assert "Back to search" not in text
    html = _page()
    assert 'id="back-home"' in html and 'id="home-button"' in html
    assert "Selected destination:" not in html
    assert "Destination stop confirmed" not in html


def test_confirm_opens_the_overview_which_replans_on_every_entry():
    html = _page()
    confirm = _between(html, 'confirmDestinationStop.addEventListener("click"', "arriveByInput.addEventListener")
    assert "confirmedDestinationStop = copyDestinationStop(selectedDestinationStop)" in confirm
    assert confirm.index("confirmedDestinationStop = copyDestinationStop") < confirm.index('pushScreen("journey")')
    apply = _between(html, "function applyScreen(name)", "function syncHomeButton")
    assert 'if (name === "journey") {\n        planJourney();' in apply
    plan = _between(html, "function planJourney()", "function peekOverviewArrivals")
    assert '"/api/journey-plan?user_lat="' in plan
    assert 'setOverviewState("loading")' in plan and 'setOverviewState("no-location")' in plan
    assert 'setOverviewState("no-route")' in plan and 'setOverviewState("unavailable")' in plan
    assert "setInterval" not in plan and "setTimeout" not in plan
    assert html.count("setInterval(") == 2


def test_at_most_one_lookup_per_overview_open_and_none_in_demo_mode():
    html = _page()
    peek = _between(html, "function peekOverviewArrivals(leg)", "function overviewPeekBus")
    assert "if (overviewPeekRequested || demoModeOn() || !leg)" in peek
    assert "overviewPeekRequested = true" in peek
    assert peek.count("fetch(") == 1
    assert '"/api/arrivals/peek?stop_code="' in peek
    plan = _between(html, "function planJourney()", "function peekOverviewArrivals")
    assert "overviewPeekRequested = false" in plan
    assert plan.count("peekOverviewArrivals(") == 1
    assert "startMonitoring" not in peek and "requestArrivals" not in peek


def test_edit_links_are_present_or_absent_as_specified():
    html = _page()
    render = _between(html, "function renderJourneyOverview()", "function syncOverviewArrive()")
    assert 'stepItem("stop", "Boarding stop"' in render
    for label in ("Edit boarding stop", "Edit bus service", "Edit transfer stop"):
        assert label not in html
    assert 'label: "Edit destination stop", action: function () { backToScreen("stops"); }' in render
    assert 'label: "Edit destination", action: function () { backToScreen("results"); }' in render
    assert 'id="overview-arrive-edit"' in html


def test_start_runs_select_planned_route_and_the_overview_has_no_pickers():
    html = _page()
    start = _between(html, 'getElementById("start-journey").addEventListener("click"', "});")
    assert start.index("selectPlannedRoute(pendingRouteOption)") < start.index('pushScreen("live")')
    overview = _between(html, 'id="journey-overview"', "</section>")
    for picker in ("stop-button", "route-choice", "service-button", 'type="radio"', "<select"):
        assert picker not in overview
    for gone in ('id="boarding-stage"', 'id="stop-list"', 'id="service-card"', 'id="continue-boarding"', "Review journey"):
        assert gone not in html


def test_reason_strings_are_approved_and_never_promise_arrival():
    copy = COPY.read_text(encoding="utf-8")
    html = _page()
    for text in (
        "Chosen for you: it should get you there by your arrive-by time.",
        "No route meets your arrive-by time. This one should get you there earliest.",
        "Chosen for you: the quickest option we found.",
    ):
        assert text in copy and text in html
        for banned in ("definitely", "guarantee", "certain to"):
            assert banned not in text.lower()
    # Item 19 of the screens 7-8 pass approved the reason lines and the transfer note.
    for name in ("reasonTargetMet", "reasonTargetMissed", "reasonNoTarget"):
        before = copy.split(name + ":", 1)[0].splitlines()[-1]
        assert "proposed" not in before, name
    assert "No direct or 1-transfer bus connection available for this trip." in _between(html, 'id="overview-no-route"', "</div>")

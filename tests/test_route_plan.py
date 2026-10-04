"""Step 14 route planning. Fixtures only — these tests do not call live APIs."""

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import arrivals
import demo
from arrivals import _with_probability
from demo import SCENARIOS
from journey import BOARDING_BUFFER_S, SLOW_WALK_M_S, leave_by_for_buses, leave_by_time
from leave_now import leave_now_notice, notification_time_iso
from explain import ACTION_ADVICE
from lta_static import StopAndRouteCache
from main import app
from nearby import EARTH_RADIUS_M
from route_plan import NO_FEASIBLE_MESSAGE, plan_route, reroute_enabled

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=SGT)
LAT = 1.3
LON = 103.8
ORIGIN = "01011"
DEST = "99999"
TRANSFER = "55555"
INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"
PLANNER = Path(__file__).resolve().parents[1] / "route_plan.py"
ROOT = Path(__file__).resolve().parents[1]


def _stop(code: str, name: str | None = None) -> dict:
    return {
        "BusStopCode": code,
        "Description": name or code,
        "RoadName": "Orchard Rd",
        "Latitude": LAT,
        "Longitude": LON,
    }


def _hop(
    service: str,
    code: str,
    sequence: int,
    distance: float | None,
    direction: int = 1,
) -> dict:
    return {
        "ServiceNo": service,
        "Direction": direction,
        "BusStopCode": code,
        "StopSequence": sequence,
        "Distance": distance,
    }


def _service(service: str, direction: int, frequency: str) -> dict:
    return {
        "ServiceNo": service,
        "Direction": direction,
        "OriginCode": ORIGIN,
        "DestinationCode": DEST,
        "AM_Peak_Freq": frequency,
        "AM_Offpeak_Freq": frequency,
        "PM_Peak_Freq": frequency,
        "PM_Offpeak_Freq": frequency,
    }


def _cache(routes: list[dict], services: list[dict] | None = None, stops: list[dict] | None = None) -> StopAndRouteCache:
    if stops is None:
        codes = []
        for route in routes:
            code = route["BusStopCode"]
            if code not in codes:
                codes.append(code)
        stops = [_stop(code) for code in codes]
    return StopAndRouteCache(stops, routes, [] if services is None else services)


def _plan(cache: StopAndRouteCache, origin: str = ORIGIN, destination: str = DEST) -> dict:
    return plan_route(cache, origin, destination, LAT, LON, LAT, LON, now=NOW)


def _minutes(km: float) -> float:
    return (km / 18) * 60


def test_route_options_are_three_labeled_static_choices_inside_ninety_minutes():
    slow = _plan(
        _cache(
            [
                _hop("1", ORIGIN, 1, 0),
                _hop("1", DEST, 2, 40),
            ]
        )
    )
    assert slow["route_status"] == "no_feasible_route"
    assert slow["message"] == NO_FEASIBLE_MESSAGE
    assert slow["options"] == []
    planned = _plan(
        _cache(
            [
                _hop("30", ORIGIN, 1, 0),
                _hop("30", DEST, 2, 9),
                _hop("20", ORIGIN, 1, 0),
                _hop("20", DEST, 2, 3.6),
                _hop("10", ORIGIN, 1, 0),
                _hop("10", DEST, 2, 1.8),
                _hop("40", ORIGIN, 1, 0),
                _hop("40", DEST, 2, 12),
            ]
        )
    )
    labels = [option["label"] for option in planned["options"]]
    assert labels == ["Fastest Route", "Fewest Transfers", "Alternative Route"]
    assert len(planned["options"]) == 3
    assert planned["options"][0]["legs"][0]["service_no"] == "10"
    assert all(option["route_type"] == "direct" for option in planned["options"])
    assert "fetch_arrivals" not in PLANNER.read_text(encoding="utf-8")


def test_direct_route_requires_the_destination_later_on_the_same_service():
    valid = _plan(
        _cache(
            [
                _hop("36", ORIGIN, 1, 0),
                _hop("36", "MID", 2, 1),
                _hop("36", DEST, 4, 3.6),
            ]
        )
    )
    assert valid["route_status"] == "ok"
    assert valid["route_type"] == "direct"
    assert valid["active_leg_index"] == 1
    assert len(valid["legs"]) == 1
    leg = valid["legs"][0]
    assert leg["boarding_stop_code"] == ORIGIN
    assert leg["alighting_stop_code"] == DEST
    assert leg["service_no"] == "36"
    assert leg["route_km"] == 3.6
    assert leg["ride_minutes"] == _minutes(3.6)
    assert "probability" not in leg
    assert valid["transfer_penalty_minutes"] == 0
    assert valid["arrive_by_state"] == "existing"

    reverse = _plan(
        _cache(
            [
                _hop("36", DEST, 1, 0),
                _hop("36", ORIGIN, 4, 3.6),
            ]
        )
    )
    assert reverse["route_status"] == "no_feasible_route"
    assert reverse["legs"] == []


def test_one_transfer_requires_the_same_stop_code_and_later_stops_on_both_legs():
    planned = _plan(
        _cache(
            [
                _hop("5", ORIGIN, 1, 0, 1),
                _hop("5", TRANSFER, 3, 1.8, 1),
                _hop("5", TRANSFER, 1, 0, 2),
                _hop("5", DEST, 4, 1.8, 2),
            ]
        )
    )
    assert planned["route_type"] == "one_transfer"
    assert planned["active_leg_index"] == 1
    assert planned["transfer_stop_code"] == TRANSFER
    assert len(planned["legs"]) == 2
    first, second = planned["legs"]
    assert first["alighting_stop_code"] == second["boarding_stop_code"] == TRANSFER
    assert first["direction"] == 1
    assert second["direction"] == 2
    assert second["alighting_stop_code"] == DEST
    assert planned["active_leg"]["service_no"] == "5"
    assert planned["active_leg"]["leg_index"] == 1
    assert "probability" not in first and "probability" not in second
    assert "leave_by" not in second
    assert planned["transfer_penalty_minutes"] == 10
    assert planned["arrive_by_state"] == "na"

    far = _stop("T2", "Far Transfer")
    far["Latitude"] = LAT + 0.02
    different_stop = _plan(
        _cache(
            [
                _hop("5", ORIGIN, 1, 0),
                _hop("5", "T1", 2, 1),
                _hop("6", "T2", 1, 0),
                _hop("6", DEST, 2, 1),
            ],
            stops=[_stop(ORIGIN), _stop("T1"), far, _stop(DEST)],
        )
    )
    assert different_stop["route_status"] == "no_feasible_route"
    assert different_stop["message"] == NO_FEASIBLE_MESSAGE
    near = _stop("T2", "Near Transfer")
    near["Latitude"] = LAT + 0.0002
    colocated = _plan(
        _cache(
            [
                _hop("5", ORIGIN, 1, 0),
                _hop("5", "T1", 2, 1),
                _hop("6", "T2", 1, 0),
                _hop("6", DEST, 2, 1),
            ],
            stops=[_stop(ORIGIN), _stop("T1"), near, _stop(DEST)],
        )
    )
    assert colocated["route_status"] == "ok"
    assert colocated["route_type"] == "one_transfer"
    assert colocated["transfer_distance_m"] <= 50

    dest_before_transfer = _plan(
        _cache(
            [
                _hop("5", ORIGIN, 1, 0),
                _hop("5", TRANSFER, 3, 1),
                _hop("6", DEST, 1, 0),
                _hop("6", TRANSFER, 3, 1),
            ]
        )
    )
    assert dest_before_transfer["route_status"] == "no_feasible_route"


def test_same_service_and_direction_through_an_intermediate_stop_stays_direct():
    planned = _plan(
        _cache(
            [
                _hop("7", ORIGIN, 1, 0),
                _hop("7", TRANSFER, 2, 1),
                _hop("7", DEST, 3, 2),
            ]
        )
    )
    assert planned["route_type"] == "direct"
    assert len(planned["legs"]) == 1
    assert planned["legs"][0]["alighting_stop_code"] == DEST
    assert planned["transfer_stop_code"] is None


def test_lowest_generalized_time_wins_and_catch_probability_is_not_an_input():
    source = PLANNER.read_text(encoding="utf-8")
    assert "score_buses" not in source
    assert "probability" not in source
    assert "leave_by" not in source
    planned = _plan(
        _cache(
            [
                _hop("99", ORIGIN, 1, 0),
                _hop("99", DEST, 2, 18),
                _hop("1", ORIGIN, 1, 0),
                _hop("1", TRANSFER, 2, 1.8),
                _hop("2", TRANSFER, 1, 0),
                _hop("2", DEST, 2, 1.8),
            ]
        )
    )
    assert planned["route_type"] == "one_transfer"
    assert planned["transfer_penalty_minutes"] == 10
    assert planned["generalized_time_minutes"] == 6 + _minutes(1.8) + _minutes(1.8) + 10
    direct = _plan(
        _cache(
            [
                _hop("3", ORIGIN, 1, 0),
                _hop("3", DEST, 2, 1.8),
                _hop("1", ORIGIN, 1, 0),
                _hop("1", TRANSFER, 2, 9),
                _hop("2", TRANSFER, 1, 0),
                _hop("2", DEST, 2, 9),
            ]
        )
    )
    assert direct["route_type"] == "direct"
    assert direct["transfer_penalty_minutes"] == 0
    assert direct["generalized_time_minutes"] == 6 + _minutes(1.8)


def test_tie_break_is_fewer_transfers_then_shorter_km_then_service_then_direction():
    fewer_transfers = _plan(
        _cache(
            [
                _hop("9", ORIGIN, 1, 0),
                _hop("9", DEST, 2, 6),
                _hop("1", ORIGIN, 1, 0),
                _hop("1", TRANSFER, 2, 1.5),
                _hop("2", TRANSFER, 1, 0),
                _hop("2", DEST, 2, 1.5),
            ]
        )
    )
    assert fewer_transfers["route_type"] == "direct"
    assert fewer_transfers["legs"][0]["service_no"] == "9"
    assert fewer_transfers["generalized_time_minutes"] == 6 + _minutes(6)

    shorter = _plan(
        _cache(
            [
                _hop("20", ORIGIN, 1, 0),
                _hop("20", DEST, 2, 3.6),
                _hop("30", ORIGIN, 1, 0),
                _hop("30", DEST, 2, 1.8),
            ],
            services=[_service("20", 1, "12"), _service("30", 1, "24")],
        )
    )
    assert shorter["legs"][0]["service_no"] == "30"
    assert shorter["generalized_time_minutes"] == 12 + _minutes(1.8)

    lexical = _plan(
        _cache(
            [
                _hop("2", ORIGIN, 1, 0),
                _hop("2", DEST, 2, 1.8),
                _hop("10", ORIGIN, 1, 0),
                _hop("10", DEST, 2, 1.8),
            ]
        )
    )
    assert lexical["legs"][0]["service_no"] == "10"

    direction = _plan(
        _cache(
            [
                _hop("8", ORIGIN, 1, 0, 2),
                _hop("8", DEST, 2, 1.8, 2),
                _hop("8", ORIGIN, 1, 0, 1),
                _hop("8", DEST, 2, 1.8, 1),
            ]
        )
    )
    assert direction["legs"][0]["direction"] == 1

    forward = [
        _hop("20", ORIGIN, 1, 0),
        _hop("20", "T1", 2, 1.8),
        _hop("1", "T1", 1, 0),
        _hop("1", DEST, 2, 1.8),
        _hop("10", ORIGIN, 1, 0),
        _hop("10", "T2", 2, 1.8),
        _hop("99", "T2", 1, 0),
        _hop("99", DEST, 2, 1.8),
    ]
    apart = [_stop(code) for code in (ORIGIN, "T1", DEST)]
    far_transfer = _stop("T2")
    far_transfer["Latitude"] = LAT + 0.02
    apart.append(far_transfer)
    assert _plan(_cache(forward, stops=apart))["legs"][0]["service_no"] == "10"
    assert _plan(_cache(list(reversed(forward)), stops=apart))["legs"][0]["service_no"] == "10"
    assert [leg["service_no"] for leg in _plan(_cache(list(reversed(forward)), stops=apart))["legs"]] == ["10", "99"]


def test_unusable_route_km_cannot_win_and_is_not_replaced_with_a_duration():
    planned = _plan(
        _cache(
            [
                _hop("1", ORIGIN, 1, 0),
                _hop("1", DEST, 2, None),
                _hop("4", ORIGIN, 1, 0),
                _hop("4", DEST, 2, 1.8),
            ]
        )
    )
    assert planned["legs"][0]["service_no"] == "4"
    assert planned["legs"][0]["ride_minutes"] == _minutes(1.8)
    assert planned["generalized_time_minutes"] == 6 + _minutes(1.8)

    unranked = _plan(
        _cache(
            [
                _hop("1", ORIGIN, 1, 0),
                _hop("1", DEST, 2, None),
            ]
        )
    )
    assert unranked["route_status"] == "no_feasible_route"
    assert unranked["message"] == NO_FEASIBLE_MESSAGE
    assert unranked["route_type"] is None
    assert unranked["legs"] == []
    assert unranked["options"] == []

    transfer_null = _plan(
        _cache(
            [
                _hop("1", ORIGIN, 1, 0),
                _hop("1", "55555", 2, None),
                _hop("2", "55555", 1, 0),
                _hop("2", DEST, 2, 1.8),
            ]
        )
    )
    assert transfer_null["route_status"] == "no_feasible_route"
    assert transfer_null["legs"] == []


def test_no_feasible_route_uses_the_locked_status_and_message():
    missing = _plan(_cache([_hop("1", ORIGIN, 1, 0), _hop("1", "OTHER", 2, 1)]))
    assert missing["route_status"] == "no_feasible_route"
    assert missing["message"] == "No direct or 1-transfer bus connection available for this trip."
    assert missing["route_type"] is None
    assert missing["legs"] == []
    assert missing["generalized_time_minutes"] is None

    same_stop = _plan(_cache([_hop("1", ORIGIN, 1, 0), _hop("1", ORIGIN, 2, 1)]), destination=ORIGIN)
    assert same_stop["route_status"] == "no_feasible_route"
    assert same_stop["legs"] == []


def test_route_plan_endpoint_returns_the_planner_result_without_calling_arrivals(monkeypatch):
    calls = []
    monkeypatch.setattr("main.load_static_data", lambda: _cache([
        _hop("36", ORIGIN, 1, 0),
        _hop("36", DEST, 2, 1.8),
    ]))
    monkeypatch.setattr("main.fetch_arrivals", lambda *args, **kwargs: calls.append("fetch"))
    monkeypatch.setattr(arrivals, "fetch_arrivals", lambda *args, **kwargs: calls.append("arrivals"))
    monkeypatch.setattr(demo, "begin_arrival_poll", lambda *args, **kwargs: calls.append("demo"))
    monkeypatch.setattr(demo, "simulated_lta_response", lambda *args, **kwargs: calls.append("fixture"))
    with TestClient(app) as client:
        response = client.get(
            "/api/route-plan",
            params={
                "boarding_stop_code": ORIGIN,
                "destination_stop_code": DEST,
                "user_lat": LAT,
                "user_lon": LON,
                "dest_lat": LAT,
                "dest_lon": LON,
            },
        )
    assert calls == []
    assert response.status_code == 200
    body = response.json()
    assert body["route_type"] == "direct"
    assert body["legs"][0]["service_no"] == "36"
    assert "/api/route-plan" in app.openapi()["paths"]


def test_step_11_reroute_stays_on_for_active_transfer_leg_1_active_transfer_leg_2_and_direct_routes(monkeypatch):
    calls = {"reroute": 0}

    def fake_fetch(*args, **kwargs):
        return {"status": "ok", "buses": [], "stop_code": ORIGIN, "service_no": "18"}

    def fake_reroute(**kwargs):
        calls["reroute"] += 1
        return {"switched": False, "reroute": None}

    monkeypatch.setattr("main.load_static_data", lambda: StopAndRouteCache([], [], []))
    monkeypatch.setattr("main.fetch_arrivals", fake_fetch)
    monkeypatch.setattr("main.plan_reroute", fake_reroute)
    monkeypatch.setattr("main.log_scored_poll", lambda **kwargs: None)
    monkeypatch.setattr(demo, "demo_enabled", lambda: False)
    params = {
        "stop_code": ORIGIN,
        "service_no": "18",
        "lat": LAT,
        "lon": LON,
        "accuracy": 10,
        "destination_stop_code": DEST,
        "dest_lat": LAT,
        "dest_lon": LON,
    }
    with TestClient(app) as client:
        plain = client.get("/api/arrivals", params=params)
        assert plain.status_code == 200
        assert calls["reroute"] == 1
        held = client.get("/api/arrivals", params={**params, "route_type": "one_transfer", "leg_index": 1})
        assert held.status_code == 200
        assert calls["reroute"] == 2
        second = client.get("/api/arrivals", params={**params, "route_type": "one_transfer", "leg_index": 2})
        assert second.status_code == 200
        assert calls["reroute"] == 3
        direct = client.get("/api/arrivals", params={**params, "route_type": "direct", "leg_index": 1})
        assert direct.status_code == 200
        assert calls["reroute"] == 4
    assert reroute_enabled(None, None) is True
    assert reroute_enabled("direct", 1) is True
    assert reroute_enabled("one_transfer", 1) is True
    assert reroute_enabled("one_transfer", 2) is True
    assert "def plan_reroute" not in (ROOT / "main.py").read_text(encoding="utf-8")


def test_leave_by_stays_on_the_active_stop_distance():
    eta = NOW + timedelta(minutes=8)
    leg_1 = leave_by_time(eta, 80)
    leg_2 = leave_by_time(eta, 40)
    assert leg_1 == eta - timedelta(seconds=80 / SLOW_WALK_M_S + BOARDING_BUFFER_S)
    assert leg_2 == eta - timedelta(seconds=40 / SLOW_WALK_M_S + BOARDING_BUFFER_S)
    assert SLOW_WALK_M_S == 1.1
    assert BOARDING_BUFFER_S == 45
    assert leg_1 != leg_2


def test_page_keeps_the_active_leg_on_the_existing_poll_and_advances_only_on_the_button():
    html = INDEX.read_text(encoding="utf-8")
    assert html.count("setInterval(") == 2
    assert "Start journey" in html
    for gone in ("I'm On Board", "Start Next Leg", "Track Leg 2", "You passed your stop", "Arrived at ", "id=\"route-plan\""):
        assert gone not in html, gone
    assert 'id="back-home"' in html
    assert ">Back</button>" in html
    assert "watchPosition" not in html
    assert "No direct or 1-transfer bus connection available for this trip." in html
    assert 'journeyComparison.textContent = "Arrive-by check: N/A"' not in html
    journey_request = html.split("function loadJourney()", 1)[1].split("fetch(url)", 1)[0]
    assert "&transfer=1" in journey_request
    assert "leg1_ride_minutes" in journey_request
    assert "leg2_ride_minutes" in journey_request
    render_journey = html.split("function renderJourney(body)", 1)[1].split("function loadJourney()", 1)[0]
    assert "body.comparison_label" in render_journey
    assert "one_transfer" not in render_journey
    assert "body.comparison_label" in html
    assert 'journeyLeaveBy.textContent = "Leave-by: " + formatTime(lastSuccess.leave_by, true);' in html
    assert "&route_type=" in html
    assert "&leg_index=" in html
    assert "openLeg2" not in html and "activeRoutePlan.leg_index = 2" not in html
    begin = html.split("function beginPlannedLeg()", 1)[1].split("function syncPlannedLegAfterReroute", 1)[0]
    assert begin.index("leg.boarding_stop_code") < begin.index("startMonitoring(leg.service_no)")
    assert "Fastest Route" not in html  # labels stay server-side; the app picks one option
    plan = html.split("function planJourney()", 1)[1].split("function peekOverviewArrivals", 1)[0]
    assert "beginPlannedLeg()" not in plan
    assert "startMonitoring" not in plan


def test_route_planning_does_not_use_demo_fixtures_or_add_scenarios():
    source = PLANNER.read_text(encoding="utf-8")
    for banned in ("fetch_arrivals", "BusArrival", "demo", "onemap", "openai", "OneMap", "OpenAI"):
        assert banned not in source
    assert SCENARIOS == (
        "LTA API Timeout / Proxy Error",
        "Stale Data Poll",
        "Schedule-Only / Monitored = 0",
        "GPS Fix/Age Penalty",
        "Auto-Reroute Opportunity",
        "OneMap Zero Results / API Error",
        "Unsafe / Contradictory OpenAI Output",
    )


def test_two_leg_plan_then_first_leg_poll_uses_the_boarding_stop(monkeypatch):
    transfer_lat = LAT + math.degrees(250 / EARTH_RADIUS_M)
    stops = [
        _stop(ORIGIN, "Origin Stop"),
        {
            "BusStopCode": "55555",
            "Description": "Transfer Stop",
            "RoadName": "Rd",
            "Latitude": transfer_lat,
            "Longitude": LON,
        },
        _stop(DEST, "Destination Stop"),
    ]
    routes = [
        _hop("36", ORIGIN, 1, 0),
        _hop("36", "55555", 2, 1.8),
        _hop("14", "55555", 1, 0, 2),
        _hop("14", DEST, 2, 1.8, 2),
    ]
    cache = _cache(routes, stops=stops)
    polls = []
    demo_polls = []
    reroute_seen = []

    def fake_fetch(stop_code, service_no, user_lat=None, user_lon=None, accuracy=None, location_timestamp=None, cache=None, **kwargs):
        polls.append((stop_code, service_no))
        # A whole-second clock: the two polls each read the clock, and a sub-second part rounded the slack
        # difference to 199 or 201 now and then. With whole seconds both polls see exactly 480 s to the bus.
        moment = datetime.now(SGT).replace(microsecond=0)
        arrival = (moment + timedelta(minutes=8)).isoformat()
        buses = [{"arrival_time": arrival, "monitored": True, "position": "NextBus"}]
        scored = _with_probability(
            buses,
            stop_code=stop_code,
            service_no=service_no,
            user_lat=user_lat,
            user_lon=user_lon,
            accuracy=accuracy,
            location_timestamp=location_timestamp,
            cache=cache,
            now=moment,
        )
        leave = leave_by_for_buses(
            scored,
            stop_code=stop_code,
            user_lat=user_lat,
            user_lon=user_lon,
            cache=cache,
            now=moment,
        )
        notice_time = notification_time_iso(leave)
        stop = cache.stop_by_code(stop_code) if cache is not None else None
        stop_name = stop["Description"] if isinstance(stop, dict) else stop_code
        return {
            "status": "ok",
            "stop_code": stop_code,
            "service_no": service_no,
            "buses": scored,
            "leave_by": leave,
            "fetched_at": moment.isoformat(),
            "notification_time": notice_time,
            "leave_now": leave_now_notice(
                scored,
                service_no=service_no,
                stop_code=stop_code,
                stop_name=stop_name,
                leave_by_iso=leave,
                notification_time=notice_time,
                arrival_status="ok",
            ),
        }

    def fake_reroute(**kwargs):
        reroute_seen.append(kwargs.get("last_reroute_at"))
        return {"switched": False, "reroute": None}

    monkeypatch.setattr("main.load_static_data", lambda: cache)
    monkeypatch.setattr("main.fetch_arrivals", fake_fetch)
    monkeypatch.setattr("main.plan_reroute", fake_reroute)
    monkeypatch.setattr("main.log_scored_poll", lambda **kwargs: None)
    monkeypatch.setattr(demo, "demo_enabled", lambda: False)
    monkeypatch.setattr(demo, "begin_arrival_poll", lambda stop, service: demo_polls.append((stop, service)))

    with TestClient(app) as client:
        planned = client.get(
            "/api/route-plan",
            params={
                "boarding_stop_code": ORIGIN,
                "destination_stop_code": DEST,
                "user_lat": LAT,
                "user_lon": LON,
                "dest_lat": LAT,
                "dest_lon": LON,
            },
        )
        assert demo_polls == []
        assert polls == []
        body = planned.json()
        assert body["route_status"] == "ok"
        assert body["route_type"] == "one_transfer"
        assert body["active_leg"]["leg_index"] == 1
        assert body["active_leg"]["boarding_stop_code"] == ORIGIN
        assert body["active_leg"]["service_no"] == "36"
        assert body["transfer_stop_code"] == "55555"
        assert body["transfer_penalty_minutes"] == 10
        assert body["arrive_by_state"] == "na"
        assert [leg["service_no"] for leg in body["legs"]] == ["36", "14"]
        assert body["legs"][0]["alighting_stop_code"] == body["legs"][1]["boarding_stop_code"]
        assert "probability" not in body["legs"][1]
        assert "leave_by" not in body["legs"][1]
        origin_code = body["legs"][0]["boarding_stop_code"]
        leg_2 = body["legs"][1]
        shared = {
            "lat": LAT,
            "lon": LON,
            "accuracy": 12,
            "destination_stop_code": DEST,
            "dest_lat": LAT,
            "dest_lon": LON,
        }
        first = client.get(
            "/api/arrivals",
            params={
                **shared,
                "stop_code": origin_code,
                "service_no": body["legs"][0]["service_no"],
                "route_type": "one_transfer",
                "leg_index": 1,
                "explanation_rendered": 0,
            },
        )
    assert first.status_code == 200
    first_body = first.json()
    assert polls == [(ORIGIN, "36")]
    assert demo_polls == [(ORIGIN, "36")]
    assert "reroute" in first_body
    assert reroute_seen == [None]
    assert first_body["leave_now"]["bus_id"].startswith("36|01011|")
    assert set(first_body["explanation"]["context"]) == {"band", "uncertain"}

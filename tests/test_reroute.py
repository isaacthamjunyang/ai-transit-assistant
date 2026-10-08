"""Auto-reroute decisions. Fixtures only — these tests do not call live APIs."""

import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

import observations
from arrivals import ArrivalUnavailable, fetch_arrivals
from catch_heuristic import score_buses
from journey import leave_by_time, parse_journey_time
from lta_static import StopAndRouteCache
from main import app
from nearby import EARTH_RADIUS_M, haversine_m
from observations import record_observation
from reroute import (
    apply_active_target,
    log_scored_poll,
    plan_reroute,
    resolve_pinned_target,
)

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
LAT = 1.3
LON = 103.8
ORIGIN = "01011"
DEST = "99999"
INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"
REROUTE_SOURCE = Path(__file__).resolve().parents[1] / "reroute.py"


def _north(metres: float) -> tuple[float, float]:
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _stop(code: str, name: str, lat: float, lon: float) -> dict:
    return {
        "BusStopCode": code,
        "Description": name,
        "RoadName": "Orchard Rd",
        "Latitude": lat,
        "Longitude": lon,
    }


def _hop(service: str, code: str, sequence: int, distance: float | None) -> dict:
    return {
        "ServiceNo": service,
        "Direction": 1,
        "BusStopCode": code,
        "StopSequence": sequence,
        "Distance": distance,
    }


def _cache(stops: list[dict], routes: list[dict]) -> StopAndRouteCache:
    return StopAndRouteCache(stops, routes, [])


def _simple_cache(dest_distance: float | None = 2.0) -> StopAndRouteCache:
    dest_lat, dest_lon = _north(2000)
    return _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", DEST, 5, dest_distance),
        ],
    )


def _bus(
    position: str,
    low: int,
    high: int,
    point: int,
    eta: str = "2026-09-29T14:20:00+08:00",
    *,
    missed: bool = False,
    primary: bool = False,
    quality: str = "live",
) -> dict:
    return {
        "position": position,
        "arrival_time": eta,
        "is_missed": missed,
        "is_primary": primary,
        "monitored": True,
        "latitude": LAT,
        "longitude": LON,
        "probability": {
            "point": point,
            "range_low": low,
            "range_high": high,
            "slack_seconds": 12,
            "data_quality": quality,
        },
    }


def _current(buses: list[dict], status: str = "ok", service: str = "18", stop: str = ORIGIN) -> dict:
    return {
        "status": status,
        "stop_code": stop,
        "service_no": service,
        "buses": buses,
    }


def _primary(high: int = 39, point: int = 30, low: int = 20, quality: str = "live") -> dict:
    return _bus("NextBus", low, high, point, "2026-09-29T14:08:00+08:00", primary=True, quality=quality)


def _decide(
    buses: list[dict],
    cache: StopAndRouteCache | None = None,
    *,
    status: str = "ok",
    arrive_by: datetime | None = None,
    last_reroute_at: datetime | None = None,
    accuracy: float = 12,
    location_timestamp: float | None = None,
    loader=None,
    place: tuple[float, float] | None = None,
    destination: str = DEST,
    db_path=None,
    write_observation: bool = False,
) -> dict:
    if loader is None:
        def loader(_code, _service):
            raise AssertionError("alternate arrivals were requested")

    dest_lat, dest_lon = _north(2000)
    if place is None:
        place = (dest_lat, dest_lon)
    return plan_reroute(
        cache=cache if cache is not None else _simple_cache(),
        current=_current(buses, status=status),
        user_lat=LAT,
        user_lon=LON,
        accuracy_m=accuracy,
        location_timestamp=location_timestamp,
        destination_stop_code=destination,
        place_lat=place[0],
        place_lon=place[1],
        arrive_by=arrive_by,
        last_reroute_at=last_reroute_at,
        now=NOW,
        loader=loader,
        db_path=db_path,
        write_observation=write_observation,
    )


def test_low_range_without_a_qualifying_alternative_keeps_the_route():
    decision = _decide([_primary(), _bus("NextBus2", 40, 55, 48)])
    assert decision["switched"] is False
    assert decision["reroute"] is None
    assert decision["no_better_option"] == (
        "Primary bus target has low catch probability (30%), "
        "but no better direct alternative meets the 15% improvement threshold."
    )


def test_exact_15_point_lower_bound_switches():
    decision = _decide([_primary(), _bus("NextBus2", 54, 80, 70)])
    assert decision["switched"] is True
    reroute = decision["reroute"]
    assert reroute["service_no"] == "18"
    assert reroute["stop"]["stop_code"] == ORIGIN
    assert reroute["destination_stop_code"] == DEST
    assert reroute["reroute_reason"] == (
        "Switched from Bus 18 (01011) [high: 39%] to Bus 18 (01011) [low: 54%]: +15% margin"
    )


def test_14_point_gap_does_not_switch():
    decision = _decide([_primary(), _bus("NextBus2", 53, 80, 90)])
    assert decision["switched"] is False
    assert decision["no_better_option"].startswith(
        "Primary bus target has low catch probability (30%)"
    )


def test_point_probability_does_not_replace_range_high():
    blocked = _decide([_primary(high=50, point=5), _bus("NextBus2", 99, 99, 99)])
    assert blocked["switched"] is False
    assert blocked["no_better_option"] is None
    switched = _decide([_primary(high=39, point=90), _bus("NextBus2", 54, 70, 10)])
    assert switched["switched"] is True
    assert switched["reroute"]["probability_line"].endswith("vs previous about 90%.")


def test_next_bus_2_can_qualify():
    decision = _decide([_primary(), _bus("NextBus2", 70, 88, 80)])
    assert decision["switched"] is True
    assert "NextBus2" not in decision["reroute"]["message"]
    assert decision["reroute"]["arrival_time"] == "2026-09-29T14:20:00+08:00"


def test_next_bus_3_can_qualify():
    decision = _decide(
        [
            _primary(),
            _bus("NextBus2", 41, 50, 45, "2026-09-29T14:12:00+08:00"),
            _bus("NextBus3", 70, 88, 80, "2026-09-29T14:30:00+08:00"),
        ]
    )
    assert decision["switched"] is True
    assert decision["reroute"]["arrival_time"] == "2026-09-29T14:30:00+08:00"


def test_the_recommender_picks_the_highest_point_among_those_that_pass_the_improvement_rule():
    calls = []

    def loader(code, service):
        calls.append((code, service))
        return _current(
            [_bus("NextBus", 80, 90, 40, "2026-09-29T14:25:00+08:00", primary=True)],
            stop=code,
            service=service,
        )

    alt_lat, alt_lon = _north(120)
    dest_lat, dest_lon = _north(2000)
    cache = _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop("01022", "Near", alt_lat, alt_lon),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", DEST, 5, 2),
            _hop("36", "01022", 1, 0),
            _hop("36", DEST, 4, 1),
        ],
    )
    decision = _decide(
        [_primary(), _bus("NextBus2", 60, 70, 95)],
        cache,
        loader=loader,
    )
    assert decision["switched"] is True
    # Both pass the improvement rule (range_low 60 and 80 against 39 + 15). The recommender then takes the
    # highest point, 95 at the current stop, over the other stop's 40 (it no longer ranks by range_low).
    assert decision["reroute"]["service_no"] == "18"
    assert decision["reroute"]["stop"]["stop_code"] == ORIGIN
    assert decision["options"]["recommended"]["reason_code"] == "HIGHEST_CHANCE"
    assert calls == [("01022", "36")]


def test_equal_chance_with_arrive_by_takes_the_on_time_option_at_the_current_stop():
    def loader(code, service):
        return _current(
            [_bus("NextBus", 70, 90, 75, "2026-09-29T14:40:00+08:00", primary=True)],
            stop=code,
            service=service,
        )

    alt_lat, alt_lon = _north(100)
    dest_lat, dest_lon = _north(2000)
    cache = _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop("01022", "Short", alt_lat, alt_lon),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", DEST, 6, 5),
            _hop("36", "01022", 1, 0),
            _hop("36", DEST, 3, 1),
        ],
    )
    decision = _decide(
        [_primary(), _bus("NextBus2", 70, 90, 75, "2026-09-29T14:05:00+08:00")],
        cache,
        loader=loader,
        arrive_by=NOW + timedelta(hours=3),
        place=(dest_lat, dest_lon),
    )
    # Equal points. Bus 18 at the current stop is also the earlier arrival (its ride is anchored on a 5 minute ETA),
    # so it is the highest chance on time; the walk tie-break itself is covered in test_recommend.py.
    assert decision["reroute"]["service_no"] == "18"
    assert decision["reroute"]["stop"]["stop_code"] == ORIGIN
    assert decision["options"]["recommended"]["reason_code"] == "HIGHEST_CHANCE_ON_TIME"


def test_the_highest_point_wins_without_arrive_by_even_at_a_later_arrival():
    def loader(code, service):
        return _current(
            [_bus("NextBus", 70, 90, 99, "2026-09-29T14:40:00+08:00", primary=True)],
            stop=code,
            service=service,
        )

    alt_lat, alt_lon = _north(100)
    dest_lat, dest_lon = _north(2000)
    cache = _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop("01022", "Short", alt_lat, alt_lon),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", DEST, 6, 1),
            _hop("36", "01022", 1, 0),
            _hop("36", DEST, 3, 1),
        ],
    )
    decision = _decide(
        [_primary(), _bus("NextBus2", 70, 90, 40, "2026-09-29T14:05:00+08:00")],
        cache,
        loader=loader,
    )
    # Point 99 at the other stop beats point 40 at the current stop; the earlier ETA is no longer a tie-break here.
    assert decision["reroute"]["service_no"] == "36"
    assert decision["reroute"]["stop"]["stop_code"] == "01022"
    assert decision["options"]["recommended"]["reason_code"] == "HIGHEST_CHANCE"


def test_same_service_at_another_stop_is_allowed():
    def loader(code, service):
        return _current(
            [_bus("NextBus", 80, 90, 85, primary=True)],
            stop=code,
            service=service,
        )

    alt_lat, alt_lon = _north(150)
    dest_lat, dest_lon = _north(2000)
    cache = _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop("01022", "Next door", alt_lat, alt_lon),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", "01022", 2, 0.4),
            _hop("18", DEST, 6, 2),
        ],
    )
    decision = _decide(
        [_primary(), _bus("NextBus2", 42, 55, 48)],
        cache,
        loader=loader,
    )
    assert decision["switched"] is True
    assert decision["reroute"]["service_no"] == "18"
    assert decision["reroute"]["stop"]["stop_code"] == "01022"
    assert decision["reroute"]["destination_stop_code"] == DEST


def test_only_the_two_closest_alternate_stops_are_used():
    calls = []

    def loader(code, service):
        calls.append(code)
        return _current([_bus("NextBus", 99, 99, 99, primary=True)], stop=code, service=service)

    dest_lat, dest_lon = _north(2000)
    spots = {
        "near": _north(50),
        "c100": _north(100),
        "c200": _north(200),
        "c300": _north(300),
        "far": _north(500),
    }
    stops = [_stop(ORIGIN, "Origin", LAT, LON), _stop(DEST, "Destination", dest_lat, dest_lon)]
    routes = [_hop("18", ORIGIN, 1, 0), _hop("18", DEST, 9, 3)]
    for code, (lat, lon) in spots.items():
        stops.append(_stop(code, code, lat, lon))
        if code != "near":
            routes.append(_hop("36", code, 2, 0.2))
    routes.append(_hop("36", DEST, 8, 2))
    cache = _cache(stops, routes)
    for code, (lat, lon) in spots.items():
        distance = haversine_m(LAT, LON, lat, lon)
        if code == "far":
            assert distance > 400
        else:
            assert distance <= 400
    decision = _decide([_primary(), _bus("NextBus2", 40, 50, 45)], cache, loader=loader)
    assert calls == ["c100", "c200"]
    assert decision["reroute"]["stop"]["stop_code"] == "c100"


def test_stop_beyond_400m_is_not_an_alternate():
    calls = []

    def loader(code, service):
        calls.append(code)
        return {"status": "ok", "buses": []}

    dest_lat, dest_lon = _north(2000)
    far_lat, far_lon = _north(450)
    cache = _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop("far", "Far", far_lat, far_lon),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", DEST, 5, 2),
            _hop("36", "far", 2, 0),
            _hop("36", DEST, 6, 1),
        ],
    )
    decision = _decide([_primary()], cache, loader=loader)
    assert calls == []
    assert decision["switched"] is False


def test_a_late_option_is_kept_and_the_recommender_names_none_by_target():
    # The old arrive-by filter dropped a candidate whose estimate was after the target. A late option now
    # stays: it is labelled and the recommender handles it (NONE_BY_TARGET).
    buses = [_primary(), _bus("NextBus2", 70, 90, 80)]
    roomy = _decide(buses, _simple_cache(2.0), arrive_by=NOW + timedelta(hours=2), place=_north(2000))
    tight = _decide(buses, _simple_cache(2.0), arrive_by=NOW + timedelta(minutes=12), place=_north(2000))
    assert roomy["switched"] is True and tight["switched"] is True
    assert roomy["options"]["recommended"]["reason_code"] == "HIGHEST_CHANCE_ON_TIME"
    assert roomy["options"]["recommended"]["after_target"] is False
    assert tight["options"]["recommended"]["reason_code"] == "NONE_BY_TARGET"
    assert tight["options"]["recommended"]["after_target"] is True


def test_datetime_local_arrive_by_is_read_as_singapore_time_and_a_blank_value_sets_no_target():
    buses = [_primary(), _bus("NextBus2", 70, 90, 80)]
    cache = _simple_cache(2.0)
    place = _north(2000)
    set_value = _decide(
        buses,
        cache,
        arrive_by=parse_journey_time("2026-09-29T14:12"),
        place=place,
    )
    blank = _decide(buses, cache, arrive_by=None, place=place)
    assert set_value["options"]["recommended"]["reason_code"] == "NONE_BY_TARGET"
    assert blank["options"]["recommended"]["reason_code"] == "HIGHEST_CHANCE"


def test_null_ride_minutes_gives_no_estimate_and_is_not_on_time_when_arrive_by_is_set():
    decision = _decide(
        [_primary(), _bus("NextBus2", 90, 95, 92)],
        _simple_cache(None),
        arrive_by=NOW + timedelta(hours=5),
    )
    # Kept in the list with no estimate. Nothing can be on time, so it is the only (unverified) recommendation.
    option = decision["options"]["recommended"]
    assert option["estimated_arrival"] is None
    assert option["reason_code"] == "NONE_BY_TARGET"


def test_without_arrive_by_a_null_ride_can_still_qualify():
    decision = _decide(
        [_primary(), _bus("NextBus2", 90, 95, 92)],
        _simple_cache(None),
    )
    assert decision["switched"] is True


def test_uncertain_gps_does_not_switch():
    called = []

    def loader(code, service):
        called.append(code)
        return {"status": "ok", "buses": []}

    by_accuracy = _decide(
        [_primary(), _bus("NextBus2", 90, 95, 92)],
        accuracy=101,
        loader=loader,
    )
    by_age = _decide(
        [_primary(), _bus("NextBus2", 90, 95, 92)],
        accuracy=10,
        location_timestamp=NOW.timestamp() - 61,
        loader=loader,
    )
    fresh = _decide(
        [_primary(), _bus("NextBus2", 90, 95, 92)],
        accuracy=100,
        location_timestamp=NOW.timestamp() - 60,
    )
    assert by_accuracy["switched"] is False
    assert by_accuracy["no_better_option"] is None
    assert by_age["switched"] is False
    assert called == []
    assert fresh["switched"] is True


def test_stale_or_unavailable_poll_does_not_switch():
    called = []

    def loader(code, service):
        called.append(code)
        return {"status": "ok", "buses": []}

    stale = _decide([_primary(), _bus("NextBus2", 90, 95, 92)], status="stale", loader=loader)
    failed = _decide(
        [_primary(), _bus("NextBus2", 90, 95, 92)],
        status="unavailable",
        loader=loader,
    )
    assert stale["switched"] is False
    assert failed["switched"] is False
    assert stale["reroute"] is None
    assert called == []


def test_missed_candidate_is_not_selected():
    missed_eta = (NOW - timedelta(seconds=31)).isoformat()
    scored = score_buses(
        [
            {
                "position": "NextBus",
                "arrival_time": missed_eta,
                "monitored": True,
                "latitude": LAT,
                "longitude": LON,
            }
        ],
        user_lat=LAT,
        user_lon=LON,
        accuracy_m=10,
        stop_lat=LAT,
        stop_lon=LON,
        services=[],
        routes=[],
        service_no="18",
        stop_code=ORIGIN,
        now=NOW,
    )
    assert scored[0]["is_missed"] is True
    decision = _decide(
        [
            _primary(),
            _bus("NextBus2", 95, 99, 97, missed=True),
            _bus("NextBus3", 40, 50, 45),
        ]
    )
    assert decision["switched"] is False


def test_switch_replaces_service_and_stop_and_keeps_the_destination():
    def loader(code, service):
        return _current(
            [_bus("NextBus", 80, 92, 86, primary=True)],
            stop=code,
            service=service,
        )

    alt_lat, alt_lon = _north(180)
    dest_lat, dest_lon = _north(2000)
    cache = _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop("01022", "Replacement", alt_lat, alt_lon),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", DEST, 5, 2),
            _hop("174", "01022", 1, 0),
            _hop("174", DEST, 4, 1.5),
        ],
    )
    decision = _decide([_primary()], cache, loader=loader)
    reroute = decision["reroute"]
    assert reroute["service_no"] == "174"
    assert reroute["stop"]["stop_code"] == "01022"
    assert reroute["destination_stop_code"] == DEST
    follow = plan_reroute(
        cache=cache,
        current=_current(
            [_bus("NextBus", 70, 88, 80, primary=True)],
            service="174",
            stop="01022",
        ),
        user_lat=LAT,
        user_lon=LON,
        accuracy_m=12,
        location_timestamp=None,
        destination_stop_code=DEST,
        place_lat=dest_lat,
        place_lon=dest_lon,
        arrive_by=None,
        last_reroute_at=NOW,
        now=NOW + timedelta(seconds=30),
        loader=loader,
    )
    assert follow["switched"] is False


def test_cooldown_blocks_until_120_seconds_and_then_requires_20_points():
    tempting = [_primary(), _bus("NextBus2", 90, 95, 92)]
    calls = []

    def loader(code, service):
        calls.append((code, service))
        raise AssertionError("cooldown must not score an alternative")

    during = _decide(
        tempting,
        last_reroute_at=NOW - timedelta(seconds=119),
        loader=loader,
    )
    barely = _decide(
        [_primary(), _bus("NextBus2", 54, 80, 70)],
        last_reroute_at=NOW - timedelta(seconds=120),
    )
    enough = _decide(
        [_primary(), _bus("NextBus2", 59, 80, 70)],
        last_reroute_at=NOW - timedelta(seconds=120),
    )
    assert calls == []
    assert during["switched"] is False
    assert during["no_better_option"] is None
    assert barely["switched"] is False
    assert barely["no_better_option"] == (
        "Primary bus target has low catch probability (30%), "
        "but no better direct alternative meets the post-reroute 20% improvement threshold."
    )
    assert enough["switched"] is True
    assert "+20% margin" in enough["reroute"]["reroute_reason"]


def test_cooldown_starts_when_a_switch_fires_not_when_an_alternative_is_scored():
    weak = _decide([_primary(), _bus("NextBus2", 50, 60, 55)])
    assert weak["switched"] is False
    later = _decide(
        [_primary(), _bus("NextBus2", 54, 80, 70)],
        last_reroute_at=None,
    )
    assert later["switched"] is True
    blocked = _decide(
        [_primary(), _bus("NextBus2", 90, 95, 92)],
        last_reroute_at=NOW,
    )
    assert blocked["switched"] is False


def test_alternate_fetch_failure_does_not_fail_the_current_poll():
    def loader(code, service):
        if code == "01021":
            raise ArrivalUnavailable("down")
        return _current(
            [_bus("NextBus", 80, 90, 85, primary=True)],
            stop=code,
            service=service,
        )

    dest_lat, dest_lon = _north(2000)
    stops = [
        _stop(ORIGIN, "Origin", LAT, LON),
        _stop(DEST, "Destination", dest_lat, dest_lon),
    ]
    routes = [_hop("18", ORIGIN, 1, 0), _hop("18", DEST, 8, 2)]
    for index, metres in enumerate((100, 200), start=1):
        code = f"0102{index}"
        lat, lon = _north(metres)
        stops.append(_stop(code, code, lat, lon))
        routes.extend([_hop("36", code, 2, 0), _hop("36", DEST, 6, 1)])
    decision = _decide([_primary()], _cache(stops, routes), loader=loader)
    assert decision["switched"] is True
    assert decision["reroute"]["stop"]["stop_code"] == "01022"


def test_reroute_copy_uses_the_old_and_new_results():
    decision = _decide([_primary(point=28), _bus("NextBus2", 60, 81, 73)])
    reroute = decision["reroute"]
    assert reroute["title"] == "Route Updated"
    assert reroute["message"] == "Switched to Bus 18 at Origin (01011)."
    assert reroute["probability_line"] == (
        "Catch probability: about 73% vs previous about 28%."
    )
    assert reroute["notification_title"] == "Route Updated \u2014 Bus 18"
    assert reroute["notification_body"] == (
        "Switched to Bus 18 at Origin. Catch probability: 73% (range 60\u201381%)."
    )


def test_page_shows_the_server_copy_and_does_not_request_permission(tmp_path):
    html = INDEX.read_text(encoding="utf-8")
    assert html.count("Notification.requestPermission") == 1
    assert "showLocalNotification(notice.title, { body: notice.body })" in html
    assert "new Notification(reroute.notification_title, { body: reroute.notification_body })" in html
    notify = html.split("function notifyReroute", 1)[1].split("function clearRerouteState", 1)[0]
    assert "requestPermission" not in notify
    assert 'Notification.permission !== "granted"' in notify
    switch = html.split("function applyRouteSwitch", 1)[1].split("function highlightBoardingSelection", 1)[0]
    assert "confirmedDestinationStop" not in switch
    assert "selectedBoardingStop = reroute.stop" in switch
    assert switch.index("clearLeaveNowState") < switch.index("startMonitoring")
    assert switch.index("lastRerouteAt") < switch.index("startMonitoring")
    assert "rerouteTitle.textContent = reroute.title" in html
    assert "rerouteMessage.textContent = reroute.message" in html
    assert "rerouteProbability.textContent = reroute.probability_line" in html
    assert "decision.no_better_option" in html
    assert html.count("setInterval(") == 3
    assert "var POLL_MS = 20000;" in html
    assert "not_before" not in html
    assert "arrivalNotBefore" not in html
    assert "pinnedEtaTimestamp" in html
    assert "pinned_eta" in html
    assert "Notifications Optional" in html
    assert "Enable Notifications" in html


def test_sqlite_records_the_switch_and_keeps_a_normal_observation(tmp_path):
    path = tmp_path / "observations.db"
    record_observation(
        {
            "timestamp": "2026-09-29T13:00:00+08:00",
            "stop_code": "08057",
            "service": "36",
            "direction": 1,
            "eta": "2026-09-29T13:10:00+08:00",
            "monitored": 1,
            "bus_lat": 1.1,
            "bus_lon": 103.1,
            "user_lat": 1.2,
            "user_lon": 103.2,
            "gps_accuracy": 8,
            "walk_metres": 40,
            "slack_seconds": 5,
            "p": 55,
            "p_low": 40,
            "p_high": 70,
            "data_quality": "live",
            "reroute_fired": 0,
            "reroute_reason": "",
        },
        path,
    )
    buses = [_primary(), _bus("NextBus2", 54, 80, 70)]
    decision = _decide(buses, db_path=path, write_observation=True)
    with sqlite3.connect(path) as connection:
        planned = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert planned == 1
    reason = decision["reroute"]["reroute_reason"]
    assert log_scored_poll(
        cache=_simple_cache(),
        current=_current(buses),
        bus=buses[0],
        user_lat=LAT,
        user_lon=LON,
        accuracy_m=12,
        now=NOW,
        reroute_fired=True,
        reroute_reason=reason,
        destination_stop_code=DEST,
        db_path=path,
    )
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = list(connection.execute("SELECT * FROM observations ORDER BY id"))
    assert len(rows) == 2
    assert rows[0]["stop_code"] == "08057"
    assert rows[0]["service"] == "36"
    assert rows[0]["p"] == 55
    assert rows[0]["reroute_fired"] == 0
    assert rows[0]["reroute_reason"] == ""
    assert rows[1]["reroute_fired"] == 1
    assert rows[1]["reroute_reason"] == reason
    assert rows[1]["stop_code"] == ORIGIN
    assert rows[1]["service"] == "18"
    assert rows[1]["p"] == 30
    assert rows[1]["p_low"] == 20
    assert rows[1]["p_high"] == 39
    assert rows[1]["data_quality"] == "live"
    assert rows[1]["direction"] == 1
    assert "sqlite" not in str(decision)


def _three_bus_payload(third: str = "2026-09-29T14:40:00+08:00") -> dict:
    return {
        "BusStopCode": ORIGIN,
        "Services": [
            {
                "ServiceNo": "18",
                "NextBus": {
                    "EstimatedArrival": "2026-09-29T14:05:00+08:00",
                    "Latitude": "1.3",
                    "Longitude": "103.8",
                    "Load": "SEA",
                    "Monitored": 1,
                },
                "NextBus2": {
                    "EstimatedArrival": "2026-09-29T14:20:00+08:00",
                    "Latitude": "1.31",
                    "Longitude": "103.81",
                    "Load": "SEA",
                    "Monitored": 1,
                },
                "NextBus3": {
                    "EstimatedArrival": third,
                    "Latitude": "1.32",
                    "Longitude": "103.82",
                    "Load": "SEA",
                    "Monitored": 1,
                },
            }
        ],
    }


def _fetch_three(payload: dict | None = None) -> dict:
    body = _three_bus_payload() if payload is None else payload

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return fetch_arrivals(
            ORIGIN,
            "18",
            client=client,
            account_key="test-account-key",
            now=NOW,
            user_lat=LAT,
            user_lon=LON,
            accuracy=10,
            cache=_simple_cache(),
        )


def test_raw_arrivals_stay_complete_for_step_6():
    scored = _fetch_three()
    assert [bus["position"] for bus in scored["buses"]] == ["NextBus", "NextBus2", "NextBus3"]
    assert scored["buses"][0]["is_primary"] is True
    assert scored["buses"][1]["is_primary"] is False
    assert "not_before" not in fetch_arrivals.__code__.co_varnames
    schema = app.openapi()["paths"]["/api/arrivals"]["get"]["parameters"]
    names = {item["name"] for item in schema}
    assert "not_before" not in names
    assert "pinned_eta" in names


def test_arrivals_endpoint_returns_the_reroute_without_a_live_call(tmp_path, monkeypatch):
    dest_lat, dest_lon = _north(2000)
    alt_lat, alt_lon = _north(150)
    cache = _cache(
        [
            _stop(ORIGIN, "Origin", LAT, LON),
            _stop("01022", "Next door", alt_lat, alt_lon),
            _stop(DEST, "Destination", dest_lat, dest_lon),
        ],
        [
            _hop("18", ORIGIN, 1, 0),
            _hop("18", "01022", 2, 0.4),
            _hop("18", DEST, 6, 2),
        ],
    )
    calls = []

    def fake(stop_code, service_no, **_kwargs):
        calls.append((stop_code, service_no))
        if stop_code == ORIGIN:
            buses = [_primary(), _bus("NextBus2", 41, 50, 45)]
        else:
            buses = [_bus("NextBus", 80, 90, 85, primary=True)]
        return _current(buses, service=service_no, stop=stop_code)

    monkeypatch.setattr("main.load_static_data", lambda: cache)
    monkeypatch.setattr("main.fetch_arrivals", fake)
    # The search fetches each stop once for all its services; the fake answers per service the same way.
    monkeypatch.setattr(
        "main.fetch_stop_arrivals",
        lambda stop_code, services, **_kwargs: {service: fake(stop_code, service) for service in services},
    )
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    with TestClient(app) as client:
        plain = client.get("/api/arrivals", params={"stop_code": ORIGIN, "service_no": "18"})
        response = client.get(
            "/api/arrivals",
            params={
                "stop_code": ORIGIN,
                "service_no": "18",
                "lat": LAT,
                "lon": LON,
                "accuracy": 12,
                "destination_stop_code": DEST,
                "dest_lat": dest_lat,
                "dest_lon": dest_lon,
            },
        )
    assert plain.status_code == 200
    assert "reroute" not in plain.json()
    assert "sqlite" not in plain.text
    assert response.status_code == 200
    assert "sqlite" not in response.text
    body = response.json()
    assert body["reroute"]["switched"] is True
    assert body["reroute"]["reroute"]["service_no"] == "18"
    assert body["reroute"]["reroute"]["stop"]["stop_code"] == "01022"
    assert body["reroute"]["reroute"]["destination_stop_code"] == DEST
    assert calls[0] == (ORIGIN, "18")
    assert ("01022", "18") in calls
    with sqlite3.connect(tmp_path / "observations.db") as connection:
        rows = list(
            connection.execute(
                "SELECT stop_code, reroute_fired, reroute_reason FROM observations ORDER BY id"
            )
        )
    fired = [row for row in rows if row[1] == 1]
    assert len(rows) == 3
    assert len(fired) == 1
    assert fired[0][0] == ORIGIN
    assert fired[0][2] == body["reroute"]["reroute"]["reroute_reason"]
    assert all(row[1] == 0 and row[2] == "" for row in rows if row is not fired[0])


def test_reroute_module_does_not_reimplement_the_catch_formula():
    source = REROUTE_SOURCE.read_text(encoding="utf-8")
    assert "import openai" not in source
    assert "OpenAI(" not in source
    assert "0.025" not in source
    assert "import onemap" not in source
    assert "search_destinations" not in source


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _shift_payload(first: str, second: str, third: str) -> dict:
    payload = _three_bus_payload(third)
    payload["Services"][0]["NextBus"]["EstimatedArrival"] = first
    payload["Services"][0]["NextBus2"]["EstimatedArrival"] = second
    return payload


def test_not_before_is_gone_from_the_implementation():
    root = INDEX.parent.parent
    for name in ("main.py", "arrivals.py", "reroute.py", "journey.py", "leave_now.py", "static/index.html"):
        text = (root / name).read_text(encoding="utf-8")
        assert "not_before" not in text
        assert "arrivalNotBefore" not in text


def test_pinned_eta_can_move_slots_and_the_raw_list_stays_intact():
    first = _fetch_three()
    pin = _epoch("2026-09-29T14:20:00+08:00")
    target, updated = resolve_pinned_target(first["buses"], pin, NOW)
    assert target["position"] == "NextBus2"
    assert updated == pin
    assert [bus["position"] for bus in first["buses"]] == ["NextBus", "NextBus2", "NextBus3"]
    assert first["buses"][0]["is_primary"] is True
    assert first["buses"][1]["is_primary"] is False

    moved = _fetch_three(
        _shift_payload(
            "2026-09-29T14:20:00+08:00",
            "2026-09-29T14:35:00+08:00",
            "2026-09-29T14:50:00+08:00",
        )
    )
    again, updated_again = resolve_pinned_target(moved["buses"], updated, NOW)
    assert again["position"] == "NextBus"
    assert updated_again == pin
    assert [bus["position"] for bus in moved["buses"]] == ["NextBus", "NextBus2", "NextBus3"]

    as_third = _fetch_three()
    third_pin = _epoch("2026-09-29T14:40:00+08:00")
    on_third, third_updated = resolve_pinned_target(as_third["buses"], third_pin, NOW)
    assert on_third["position"] == "NextBus3"
    as_second = _fetch_three(
        _shift_payload(
            "2026-09-29T14:10:00+08:00",
            "2026-09-29T14:40:00+08:00",
            "2026-09-29T14:55:00+08:00",
        )
    )
    on_second, _ = resolve_pinned_target(as_second["buses"], third_updated, NOW)
    assert on_second["position"] == "NextBus2"


def test_smallest_eta_difference_wins_and_180_seconds_is_the_window():
    pin = _epoch("2026-09-29T14:20:00+08:00")
    buses = [
        _bus("NextBus", 20, 30, 25, "2026-09-29T14:21:40+08:00", primary=True),
        _bus("NextBus2", 40, 50, 45, "2026-09-29T14:20:40+08:00"),
        _bus("NextBus3", 60, 70, 65, "2026-09-29T14:20:10+08:00"),
    ]
    target, updated = resolve_pinned_target(buses, pin, NOW)
    assert target["position"] == "NextBus3"
    assert updated == _epoch("2026-09-29T14:20:10+08:00")
    assert [bus["position"] for bus in buses] == ["NextBus", "NextBus2", "NextBus3"]

    edge = NOW + timedelta(minutes=10)
    edge_buses = [_bus("NextBus", 20, 30, 25, edge.isoformat(), primary=True)]
    matched, matched_epoch = resolve_pinned_target(
        edge_buses, edge.timestamp() - 180, NOW
    )
    assert matched is edge_buses[0]
    assert matched_epoch == edge.timestamp()
    assert resolve_pinned_target(edge_buses, edge.timestamp() - 181, NOW) == (None, None)


def test_overdue_pin_clears_before_matching_and_a_gap_is_not_missed():
    overdue = NOW - timedelta(seconds=31)
    nearby = NOW + timedelta(seconds=20)
    buses = [
        _bus("NextBus", 10, 20, 15, overdue.isoformat(), missed=True),
        _bus("NextBus2", 60, 80, 70, nearby.isoformat(), primary=True),
    ]
    assert resolve_pinned_target(buses, overdue.timestamp(), NOW) == (None, None)

    exact = NOW - timedelta(seconds=30)
    held = [_bus("NextBus", 60, 80, 70, exact.isoformat(), primary=True)]
    target, updated = resolve_pinned_target(held, exact.timestamp(), NOW)
    assert target is held[0]
    assert updated == exact.timestamp()

    future_pin = (NOW + timedelta(minutes=10)).timestamp()
    far = [_bus("NextBus", 60, 80, 70, (NOW + timedelta(minutes=10, seconds=181)).isoformat(), primary=True)]
    assert resolve_pinned_target(far, future_pin, NOW) == (None, None)


def test_cleared_pin_returns_to_step_6_leave_by():
    scored = _fetch_three()
    primary_leave = scored["leave_by"]
    primary_notice = scored["notification_time"]
    primary_point = scored["buses"][0]["probability"]["point"]
    target, _updated = resolve_pinned_target(
        scored["buses"], _epoch("2026-09-29T14:20:00+08:00"), NOW
    )
    cache = _simple_cache()
    apply_active_target(scored, target, user_lat=LAT, user_lon=LON, cache=cache, now=NOW)
    pinned_eta = datetime.fromisoformat("2026-09-29T14:20:00+08:00")
    assert scored["leave_by"] == leave_by_time(pinned_eta, 0).replace(microsecond=0).isoformat()
    assert scored["notification_time"] != primary_notice
    assert scored["buses"][0]["is_primary"] is True
    assert scored["buses"][1]["is_active_target"] is True
    assert scored["buses"][0]["probability"]["point"] == primary_point
    assert [bus["position"] for bus in scored["buses"]] == ["NextBus", "NextBus2", "NextBus3"]

    scored["leave_by"] = "1999-01-01T00:00:00+08:00"
    scored["notification_time"] = "1999-01-01T00:00:00+08:00"
    apply_active_target(scored, None, user_lat=LAT, user_lon=LON, cache=cache, now=NOW)
    assert scored["leave_by"] == primary_leave
    assert scored["notification_time"] == primary_notice
    assert "1999" not in scored["leave_by"]
    assert all("is_active_target" not in bus for bus in scored["buses"])
    assert scored["buses"][0]["is_primary"] is True


def test_scored_poll_logging_is_one_row_and_skips_a_poll_with_no_score(tmp_path):
    path = tmp_path / "observations.db"
    bus = _primary()
    assert log_scored_poll(
        cache=_simple_cache(),
        current=_current([bus]),
        bus=bus,
        user_lat=LAT,
        user_lon=LON,
        accuracy_m=12,
        now=NOW,
        reroute_fired=False,
        reroute_reason="",
        destination_stop_code=DEST,
        db_path=path,
    )
    assert log_scored_poll(
        cache=_simple_cache(),
        current=_current([]),
        bus={"position": "NextBus"},
        user_lat=LAT,
        user_lon=LON,
        accuracy_m=12,
        now=NOW,
        reroute_fired=False,
        reroute_reason="",
        db_path=path,
    ) is False
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = list(connection.execute("SELECT * FROM observations"))
    assert len(rows) == 1
    assert rows[0]["reroute_fired"] == 0
    assert rows[0]["reroute_reason"] == ""
    assert rows[0]["stop_code"] == ORIGIN
    assert rows[0]["service"] == "18"
    assert rows[0]["p"] == 30
    assert rows[0]["p_low"] == 20
    assert rows[0]["p_high"] == 39
    assert rows[0]["eta"] == "2026-09-29T14:08:00+08:00"
    assert rows[0]["monitored"] == 1
    assert rows[0]["gps_accuracy"] is None  # the position and its accuracy are not stored
    assert rows[0]["user_lat"] is None and rows[0]["user_lon"] is None


def test_unavailable_poll_does_not_write_a_scored_observation(tmp_path, monkeypatch):
    path = tmp_path / "observations.db"

    def fail(*_args, **_kwargs):
        raise ArrivalUnavailable("down")

    monkeypatch.setattr("main.load_static_data", lambda: _simple_cache())
    monkeypatch.setattr("main.fetch_arrivals", fail)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", path)
    with TestClient(app) as client:
        response = client.get("/api/arrivals", params={"stop_code": ORIGIN, "service_no": "18"})
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert not path.exists()


def test_endpoint_pin_keeps_the_raw_list_and_clears_outside_the_window(tmp_path, monkeypatch):
    moment = datetime.now(SGT).replace(microsecond=0)
    primary_eta = moment + timedelta(minutes=8)
    pinned_eta = moment + timedelta(minutes=20)
    later_eta = moment + timedelta(minutes=40)
    buses = [
        _bus("NextBus", 20, 39, 30, primary_eta.isoformat(), primary=True),
        _bus("NextBus2", 60, 80, 70, pinned_eta.isoformat()),
        _bus("NextBus3", 10, 20, 15, later_eta.isoformat()),
    ]

    def fake(stop_code, service_no, **_kwargs):
        return {
            "status": "ok",
            "stop_code": stop_code,
            "service_no": service_no,
            "fetched_at": moment.isoformat(),
            "buses": [dict(bus) for bus in buses],
            "leave_by": "1999-01-01T00:00:00+08:00",
            "notification_time": "1999-01-01T00:00:00+08:00",
            "leave_now": {"eligible": False},
        }

    monkeypatch.setattr("main.load_static_data", lambda: _simple_cache())
    monkeypatch.setattr("main.fetch_arrivals", fake)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    params = {"stop_code": ORIGIN, "service_no": "18", "lat": LAT, "lon": LON, "accuracy": 10}
    with TestClient(app) as client:
        kept = client.get("/api/arrivals", params={**params, "pinned_eta": pinned_eta.timestamp()})
        cleared = client.get(
            "/api/arrivals",
            params={**params, "pinned_eta": pinned_eta.timestamp() - 181},
        )
    body = kept.json()
    assert [bus["position"] for bus in body["buses"]] == ["NextBus", "NextBus2", "NextBus3"]
    assert body["buses"][0]["is_primary"] is True
    assert body["buses"][1]["is_active_target"] is True
    assert body["pinned_eta_timestamp"] == pinned_eta.timestamp()
    assert body["leave_by"] == leave_by_time(pinned_eta, 0).replace(microsecond=0).isoformat()
    assert "1999" not in body["leave_by"]
    gone = cleared.json()
    assert gone["pinned_eta_timestamp"] is None
    assert gone["leave_by"] == leave_by_time(primary_eta, 0).replace(microsecond=0).isoformat()
    assert "1999" not in gone["leave_by"]
    assert all("is_active_target" not in bus for bus in gone["buses"])
    assert [bus["position"] for bus in gone["buses"]] == ["NextBus", "NextBus2", "NextBus3"]

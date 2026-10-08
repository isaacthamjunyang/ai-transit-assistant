"""Deterministic catch-probability tests. No live API and no database."""

from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

import catch_heuristic
from catch_heuristic import (
    BOARDING_BUFFER_S,
    FALLBACK_HEADWAY_S,
    FAST_WALK_M_S,
    HISTORICAL_LATENESS_S,
    POINT_WALK_M_S,
    RELIABILITY_LABEL,
    SGT,
    SLOW_WALK_M_S,
    catch_probability,
    headway_seconds,
    high_slack,
    low_slack,
    parse_headway_seconds,
    effective_accuracy_m,
    is_location_uncertain,
    location_age_seconds,
    normalize_location_timestamp,
    point_slack,
    score_buses,
    straight_line_m,
    to_percent,
    walk_seconds,
)
from nearby import EARTH_RADIUS_M, haversine_m

NOW = datetime(2026, 9, 29, 14, 0, 0, tzinfo=SGT)


@pytest.fixture(autouse=True)
def _formula_only(monkeypatch):
    """These tests check the formula with the user standing at the stop (distance 0). The at-stop rule, which gives 97
    there, is off for them; it has its own tests in tests/test_at_stop.py."""
    monkeypatch.setattr(catch_heuristic, "AT_STOP_MAX_ACCURACY_M", -1)


def _service(direction: int, origin: str, destination: str, **freqs) -> dict:
    record = {
        "ServiceNo": "36",
        "Direction": direction,
        "OriginCode": origin,
        "DestinationCode": destination,
        "AM_Peak_Freq": "10-10",
        "AM_Offpeak_Freq": "20-20",
        "PM_Peak_Freq": "30-30",
        "PM_Offpeak_Freq": "40-40",
    }
    record.update(freqs)
    return record


def _routes(*directions: int) -> list[dict]:
    return [
        {
            "ServiceNo": "36",
            "Direction": direction,
            "StopSequence": 1,
            "BusStopCode": "08057",
            "Distance": 0,
        }
        for direction in directions
    ]


def _bus(minutes: int, monitored: bool = True, origin: str | None = None, destination: str | None = None) -> dict:
    arrival = NOW + timedelta(minutes=minutes)
    return {
        "position": "NextBus",
        "arrival_time": arrival.replace(microsecond=0).isoformat(),
        "monitored": monitored,
        "latitude": None,
        "longitude": None,
        "origin_code": origin,
        "destination_code": destination,
    }


def _score(
    buses,
    *,
    accuracy=10,
    services=None,
    routes=None,
    minutes_offset=0,
    location_timestamp=None,
    **extra,
):
    return score_buses(
        buses,
        user_lat=1.3,
        user_lon=103.8,
        accuracy_m=accuracy,
        stop_lat=extra.get("stop_lat", 1.3),
        stop_lon=extra.get("stop_lon", 103.8),
        services=[] if services is None else services,
        routes=[] if routes is None else routes,
        service_no="36",
        stop_code="08057",
        now=NOW + timedelta(minutes=minutes_offset),
        location_timestamp=location_timestamp,
    )


def test_haversine_matches_the_nearby_straight_line():
    assert straight_line_m(1.3, 103.8, 1.3, 103.8) == 0
    assert straight_line_m(1.3, 103.8, 2.3, 103.8) == pytest.approx(
        haversine_m(1.3, 103.8, 2.3, 103.8)
    )
    assert straight_line_m(1.3, 103.8, 2.3, 103.8) == pytest.approx(
        EARTH_RADIUS_M * 3.141592653589793 / 180, rel=1e-6
    )


def test_walk_times_use_the_three_speeds():
    assert walk_seconds(125, POINT_WALK_M_S) == pytest.approx(100)
    assert walk_seconds(110, SLOW_WALK_M_S) == pytest.approx(100)
    assert walk_seconds(140, FAST_WALK_M_S) == pytest.approx(100)
    assert POINT_WALK_M_S == 1.25
    assert SLOW_WALK_M_S == 1.1
    assert FAST_WALK_M_S == 1.4


def test_slack_includes_the_45_second_buffer_and_gps_terms():
    assert BOARDING_BUFFER_S == 45
    seconds_until = 400
    distance = 125
    accuracy = 12.5
    assert point_slack(seconds_until, distance) == pytest.approx(
        seconds_until - (distance / 1.25) - 45
    )
    assert low_slack(seconds_until, distance, accuracy) == pytest.approx(
        seconds_until - (distance / 1.1) - 45 - (accuracy / 1.25)
    )
    assert high_slack(seconds_until, distance) == pytest.approx(
        seconds_until - (distance / 1.4) - 45
    )
    assert HISTORICAL_LATENESS_S == 0


def test_sigmoid_floor_ceiling_and_rounding():
    assert to_percent(catch_probability(90)) == 50
    assert to_percent(catch_probability(-10_000)) == 5
    assert to_percent(catch_probability(10_000)) == 92
    assert catch_probability(-10_000) == pytest.approx(0.05)
    assert catch_probability(10_000) == pytest.approx(0.92)
    assert to_percent(0.638) == 64
    assert to_percent(0.634) == 63
    assert to_percent(catch_probability(200)) > to_percent(catch_probability(90))


def test_gps_worse_than_100_metres_widens_only_the_low_end():
    bus = [_bus(8)]
    tight = _score(bus, accuracy=20, stop_lat=1.301, stop_lon=103.801)[0]
    wide = _score(bus, accuracy=180, stop_lat=1.301, stop_lon=103.801)[0]
    assert wide["probability"]["point"] == tight["probability"]["point"]
    assert wide["probability"]["range_low"] < tight["probability"]["range_low"]
    assert wide["probability"]["data_quality"] == "location uncertain"
    assert tight["probability"]["data_quality"] == "live"
    same = _score(bus, accuracy=100)[0]
    assert same["probability"]["data_quality"] == "live"


def test_headway_parse_and_fallbacks():
    assert parse_headway_seconds("12-15") == 810
    assert parse_headway_seconds("12–15") == 810
    assert parse_headway_seconds("often") is None
    assert parse_headway_seconds("") is None
    services = [_service(1, "A", "B", AM_Offpeak_Freq="often")]
    assert (
        headway_seconds(services, _routes(1), "36", "08057", None, None, NOW)
        == FALLBACK_HEADWAY_S
    )
    assert headway_seconds([], [], "36", "08057", None, None, NOW) == 720


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        (datetime(2026, 9, 29, 0, 0, tzinfo=SGT), 720),
        (datetime(2026, 9, 29, 6, 29, tzinfo=SGT), 720),
        (datetime(2026, 9, 29, 6, 30, tzinfo=SGT), 600),
        (datetime(2026, 9, 29, 8, 30, tzinfo=SGT), 600),
        (datetime(2026, 9, 29, 8, 31, tzinfo=SGT), 1200),
        (datetime(2026, 9, 29, 16, 59, tzinfo=SGT), 1200),
        (datetime(2026, 9, 29, 17, 0, tzinfo=SGT), 1800),
        (datetime(2026, 9, 29, 19, 0, tzinfo=SGT), 1800),
        (datetime(2026, 9, 29, 19, 1, tzinfo=SGT), 2400),
        (datetime(2026, 9, 29, 23, 59, tzinfo=SGT), 2400),
    ],
)
def test_frequency_window_uses_singapore_time(clock, expected):
    services = [_service(1, "A", "B")]
    assert headway_seconds(services, _routes(1), "36", "08057", "A", "B", clock) == expected


def test_direction_selects_the_matching_service_record():
    services = [
        _service(1, "A", "B", AM_Offpeak_Freq="10-10"),
        _service(2, "C", "D", AM_Offpeak_Freq="2-2"),
    ]
    matched = headway_seconds(services, _routes(1, 2), "36", "08057", "C", "D", NOW)
    assert matched == 120
    first = headway_seconds(services, _routes(1, 2), "36", "08057", None, None, NOW)
    assert first == 600


def test_schedule_only_lowers_the_bad_side_and_caps_at_60():
    services = [_service(1, "A", "B", AM_Offpeak_Freq="2-2")]
    soon = {
        "position": "NextBus",
        "arrival_time": (NOW + timedelta(seconds=135)).isoformat(),
        "monitored": True,
        "origin_code": "A",
        "destination_code": "B",
    }
    soon_schedule = dict(soon, monitored=False)
    live = _score([soon], services=services, routes=_routes(1))[0]
    schedule = _score([soon_schedule], services=services, routes=_routes(1))[0]
    assert live["probability"]["point"] == schedule["probability"]["point"]
    assert schedule["probability"]["range_low"] < live["probability"]["range_low"]
    assert schedule["probability"]["data_quality"] == "schedule"
    assert schedule["probability"]["reliability_label"] == RELIABILITY_LABEL
    distant = _score(
        [_bus(40, False, "A", "B")], services=services, routes=_routes(1)
    )[0]
    assert distant["probability"]["point"] <= 60
    assert distant["probability"]["range_low"] <= 60
    assert distant["probability"]["range_high"] <= 60


def test_missed_bus_has_no_probability_and_the_next_bus_is_primary():
    late = NOW - timedelta(seconds=31)
    exact = NOW - timedelta(seconds=30)
    later = NOW + timedelta(minutes=10)
    buses = [
        {
            "position": "NextBus",
            "arrival_time": late.replace(microsecond=0).isoformat(),
            "monitored": True,
            "origin_code": None,
            "destination_code": None,
        },
        {
            "position": "NextBus2",
            "arrival_time": exact.replace(microsecond=0).isoformat(),
            "monitored": True,
            "origin_code": None,
            "destination_code": None,
        },
        {
            "position": "NextBus3",
            "arrival_time": later.replace(microsecond=0).isoformat(),
            "monitored": False,
            "origin_code": None,
            "destination_code": None,
        },
    ]
    scored = _score(buses)
    assert [bus["position"] for bus in scored] == ["NextBus", "NextBus2", "NextBus3"]
    assert scored[0]["is_missed"] is True
    assert scored[0]["probability"] is None
    assert scored[0]["is_primary"] is False
    assert scored[1]["is_missed"] is False
    assert scored[1]["is_primary"] is True
    assert scored[1]["probability"]["point"] != scored[2]["probability"]["point"]
    assert "origin_code" not in scored[0]


def test_missing_location_leaves_probability_null():
    scored = score_buses(
        [_bus(5), _bus(12)],
        user_lat=None,
        user_lon=1.3,
        accuracy_m=10,
        stop_lat=1.3,
        stop_lon=103.8,
        services=[],
        routes=[],
        service_no="36",
        stop_code="08057",
        now=NOW,
    )
    assert scored[0]["probability"] is None
    assert scored[0]["is_missed"] is False
    assert scored[0]["is_primary"] is True
    assert scored[1]["probability"] is None


def test_location_fix_age_marks_uncertainty_without_a_new_penalty():
    bus = [_bus(4)]
    place = {"stop_lat": 1.301, "stop_lon": 103.801}
    fresh_stamp = NOW.timestamp() - 30
    boundary_stamp = NOW.timestamp() - 60
    old_stamp = NOW.timestamp() - 61
    fresh = _score(bus, accuracy=20, location_timestamp=fresh_stamp, **place)[0]["probability"]
    boundary = _score(bus, accuracy=20, location_timestamp=boundary_stamp, **place)[0]["probability"]
    old = _score(bus, accuracy=20, location_timestamp=old_stamp, **place)[0]["probability"]
    exact_accuracy = _score(bus, accuracy=100, location_timestamp=fresh_stamp, **place)[0]["probability"]
    poor = _score(bus, accuracy=180, location_timestamp=fresh_stamp, **place)[0]["probability"]
    both = _score(bus, accuracy=180, location_timestamp=old_stamp, **place)[0]["probability"]
    omitted = _score(bus, accuracy=20, **place)[0]["probability"]

    assert fresh["data_quality"] == "live"
    assert boundary["data_quality"] == "live"
    assert exact_accuracy["data_quality"] == "live"
    assert old["data_quality"] == "location uncertain"
    assert poor["data_quality"] == "location uncertain"
    assert both["data_quality"] == "location uncertain"
    assert omitted["data_quality"] == "live"

    assert old["point"] == fresh["point"] == omitted["point"]
    assert old["range_low"] < fresh["range_low"]
    assert omitted["range_low"] == fresh["range_low"]
    assert boundary["range_low"] == fresh["range_low"]
    assert old["range_high"] == fresh["range_high"] == boundary["range_high"]
    assert poor["point"] == fresh["point"]
    assert poor["range_low"] < fresh["range_low"]
    assert both["point"] == poor["point"]
    assert both["range_high"] == poor["range_high"]
    assert both["range_low"] <= poor["range_low"]
    assert is_location_uncertain(20, 60) is False
    assert is_location_uncertain(100, 30) is False
    assert is_location_uncertain(20, 60.1) is True
    assert is_location_uncertain(100.1, 10) is True


def test_effective_accuracy_widens_only_the_low_end_after_60_seconds():
    assert effective_accuracy_m(18, 30) == pytest.approx(18)
    assert effective_accuracy_m(18, 60) == pytest.approx(18)
    assert effective_accuracy_m(18, None) == pytest.approx(18)
    assert effective_accuracy_m(18, 61) == pytest.approx(100 + 1.25 * (61 - 60))
    assert effective_accuracy_m(18, 60.1) == pytest.approx(100 + 1.25 * 0.1)
    assert effective_accuracy_m(18, 70) == pytest.approx(112.5)
    assert effective_accuracy_m(150, 30) == pytest.approx(150)
    assert effective_accuracy_m(150, 70) == pytest.approx(162.5)
    assert effective_accuracy_m(180, 70) == pytest.approx(180 + 1.25 * 10)

    bus = [_bus(4)]
    place = {"stop_lat": 1.301, "stop_lon": 103.801}
    fresh = _score(bus, accuracy=18, location_timestamp=NOW.timestamp() - 30, **place)[0]
    boundary = _score(bus, accuracy=18, location_timestamp=NOW.timestamp() - 60, **place)[0]
    old = _score(bus, accuracy=18, location_timestamp=NOW.timestamp() - 70, **place)[0]
    near = [_bus(4)]
    poor_fresh = _score(near, accuracy=150, location_timestamp=NOW.timestamp() - 30)[0]
    poor_old = _score(near, accuracy=150, location_timestamp=NOW.timestamp() - 70)[0]
    assert boundary["probability"]["range_low"] == fresh["probability"]["range_low"]
    assert boundary["probability"]["data_quality"] == "live"
    assert old["probability"]["point"] == fresh["probability"]["point"]
    assert old["probability"]["range_high"] == fresh["probability"]["range_high"]
    assert old["probability"]["range_low"] < fresh["probability"]["range_low"]
    assert old["probability"]["data_quality"] == "location uncertain"
    assert poor_fresh["probability"]["data_quality"] == "location uncertain"
    assert poor_fresh["probability"]["point"] == poor_old["probability"]["point"]
    assert poor_fresh["probability"]["range_high"] == poor_old["probability"]["range_high"]
    assert poor_old["probability"]["range_low"] < poor_fresh["probability"]["range_low"]
    distance = straight_line_m(1.3, 103.8, 1.301, 103.801)
    seconds_until = 8 * 60
    assert low_slack(seconds_until, distance, effective_accuracy_m(18, 70)) == pytest.approx(
        seconds_until - (distance / 1.1) - 45 - (112.5 / 1.25)
    )
    assert high_slack(seconds_until, distance) == pytest.approx(
        seconds_until - (distance / 1.4) - 45
    )


def test_location_timestamp_units_and_injected_clock():
    epoch = NOW.timestamp()
    assert normalize_location_timestamp(epoch - 61) == pytest.approx(epoch - 61)
    assert normalize_location_timestamp((epoch - 61) * 1000) == pytest.approx(epoch - 61)
    assert normalize_location_timestamp(1e11) == pytest.approx(1e11)
    assert location_age_seconds(epoch - 61, NOW) == pytest.approx(61)
    assert location_age_seconds((epoch - 61) * 1000, NOW) == pytest.approx(61)
    assert location_age_seconds(epoch, NOW + timedelta(seconds=75)) == pytest.approx(75)
    assert location_age_seconds(epoch + 40, NOW) == 0.0
    seconds = _score([_bus(8)], accuracy=10, location_timestamp=epoch - 61)[0]
    millis = _score([_bus(8)], accuracy=10, location_timestamp=(epoch - 61) * 1000)[0]
    assert seconds["probability"]["data_quality"] == "location uncertain"
    assert millis["probability"]["point"] == seconds["probability"]["point"]
    assert millis["probability"]["range_low"] == seconds["probability"]["range_low"]


@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), float("-inf"), -1, -0.01, "1700000000", True],
)
def test_invalid_location_timestamp_is_rejected(bad):
    with pytest.raises(ValueError):
        normalize_location_timestamp(bad)
    with pytest.raises(ValueError):
        location_age_seconds(bad, NOW)
    with pytest.raises(ValueError):
        _score([_bus(8)], location_timestamp=bad)


def test_scoring_does_not_call_http_or_sqlite(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network was used")

    monkeypatch.setattr(httpx, "get", explode)
    monkeypatch.setattr(httpx, "Client", explode)
    _score([_bus(6)])
    source = Path(catch_heuristic.__file__).read_text(encoding="utf-8").lower()
    assert "sqlite" not in source
    assert "openai" not in source

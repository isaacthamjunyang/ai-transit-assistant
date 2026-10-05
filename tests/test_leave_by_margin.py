"""leave_by = bus ETA - walk time - LEAVE_MARGIN_SECONDS, one function for every place that shows it."""

from datetime import datetime, timedelta, timezone

import pytest

import config
import reroute
from catch_heuristic import catch_probability, point_slack, score_buses, straight_line_m, to_percent
from journey import leave_by_time, parse_journey_time, resolve_leave_by
from leave_now import LEAVE_NOW_MARGIN_S, notification_time_from_leave_by

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 5, 22, 0, tzinfo=SGT)
DISTANCES = (100, 300, 600, 900)
SPEEDS = (1.0, 1.25, 1.4)
ETAS = (3, 8, 15)


def test_the_margin_is_135_seconds():
    assert config.LEAVE_MARGIN_SECONDS == 135


@pytest.mark.parametrize("distance", DISTANCES)
@pytest.mark.parametrize("speed", SPEEDS)
@pytest.mark.parametrize("eta_minutes", ETAS)
def test_leave_by_grid_is_eta_minus_raw_walk_seconds_minus_135(distance, speed, eta_minutes):
    eta = NOW + timedelta(minutes=eta_minutes)
    expected = eta - timedelta(seconds=distance / speed + 135)
    assert leave_by_time(eta, distance, speed) == expected
    assert resolve_leave_by(eta=eta, distance_m=distance, arrival_status="ok", now=NOW, walk_speed_m_s=speed) == expected
    assert reroute._leave_by_iso(eta, distance, speed) == expected.replace(microsecond=0).isoformat()


def test_the_four_places_share_one_function():
    import inspect
    import journey
    assert "leave_by_time(" in inspect.getsource(journey.resolve_leave_by)
    assert "leave_by_time(" in inspect.getsource(reroute._leave_by_iso)
    assert "range_speeds" not in inspect.getsource(journey.resolve_leave_by)
    assert "range_speeds" not in inspect.getsource(reroute._leave_by_iso)
    assert "slow" not in inspect.getsource(journey.leave_by_time)


@pytest.mark.parametrize("margin, percent", [(0, 5), (45, 10), (90, 25), (135, 50), (180, 75), (240, 92)])
def test_catch_probability_at_leave_by_for_each_margin(margin, percent):
    walk = 300 / 1.25
    seconds_until_eta = walk + margin  # now = leave_by when the margin is LEAVE_MARGIN_SECONDS
    assert to_percent(catch_probability(point_slack(seconds_until_eta, 300, 1.25))) == percent


def test_the_app_itself_scores_50_percent_at_leave_by_and_about_82_a_minute_earlier():
    stop_lat, stop_lon = 1.3000, 103.8000
    user_lat, user_lon = 1.3000 + 300 / 111_195, 103.8000
    distance = straight_line_m(user_lat, user_lon, stop_lat, stop_lon)
    eta = NOW + timedelta(minutes=10)
    leave_by = leave_by_time(eta, distance, 1.25)
    points = {}
    for label, moment in (("at", leave_by), ("before", leave_by - timedelta(seconds=60))):
        bus = {"arrival_time": eta.isoformat(), "monitored": True}
        scored = score_buses(
            [bus], user_lat=user_lat, user_lon=user_lon, accuracy_m=10, stop_lat=stop_lat, stop_lon=stop_lon,
            services=[], routes=[], service_no="36", stop_code="01011", now=moment, walk_speed_m_s=1.25,
        )
        points[label] = scored[0]["probability"]["point"]
    assert points["at"] == 50
    assert points["before"] == 82


@pytest.mark.parametrize("distance, earlier_s", [(300, 57.3), (600, 24.5), (900, -8.2)])
def test_alert_timing_against_the_old_slow_end_rule(distance, earlier_s):
    eta = NOW + timedelta(minutes=15)
    old = eta - timedelta(seconds=distance / 1.1 + 45)
    new = leave_by_time(eta, distance, 1.25)
    assert (old - new).total_seconds() == pytest.approx(earlier_s, abs=0.1)
    assert notification_time_from_leave_by(new) == new - timedelta(seconds=LEAVE_NOW_MARGIN_S)

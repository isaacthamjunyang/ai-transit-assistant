"""Arrival range, spare minutes, a missed bus, and the planning warning."""

import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from explain import GUARANTEE_PHRASES
from journey import (
    COMPARISON_NOTE,
    COMPARISON_UNAVAILABLE,
    LATE_LABEL,
    ON_TRACK_LABEL,
    RIDE_TOLERANCE,
    arrival_window,
    build_journey,
    miss_line,
    past_arrive_by,
    planning_warning,
    resolve_arrive_chip,
    show_if_you_miss,
)
from lta_static import StopAndRouteCache

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
USER = (1.3, 103.8)
PLACE = (1.32, 103.8)
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
COPY = ROOT / "static" / "copy.js"


def _stop(code, lat, lon, name):
    return {
        "BusStopCode": code,
        "Description": name,
        "RoadName": "Orchard Rd",
        "Latitude": lat,
        "Longitude": lon,
    }


def _route(service, sequence, code, distance):
    return {
        "ServiceNo": service,
        "Direction": 1,
        "StopSequence": sequence,
        "BusStopCode": code,
        "Distance": distance,
    }


def _service(service, freq):
    return {
        "ServiceNo": service,
        "Direction": 1,
        "OriginCode": "A",
        "DestinationCode": "Z",
        "AM_Peak_Freq": freq,
        "AM_Offpeak_Freq": freq,
        "PM_Peak_Freq": freq,
        "PM_Offpeak_Freq": freq,
    }


def _usable_cache():
    return StopAndRouteCache(
        [_stop("B", *USER, "Boarding"), _stop("D", *PLACE, "Dest")],
        [_route("36", 1, "B", 1.0), _route("36", 4, "D", 3.5)],
        [_service("36", "10-10")],
    )


def _null_ride_cache():
    return StopAndRouteCache(
        [_stop("B", *USER, "Boarding"), _stop("D", *PLACE, "Dest")],
        [_route("36", 1, "B", 2.0), _route("36", 4, "D", 0.4)],
        [_service("36", "10-10")],
    )


def _journey(cache, **kwargs):
    values = {"boarding_stop_code": "B", "service_no": "36", "now": NOW}
    values.update(kwargs)
    return build_journey(cache, PLACE[0], PLACE[1], USER[0], USER[1], "D", **values)


def _window(**kwargs):
    values = {
        "board_walk_minutes": 0,
        "wait_minutes": 0,
        "ride_minutes": 100,
        "end_walk_metres": 0,
        "basis": "planned",
    }
    values.update(kwargs)
    return arrival_window(NOW, **values)


def test_ride_tolerance_is_the_named_range_factor():
    assert RIDE_TOLERANCE == 0.15
    window = _window()
    assert window["point_minutes"] == 100
    assert window["arrival_low"] == NOW + timedelta(minutes=85)
    assert window["arrival_high"] == NOW + timedelta(minutes=115)
    walked = _window(ride_minutes=10, end_walk_metres=840)
    assert walked["point_minutes"] == math.ceil(10 + 840 / 1.25 / 60)
    assert walked["arrival_low"] == NOW + timedelta(minutes=math.ceil(10 * 0.85 + 840 / 1.4 / 60))
    assert walked["arrival_high"] == NOW + timedelta(minutes=math.ceil(10 * 1.15 + 840 / 1.1 / 60))
    assert walked["arrival_low"] <= walked["estimated_arrival"] <= walked["arrival_high"]


def test_spare_sign_matches_the_existing_status():
    body = _journey(_usable_cache(), arrive_by=NOW + timedelta(minutes=10))
    minutes = body["ride_minutes"]
    late = _journey(_usable_cache(), arrive_by=NOW + timedelta(minutes=minutes) - timedelta(seconds=1))
    assert late["spare_minutes"] < 0
    assert late["comparison_label"] == LATE_LABEL
    assert late["arrival_point"] == late["estimated_arrival"]
    same = _journey(_usable_cache(), arrive_by=NOW + timedelta(minutes=minutes))
    assert same["spare_minutes"] == 0
    assert same["comparison_label"] == ON_TRACK_LABEL
    early = _journey(_usable_cache(), arrive_by=NOW + timedelta(minutes=minutes + 6))
    assert early["spare_minutes"] == 6
    assert early["comparison_label"] == ON_TRACK_LABEL
    assert early["arrival_low"] <= early["arrival_point"] <= early["arrival_high"]


def test_blank_target_keeps_the_estimate_and_skips_spare_and_status():
    blank = _journey(_usable_cache())
    assert blank["comparison_label"] == ""
    assert blank["comparison_note"] == ""
    assert blank["estimated_arrival"] is None
    assert blank["arrival_point"] is not None
    assert blank["spare_minutes"] is None


def test_null_ride_has_no_estimate_and_keeps_the_na_note():
    assert _window(ride_minutes=None) is None
    body = _journey(_null_ride_cache(), arrive_by=NOW + timedelta(minutes=5))
    assert body["ride_minutes"] is None
    assert body["arrival_point"] is None
    assert body["spare_minutes"] is None
    assert body["comparison_label"] == COMPARISON_UNAVAILABLE
    assert body["comparison_note"] == COMPARISON_NOTE


def test_transfer_uses_both_legs_and_a_null_leg_stays_na():
    both = build_journey(
        _usable_cache(),
        PLACE[0],
        PLACE[1],
        USER[0],
        USER[1],
        "D",
        boarding_stop_code="B",
        service_no="36",
        arrive_by=NOW + timedelta(hours=2),
        now=NOW,
        transfer=True,
        leg1_ride_minutes=4,
        leg2_ride_minutes=6,
        leg1_service_no="36",
        leg1_direction=1,
    )
    assert both["ride_minutes"] is not None
    assert both["arrival_point"] == both["estimated_arrival"]
    assert both["spare_minutes"] > 0
    assert both["comparison_label"] == ON_TRACK_LABEL
    assert both["arrival_low"] <= both["arrival_point"] <= both["arrival_high"]
    missing = build_journey(
        _usable_cache(),
        PLACE[0],
        PLACE[1],
        USER[0],
        USER[1],
        "D",
        boarding_stop_code="B",
        service_no="36",
        arrive_by=NOW + timedelta(hours=2),
        now=NOW,
        transfer=True,
        leg1_ride_minutes=4,
        leg2_ride_minutes=None,
        leg1_service_no="36",
        leg1_direction=1,
    )
    assert missing["ride_minutes"] is None
    assert missing["arrival_point"] is None
    assert missing["comparison_label"] == COMPARISON_UNAVAILABLE
    assert missing["comparison_note"] == COMPARISON_NOTE


def test_if_you_miss_follows_each_live_condition():
    shown = {
        "status": "ok",
        "stale": False,
        "schedule_only": False,
        "arrival_count": 2,
        "on_board": False,
    }
    assert show_if_you_miss(**shown) is True
    for key, value in (
        ("on_board", True),
        ("stale", True),
        ("schedule_only", True),
        ("status", "unavailable"),
        ("arrival_count", 1),
    ):
        hidden = dict(shown)
        hidden[key] = value
        assert show_if_you_miss(**hidden) is False
    # the page no longer draws the line (the server still works the data out)
    script = INDEX.read_text(encoding="utf-8")
    assert "function showMiss(" not in script and "function renderMiss(" not in script
    assert 'id="if-you-miss"' not in script


def test_miss_line_uses_the_second_arrival_and_omits_a_null_ride():
    buses = [
        {"arrival_time": (NOW + timedelta(minutes=4)).isoformat()},
        {"arrival_time": (NOW + timedelta(minutes=12)).isoformat(), "monitored": True},
    ]
    waiting = miss_line(
        NOW,
        "36",
        buses,
        {
            "board_walk_minutes": 0,
            "wait_minutes": 5,
            "ride_minutes": None,
            "end_walk_metres": 0,
        },
        NOW + timedelta(hours=1),
    )
    assert waiting["service_no"] == "36"
    assert waiting["in_minutes"] == 12
    assert waiting["estimated_arrival"] is None
    caught = miss_line(
        NOW,
        "36",
        buses,
        {
            "board_walk_minutes": 0,
            "wait_minutes": 5,
            "ride_minutes": 10,
            "end_walk_metres": 0,
        },
        NOW + timedelta(minutes=20),
    )
    assert caught["estimated_arrival"] is not None
    assert caught["spare_minutes"] < 0
    assert caught["basis"] == "live"
    assert miss_line(NOW, "36", buses[:1], None, None) is None
    # A schedule-only later arrival is not anchored: it keeps the planned basis (half the headway as the wait).
    scheduled = [buses[0], {"arrival_time": (NOW + timedelta(minutes=12)).isoformat(), "monitored": False}]
    planned = miss_line(
        NOW, "36", scheduled,
        {"board_walk_minutes": 0, "wait_minutes": 5, "ride_minutes": 10, "end_walk_metres": 0},
        NOW + timedelta(minutes=20),
    )
    assert planned["basis"] == "planned" and planned["spare_minutes"] >= 0


def test_planning_warning_only_when_every_option_is_late():
    target = NOW + timedelta(minutes=30)
    late = planning_warning(NOW, target, [41, 50])
    assert late["earliest_arrival"] == (NOW + timedelta(minutes=41)).isoformat()
    assert late["target"] == target.replace(microsecond=0).isoformat()
    assert planning_warning(NOW, target, [20, 41]) is None
    assert planning_warning(NOW, target, [30]) is None
    assert planning_warning(NOW, target, []) is None
    assert planning_warning(NOW, None, [41]) is None
    assert planning_warning(NOW, target, [None, float("nan")]) is None


def test_chip_resolution_rounds_up_to_five_minutes_including_past_midnight():
    assert resolve_arrive_chip(datetime(2026, 9, 29, 14, 7, 12, tzinfo=SGT), 30) == datetime(
        2026, 9, 29, 14, 40, tzinfo=SGT
    )
    assert resolve_arrive_chip(datetime(2026, 9, 29, 14, 0, tzinfo=SGT), 30) == datetime(
        2026, 9, 29, 14, 30, tzinfo=SGT
    )
    assert resolve_arrive_chip(datetime(2026, 9, 29, 23, 42, tzinfo=SGT), 30) == datetime(
        2026, 9, 30, 0, 15, tzinfo=SGT
    )
    assert resolve_arrive_chip(datetime(2026, 9, 29, 23, 40, tzinfo=SGT), 30) == datetime(
        2026, 9, 30, 0, 10, tzinfo=SGT
    )


def test_a_custom_time_earlier_than_now_is_rejected():
    assert past_arrive_by(NOW, NOW - timedelta(minutes=1)) is True
    assert past_arrive_by(NOW, NOW) is False
    assert past_arrive_by(NOW, NOW + timedelta(minutes=5)) is False


def test_new_arrive_by_strings_avoid_guaranteed_arrival_wording():
    copy = COPY.read_text(encoding="utf-8")
    block = copy.split("arriveBy: {", 1)[1].split("noRoute:", 1)[0]
    html = INDEX.read_text(encoding="utf-8")
    assert "latePhrase" not in html
    combined = block.lower()
    for banned in GUARANTEE_PHRASES:
        assert banned not in combined
    assert "That time has already passed today. Choose Tomorrow or a later time." in html
    assert "If you miss it" not in html  # the miss row is gone from Page A
    assert "Change time" in html
    assert re.search(r"In 30 min", html)

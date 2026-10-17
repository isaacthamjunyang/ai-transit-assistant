"""At the stop: under 30 m from the boarding stop, a fix of 30 m or better no older than 60 s, live data.

The probability is AT_STOP_PROBABILITY (97) with the same number as both ends of the range and the action is wait. One
function (catch_heuristic.score_buses) decides it for the poll, the rescore, /api/journey and the reroute rows.
"""

import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import catch_heuristic
import demo
from catch_heuristic import score_buses
from config import AT_STOP_MAX_ACCURACY_M, AT_STOP_PROBABILITY
from leave_now import leave_now_notice
from nearby import EARTH_RADIUS_M, haversine_m
from pace import is_near_stop
from test_reroute import _bus, _decide, _primary
from test_rescore import PARAMS, _north, _poll, _rescore, client, lta  # noqa: F401  (fixtures)

import math

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 8, 15, 55, 0, tzinfo=SGT)
LAT, LON = 1.3, 103.8
ROOT = Path(__file__).resolve().parents[1]


def _bus_in(seconds, monitored=True):
    arrival = NOW + timedelta(seconds=seconds)
    return {"position": "NextBus", "arrival_time": arrival.replace(microsecond=0).isoformat(), "monitored": monitored,
            "latitude": None, "longitude": None, "origin_code": None, "destination_code": None}


def _score(metres, *, accuracy=8, age=None, seconds=240, monitored=True):
    lat = LAT + math.degrees(metres / EARTH_RADIUS_M)
    return score_buses(
        [_bus_in(seconds, monitored)], user_lat=lat, user_lon=LON, accuracy_m=accuracy, stop_lat=LAT, stop_lon=LON,
        services=[], routes=[], service_no="36", stop_code="08057", now=NOW,
        location_timestamp=None if age is None else NOW.timestamp() - age,
    )[0]


# ---- the numbers

def test_at_the_stop_the_probability_is_97_with_the_same_range_and_nothing_else_changes_it():
    chance = _score(10)["probability"]
    assert AT_STOP_PROBABILITY == 97 and AT_STOP_MAX_ACCURACY_M == 30
    assert (chance["point"], chance["range_low"], chance["range_high"]) == (97, 97, 97)
    assert chance["at_stop"] is True and chance["band"] == "ok" and chance["data_quality"] == "live"
    assert chance["location_reason"] is None and chance["pace"] is None
    assert chance["slack_seconds"] == 240  # no walk time and no 45 s buffer: the seconds until the bus


def test_no_walk_time_and_no_buffer_even_when_the_bus_is_a_minute_away():
    assert _score(10, seconds=60)["probability"]["point"] == 97 and _score(10, seconds=0)["probability"]["point"] == 97


def test_elsewhere_the_cap_is_still_92_and_at_stop_is_false():
    for metres in (31, 60, 150, 600):
        chance = _score(metres)["probability"]
        assert chance["at_stop"] is False and chance["point"] <= 92 and chance["range_high"] <= 92


# ---- the 30 m boundary: strictly under 30 m, the pace.is_near_stop rule

@pytest.mark.parametrize("metres, expected", [(0, True), (29, True), (29.9, True), (30.1, False), (31, False), (60, False)])
def test_the_30_m_boundary(metres, expected):
    assert haversine_m(LAT + math.degrees(metres / EARTH_RADIUS_M), LON, LAT, LON) == pytest.approx(metres, abs=0.01)
    assert _score(metres)["probability"]["at_stop"] is expected


def test_exactly_30_m_is_not_at_the_stop_and_the_rule_is_the_one_pace_function():
    assert is_near_stop(29.999) is True and is_near_stop(30) is False and is_near_stop(30.001) is False
    source = inspect.getsource(score_buses)
    assert "is_near_stop(distance_m)" in source  # not a second copy of the 30


# ---- the fix: 30 m accuracy or better, 60 s or younger

@pytest.mark.parametrize("accuracy, expected", [(5, True), (30, True), (30.5, False), (31, False), (100, False), (101, False)])
def test_the_accuracy_limit_is_30_m(accuracy, expected):
    chance = _score(10, accuracy=accuracy)["probability"]
    assert chance["at_stop"] is expected
    if not expected:
        assert chance["point"] != 97  # the normal formula applies
    assert (chance["data_quality"] == "location uncertain") is (accuracy > 100)


@pytest.mark.parametrize("age, expected", [(0, True), (59, True), (60, True), (61, False), (300, False), (None, True)])
def test_the_age_limit_is_60_s(age, expected):
    chance = _score(10, age=age)["probability"]
    assert chance["at_stop"] is expected
    if age is not None and age > 60:
        assert chance["data_quality"] == "location uncertain" and chance["point"] != 97


# ---- the rule never applies to schedule-only data, a missed bus, Demo Mode or a poll with no score

def test_schedule_only_data_never_uses_the_rule():
    chance = _score(10, monitored=False)["probability"]
    assert chance["at_stop"] is False and chance["point"] <= 60 and chance["data_quality"] == "schedule"


def test_a_missed_bus_has_no_probability_at_all():
    bus = _score(10, seconds=-45)
    assert bus["is_missed"] is True and bus["probability"] is None


def test_the_bus_within_the_30_s_grace_is_still_at_97():
    assert _score(10, seconds=-20)["probability"]["point"] == 97  # arriving now: the card says so


def test_demo_mode_keeps_its_scripted_values(monkeypatch):
    monkeypatch.setattr(demo, "demo_enabled", lambda *a, **k: True)
    chance = _score(10)["probability"]
    assert chance["at_stop"] is False and chance["point"] != 97


def test_no_location_gives_no_probability_and_no_rule():
    bus = score_buses([_bus_in(240)], user_lat=None, user_lon=None, accuracy_m=None, stop_lat=LAT, stop_lon=LON, services=[],
                      routes=[], service_no="36", stop_code="08057", now=NOW)[0]
    assert bus["probability"] is None


# ---- one function for all four places

def test_the_rule_lives_in_score_buses_only():
    for name in ("main.py", "arrivals.py", "reroute.py", "journey.py", "journey_plan.py", "route_plan.py", "recommend.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "AT_STOP_PROBABILITY" not in text and "AT_STOP_MAX_ACCURACY_M" not in text, name
    assert "AT_STOP_PROBABILITY" in inspect.getsource(catch_heuristic.score_buses)


def test_the_poll_and_the_rescore_give_the_same_at_stop_answer(client):
    lat = _north(15)[0]
    params = dict(PARAMS, lat=lat, lon=LON, accuracy=8)
    import time
    poll = client.get("/api/arrivals", params=dict(params, location_timestamp=time.time())).json()
    rescored = client.get("/api/rescore", params=dict(params, location_timestamp=time.time(), explanation_rendered=1)).json()
    for body in (poll, rescored):
        chance = body["buses"][0]["probability"]
        assert (chance["point"], chance["range_low"], chance["range_high"], chance["at_stop"]) == (97, 97, 97, True)
        assert body["near_stop"] is True
    assert rescored["chosen_action"] == "wait" and poll["chosen_action"] == "wait"


def test_the_rescore_card_is_the_at_stop_text_with_the_tile_minutes(client):
    import time
    params = dict(PARAMS, lat=_north(15)[0], lon=LON, accuracy=8, location_timestamp=time.time())
    client.get("/api/arrivals", params=params)
    body = client.get("/api/rescore", params=dict(params, explanation_rendered=1)).json()
    pack = body["explanation"]
    assert pack["at_stop"] is True and pack["action"] == "wait" and pack["call"] is False and pack["pending"] is False
    assert re.fullmatch(r"You're here\. \d+ minutes to wait\.", pack["text"]), pack["text"]


# ---- the notifications and the reroute decision

def test_no_leave_now_notice_at_the_stop():
    chance = {"point": 97, "range_low": 97, "range_high": 97, "data_quality": "live", "at_stop": True}
    bus = {"is_primary": True, "is_missed": False, "position": "NextBus", "probability": chance}
    notice = leave_now_notice([bus], service_no="36", stop_code="08057", stop_name="Boarding",
                              leave_by_iso="2026-10-08T16:00:00+08:00", notification_time="2026-10-08T15:59:00+08:00")
    assert notice["eligible"] is False and notice["title"] is None and notice["body"] is None
    chance["at_stop"] = False
    assert leave_now_notice([bus], service_no="36", stop_code="08057", stop_name="Boarding",
                            leave_by_iso="2026-10-08T16:00:00+08:00",
                            notification_time="2026-10-08T15:59:00+08:00")["eligible"] is True


def test_the_notice_shows_the_range_only_when_low_and_high_differ():
    def body_for(low, high):
        chance = {"point": 70, "range_low": low, "range_high": high, "data_quality": "live", "at_stop": False}
        bus = {"is_primary": True, "is_missed": False, "position": "NextBus", "probability": chance}
        return leave_now_notice([bus], service_no="36", stop_code="08057", stop_name="Boarding",
                                leave_by_iso="2026-10-08T16:00:00+08:00",
                                notification_time="2026-10-08T15:59:00+08:00")["body"]
    assert body_for(50, 80).endswith("Catch probability: 70% (50–80%).")
    assert body_for(70, 70).endswith("Catch probability: about 70%.")


def test_the_page_shows_the_range_in_the_5_minute_notification_only_when_it_differs():
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    block = page.split("function maybeFiveMinuteReminder", 1)[1].split("function syncLeaveNow", 1)[0]
    assert "chance.range_low === chance.range_high" in block
    assert '" Catch probability: about " + chance.point + "%."' in block


def test_no_reroute_fires_at_the_stop():
    decision = _decide([_primary(high=97, point=97, low=97), _bus("NextBus2", 90, 99, 95)])  # a loader that raises if asked
    assert decision["switched"] is False and decision["reroute"] is None


def test_the_reroute_trigger_needs_a_range_high_under_40_so_97_never_qualifies():
    import reroute
    assert reroute.RANGE_HIGH_BELOW == 40 and AT_STOP_PROBABILITY >= reroute.RANGE_HIGH_BELOW

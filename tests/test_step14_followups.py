"""Projected Leg 2 headway and continuous transfer-wait confirmation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from lta_static import StopAndRouteCache
from main import _attach_leg2_schedule
from route_plan import projected_transfer_epoch, schedule_headway_minutes
from transfer_wait import fresh_transfer_wait, note_transfer_fix

SGT = timezone(timedelta(hours=8))
INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"
TRANSFER = "55555"


def _service() -> dict:
    return {
        "ServiceNo": "14",
        "Direction": 1,
        "OriginCode": "01011",
        "DestinationCode": "99999",
        "AM_Peak_Freq": "10",
        "AM_Offpeak_Freq": "12",
        "PM_Peak_Freq": "4",
        "PM_Offpeak_Freq": "15",
    }


def _cache() -> StopAndRouteCache:
    stop = {
        "BusStopCode": TRANSFER,
        "Description": "Transfer",
        "RoadName": "Rd",
        "Latitude": 1.3,
        "Longitude": 103.8,
    }
    route = {
        "ServiceNo": "14",
        "Direction": 1,
        "BusStopCode": TRANSFER,
        "StopSequence": 1,
        "Distance": 0,
    }
    return StopAndRouteCache([stop], [route], [_service()])


def test_leg2_headway_uses_the_projected_transfer_epoch():
    planning = datetime(2026, 9, 29, 10, 0, tzinfo=SGT)
    eta = datetime(2026, 9, 29, 18, 0, tzinfo=SGT)
    projected = projected_transfer_epoch(eta, 20)
    assert projected == eta + timedelta(minutes=20)
    cache = _cache()
    assert schedule_headway_minutes(cache, "14", 1, TRANSFER, planning) == 12
    assert schedule_headway_minutes(cache, "14", 1, TRANSFER, projected) == 4
    payload = {
        "buses": [
            {
                "is_primary": True,
                "is_missed": False,
                "arrival_time": eta.replace(microsecond=0).isoformat(),
            }
        ]
    }
    _attach_leg2_schedule(
        payload,
        cache=cache,
        route_type="one_transfer",
        leg_index=1,
        leg2_service_no="14",
        leg2_direction=1,
        leg2_stop_code=TRANSFER,
        leg1_ride_minutes=20,
    )
    assert payload["leg2_schedule_headway_minutes"] == 4
    assert payload["leg2_projected_arrival"].startswith("2026-09-29T18:20:00")


def test_inside_radius_starts_a_wait_and_thirty_confirmed_seconds_activate():
    state = fresh_transfer_wait()
    assert note_transfer_fix(state, 40, 0, True) == "waiting"
    assert note_transfer_fix(state, 20, 10, True) == "waiting"
    assert note_transfer_fix(state, 10, 20, True) == "waiting"
    assert note_transfer_fix(state, 10, 30, True) == "activate"


def test_leaving_before_thirty_seconds_cancels_and_return_starts_again():
    state = fresh_transfer_wait()
    assert note_transfer_fix(state, 10, 0, True) == "waiting"
    assert note_transfer_fix(state, 80, 10, True) == "cancel"
    assert note_transfer_fix(state, 10, 30, True) == "waiting"
    assert note_transfer_fix(state, 10, 45, True) == "waiting"
    assert note_transfer_fix(state, 10, 60, True) == "activate"


def test_missing_or_invalid_fix_does_not_complete_a_silent_thirty_seconds():
    state = fresh_transfer_wait()
    assert note_transfer_fix(state, 10, 0, True) == "waiting"
    assert note_transfer_fix(state, None, 30, False) == "ignore"
    assert state["armed_at"] == 0
    assert note_transfer_fix(state, 10, 30, True) == "waiting"
    assert state["armed_at"] == 30


def test_fix_within_50m_before_im_on_board_shows_no_prompt_and_starts_no_phase_2():
    html = INDEX.read_text(encoding="utf-8")
    fix = html.split("function onJourneyFix(position)", 1)[1].split("function updateTransferPrompt", 1)[0]
    guard = fix.split("updateTransferPrompt", 1)[0]
    assert "if (!onBoard)" in guard
    assert "return;" in guard.split("if (!onBoard)", 1)[1]
    assert "activateLeg2" not in fix
    assert "startNextLeg" not in fix
    assert "startJourneyWatch()" in html
    prompt = html.split("function updateTransferPrompt", 1)[1].split("function checkMissedStop", 1)[0]
    assert "Arrived at " in prompt
    assert "activateLeg2()" in prompt
    assert "distanceMetres > 50" in html


def test_track_leg_2_is_immediate_and_location_watch_does_not_add_an_interval():
    html = INDEX.read_text(encoding="utf-8")
    button = html.split('id="track-leg-2"', 1)[1]
    assert "activateLeg2" in html
    assert "function activateLeg2()" in html
    activation = html.split("function activateLeg2()", 1)[1].split("function exitJourney", 1)[0]
    assert "startNextLeg()" in activation
    assert "setInterval" not in activation
    assert html.count("setInterval(") == 2
    watcher = html.split("function noteTransferFix", 1)[1].split("function checkMissedStop", 1)[0]
    assert "setTimeout" not in watcher
    assert "setInterval" not in watcher
    assert "watchPosition" in html
    assert "clearWatch" in html

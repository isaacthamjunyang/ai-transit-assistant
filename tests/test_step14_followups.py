"""Projected Leg 2 headway."""

from datetime import datetime, timedelta, timezone

from lta_static import StopAndRouteCache
from main import _attach_leg2_schedule
from route_plan import projected_transfer_epoch, schedule_headway_minutes

SGT = timezone(timedelta(hours=8))
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

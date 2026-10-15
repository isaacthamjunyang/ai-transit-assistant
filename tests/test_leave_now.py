"""Leave-now notification rules. Fixtures only — these tests do not call live APIs."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from arrivals import fetch_arrivals
from journey import leave_by_time
from leave_now import (
    LEAVE_NOW_MARGIN_S,
    leave_now_notice,
    notification_time_from_leave_by,
    notification_time_iso,
)
from lta_static import StopAndRouteCache

SGT = timezone(timedelta(hours=8))
PAGE = Path(__file__).resolve().parents[1] / "static" / "index.html"
TITLE = "Leave Now — Bus 36"
BODY = "Walk to Boarding now to catch Bus 36. Catch probability: 64% (51–78%)."


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _stop():
    return {
        "BusStopCode": "08057",
        "Description": "Boarding",
        "RoadName": "Orchard Rd",
        "Latitude": 1.3,
        "Longitude": 103.8,
    }


def _bus(position, *, primary=True, missed=False, point=64, low=51, high=78, quality="live"):
    return {
        "position": position,
        "arrival_time": "2026-09-29T15:10:00+08:00",
        "is_primary": primary,
        "is_missed": missed,
        "probability": {
            "point": point,
            "range_low": low,
            "range_high": high,
            "data_quality": quality,
        },
    }


def _notice(buses, **overrides):
    fields = {
        "service_no": "36",
        "stop_code": "08057",
        "stop_name": "Boarding",
        "leave_by_iso": "2026-09-29T14:57:15+08:00",
        "notification_time": "2026-09-29T14:56:15+08:00",
        "arrival_status": "ok",
    }
    fields.update(overrides)
    return leave_now_notice(buses, **fields)


def test_notification_time_is_leave_by_minus_60_seconds_only():
    leave_by = datetime(2026, 9, 29, 14, 57, 15, tzinfo=SGT)
    assert LEAVE_NOW_MARGIN_S == 60
    assert notification_time_from_leave_by(leave_by) == leave_by - timedelta(seconds=60)
    assert notification_time_iso("2026-09-29T14:57:15+08:00") == "2026-09-29T14:56:15+08:00"
    assert notification_time_iso(None) is None


def test_step_9_leave_by_does_not_include_the_60_second_margin():
    eta = datetime(2026, 9, 29, 14, 58, tzinfo=SGT)
    distance_m = 110
    leave_by = leave_by_time(eta, distance_m)
    walk_s = distance_m / 1.25
    assert leave_by == eta - timedelta(seconds=walk_s + 135)
    assert notification_time_from_leave_by(leave_by) == leave_by - timedelta(seconds=60)
    assert leave_by != eta - timedelta(seconds=walk_s + 135 + 60)


def test_live_poll_keeps_leave_by_and_sets_notification_time(monkeypatch):
    # the user stands at the stop in this fixture: the at-stop rule is off here, it has its own tests (test_at_stop.py)
    monkeypatch.setattr("catch_heuristic.AT_STOP_MAX_ACCURACY_M", -1)
    cache = StopAndRouteCache([_stop()], [], [])
    payload = {
        "BusStopCode": "08057",
        "Services": [
            {
                "ServiceNo": "36",
                "NextBus": {
                    "EstimatedArrival": "2026-09-29T14:58:00+08:00",
                    "Latitude": "1.3",
                    "Longitude": "103.8",
                    "Monitored": 1,
                },
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        body = fetch_arrivals(
            "08057",
            "36",
            client=client,
            account_key="test-account-key",
            now=datetime(2026, 9, 29, 14, 54, tzinfo=SGT),
            user_lat=1.3,
            user_lon=103.8,
            accuracy=18,
            cache=cache,
        )
    assert body["leave_by"] == "2026-09-29T14:55:45+08:00"
    assert body["notification_time"] == "2026-09-29T14:54:45+08:00"
    chance = body["buses"][0]["probability"]
    assert chance["range_high"] >= 40
    assert body["leave_now"]["eligible"] is True
    assert body["leave_now"]["bus_id"] == "36|08057|NextBus"
    assert body["leave_now"]["title"] == f"Leave Now — Bus 36"
    assert body["leave_now"]["body"] == (
        "Walk to Boarding now to catch Bus 36. "
        f"Catch probability: {chance['point']}% ({chance['range_low']}–{chance['range_high']}%)."
    )


def test_range_high_gates_the_notification_and_point_does_not():
    allowed = _notice([_bus("NextBus", point=10, low=5, high=40)])
    blocked = _notice([_bus("NextBus", point=90, low=20, high=39)])
    assert allowed["eligible"] is True
    assert allowed["range_high"] == 40
    assert blocked["eligible"] is False
    assert blocked["title"] is None
    assert blocked["body"] is None


def test_exact_notification_payload():
    notice = _notice([_bus("NextBus")])
    assert notice["title"] == TITLE
    assert notice["body"] == BODY


def test_unavailable_stale_uncertain_and_missed_suppress_notification():
    buses = [_bus("NextBus")]
    assert _notice(buses, arrival_status="unavailable")["eligible"] is False
    assert _notice(buses, arrival_status="stale")["eligible"] is False
    assert _notice(buses, leave_by_iso=None, notification_time=None)["eligible"] is False
    uncertain = _notice([_bus("NextBus", quality="location uncertain", high=80)])
    assert uncertain["eligible"] is False
    missed = _notice(
        [
            _bus("NextBus", primary=False, missed=True, high=90),
            _bus("NextBus2", primary=True, missed=False, high=30, point=20, low=10),
        ]
    )
    assert missed["bus_id"] == "36|08057|NextBus2"
    assert missed["eligible"] is False
    follow = _notice(
        [
            _bus("NextBus", primary=False, missed=True),
            _bus("NextBus2", primary=True, missed=False, high=70, point=60, low=50),
        ]
    )
    assert follow["eligible"] is True
    assert follow["bus_id"] == "36|08057|NextBus2"
    assert "NextBus2" in follow["bus_id"]
    assert follow["title"] == "Leave Now — Bus 36"


def test_bus_id_stays_put_when_only_the_eta_changes():
    first = _notice([_bus("NextBus")])
    moved = _bus("NextBus")
    moved["arrival_time"] = "2026-09-29T15:20:00+08:00"
    second = _notice([moved])
    other = _notice([_bus("NextBus2")])
    assert first["bus_id"] == second["bus_id"] == "36|08057|NextBus"
    assert other["bus_id"] == "36|08057|NextBus2"
    assert other["bus_id"] != first["bus_id"]


def test_permission_card_is_explicit_and_not_requested_on_load():
    html = _page()
    assert html.count("Notification.requestPermission") == 1
    enable_start = html.find("function onEnableNotifications")
    enable_end = html.find("function renderNotificationPermission")
    enable_fn = html[enable_start:enable_end]
    assert "Notification.requestPermission()" in enable_fn
    assert "Notification.permission !== \"default\"" in enable_fn
    assert "Notifications Optional" in html
    assert "Get an audio/visual alert 60 seconds before your walk deadline." in html
    assert "Enable Notifications" in html
    assert "Notifications active — Leave-now alert set" in html
    assert "Browser notifications are blocked. Keep this page open to see live leave-by alerts." in html
    confirm_start = html.find('confirmDestinationStop.addEventListener("click"')
    confirm_end = html.find("function clearLeaveNowTimer")
    confirm_fn = html[confirm_start:confirm_end]
    assert "renderNotificationPermission()" in confirm_fn
    assert "Notification.requestPermission" not in confirm_fn
    # The notification permission is never asked on load. (The motion permission is a different API: it is asked only
    # inside the Start journey tap, see test_walk_speed_wiring.)
    assert "Notification.requestPermission" not in html[html.find("function requestLocation"):]
    assert "function loadJourney" in html
    load_start = html.find("function loadJourney")
    load_end = html.find('confirmDestinationStop.addEventListener("click"')
    assert "requestPermission" not in html[load_start:load_end]


def test_page_schedules_from_notification_time_and_blocks_unsafe_data():
    html = _page()
    sync_start = html.find("function syncLeaveNow")
    sync_end = html.find("function requestLocation")
    sync_fn = html[sync_start:sync_end]
    assert "body.notification_time" in sync_fn
    assert "chance.range_high < 40" in sync_fn
    assert "chance.point < 40" not in html
    assert "point >= 40" not in html
    assert 'chance.data_quality === "location uncertain"' in sync_fn
    assert "arrivalsBlockLeaveNow()" in sync_fn
    assert "displayFrozen || successAgeMs() > STALE_MS" in html
    assert "primary.is_missed" in sync_fn
    assert "etaIsMissed(primary.arrival_time)" in sync_fn
    assert "recheckAfterMiss(busId)" in sync_fn
    assert "clearTimeout(leaveNowTimer)" in html
    assert "lastNotifiedBusId !== busId" in sync_fn
    assert "lastNotifiedBusId = null" in sync_fn
    assert "lastNotifiedBusId = busId" in html
    assert "pushManager" not in html and "PushManager" not in html and "sync.register" not in html
    page_w = html.split("// ---- Page W:", 1)[1].split("// Screen 8:", 1)[0]
    # the leave-now alert keeps working in a hidden tab; only Page W's own watch and the shared rescore gate stop when the tab is hidden
    assert "document.hidden" not in html.replace(page_w, "")
    assert page_w.count("document.hidden") == 2 and "leaveNow" not in page_w and "notification" not in page_w.lower()
    panel_start = html.find("function clearJourneyPanel")
    panel_end = html.find("function renderJourneyLeaveBy")
    assert "clearLeaveNowState()" in html[panel_start:panel_end]
    assert "clearLeaveNowState()" in html[html.find('confirmDestinationStop.addEventListener("click"'):html.find("function clearLeaveNowTimer")]

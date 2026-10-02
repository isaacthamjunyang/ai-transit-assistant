"""Question bar, Yes and No branches, end rules, transfer alert, service worker and the Leg 2 input rule."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import config
from catch_heuristic import score_buses
from destination_stops import BUS_SPEED_KM_H
from lta_static import StopAndRouteCache
from main import _reach_window, app

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
SW = ROOT / "static" / "sw.js"
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 18, 0, tzinfo=SGT)


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    head = text.split(start, 1)[1]
    assert end in head, end
    return head.split(end, 1)[0]


def test_named_constants_and_the_page_receives_them():
    assert not hasattr(config, "CATCH_PROMPT_LEAD_SECONDS")
    assert config.UNANSWERED_END_MINUTES == 10
    assert config.MAX_MONITOR_MINUTES == 60
    assert config.TRANSFER_NEAR_METERS == 300
    assert config.TRANSFER_WATCH_MAX_MINUTES == 90
    assert config.TRANSFER_BUS_SPEED_MPS == BUS_SPEED_KM_H / 3.6
    assert config.LEG2_REACH_RANGE_FRACTION == 0.25
    with TestClient(app) as client:
        text = client.get("/").text
    for name, value in config.PAGE_CONSTANTS.items():
        assert f"var {name} = {value};" in text, name


def test_question_bar_is_always_on_page_b_and_absent_on_page_a():
    html = _page()
    bar = _between(html, 'id="catch-bar"', "</div>\n  </div>")
    assert 'role="group"' in html.split('id="catch-bar"', 1)[1].split(">", 1)[0]
    assert "Did you catch the bus?" in bar and "Yes, I caught it" in bar and "No, I missed it" in bar
    assert 'id="catch-yes" class="primary action-yes"' in bar and 'id="catch-no" class="secondary action-no"' in bar
    assert "CATCH_PROMPT_LEAD_SECONDS" not in html and "catchLatch" not in html
    sync = _between(html, "function syncCatchBar()", "// Runs on the one-second display tick")
    assert 'contains("is-page-b")' in sync and 'qualityState() !== "no-service"' in sync
    assert "monitoringActive && !endedKind && !missedMode" in sync
    assert 'contains("is-page-a")' in sync  # the See bus arrival times bar is the Page A twin
    note = _between(html, "function noteTrackedBus(body)", "function syncCatchBar")
    assert "lastEtaMs > Date.now()" in note  # the ETA freezes once it has passed
    tick = _between(html, "function tickTracking()", "// Stops polling")
    assert "now - lastEtaMs >= UNANSWERED_END_MINUTES * 60000" in tick and "MAX_MONITOR_MINUTES" in tick
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    block = _between(css, ".catch-bar {", "}")
    assert "position: fixed" in block and "env(safe-area-inset-bottom)" in block
    assert "body.has-catch-bar" in css
    refresh = _between(html, "function refreshDisplay(generation)", "function clearPrimaryBus")
    assert refresh.index("tickTracking()") < refresh.index("renderLiveTracking()")


def test_yes_ends_a_direct_route_and_starts_the_watch_only_for_transfers():
    html = _page()
    yes = _between(html, "function answerCaught()", "function renderOnWay()")
    assert yes.index("stopTracking()") < yes.index('pushScreen("onway")')
    assert "if (transfer) {\n        startTransferWatch();" in yes
    assert yes.count("startTransferWatch()") == 1
    stop = _between(html, "function stopTracking()", "function markTrackingStopped")
    for needle in ("clearInterval(pollTimer)", "clearInterval(displayTimer)", "monitoringActive = false", "stopTransferWatch()",
                   "clearLeaveNowTimer()", "clearRerouteProposal()", "resetPaceGuidance()"):
        assert needle in stop
    way = _between(html, "function renderOnWay()", "function answerMissed()")
    assert '"done"' in way and "ON_BOARD_TEXT" in way and "TRANSFER_NOTE" in way
    assert "I'm On Board" not in html


def test_no_runs_the_on_demand_search_and_end_rules_stop_everything():
    html = _page()
    no = _between(html, "function answerMissed()", "function showMissedOptions")
    url = _between(html, "function optionsUrl(entry, missedEpoch)", "function canSearchOptions")
    assert "/api/reroute-options?" in url and "missed_eta=" in url
    assert no.index("stopTracking()") < no.index('openPageC("missed", missedEpoch)')
    assert "BUS_LEFT_NOTICE" in no  # the missed banner is the top element of Page C
    load = _between(html, "function loadPageCOptions()", "function pageCRefreshCooling()")
    assert "onDemand: true" in load
    tick = _between(html, "function tickTracking()", "// Stops polling")
    assert 'endTracking("max")' in tick and 'endTracking("unanswered")' in tick
    assert "MAX_MONITOR_MINUTES * 60000" in tick and "UNANSWERED_END_MINUTES * 60000" in tick
    end = _between(html, "function endTracking(kind)", "function resetTrackingState")
    assert "stopTracking()" in end and 'role="status"' in html
    assert "Tracking ended. Your bus's expected arrival time has passed." in html
    assert "Tracking stopped after 60 minutes." in html
    assert "resetTrackingState()" in _between(html, "function invalidateSession()", "function clearArrivalPanel")
    # Back from the on-your-way overview goes home, with the Leave confirm while the transfer watch runs.
    back = _between(html, "function requestBack()", "var pendingLeaveAction")
    assert '"onway"' in back and "transferWatchActive" in back and "goHome()" in back


def test_transfer_alert_rules():
    html = _page()
    fix = _between(html, "function onTransferFix(position)", "function fireTransferAlert")
    assert "coords.accuracy <= UNCERTAIN_ACCURACY_M" in fix and "COUNTED_FIX_MAX_AGE_S" in fix
    assert "metres <= TRANSFER_NEAR_METERS ? transferNearCount + 1 : 0" in fix
    assert "transferNearCount >= 2" in fix and "transferAlertShown" in fix
    assert "userLat" not in fix and "localStorage" not in fix and "fetch(" not in fix  # nothing stored or logged
    fire = _between(html, "function fireTransferAlert(stop)", "function showTransferPrompt")
    assert "transferAlertShown = true" in fire and "showLocalNotification(" in fire
    assert 'TRANSFER_NOTIFICATION_TAG = "transfer-alert"' in html
    assert "Get ready to change bus" in html
    assert "You are reaching {stop name}. Tap to check your chance of catching Bus {service}." in html
    start = _between(html, "function startTransferWatch()", "function stopTransferWatch")
    assert "watchPosition" in start and "TRANSFER_WATCH_MAX_MINUTES * 60000" in start and "transferNoGps = true" in start
    assert "Turn on location to get a transfer alert." in html
    prompt = html.split('id="transfer-top"', 1)[1].split("</div>", 1)[0]
    assert "You are reaching the second bus stop" in prompt and 'id="transfer-next"' in prompt and "<strong" in prompt
    assert 'role="alert"' in html.split('id="transfer-top"', 1)[1].split(">", 1)[0]
    assert html.index('id="transfer-top"') < html.index("<header")
    show = _between(html, "function showTransferPrompt(stop)", "function hideTransferPrompt")
    assert ".focus(" not in show
    assert "database" not in fix.lower() and "sqlite" not in fix.lower()


def test_service_worker_is_minimal_and_served():
    source = SW.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    for forbidden in ('"fetch"', '"push"', "caches", '"sync"', "localStorage", "indexedDB", "importScripts"):
        assert forbidden not in code, forbidden
    assert code.count("addEventListener(") == 3
    for handler in ('"install"', '"activate"', '"notificationclick"'):
        assert handler in code
    assert "skipWaiting()" in code and "clients.claim()" in code
    assert 'postMessage({ type: "transfer-alert" })' in code and 'openWindow("/")' in code and "notification.close()" in code
    with TestClient(app) as client:
        response = client.get("/sw.js")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]
    html = _page()
    assert 'register("/sw.js")' in html
    enable = _between(html, "function onEnableNotifications()", "function renderNotificationPermission")
    assert "registerNotificationWorker()" in enable and "requestPermission" in enable
    helper = _between(html, "function showLocalNotification(title, options)", "function registerNotificationWorker")
    assert helper.index("swRegistration.showNotification") < helper.index("new Notification(title, options)")
    assert 'Notification.permission !== "granted"' in helper
    assert html.count("Notification.requestPermission") == 1
    assert "manifest" not in html.lower().split("<head>", 1)[1].split("</head>", 1)[0]


def test_next_opens_leg_2_and_leg_2_page_differences():
    html = _page()
    nxt = _between(html, "function acknowledgeTransferAlert()", "// Local notifications go through")
    assert "stopTransferWatch()" in nxt and "openLeg2()" in nxt
    assert html.index('id="catch-bar"') > html.index("</main>")
    tiles = _between(html, "function renderLeaveTiles()", "// Screen 8")
    assert "LEG2_REACH_LABEL" in tiles and "lastSuccess.reach_stop" in tiles
    card = _between(html, "function renderCatchCard(hero)", "function renderLeaveTiles")
    assert "LEG2_CAPTION" in card and "usable && !onLeg2()" in card
    assert 'var LEG2_CAPTION = "based on how far you are from the stop";' in html
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    assert "body.is-leg2 #pace-slot" in css and "body.is-leg2 #ai-explanation" not in css  # the pace chip hides, the AI card shows
    poll = _between(html, "function requestArrivals(generation)", "function applySuccess")
    assert "explanation_rendered" in poll and "explained_action" in poll  # the AI card is shown on Leg 2 too
    sync = _between(html, "function syncLeaveNow(body)", "function renderCatchWarning")
    assert "onLeg2()" in sync


def _cache() -> StopAndRouteCache:
    stop = {"BusStopCode": "11111", "Description": "Transfer", "RoadName": "Rd", "Latitude": 1.3, "Longitude": 103.8}
    return StopAndRouteCache([stop], [], [])


def _bus(minutes: float) -> dict:
    return {
        "position": "NextBus",
        "arrival_time": (NOW + timedelta(minutes=minutes)).isoformat(),
        "monitored": True,
        "origin_code": None,
        "destination_code": None,
    }


def _score(**extra) -> dict:
    # About 500 m from the stop, a bus due in 200 seconds.
    buses = score_buses(
        [_bus(200 / 60)], user_lat=1.3 + 500 / 111_195, user_lon=103.8, accuracy_m=10, stop_lat=1.3, stop_lon=103.8,
        services=[], routes=[], service_no="106", stop_code="11111", now=NOW, **extra,
    )
    return buses[0]["probability"]


def test_leg_2_uses_the_vehicle_speed_input_with_a_plus_minus_25_percent_range():
    walking = _score()
    riding = _score(reach_speed_m_s=config.TRANSFER_BUS_SPEED_MPS, reach_range_fraction=config.LEG2_REACH_RANGE_FRACTION)
    # 500 m at 5 m/s is 100 s; at 1.25 m/s it is 400 s. The formula, the buffer and the thresholds are the same.
    assert walking["point"] < 10
    assert riding["point"] > walking["point"] + 15
    assert riding["range_low"] <= riding["point"] <= riding["range_high"]
    assert riding["pace"] is None  # the pace chip is hidden on Leg 2
    # The range is plus or minus 25% on the reach time: 125 s slow, 75 s fast.
    from catch_heuristic import catch_probability, high_slack, low_slack, point_slack, to_percent

    speed = config.TRANSFER_BUS_SPEED_MPS
    seconds = 200.0
    distance = 500.0
    assert riding["range_high"] == to_percent(catch_probability(high_slack(seconds, distance, speed / 0.75)))
    assert riding["point"] == to_percent(catch_probability(point_slack(seconds, distance, speed)))
    assert riding["range_low"] == to_percent(catch_probability(low_slack(seconds, distance, 10.0, speed / 1.25)))


def test_reach_window_is_now_plus_the_time_to_the_stop():
    window = _reach_window(_cache(), "11111", 1.3 + 500 / 111_195, 103.8, NOW)
    assert window["distance_m"] in range(498, 503)
    point = datetime.fromisoformat(window["point"]) - NOW
    low = datetime.fromisoformat(window["low"]) - NOW
    high = datetime.fromisoformat(window["high"]) - NOW
    assert abs(point.total_seconds() - 100) < 2
    assert abs(low.total_seconds() - 75) < 2 and abs(high.total_seconds() - 125) < 2
    assert _reach_window(_cache(), "99999", 1.3, 103.8, NOW) is None

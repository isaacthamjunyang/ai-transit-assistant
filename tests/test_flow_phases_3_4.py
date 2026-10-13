"""Question bar, Yes and No branches, end rules and the service worker."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

import config
from main import app

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
SW = ROOT / "static" / "sw.js"


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


def test_yes_ends_tracking_for_every_route_and_shows_the_overview():
    html = _page()
    yes = _between(html, "function answerCaught()", "function renderOnWay()")
    assert yes.index("stopTracking()") < yes.index('pushScreen("onway")')
    assert "Watch" not in yes and "leg_index" not in yes
    stop = _between(html, "function stopTracking()", "function markTrackingStopped")
    for needle in ("clearInterval(pollTimer)", "clearInterval(displayTimer)", "monitoringActive = false",
                   "clearLeaveNowTimer()", "clearRerouteProposal()", "resetPaceGuidance()",
                   "paceJourneyActive = false", "syncPaceEstimator()"):
        assert needle in stop
    way = _between(html, "function renderOnWay()", "function answerMissed()")
    assert '"done"' in way and "ON_BOARD_TEXT" in way
    assert "scheduleLine(leg)" in way and "FIRST_BUS_ONLY_NOTE" not in html  # the headway comes through scheduleLine
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
    # Back from the on-your-way overview goes home.
    back = _between(html, "function requestBack()", "var pendingLeaveAction")
    assert '"onway"' in back and "goHome()" in back


def test_service_worker_is_minimal_and_served():
    source = SW.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    for forbidden in ('"fetch"', '"push"', "caches", '"sync"', "localStorage", "indexedDB", "importScripts"):
        assert forbidden not in code, forbidden
    assert code.count("addEventListener(") == 3
    for handler in ('"install"', '"activate"', '"notificationclick"'):
        assert handler in code
    assert "skipWaiting()" in code and "clients.claim()" in code
    assert "postMessage" not in code and 'openWindow("/")' in code and "notification.close()" in code
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

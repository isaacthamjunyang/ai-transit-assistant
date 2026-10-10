"""Live page clean-up: no-service layout, removed legs panel, live map toggle, warnings from real data."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"
CSS = STATIC / "components.css"
COPY = STATIC / "copy.js"
GUIDE = STATIC / "styleguide.html"

NO_SERVICE = "No buses currently in service at this stop."


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    head = text.split(start, 1)[1]
    assert end in head, end
    return head.split(end, 1)[0]


def test_no_service_and_unavailable_use_the_status_card_layout():
    html = _page()
    state = _between(html, "function qualityState()", "function staleArrivingText")
    assert '"no-service"' in state and '"unavailable"' in state and '"stale"' in state
    assert "lastSuccess.buses.length === 0" in state
    sync = _between(html, "function syncQuality()", "function activePlannedLeg")
    assert 'classList.toggle("is-data-blocked", state !== "")' in sync
    assert 'state === "no-service" ? NO_SERVICE_TEXT' in sync
    assert 'getElementById("next-buses-empty")' in sync
    # Only the stale state carries a time; no-service and unavailable never show an estimate.
    assert 'var arrivingText = state === "stale" ? staleArrivingText() : ""' in sync
    css = CSS.read_text(encoding="utf-8")
    block = _between(css, "body.is-data-blocked #arrival-card,", "}")
    for target in ("#pace-slot", "#leave-tiles", "#if-you-miss", "#ai-explanation", "#reroute-block"):
        assert target in block
    status = _between(html, 'id="stale-status"', "</section>")
    for needle in ("bus-tile--hero", "pill pill--schedule", "info-box", 'id="stale-info"'):
        assert needle in status
    assert "%" not in status
    assert 'id="next-buses-empty"' in html
    assert NO_SERVICE in html and NO_SERVICE in COPY.read_text(encoding="utf-8")


def test_empty_response_keeps_the_existing_logic():
    html = _page()
    empty = _between(html, "function handleEmptyBuses(body)", "function setArrivalTone")
    assert "lastSuccess = body" in empty
    assert "renderCatchCard(null)" in empty
    assert "No buses currently in service at this stop." in empty


def test_legs_panel_and_its_controls_are_gone():
    html = _page()
    css = CSS.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")
    copy = COPY.read_text(encoding="utf-8")
    for gone in ("Start Next Leg", "start-next-leg", "Next action:", "I'm On Board", "im-on-board", "on-board-note", "onBoard",
                 "The chosen route is drawn on the map", "route-motif", "route-strip-part", "id=\"route-plan\"", "route-plan-body",
                 "renderRouteStrip", "function startNextLeg", "function activateLeg2", "function checkMissedStop",
                 "function findReanchorStop", "function noteTransferFix", "function onJourneyFix", "function startJourneyWatch",
                 "missed-stop", "You passed your stop", "TRANSFER_WAIT_MS", "track-leg-2", "transfer-prompt", "leg2-prompt",
                 "Activate Leg 2 Live Tracking"):
        assert gone not in html, gone
    # "Arrived at " belonged to the removed missed-stop UI; Page W's state line "Arrived at the stop" is the only use now
    # (a train says "the station": TRAIN_PAGE.walkArrived)
    assert html.count("Arrived at ") == 2 and 'arrived: "Arrived at the stop"' in html and 'walkArrived: "Arrived at the station"' in html
    for gone in ("live-card__board", "route-motif", "leg2-banner", "journey-timeline", "service-plate", "#track-leg-2"):
        assert gone not in css, gone
    assert "live-card__board" not in guide and "onBoard" not in copy
    assert not (ROOT / "transfer_wait.py").exists()


def test_live_map_has_a_destination_pin_and_a_full_route_toggle():
    html = _page()
    css = CSS.read_text(encoding="utf-8")
    button = _between(html, 'id="live-full-route"', "</button>")
    assert 'aria-pressed="false"' in html.split('id="live-full-route"', 1)[1].split(">", 1)[0]
    assert "<svg" in button and "Full route" in button
    assert "Near me" in html and "Near me" in COPY.read_text(encoding="utf-8")
    pin = _between(html, "function syncLiveDestination()", "function routeLinePoints")
    assert "dest-pin__svg" in pin and "dest-pin__body" in pin and "map-dest-live__label" in pin
    assert "confirmedDestinationStop" in pin
    assert "fill: var(--map-destination)" in css
    fit = _between(html, "function fitFullRoute()", "function setLiveFull")
    for needle in ("routeLinePoints()", "userLat", "boardingPoint()", "liveBusTag", "liveDestMarker", "padding"):
        assert needle in fit
    local = _between(html, "function fitLiveView(busPoint, stopPoint)", "function setStatusCell")
    assert "liveFull || liveUserMoved" in local
    click = _between(html, 'getElementById("live-full-route").addEventListener("click"', "\n    });")
    assert "setLiveFull(false)" in click and "setLiveFull(true)" in click and "fitFullRoute()" in click
    assert "Range: " in _between(html, "var RangeControl", "mapScale") or "map-range" in html


def test_warnings_come_from_real_data_not_demo_mode():
    html = _page()
    sync = _between(html, "function syncQuality()", "function activePlannedLeg")
    assert "demo" not in sync.lower()
    state = _between(html, "function qualityState()", "function staleArrivingText")
    assert "demo" not in state.lower()
    assert "STALE_MS" in html and "var STALE_MS = 60000;" in html
    slot = _between(html, 'id="alert-slot"', 'id="arrival-card"')
    assert slot.index('id="quality-banner"') < slot.index('id="stale-status"') < slot.index('id="location-card"')
    live = _between(html, "function renderLiveTracking()", 'document.getElementById("live-refresh")')
    assert "syncQuality()" in live


def test_no_colour_literals_or_inline_styles_in_new_code():
    css = CSS.read_text(encoding="utf-8")
    tail = css.split("/* Live map: destination pin", 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", tail)
    assert 'style="' not in _page() and 'style="' not in GUIDE.read_text(encoding="utf-8")

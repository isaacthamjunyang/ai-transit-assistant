"""Page B after tracking stops, the pill and counter rule, and the map's reserved rectangles."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def _page() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    return text.split(start, 1)[1].split(end, 1)[0]


def test_pill_and_last_update_use_the_same_time_and_the_same_60_second_rule():
    html = _page()
    stale = _between(html, "function dataIsStale()", "function successAgeMs()")
    assert "displayFrozen || successAgeMs() > STALE_MS" in stale
    assert "var STALE_MS = 60000;" in html
    live = _between(html, "function renderLiveTracking()", 'document.getElementById("live-refresh")')
    assert 'dataIsStale() ? "stale"' in live and "displayFrozen ? \"stale\"" not in live
    assert "relativeAge(iso)" in live and "body.fetched_at" in live  # the counter reads the same fetched-at time
    assert "lastSuccess.fetched_at" in _between(html, "function successAgeMs()", "function requestArrivals")  # one fetched-at time
    card = _between(html, "function renderCatchCard(hero)", "function renderLeaveTiles")
    assert "dataIsStale()" in card


def test_page_b_after_tracking_stops():
    html = _page()
    stopped = _between(html, "function markTrackingStopped()", "function endTracking(kind)")
    assert 'pill.className = "pill pill--stopped"' in stopped and "TRACKING_STOPPED_TEXT" in stopped
    assert 'var TRACKING_STOPPED_TEXT = "Tracking stopped";' in html
    assert "clearLiveBusTag()" in stopped  # no live bus tag on the map
    assert "renderNextBuses(" in stopped and ", null)" in stopped  # no selected outline and no (Arriving)
    assert "syncRefreshButton()" in stopped
    refresh = _between(html, "function syncRefreshButton()", "function manualRefresh()")
    assert "!monitoringActive" in refresh and 'setAttribute("aria-disabled"' in refresh
    tiles = _between(html, "function renderNextBuses(buses, hero)", "// Reserved rectangles")
    assert 'trackingStopped && new Date(bus.arrival_time).getTime() <= Date.now()' in tiles
    assert '"Missed"' in tiles
    sync = _between(html, "function syncCatchBar()", "// Runs on the one-second display tick")
    assert "monitoringActive && !endedKind && !missedMode" in sync  # no question bar once tracking has stopped
    assert "trackingStopped = false" in _between(html, "function resetTrackingState()", "function planNewJourney")
    assert ".pill--stopped" in (STATIC / "components.css").read_text(encoding="utf-8")
    assert "Tracking stopped" in (STATIC / "copy.js").read_text(encoding="utf-8")


def test_the_map_keeps_labels_tags_and_pins_out_of_the_reserved_rectangles():
    html = _page()
    reserved = _between(html, "function liveReservedRects()", "var LIVE_TAG_SIDES")
    assert "mapScale.getContainer()" in reserved and 'getElementById("live-full-route")' in reserved and "leaflet-control-attribution" in reserved
    layout = _between(html, "function layoutLiveLabel()", 'map.on("zoomend moveend", layoutLiveLabel)')
    assert "reserved.concat(pin ? [pin] : []" in layout  # the destination label avoids the chip, the button and the pin
    assert "LIVE_TAG_SIDES" in layout and "liveBusTag.setIcon(liveTagIcon" in layout  # the tag moves to another side
    assert 'label.classList.toggle("is-label-hidden", !chosenLabel)' in layout  # a label is hidden rather than left under them
    assert 'youLabel.classList.toggle("is-label-hidden"' in layout  # the You label yields to the stop label
    assert "paddingTopLeft: [40, 96], paddingBottomRight: [140, 76]" in html  # the fit keeps pins clear of the corner controls
    css = (STATIC / "components.css").read_text(encoding="utf-8")
    for side in ("is-right", "is-top", "is-bottom"):
        assert f".map-dest-live__label.{side}" in css

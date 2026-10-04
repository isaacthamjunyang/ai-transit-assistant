"""Screens 5 and 6: journey overview and live bus tracking. Static checks; no live APIs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
COPY = ROOT / "static" / "copy.js"
CSS = ROOT / "static" / "components.css"
THEME = ROOT / "static" / "theme.css"


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_overview_order_and_edit_routes():
    html = _page()
    render = _between(html, "function renderJourneyOverview()", "function syncOverviewArrive()")
    order = [
        'stepItem("origin"',
        '"Boarding stop"',
        '"Bus service"',
        '"Destination stop"',
        'stepItem("destination", "Destination"',
    ]
    positions = [render.index(marker) for marker in order]
    assert positions == sorted(positions)
    origin = _between(render, 'stepItem("origin"', "));")
    assert "], null)" in origin + ")"
    assert "Edit boarding stop" not in html and "Edit bus service" not in html and "Edit transfer stop" not in html
    assert "list.appendChild(stepItem(\"bus\", \"Bus service\", lines, null));" in render
    assert 'label: "Edit destination stop", action: function () { backToScreen("stops"); }' in render
    assert 'label: "Edit destination", action: function () { backToScreen("results"); }' in render
    assert '" to boarding stop"' in render and "formatDistance(toBoard)" in render
    # Edit is the same as Back: it walks the history stack and adds no state of its own.
    back = _between(html, "function backToScreen(name)", "function closeStopsNote")
    assert "history.go(-steps)" in back


def test_transfer_variant_adds_a_transfer_stop_and_a_schedule_only_second_bus():
    html = _page()
    render = _between(html, "function renderJourneyOverview()", "function syncOverviewArrive()")
    assert "index === 0 && legs.length > 1" in render
    assert '"Transfer stop"' in render
    assert "var live = index === 0 ? liveDataFor(leg) : null;" in render
    assert 'typeof leg.published_headway_minutes === "number"' in render
    copy = COPY.read_text(encoding="utf-8")
    assert "/* proposed, needs approval */" in copy
    assert 'firstBusOnly: "Live tracking covers your first bus only."' in copy
    assert 'headway: "Schedule: about every {minutes} min."' in copy
    assert "FIRST_BUS_ONLY_NOTE" in render and "SCHEDULE_HEADWAY" in render


def test_bottom_button_runs_the_existing_select_and_start_action():
    html = _page()
    markup = _between(html, 'id="journey-overview"', "</section>")
    assert '<button type="button" id="start-journey" class="primary primary--icon" disabled>' in markup
    assert "<span>Start journey</span>" in markup
    assert "Select & Start Journey" not in html
    start = _between(html, 'getElementById("start-journey").addEventListener("click"', "});")
    assert start.index("selectPlannedRoute(pendingRouteOption)") < start.index('pushScreen("live")')


def test_arrive_by_box_mirrors_the_shared_display_and_opens_the_sheet():
    html = _page()
    summary = _between(html, "function syncArriveBySummary()", "function renderJourney")
    assert 'getElementById("overview-arrive-value")' in summary
    assert "cloneNode(true)" in summary
    assert 'getElementById("overview-arrive-edit").addEventListener("click", openArriveSheet)' in html
    mirror = _between(html, "function syncOverviewArrive()", "// Screen 6")
    assert '"journey-arrival-estimate", "overview-arrive-estimate"' in mirror
    assert "journeyComparison" in mirror
    assert '["route", "journey", "overview"]' in html


def test_tiles_are_display_only_capped_at_three_with_arriving_on_the_monitored_bus():
    html = _page()
    tiles = _between(html, "function renderNextBuses(buses, hero)", "// Reserved rectangles")
    assert "buses.slice(0, 3)" in tiles
    assert 'document.createElement("li")' in tiles
    assert "button" not in tiles and "addEventListener" not in tiles and "tabIndex" not in tiles
    assert tiles.count('"(Arriving)"') == 1
    assert 'if (bus === hero) {\n          var arriving' in tiles
    assert 'id="next-buses" class="bus-tiles" role="list"' in html
    css = CSS.read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert ".bus-tile-card.is-selected {\n  box-shadow: 0 0 0 2px var(--color-selected-outline);" in css


def test_refresh_has_a_cooldown_and_adds_no_second_timer():
    html = _page()
    assert "var MANUAL_REFRESH_MIN_SECONDS = 10;" in html
    assert html.count("setInterval(") == 2
    arm = _between(html, "function armPollTimer(generation)", "function successAgeMs")
    assert "clearInterval(pollTimer)" in arm and "POLL_MS" in arm
    refresh = _between(html, "function manualRefresh()", "function relativeAge")
    assert refresh.index("refreshCoolingDown()") < refresh.index("requestArrivals(monitorGeneration)")
    assert "demoModeOn()" in refresh
    assert "armPollTimer(monitorGeneration)" in refresh
    sync = _between(html, "function syncRefreshButton()", "function manualRefresh")
    assert 'setAttribute("aria-disabled", blocked ? "true" : "false")' in sync
    css = CSS.read_text(encoding="utf-8")
    spin = _between(css, "@media (prefers-reduced-motion: no-preference) {\n  .refresh-button.is-spinning .icon {", "}")
    assert "animation: refresh-spin" in spin


def test_status_grid_states_and_relative_time_counter():
    html = _page()
    live = _between(html, "function renderLiveTracking()", 'document.getElementById("live-refresh")')
    for text in ("Live bus location available", "Live bus location unavailable", "Monitored (live GPS)", "Not monitored (no GPS)"):
        assert text in live
        assert text in COPY.read_text(encoding="utf-8")
    assert "userAccuracy > UNCERTAIN_ACCURACY_M ? \"is-warn\"" in live
    assert 'updated.setAttribute("datetime", iso)' in live
    assert 'aria-live="off"><time id="status-updated"' in html
    assert 'id="live-status-announce" class="visually-hidden" aria-live="polite"' in html
    ages = _between(html, "function relativeAge(iso)", "function hasBusPosition")
    assert '" seconds ago"' in ages and '" min " + (seconds % 60) + " sec ago"' in ages
    tick = _between(html, "function refreshDisplay(generation)", "function clearPrimaryBus")
    assert "renderLiveTracking()" in tick


def test_no_bus_tag_without_coordinates_and_no_invented_position():
    html = _page()
    has = _between(html, "function hasBusPosition(bus)", "function renderNextBuses")
    assert "bus.monitored" in has and "isFinite(bus.latitude)" in has and "isFinite(bus.longitude)" in has
    tag = _between(html, "function syncLiveBusTag(hero)", "function fitLiveView")
    assert tag.index("if (!hasBusPosition(hero) || displayFrozen)") < tag.index("clearLiveBusTag()")
    assert "[hero.latitude, hero.longitude]" in tag
    fit = _between(html, "function fitLiveView(busPoint, stopPoint)", "function setStatusCell")
    assert "liveUserMoved" in fit and "liveFit.withBus" in fit
    css = CSS.read_text(encoding="utf-8")
    assert "background: var(--map-live-bus);" in css
    theme = THEME.read_text(encoding="utf-8")
    assert theme.count("--map-live-bus:") == 4
    assert theme.count("--step-node-destination:") == 4


def test_live_page_order_puts_the_bus_card_last():
    html = _page()
    order = ['id="alert-slot"', 'id="arrival-card"', 'id="pace-slot"', 'id="leave-tiles"', 'id="if-you-miss"',
             'id="ai-explanation"', 'id="live-tracking"', 'id="journey-panel"']
    positions = [html.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert 'id="im-on-board"' not in html and 'id="transfer-prompt"' not in html and 'id="track-leg-2"' not in html

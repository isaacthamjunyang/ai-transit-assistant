"""Screens 1-4 fix pass: mandatory arrive-by, header home button, select-then-confirm, display strings. Static checks."""

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


def test_saved_place_row_runs_saved_actions_only_and_does_not_search():
    html = _page()
    chips = _between(html, 'getElementById("quick-picks").addEventListener("click"', "});")
    assert "savedPlaceAction(chip)" in chips
    assert "destinationInput.value" not in chips
    assert "requestSubmit" not in chips
    assert "pushScreen" not in chips
    assert "fetch(" not in chips


def test_incomplete_form_shows_messages_and_does_not_search():
    html = _page()
    submit = _between(html, 'destinationForm.addEventListener("submit", function (event) {', 'fetch("/api/destinations')
    gate = submit.index("if (!syncSearchReadiness())")
    assert gate < submit.index("destinationSearchInFlight = true")
    assert "searchAttempted = true" in submit
    ready = _between(html, "function syncSearchReadiness()", "destinationForm.addEventListener")
    assert "hasDestination && arriveByPicked" in ready
    assert 'setAttribute("aria-disabled", ready ? "false" : "true")' in ready
    assert 'id="find-route" aria-disabled="true"' in html
    for text in ("Enter a destination to continue.", "Choose when you need to arrive, or select No target."):
        assert text in html
        assert text in COPY.read_text(encoding="utf-8")
    assert '<p id="destination-required" class="field-help home-only" aria-live="polite">' in html
    assert '<p id="arrive-required" class="field-help" aria-live="polite">' in html
    assert html.count('aria-live="polite"') >= 2
    assert '<span id="arrive-required-tag" class="required-tag">Required</span>' in html


def test_no_target_counts_but_an_untouched_field_or_past_custom_time_does_not():
    html = _page()
    assert "var arriveByPicked = false;" in html
    apply = _between(html, "function applyArriveValue(value, chipId)", "function ")
    assert "arriveByPicked = true" in apply
    none = _between(html, 'getElementById("arrive-none").addEventListener("click"', "});")
    assert 'applyArriveValue("", "arrive-none")' in none
    edit = _between(html, "function onArriveCustomEdit()", "arriveTimeInput.addEventListener")
    assert edit.index("arriveCustomResult()") < edit.index("arriveByPicked = result.problem === null")  # a past time is not picked
    custom = _between(html, 'getElementById("arrive-custom").addEventListener("click"', "});")
    assert "onArriveCustomEdit()" in custom


def test_header_button_resets_the_journey_and_keeps_the_fields():
    html = _page()
    assert '<button type="button" class="app-header__brand app-header__home" id="home-button" aria-label="Beat the Bus and MRT, go to home"' in html
    exit_fn = _between(html, "function exitJourney(keepFields)", "function goHome()")
    assert "if (!keepFields) {\n        arriveByInput.value = \"\";" in exit_fn
    assert "if (!keepFields) {\n        destinationInput.value = \"\";" in exit_fn
    home = _between(html, "function goHome()", "function requestHome()")
    assert "exitJourney(true)" in home
    request = _between(html, "function requestHome()", "function requestLocation")
    assert request.index("if (monitoringActive)") < request.index("openLeaveDialog()") < request.index("goHome()")
    assert 'pendingLeaveAction = "home"' in request
    assert 'screenStack[screenStack.length - 1] === "home"' in request
    leave = _between(html, "function confirmLeave()", "function chooseTheme")
    assert leave.index("endMonitoring()") < leave.index("goHome()")
    sync = _between(html, "function syncHomeButton()", "function syncBackRow()")
    assert 'setAttribute("aria-current", "page")' in sync
    css = CSS.read_text(encoding="utf-8")
    assert ".app-header__home:focus-visible" in css
    assert "min-height: var(--tap-min)" in _between(css, ".app-header__home {", "}")


def test_row_and_marker_taps_select_only_and_the_footer_opens_screen_four():
    html = _page()
    choose = _between(html, "function chooseDestinationStop(stop)", "function openDestinationConfirm")
    assert "selectDestinationStop(stop)" in choose
    assert "map.panInside(" in choose
    assert "setZoom" not in choose and "setView" not in choose
    row = _between(html, "function renderDestinationStopCard", "function addDestinationMarker")
    marker = _between(html, "function addDestinationMarker(stop)", "function addDestinationWalkLine")
    assert "chooseDestinationStop(stop)" in row and "chooseDestinationStop(stop)" in marker
    assert "openDestinationConfirm" not in row and "openDestinationConfirm" not in marker
    assert "scrollIntoView" in marker
    footer = _between(html, 'class="dest-sheet__footer"', "</div>")
    assert 'id="select-destination-stop" class="primary primary--icon" disabled' in footer
    assert "Select destination stop" in footer
    select = _between(html, "function selectDestinationStop(stop)", "function chooseDestinationStop")
    assert 'getElementById("select-destination-stop").disabled = false' in select
    clear = _between(html, "function clearDestinationStops()", "function clearDestinationSelection")
    assert 'getElementById("select-destination-stop").disabled = true' in clear
    opens = _between(html, 'getElementById("select-destination-stop").addEventListener("click"', "});")
    assert "openDestinationConfirm()" in opens


def test_back_and_edit_return_to_screen_three_without_clearing_the_selection():
    html = _page()
    apply = _between(html, "function applyScreen(name)", "function syncHomeButton")
    assert "selectedDestinationStop" not in apply
    assert "clearDestinationStops" not in apply
    edit = _between(html, 'getElementById("edit-destination-stop").addEventListener("click"', "});")
    assert 'backToScreen("stops")' in edit


def test_arrive_by_display_strings():
    html = _page()
    copy = COPY.read_text(encoding="utf-8")
    labels = _between(html, "var ARRIVE_LABELS = {", "};")
    for chip, text in (("arrive-none", "No target"), ("arrive-30", "In 30 min"), ("arrive-60", "In 1 hour"), ("arrive-custom", "Custom")):
        assert '"%s": "%s"' % (chip, text) in labels
    summary = _between(html, "function syncArriveBySummary()", "function renderJourney")
    assert 'display.textContent = arriveByChoice === "arrive-custom" ? ARRIVE_LABELS["arrive-custom"] : "Select time"' in summary
    assert '" · " + formatArriveByClock(arriveByInput.value)' in summary
    assert 'arriveByChoice !== "arrive-none"' in summary
    assert "select-field__time" in summary
    assert 'displayTime: "{label} · {time}"' in copy
    reopen = _between(html, "function openArrivePanel()", "function closeArrivePanel")
    assert 'selectArriveChip(arriveByPicked || arriveByChoice === "arrive-custom" ? arriveByChoice : "")' in reopen


def test_screen_one_sits_flush_and_scrollbars_are_themed():
    css = CSS.read_text(encoding="utf-8")
    assert ".wrap--notices:not(:has(> :not([hidden]))) {\n  display: none;" in css
    flush = _between(css, "body.is-screen-home #search-card,\nbody.is-screen-results #search-card {", "}")
    assert "border: 0" in flush and "box-shadow: none" in flush
    assert "scrollbar-color: var(--color-line-strong) transparent" in css
    assert "::-webkit-scrollbar-thumb" in css
    assert '<body class="is-screen-home">' in _page()


def test_selected_ring_tokens_exist_in_both_themes():
    theme = THEME.read_text(encoding="utf-8")
    for token in ("--map-selected-width: 3px", "--map-selected-halo: #FFFFFF", "--map-selected-halo-width: 2px"):
        assert theme.count(token) == 4
    assert theme.count("--map-range-text:") == 4

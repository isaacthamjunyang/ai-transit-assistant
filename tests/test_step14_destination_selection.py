"""Destination stops are chosen by the 600 m place radius, before any route."""

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"
SELECTOR = Path(__file__).resolve().parents[1] / "destination_stops.py"


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_destination_stop_selection_does_not_require_reachability_or_a_boarding_stop():
    html = _page()
    select = html.split("function selectDestinationStop(stop)", 1)[1].split("function renderDestinationStopCard", 1)[0]
    assert "is_reachable" not in select
    card = html.split("function renderDestinationStopCard", 1)[1].split("function addDestinationMarker", 1)[0]
    # Screen 3: each row is one button; a tap selects the stop only. The footer button opens screen 4.
    assert 'row.type = "button"' in card
    assert 'row.setAttribute("aria-pressed", "false")' in card
    assert "chooseDestinationStop(stop)" in card
    assert "openDestinationConfirm" not in card
    assert 'choose.textContent = "Select"' not in card
    assert 'id="select-destination-stop"' in html
    assert "No direct route from your boarding area." not in card
    assert "Bus: none" not in card
    load = html.split("function loadDestinationStops()", 1)[1].split("function clearRoutePlan", 1)[0]
    assert "/api/destination-stops?" in load
    assert "boarding_stop_code" not in load
    assert "BusArrival" not in load
    assert "/api/arrivals" not in load
    confirm = html.split('confirmDestinationStop.addEventListener("click"', 1)[1].split("function onArriveCustomEdit", 1)[0]
    assert "is_reachable" not in confirm
    assert 'pushScreen("journey")' in confirm
    assert 'getElementById("boarding-stage")' not in confirm
    assert "loadRoutePlan()" not in confirm
    assert "confirmedDestinationStop = copyDestinationStop(selectedDestinationStop)" in confirm
    screen4 = html.split('id="destination-confirm"', 1)[1].split("</section>", 1)[0]
    assert 'id="confirm-destination-stop"' in screen4
    assert "<span>Confirm</span>" in screen4 and "Confirm and find buses" not in html
    assert "Confirm destination stop" not in html
    assert "No direct or 1-transfer bus connection available for this trip." in html
    assert "No direct destination stop is reachable from your current boarding area." not in html


def test_destination_stop_selector_does_not_call_live_arrivals():
    source = SELECTOR.read_text(encoding="utf-8")
    assert "fetch_arrivals" not in source
    assert "BusArrival" not in source

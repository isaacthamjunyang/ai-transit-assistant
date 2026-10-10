"""The route preview draws stop coordinates and never starts arrivals; route cards are gone (auto-planned)."""

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


def test_route_preview_uses_stop_coordinates_and_does_not_start_arrivals():
    html = INDEX.read_text(encoding="utf-8")
    preview = html.split("function highlightJourneyRoute(option, legs)", 1)[1].split("function walkPhrase", 1)[0]
    assert "startMonitoring" not in preview
    assert "fetch(\"/api/arrivals" not in preview
    assert 'cssToken("--map-line-bus")' in html.split("function legStyle(leg)", 1)[1].split("function ", 1)[0]  # each leg has its own style (part 2)
    assert 'dashArray: "5, 10"' in preview
    coords = html.split("function legLatLngs(leg)", 1)[1].split("function clearRoutePreview", 1)[0]
    assert "stop.latitude" in coords
    assert "stop.longitude" in coords
    assert "legPath" in preview  # drawn from the decoded path, falling back to the stops
    assert '"BOARD"' in preview
    assert '"CHANGE"' in preview and '"EXIT"' in preview
    assert '"DESTINATION"' in preview
    assert "map.fitBounds" in preview
    # Route cards were removed: the app picks the route. Start journey runs the existing action.
    assert "function renderRouteOptions" not in html
    assert "route-choice" not in html.split("<script", 1)[0]
    assert "Review journey" not in html
    assert "Select & Start Journey" not in html
    start = html.split('getElementById("start-journey").addEventListener("click"', 1)[1].split("});", 1)[0]
    assert "selectPlannedRoute(pendingRouteOption" in start

"""Route cards stay static until Select & Start Journey."""

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


def test_route_preview_uses_stop_coordinates_and_does_not_start_arrivals():
    html = INDEX.read_text(encoding="utf-8")
    preview = html.split("function highlightJourneyRoute(option)", 1)[1].split("function walkPhrase", 1)[0]
    assert "startMonitoring" not in preview
    assert "fetch(\"/api/arrivals" not in preview
    assert 'color: index === 0 ? cssToken("--color-primary") : cssToken("--fill-warning")' in preview
    assert 'dashArray: "5, 10"' in preview
    coords = html.split("function legLatLngs(leg)", 1)[1].split("function clearRoutePreview", 1)[0]
    assert "stop.latitude" in coords
    assert "stop.longitude" in coords
    assert "legLatLngs" in preview
    assert '"BOARD"' in preview
    assert '"TRANSFER"' in preview
    assert '"DESTINATION"' in preview
    assert "map.fitBounds" in preview
    cards = html.split("function renderRouteOptions", 1)[1].split("function selectPlannedRoute", 1)[0]
    assert "Select & Start Journey" in cards
    assert "startMonitoring" not in cards
    assert cards.index("showRoute(option, card)") < cards.index("selectPlannedRoute(option)")
    assert "min total" in cards
    assert "legs[0].stops" not in cards or "join(\" → \")" not in cards

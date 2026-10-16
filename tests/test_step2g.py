"""Step 2g page gaps. Fixtures only — these tests do not call live APIs."""

from pathlib import Path

from fastapi.testclient import TestClient

from main import app

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
COPY = ROOT / "static" / "copy.js"

STALE_HEADING = "LTA data is stale"
STALE_UPDATED = "Last update: {time}"
STALE_BODY = (
    "Due to stale data, we cannot give a catch probability or recommend leaving now. "
    "Please wait for live data or try again later."
)
LOCATION_HEADING = "Location uncertain"
LOCATION_BODY = (
    "Your GPS accuracy is {accuracy}. We'll show a wider range for the catch "
    'probability and won\'t suggest \\"leave now\\" from this fix.'
)


def test_arrive_by_sits_on_step_one_and_a_blank_value_omits_the_query():
    html = INDEX.read_text(encoding="utf-8")
    form = html.split('id="destination-form"', 1)[1].split("</form>", 1)[0]
    assert 'id="arrive-by"' in form
    assert 'type="datetime-local"' not in form and 'id="arrive-by-time"' in form and 'type="time"' in form
    assert "arrive-by-block" not in html
    overview = html.split('id="leave-by-section"', 1)[1].split('id="reroute-block"', 1)[0]
    assert 'id="journey-comparison"' in overview
    assert 'id="arrive-by-chosen"' in overview
    assert 'id="arrive-by-edit"' in overview
    assert ">Edit</a>" in overview
    for name in ("function requestArrivals", "function loadJourney"):
        body = html.split(name, 1)[1]
        gate = body.index("if (arriveByInput.value)")
        param = body.index('"&arrive_by="')
        assert gate < param


def test_the_card_is_one_class_and_the_model_fetches_are_gated():
    html = INDEX.read_text(encoding="utf-8")
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    assert "var AI_EXPLANATION_ENABLED = true;" in html
    begin = html.split("function beginExplanation", 1)[1].split("function syncExplanation", 1)[0]
    assert begin.index("pack.model_enabled !== true") < begin.index('fetch("/api/explain"')  # the pack gates the call
    assert "/api/explain-option" not in html  # Page C shows fixed sentences; the endpoint stays dormant
    assert "#ai-explanation.is-enabled" in css
    assert "AI Explanation" in html


def test_served_page_follows_the_explanation_flag(monkeypatch):
    monkeypatch.setattr("main.ai_explanation_enabled", lambda: False)
    with TestClient(app) as client:
        off = client.get("/")
    assert off.status_code == 200
    assert "var AI_EXPLANATION_ENABLED = false;" in off.text
    monkeypatch.setattr("main.ai_explanation_enabled", lambda: True)
    with TestClient(app) as client:
        on = client.get("/")
    assert "var AI_EXPLANATION_ENABLED = true;" in on.text
    assert "fetch(\"/api/explain\"" in on.text


def test_quality_cards_use_the_locked_copy_and_existing_tints():
    html = INDEX.read_text(encoding="utf-8")
    copy = COPY.read_text(encoding="utf-8")
    for text in (STALE_HEADING, STALE_UPDATED, STALE_BODY, LOCATION_HEADING, LOCATION_BODY):
        assert text in html
        assert text in copy
    assert "banner--denied" in html.split('id="quality-banner"', 1)[1].split(">", 1)[0]
    assert "card--caution" in html.split('id="location-card"', 1)[1].split(">", 1)[0]
    sync = html.split("function syncQuality()", 1)[1].split("function activePlannedLeg", 1)[0]
    assert "displayFrozen" in html.split("function qualityState()", 1)[1].split("function staleArrivingText", 1)[0]
    assert 'chance.data_quality === "location uncertain"' in html.split("function locationCardApplies()", 1)[1].split("function syncQuality", 1)[0]
    assert "locationCardApplies()" in sync


def test_dead_bus_illustrations_are_gone():
    html = INDEX.read_text(encoding="utf-8")
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    assert "buddy-bus" not in html
    assert "companion-bus" not in html
    assert 'class="route-bus"' not in html
    assert ".buddy-bus" not in css
    assert ".companion-bus" not in css
    assert ".route-bus" not in css
    assert "route-motif" not in html

"""The spare line is gone, the late wording stays in "If you miss it", and the Arrive-by check badge moves into the AI card."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def _page() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    return text.split(start, 1)[1].split(end, 1)[0]


def test_no_spare_or_on_target_line_exists_anywhere():
    html = _page()
    copy = (STATIC / "copy.js").read_text(encoding="utf-8")
    guide = (STATIC / "styleguide.html").read_text(encoding="utf-8")
    for text in (html, copy, guide):
        for gone in ("to spare", "right on your target", "journey-spare", "tile-spare", "overview-arrive-spare", "sparePhrase",
                     "spare-line", "arriveBy.spare", "arriveBy.onTarget", "missWithSpare"):
            assert gone not in text, gone
    plan = (ROOT / "PROJECT_PLAN.md").read_bytes().decode("utf-8")
    assert "the spare line and the status agree" not in plan


def test_the_late_wording_survives_only_inside_if_you_miss():
    html = _page()
    late = _between(html, "function latePhrase(minutes)", "function estimateSentence")
    assert 'minutes < 0 ? "about " + Math.abs(minutes) + " min late" : ""' in late
    miss = _between(html, "function renderMiss(body)", "function renderPlanningWarning")
    assert "latePhrase(miss.spare_minutes)" in miss and "if (late)" in miss
    assert "Earliest arrival is about" in html  # the planning warning stays
    copy = (STATIC / "copy.js").read_text(encoding="utf-8")
    assert 'late: "about {minutes} min late"' in copy
    assert "{late}" in copy


def test_the_badge_sits_in_the_ai_card_with_the_band_prefix():
    html = _page()
    card = _between(html, 'id="ai-explanation"', "</section>")
    assert card.index('id="ai-badge"') < card.index('class="ai-card__head"')  # top left, above the title
    tiles = _between(html, "function renderLeaveTiles()", "// Screen 8")
    assert 'band === "mid" || band === "low"' in tiles and "IF_CATCH_PREFIX + label" in tiles
    assert "aiBadge.hidden = !(badgeText && aiShown)" in tiles  # hidden with no target (no label) or no AI card
    assert "status.hidden = !badgeText || aiShown" in tiles  # under the tiles only when the AI card is not shown
    assert 'var IF_CATCH_PREFIX = "If you catch this bus: ";' in html
    assert "hero.probability.band" in tiles  # the band comes from Python; no number here
    assert not re.search(r"\b(40|50)\b", _between(tiles, "var hero = ", "var aiCard"))
    # Step 9's calculation is untouched.
    journey = (ROOT / "journey.py").read_text(encoding="utf-8")
    assert 'LATE_LABEL = "Arrive-by check: Risk of delay"' in journey and 'ON_TRACK_LABEL = "Arrive-by check: On track"' in journey

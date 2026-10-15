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


def test_the_late_wording_and_the_miss_line_are_gone_from_the_page():
    html = _page()
    assert "latePhrase" not in html and "renderMiss" not in html and 'id="if-you-miss"' not in html
    assert "Earliest arrival is about" in html  # the planning warning stays
    copy = (STATIC / "copy.js").read_text(encoding="utf-8")
    for gone in ('late: "about {minutes} min late"', "{late}", "missLabel", "missWithLate", "missNoSpare", "missWait"):
        assert gone not in copy, gone


def test_no_check_pill_sits_above_the_ai_card():
    html = _page()
    card = _between(html, 'id="ai-explanation"', "</section>")
    assert 'id="ai-badge"' not in html and "ai-card__badge" not in html and "ai-card__badge" not in (STATIC / "components.css").read_text(encoding="utf-8")
    assert card.index('class="ai-card__head"') < card.index('id="ai-explanation-text"')
    tiles = _between(html, "function renderLeaveTiles()", "// Screen 8")
    assert "IF_CATCH_PREFIX" not in html and "If you catch this bus" not in html
    assert "tile-status" not in html and 'id="tile-row"' not in html and 'id="tile-note"' not in html
    assert "aiBadge" not in tiles
    copy = (STATIC / "copy.js").read_text(encoding="utf-8")
    assert "ifCatchPrefix" not in copy and "If you catch this bus" not in copy
    assert "If you catch this bus" not in (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8").replace("`If you catch this bus:` prefix", "")
    # Step 9's calculation is untouched.
    journey = (ROOT / "journey.py").read_text(encoding="utf-8")
    assert 'LATE_LABEL = "Arrive-by check: Risk of delay"' in journey and 'ON_TRACK_LABEL = "Arrive-by check: On track"' in journey

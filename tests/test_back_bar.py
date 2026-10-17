"""The Back arrow under the header, the menu without a Back row, and the progress fill contrast."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")


def test_the_back_arrow_sits_under_the_header_and_the_menu_has_no_back_row():
    header = INDEX.split("<header", 1)[1].split("</header>", 1)[0]
    assert "back-home" not in header and ">Back<" not in header
    after = INDEX.split("</header>", 1)[1][:900]
    assert 'id="back-bar"' in after and 'id="back-home"' in after and 'aria-label="Back"' in after
    assert INDEX.count('id="back-home"') == 1


def test_the_back_bar_is_hidden_on_home_not_sticky_and_a_44_px_target():
    assert 'bar.hidden = screenStack[screenStack.length - 1] === "home"' in INDEX
    block = CSS.split(".back-bar {", 1)[1].split("}", 1)[0]
    for forbidden in ("position:", "sticky", "fixed", "top:", "z-index", "safe-area-inset-top"):
        assert forbidden not in block, forbidden  # it sits in the page flow and scrolls away with the page
    assert "background: var(--color-card)" in block and "var(--color-bg)" not in block
    # a rounded block like the header: the card surface, a 1 px line, the card shadow and the card radius
    assert "border: 1px solid var(--color-line)" in block and "box-shadow: var(--shadow-card)" in block
    assert "border-radius: var(--radius-card)" in block and "backdrop-filter" not in block
    button = CSS.split(".back-bar__button {", 1)[1].split("}", 1)[0]
    assert "background" not in button and "border" not in button  # the look comes from the menu button's shared rule
    base = CSS.split(".button,\n.field__control,", 1)[1].split("}", 1)[0]
    assert ".icon-button" in base and "min-height: var(--tap-min)" in base  # 44 px, as the menu button
    assert "hover" not in button and ".back-bar__button:hover" not in CSS


def _lum(hexcolor):
    rgb = [int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_progress_fill_has_3_to_1_against_its_track_in_both_themes():
    light = re.search(r"--status-live:\s*(#[0-9A-Fa-f]{6})", THEME).group(1)
    light_line = re.search(r"--color-line:\s*(#[0-9A-Fa-f]{6})", THEME).group(1)
    dark_live = re.findall(r"--status-live:\s*(#[0-9A-Fa-f]{6})", THEME)[1]
    dark_line = re.findall(r"--color-line:\s*(#[0-9A-Fa-f]{6})", THEME)[1]
    assert _ratio(light, light_line) >= 3 and _ratio(dark_live, dark_line) >= 3
    assert "--prob-ring-ok: var(--status-live)" in THEME

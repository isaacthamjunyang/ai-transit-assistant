"""Saved-place chips on Home are styled as the Arrive by chips: unselected they have the same light outline token, fill, radius and
text colour (no green outline); selected they have the same blue selected outline. The Add place chip and the Edit / Done button
are unchanged, and selecting moves nothing. 320, 360 and 1280 px, light and dark. No live API."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
COMBOS = [(w, d) for w in (320, 360, 1280) for d in (False, True)]


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [int(value) for value in re.findall(r"\d+", text)[:3]]


def _lum(rgb):
    c = [v / 255 for v in rgb]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    high, low = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture(scope="module", params=COMBOS, ids=[f"{w}-{'dark' if d else 'light'}" for w, d in COMBOS])
def run(request, tmp_path_factory):
    width, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(f"chips{width}{dark}")) as base:
        return run_scenario("savedchips", base, {"width": width, "height": 800, "dark": dark}, timeout=300)["result"]


def test_an_unselected_saved_chip_equals_an_unselected_arrive_by_chip(run):
    saved, arrive, tokens = run["unselected"], run["arriveUnselected"], run["tokens"]
    for key in ("borderWidth", "borderStyle", "border", "background", "color", "radius", "shadow"):
        assert saved[key] == arrive[key], key
    assert _rgb(saved["border"]) == _rgb(tokens["line"]) and _rgb(saved["border"]) != _rgb(tokens["outlineSuccess"])  # no green
    assert _rgb(run["unselectedLong"]["border"]) == _rgb(tokens["line"])
    assert _contrast(saved["color"], saved["background"]) >= 4.5  # the text


def test_a_selected_saved_chip_equals_a_selected_arrive_by_chip(run):
    saved, arrive, tokens = run["selected"], run["arriveSelected"], run["tokens"]
    for key in ("borderWidth", "border", "background", "color", "radius", "shadow"):
        assert saved[key] == arrive[key], key
    blue = _rgb(tokens["outlineSelected"])
    assert saved["shadow"].replace(" ", "") == f"rgb({blue[0]},{blue[1]},{blue[2]})0px0px0px2px"
    assert _contrast(tokens["outlineSelected"], tokens["card"]) >= 3.0  # the selected outline
    assert run["arriveSelectedState"] == "true|true"
    assert run["selectedCount"] == 1 and "is-selected" in saved["cls"] and saved["pressed"] == "true"  # a state in the markup, not colour alone
    assert all(other["pressed"] == "false" and "is-selected" not in other["cls"] for other in run["others"])
    assert saved["text"] == "Work"  # the text label stays


def _relative(geometry):
    """Each chip's box relative to the first chip: the prompt that a first tap shows (pick an Arrive by) may move the whole row."""
    left, top = geometry[0][0], geometry[0][1]
    return [[round(x - left, 1), round(y - top, 1), w, h] for x, y, w, h in geometry]


def test_selecting_a_chip_moves_and_resizes_nothing(run):
    assert _relative(run["geometryBefore"]) == _relative(run["geometryAfter"])
    assert run["selected"]["w"] == run["unselected"]["w"] and run["selected"]["h"] == run["unselected"]["h"]
    assert run["selected"]["borderWidth"] == run["unselected"]["borderWidth"] == "1px"  # the ring is a shadow
    assert run["scroll"]["scrollWidth"] <= run["scroll"]["innerWidth"]


def test_add_place_and_edit_are_unchanged_and_every_target_is_44px(run):
    tokens = run["tokens"]
    for name in ("add", "addAfter"):
        add = run[name]
        assert add["borderStyle"] == "dashed" and add["borderWidth"] == "2px" and _rgb(add["border"]) == _rgb(tokens["outlineSuccess"]), name
        assert _contrast(add["color"], add["background"]) >= 4.5 and _contrast(add["border"], add["background"]) >= 3.0, name
    for name in ("edit", "editAfter"):
        edit = run[name]
        assert edit["text"] == "Edit" and edit["borderWidth"] == "2px" and edit["borderStyle"] == "solid", name
        assert _contrast(edit["border"], edit["background"]) >= 3.0 and _contrast(edit["color"], edit["background"]) >= 4.5, name
    for look in (run["unselected"], run["selected"], run["unselectedLong"], run["add"], run["edit"]):
        assert look["h"] >= 44 and look["w"] >= 44


def test_edit_mode_keeps_the_badges_the_size_and_the_layout(run):
    mode = run["editMode"]
    assert len(mode["badges"]) == 3 and all(w >= 44 and h >= 44 for w, h in mode["badges"])  # the delete x badges
    assert _relative(mode["geometry"]) == _relative(run["geometryAfter"])  # nothing moves when edit mode starts
    assert mode["done"]["text"] == "Done" and mode["done"]["pressed"] == "true"
    assert mode["chip"]["borderWidth"] == "1px" and _rgb(mode["chip"]["border"]) == _rgb(run["tokens"]["line"])


def test_the_css_the_style_guide_and_the_plan_say_so():
    block = CSS.replace("\r\n", "\n").split(".saved-chip__main {", 1)[1].split(".saved-chip__name {", 1)[0]
    assert "border-color" not in block and "success" not in block
    assert ".quick-picks .saved-chip__main {\n  padding: 0 19px;\n  border-width: 1px;\n}" in CSS.replace("\r\n", "\n")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block)
    assert "box-shadow: 0 0 0 2px var(--color-card), 0 0 0 4px" not in CSS
    assert "styled as the Arrive by chips" in GUIDE and "apart from the green outline" not in GUIDE and "with a green outline (the name only)" not in GUIDE
    para = PLAN.split("**Saved places (Home).**", 1)[1].split("\n", 1)[0]
    assert "styled as the `Arrive by` chips" in para and "(no green outline)" in para and "the same selected look as a selected `Arrive by` chip" in para
    assert "solid green saved chips" not in PLAN and b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()

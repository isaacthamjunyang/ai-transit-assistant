"""One style for every filled blue button: bold, 16 px or more, no text shadow, no blur or opacity on the label, smoothed text, white on the
fill at 4.5:1 or more, in dark and light at 360 and 1280 px. The pulse stays on Find my route, Select stop, Confirm and Start journey, and
is off on See bus arrival times and See train times. No live API."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
COMBOS = [("l360", 360, 800, False), ("d360", 360, 800, True), ("l1280", 1280, 900, False), ("d1280", 1280, 900, True)]
MUST_EXIST = {"find-route", "select-destination-stop", "confirm-destination-stop", "start-journey", "see-arrivals", "other-bus-options",
              "new-journey-start"}


@pytest.fixture(scope="module", params=COMBOS, ids=["360-light", "360-dark", "1280-light", "1280-dark"])
def run(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp("bb" + name)) as base:
        return run_scenario("bluebuttons", base, {"width": width, "height": height, "dark": dark}, timeout=300)["result"]


def _all(run):
    return [button for key in ("pageC", "addPanel", "deletePanel") for button in run[key]["buttons"]]


def _blue(run):
    return [b for b in _all(run) if b["bg"].replace(" ", "") == _rgb_text(run["pageC"]["blue"]).replace(" ", "")]


def _rgb_text(value):
    value = value.strip()
    if value.startswith("#"):
        value = value.lstrip("#")
        return "rgb(%d, %d, %d)" % tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    return value


def test_every_filled_blue_button_has_the_one_style(run):
    blue = _blue(run)
    ids = {b["id"] for b in blue if b["id"]}
    assert MUST_EXIST <= ids, MUST_EXIST - ids
    assert any(b["text"].startswith("Switch to Bus") for b in blue)  # Page C's Switch buttons
    for b in blue:
        label = b["id"] or b["text"]
        assert int(b["weight"]) >= 700, (label, b["weight"])
        assert b["size"] >= 16, (label, b["size"])
        assert b["shadow"] == "none" and b["filter"] == "none", label
        assert b["labelOpacity"] in (None, "1") and b["labelFilter"] in (None, "none"), label
        assert b["smoothing"] == "antialiased", (label, b["smoothing"])
        if not b["disabled"]:
            assert b["opacity"] == "1", label


def test_text_on_the_fill_is_4_5_to_1_in_this_theme(run):
    for b in _blue(run):
        assert b["ratio"] >= 4.5, (b["id"] or b["text"], b["ratio"])


def test_the_blue_buttons_are_44px_high_where_shown(run):
    for b in _blue(run):
        if b["shown"]:
            assert b["h"] >= 44, (b["id"] or b["text"], b["h"])


def test_the_blue_buttons_use_the_one_shared_rule_and_tokens_only():
    block = CSS.split("/* One style for every filled blue button", 1)[1].split(".primary.primary--icon {", 1)[0]
    for declaration in ("font-size: 1rem;", "font-weight: 700;", "text-shadow: none;", "-webkit-font-smoothing: antialiased;",
                        "background: var(--color-primary);", "color: var(--color-primary-ink);"):
        assert declaration in block, declaration
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block)
    assert "opacity: 1;" in block and "filter: none;" in block  # the label is never faded or blurred
    theme = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
    assert theme.count("--color-primary-ink:") >= 2 and "--color-primary:" in theme


def test_the_pulse_is_on_four_buttons_only():
    for ident, pulses in (("find-route", True), ("select-destination-stop", False), ("confirm-destination-stop", True), ("start-journey", True),
                          ("see-arrivals", False), ("other-bus-options", False), ("new-journey-start", False)):
        tag = INDEX.split(f'id="{ident}"', 1)[0].rsplit("<", 1)[1] + INDEX.split(f'id="{ident}"', 1)[1].split(">", 1)[0]
        assert ("pulse-button" in tag) is pulses, ident
    assert "`Find my route`, `Select stop`, `Confirm` and `Start journey` (one shared class, `pulse-button`) pulse" in PLAN  # Select stop only once a row is chosen
    assert "See arrival times (no pulse)" in GUIDE
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()

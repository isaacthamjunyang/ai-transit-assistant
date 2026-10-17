"""One alert component everywhere. Static checks: no old alert, banner, pill-as-message or notice class is left, every
alert-like class belongs to the shared component, every severity uses tokens only and clears the contrast limits. Browser
checks: every alert of every page (the static ones, the script-built ones) renders with the same radius, padding, border
and icon placement, full width, with no overflow at 320 and 360 px. Nothing here calls an API."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
THEME = (STATIC / "theme.css").read_text(encoding="utf-8")
GUIDE = (STATIC / "styleguide.html").read_text(encoding="utf-8")
COPY = (STATIC / "copy.js").read_text(encoding="utf-8")
ALERT_JS = (STATIC / "alert.js").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")

KINDS = ["warning", "error", "info", "success", "neutral", "simulated"]

# The classes that belong to the shared component (and its two containers).
ALLOWED = {
    "alert", "alert__icon", "alert__body", "alert__text", "alert__meta", "alert__detail", "alert__actions", "alert__toggle",
    "alert--clamp", "alert-stack", "alert-slot", "alert-slot__item", "alert-occupant", "alt-row__alert", "wrap--notices",
} | {f"alert--{kind}" for kind in KINDS}

# Old message classes that must not come back.
OLD = ("banner", "alert-row", "info-box", "field-help", "field-error", "reroute-warning", "page-c-warn", "alt-row__warn",
       "planning-banner", "train-alert", "train-alerts", "pace-chip", "pace-walk", "reroute-confirm", "reroute-notice",
       "reroute-none", "demo-banner", "unlikely-banner", "catch-warning", "arrival-warning", "notification-card",
       "leave-now-banner", "overview-reason", "leave-tile__warn", "arrive-box__status", "on-way-alert", "card--info",
       "card--caution", "card--success", "card--unavailable", "card--simulated")


def _class_tokens(text, css=False):
    """Every class name in class="..." attributes and className strings; for a stylesheet, in its selectors."""
    found = set()
    for value in re.findall(r'class=\\?"([^"\\]*)', text):
        found.update(value.split())
    for value in re.findall(r'className = \\?"([^"\\]*)', text):
        found.update(value.split())
    if css:
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for selector in re.findall(r"([^{}]+)\{", stripped):
            found.update(re.findall(r"\.([A-Za-z][\w-]*)", selector))
    return found


def test_no_old_alert_banner_or_notice_class_is_left_anywhere():
    for name, text in (("index.html", INDEX), ("components.css", CSS), ("styleguide.html", GUIDE), ("copy.js", COPY)):
        classes = _class_tokens(text, css=name == "components.css") if name != "copy.js" else set()
        for old in OLD:
            assert old not in classes, (name, old)
    # the ids of a few alerts keep their old names; only classes are checked above, ids are not classes
    assert 'id="unlikely-banner"' in INDEX and 'id="catch-warning"' in INDEX


def test_every_alert_like_class_belongs_to_the_shared_component():
    pattern = re.compile(r"alert|banner|notice|warning|error|toast|callout|message|status-line", re.I)
    for name, text in (("index.html", INDEX), ("components.css", CSS), ("styleguide.html", GUIDE),
                       ("saved-places.js", (STATIC / "saved-places.js").read_text(encoding="utf-8")),
                       ("walk-speed.js", (STATIC / "walk-speed.js").read_text(encoding="utf-8")),
                       ("first-run.js", (STATIC / "first-run.js").read_text(encoding="utf-8"))):
        for raw in sorted(_class_tokens(text, css=name == "components.css")):
            cls = raw.strip("'\"")
            if pattern.search(cls) and cls != "alert--":  # "alert--" is the prefix a script joins to a severity
                assert cls in ALLOWED, f"{name}: a new alert-like class '{cls}' is outside the shared alert component"


def test_every_static_alert_has_an_icon_first_and_text():
    for source in (INDEX, GUIDE):
        for match in re.finditer(r'<(?:div|section)[^>]*class="[^"]*\balert alert--\w+[^"]*"[^>]*>(.*?)</(?:div|section)>', source, re.S):
            body = match.group(1)
            assert body.startswith('<span class="alert__icon" aria-hidden="true"></span>') or re.match(r"['\"] \+ SG_ICON \+ ['\"]", body), body[:120]
            assert "alert__text" in body


def test_the_script_half_draws_one_icon_per_severity():
    for kind in KINDS:
        assert f'"{kind}"' in ALERT_JS.split("var ALERT_KINDS = [", 1)[1].split("];", 1)[0], kind
    for kind in ("warning", "error", "info", "success"):
        assert f"  {kind}: " in ALERT_JS.split("var ALERT_ICON_BODIES = {", 1)[1], kind
    assert ".style" not in ALERT_JS and "style=" not in ALERT_JS  # classes only, no inline style


def test_the_component_css_is_tokens_only_and_each_severity_sets_a_tint_and_an_ink():
    block = CSS.split("/* The one alert component.", 1)[1].split(".card h3,", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", block)
    assert "border: 1px solid var(--alert-ink);" in block and "border-radius: var(--radius-card);" in block
    assert "width: 100%;" in block and "font-weight: 700;" in block
    for kind in KINDS:
        rule = block.split(f".alert--{kind} {{", 1)[1].split("}", 1)[0]
        assert "--alert-tint: var(--" in rule and "--alert-ink: var(--" in rule, kind


# ---- contrast: text 4.5:1 on its tint, border 3:1 on the page and on the card, both themes -------------------------------


def _tokens(block):
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{6})", block))


def _theme(name):
    if name == "light":
        block = THEME.split(':root[data-theme="light"],', 1)[1].split("\n}", 1)[0]
    else:
        block = THEME.split(':root[data-theme="dark"],', 1)[1].split("\n}", 1)[0]
    tokens = _tokens(THEME.split(":root {", 1)[1].split("\n}", 1)[0])
    tokens.update(_tokens(block))
    return tokens


def _lum(hex6):
    channels = [int(hex6[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


PAIRS = {
    "warning": ("--tint-warning", "--status-uncertain"), "error": ("--tint-danger", "--status-unavailable"),
    "info": ("--color-secondary", "--color-secondary-ink"), "success": ("--tint-success", "--status-live"),
    "neutral": ("--tint-neutral", "--status-no-history"), "simulated": ("--tint-simulated", "--status-simulated"),
}


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("kind", KINDS)
def test_each_severity_clears_the_contrast_limits(theme, kind):
    tokens = _theme(theme)
    tint, ink = (tokens[name] for name in PAIRS[kind])
    declared = CSS.split(f".alert--{kind} {{", 1)[1].split("}", 1)[0]
    assert f"--alert-tint: var({PAIRS[kind][0]});" in declared and f"--alert-ink: var({PAIRS[kind][1]});" in declared
    assert _ratio(tint, ink) >= 4.5, (kind, theme, _ratio(tint, ink))  # text on its tint
    assert _ratio(ink, tokens["--color-paper"]) >= 3, (kind, theme)  # the 1px border against the page
    assert _ratio(ink, tokens["--color-card"]) >= 3, (kind, theme)  # and against a card


# ---- the real page ---------------------------------------------------------------------------------------------------

VIEWPORTS = [(320, 700, False), (360, 800, True), (1280, 900, False), (1280, 900, True)]


@pytest.fixture(scope="module", params=VIEWPORTS, ids=[f"{w}-{'dark' if d else 'light'}" for w, _, d in VIEWPORTS])
def alerts(request, tmp_path_factory):
    width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp("alerts")) as base:
        return run_scenario("alerts", base, {"width": width, "height": height, "dark": dark}, timeout=240)["result"]["measured"], width


def test_every_alert_of_every_page_has_the_same_radius_padding_border_and_icon_place(alerts):
    measured, width = alerts
    rows = measured["alerts"]
    assert len(rows) >= 40, len(rows)  # the markup's alerts plus the script-built ones
    for key in ("radius", "padding", "border", "fontWeight", "fontSize", "iconW", "iconLeft"):
        assert len({row[key] for row in rows}) == 1, (key, sorted({str(row[key]) for row in rows}))
    first = rows[0]
    assert first["radius"] == "12px" and first["border"] == "1px solid" and first["iconW"] == 26 and first["iconLeft"] == 13
    assert all(row["hasIcon"] and row["iconFirst"] and row["text"] for row in rows)  # icon and text, always
    assert all(row["inlineStyle"] == 0 for row in rows)


def test_every_alert_is_the_full_width_of_its_container_and_never_overflows(alerts):
    measured, width = alerts
    for row in measured["alerts"]:
        assert row["width"] == row["hostWidth"], row
        assert row["right"] <= row["viewport"], row
    assert measured["scrollWidth"] <= measured["innerWidth"] == width


def test_every_severity_and_every_page_is_covered_and_buttons_are_44_px(alerts):
    measured, _ = alerts
    rows = measured["alerts"]
    assert {row["kind"] for row in rows} >= set(KINDS)
    pages = {row["page"] for row in rows}
    for needed in ("destination-form", "destination-confirm", "destination-stop-panel", "journey-overview", "on-way",
                   "new-journey", "alert-slot", "arrival-card", "built", "pace", "train"):
        assert needed in pages, (needed, sorted(pages))
    for row in rows:
        assert all(height >= 44 for height in row["buttons"]), row


def _rgb(text):
    return [int(v) for v in re.findall(r"\d+", text)[:3]]


def _rl(rgb):
    channels = [c / 255 for c in rgb]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _cr(a, b):
    hi, lo = sorted((_rl(_rgb(a)), _rl(_rgb(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_rendered_text_and_border_colours_clear_the_limits(alerts):
    measured, _ = alerts
    for row in measured["alerts"]:
        assert _cr(row["color"], row["background"]) >= 4.5, row
        assert _cr(row["borderColor"], measured["hostBg"]) >= 3, row


def test_the_plan_names_the_shared_alert_component():
    assert "One shared alert component." in PLAN and "static/alert.js" in PLAN
    assert "compact label tags" in PLAN

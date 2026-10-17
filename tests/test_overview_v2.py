"""The approved journey overview design (tmp/design/overview-v2.html): static checks on the CSS and the page, and the real
page at 360 and 1280 px in both themes, with a stubbed OneMap (nothing here calls an API)."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_overview_legs import ALL, TABLE
from test_ride_apps import _walk_only
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")


def _block(selector):
    return CSS.split("\n" + selector + " {", 1)[1].split("}", 1)[0]


def test_the_leg_group_is_a_bordered_card_in_the_ring_colour_and_rows_have_no_hairline():
    block = CSS.split("--leg-inset: var(--space-2);", 1)[1].split("}", 1)[0]
    assert "border: 2px solid var(--leg-ring);" in block and "background: var(--color-card);" in block
    assert "journey-step + .journey-step::after" not in CSS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block)


def test_the_summary_is_the_secondary_card_with_a_large_total_time_and_keeps_the_transfer_rule():
    block = _block(".overview-summary")
    assert "background: var(--color-secondary);" in block and "border-left: 6px solid var(--summary-accent);" in block
    assert "--summary-accent: var(--status-live);" in block
    assert ".overview-summary__cell:first-child .overview-summary__value" in CSS
    assert "clamp(2rem, 10vw, 3rem)" in CSS


def test_the_arrive_card_keeps_the_locked_line_in_two_spans_and_the_time_never_wraps():
    assert 'var ARRIVE_LINE = "Arrive by: {time}";' in INDEX
    assert 'leadEl.className = "arrive-box__lead";' in INDEX and 'timeEl.className = "arrive-box__time";' in INDEX
    assert "white-space: nowrap;" in _block(".arrive-box__time") and "arrive-box__next" in INDEX  # (tomorrow) is its own span
    assert 'arrive-box__time' in GUIDE and "Arrive by" in PLAN


def test_the_empty_answer_has_full_width_buttons_and_the_two_column_ride_grid():
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in _block(".ride-apps__list")
    assert ".ride-apps__list li:last-child:nth-child(odd)" in CSS
    assert "min-height: 3rem;" in _block(".overview-state__actions .secondary")
    assert "No transit right now. Open a ride app:" in INDEX


def test_the_plan_says_the_approved_design_supersedes_the_mockup_for_the_overview():
    assert "tmp/design/overview-v2.html" in PLAN and "supersedes the mockup for this screen" in PLAN


CONFIGS = [(360, 900, False), (360, 900, True), (1280, 900, False), (1280, 900, True)]
IDS = [f"{w}-{'dark' if d else 'light'}" for w, _, d in CONFIGS]


def _run(tmp_path_factory, name, builders, table, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode(builders), rail_table=table) as base:
        return run_scenario("overviewv2", base, {"name": name, **config})["result"]


@pytest.fixture(scope="module", params=CONFIGS, ids=IDS)
def route(request, tmp_path_factory):
    width, height, dark = request.param
    return _run(tmp_path_factory, "ov2route", ALL, TABLE, width=width, height=height, dark=dark)


@pytest.fixture(scope="module", params=CONFIGS, ids=IDS)
def empty(request, tmp_path_factory):
    width, height, dark = request.param
    builders = {"TRANSIT": _walk_only, "BUS": _walk_only, "RAIL": None}
    return _run(tmp_path_factory, "ov2empty", builders, _table(), width=width, height=height, dark=dark, empty=True)


def test_route_state_groups_summary_and_arrive_card(route, request):
    route_width = int(request.node.callspec.id.split("-")[0])
    first = route["first"]
    assert first["cardBg"] == "rgba(0, 0, 0, 0)" and first["cardBorder"] == "0px" and first["cardPad"] == "0px"  # no outer card
    assert first["titleSize"] == "26px"
    assert len(first["groups"]) >= 2
    for group in first["groups"]:
        assert group["border"] == "2px" and group["style"] == "solid" and group["radius"] != "0px"
    assert all(content in ("none", "normal") for content in first["afters"])  # no hairlines between rows
    assert first["sumBar"] == "6px" and first["heroSize"] and float(first["heroSize"][:-2]) >= 32
    total, transfers, walking = first["cells"]
    assert total["x"] < transfers["x"] and abs(transfers["x"] - walking["x"]) < 1 and transfers["y"] < walking["y"]
    assert first["arriveLead"] == "Arrive by:" and re.fullmatch(r"\d{1,2}:\d{2} [AP]M", first["arriveTime"])
    assert first["arriveText"] == "Arrive by: " + first["arriveTime"] + (" (tomorrow)" if first["arriveNext"] else "")  # the locked line
    assert first["arriveTimeLines"] == 1
    assert first["scrollWidth"] <= first["innerWidth"] == route_width


def test_route_state_targets_and_long_names(route):
    for tap in route["first"]["taps"]:
        assert tap["h"] >= 44 and tap["w"] >= 44, tap
    long_names = route["longNames"]
    assert long_names["scrollWidth"] <= long_names["innerWidth"], long_names


def test_empty_state_buttons_and_ride_grid(empty):
    first = empty["first"]
    assert first["rideShown"] is True and first["scrollWidth"] <= first["innerWidth"]
    assert first["cardBg"] == "rgba(0, 0, 0, 0)"
    ride = first["ride"]
    assert len(ride) == 5 and all(link["h"] >= 44 for link in ride)
    assert abs(ride[0]["y"] - ride[1]["y"]) < 1 and ride[0]["x"] < ride[1]["x"]  # two columns
    assert ride[4]["w"] > ride[0]["w"] * 1.8  # the fifth takes the full row
    for tap in first["taps"]:
        assert tap["h"] >= 44, tap


def _rgb(text):
    return [int(v) for v in re.findall(r"\d+", text)[:3]]


def _lum(rgb):
    ch = [c / 255 for c in rgb]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def _ratio(a, b):
    hi, lo = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_priority_select_is_prominent_readable_and_does_not_shift(route):
    select = route["first"]["select"]
    assert select["box"]["h"] >= 48 and abs(select["box"]["w"] - select["wrap"]["w"]) < 1  # 48 px, full width
    assert select["border"] == "2px" and select["appearance"] == "none" and select["aria"] == "Priority"
    assert select["size"] == "16px" and select["weight"] == "700"  # the row titles' type
    assert select["size"] == select["titleSize"] and select["weight"] == select["titleWeight"]
    assert select["family"] == select["titleFamily"]
    assert _ratio(select["color"], select["bg"]) >= 4.5, select  # text
    assert _ratio(select["borderColor"], select["bg"]) >= 3, select  # outline
    chevron = select["chevron"]
    assert chevron and chevron["w"] >= 20 and chevron["right"] <= select["box"]["right"] - 8  # drawn, inside the box
    assert route["shift"]["before"] == route["shift"]["after"]  # no layout shift


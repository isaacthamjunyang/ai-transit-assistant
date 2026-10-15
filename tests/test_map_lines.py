"""The route lines of the map (plan_edits_9 4.3): tokens, 3:1 contrast in both themes, and how the page draws each leg."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
CODES = ["ns", "ew", "cg", "ne", "cc", "dt", "te", "bp", "sk", "pg", "ss"]
CASING = {"light": {"cc"}, "dark": {"ne", "dt", "te"}}


# ---- reading theme.css --------------------------------------------------------------------------------------------


def _blocks() -> list[dict]:
    """Every { ... } block of theme.css that declares tokens, in file order, as {name: value}."""
    found = []
    for body in re.findall(r"\{([^{}]*)\}", THEME):
        found.append(dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body)))
    return found


def _theme(theme: str) -> dict:
    """The tokens of one theme. The four theme blocks (light :root, dark media, light attribute, dark attribute) each hold
    --map-line-ns; the shared line tokens sit in a fifth block that every theme uses."""
    blocks = _blocks()
    holders = [b for b in blocks if "--map-line-ns" in b]
    assert len(holders) == 4
    chosen = holders[0::2] if theme == "light" else holders[1::2]
    merged = {}
    for block in blocks:
        if "--line-ns" in block:
            merged.update(block)
    for block in blocks:
        if "--color-paper" in block and (block in chosen or any(block.get("--color-paper") == c.get("--color-paper") for c in chosen)):
            merged.update(block)
    for block in chosen:
        merged.update(block)
    return merged


def _resolve(tokens: dict, value: str) -> str:
    value = value.strip()
    match = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if match:
        return _resolve(tokens, tokens[match.group(1)])
    return value


def _hex(tokens: dict, name: str) -> str | None:
    value = _resolve(tokens, tokens[name])
    return None if value == "none" else value.lstrip("#").upper()


def _luminance(hex6: str) -> float:
    channels = [int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ---- contrast ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_line_is_at_least_3_to_1_on_the_land_or_through_its_casing(theme):
    tokens = _theme(theme)
    land = _hex(tokens, "--map-land-standin")
    assert land == ("EEF4F8" if theme == "light" else "16223A")
    for code in CODES:
        line, casing = _hex(tokens, f"--map-line-{code}"), _hex(tokens, f"--map-line-{code}-casing")
        direct = _ratio(line, land)
        if casing is None:
            assert direct >= 3, (theme, code, round(direct, 2))
        else:
            assert _ratio(casing, land) >= 3 and _ratio(line, casing) >= 3, (theme, code)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_a_casing_exists_exactly_where_the_colour_alone_is_under_3_to_1(theme):
    tokens = _theme(theme)
    land = _hex(tokens, "--map-land-standin")
    needs = {code for code in CODES if _ratio(_hex(tokens, f"--map-line-{code}"), land) < 3}
    has = {code for code in CODES if _hex(tokens, f"--map-line-{code}-casing") is not None}
    assert needs == has == CASING[theme], (theme, needs, has)


def test_the_bus_and_walk_lines_are_at_least_3_to_1_on_the_land_in_both_themes():
    for theme in ("light", "dark"):
        tokens = _theme(theme)
        land = _hex(tokens, "--map-land-standin")
        assert _ratio(_hex(tokens, "--map-line-bus"), land) >= 3, theme
        assert _ratio(_hex(tokens, "--map-walk-line"), land) >= 3, theme


def test_the_line_tokens_point_at_the_badge_fills_and_hold_the_only_casing_colours():
    for theme in ("light", "dark"):
        tokens = _theme(theme)
        for code in CODES[:-1]:
            assert tokens[f"--map-line-{code}"].strip() == f"var(--line-{code})"
        assert tokens["--map-line-bus"].strip() == "var(--color-primary)"
    assert _theme("light")["--map-line-cc-casing"].strip() == "var(--color-ink)"
    assert {_hex(_theme("dark"), f"--map-line-{c}-casing") for c in CASING["dark"]} == {"FFFFFF"}


def test_the_page_reads_tokens_only_and_draws_by_pattern():
    region = INDEX.split("function legPath(leg)", 1)[1].split("function walkPhrase(metres)", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", region)
    assert ".style." not in region and "style=" not in region
    for token in ('cssToken("--map-walk-line")', 'cssToken("--map-line-bus")', 'cssToken("--map-line-" + code)',
                  'cssToken("--map-line-" + code + "-casing")'):
        assert token in region, token
    assert 'dashArray: "5, 10"' in region and 'dashArray: dotted ? "1, 9" : ""' in region
    for label in ('"BOARD"', '"CHANGE"', '"EXIT"'):
        assert f"routePin(" in region and label in region
    assert "routeDestinationFlag(place)" in region  # the destination is the green flag (tests/test_map_markers.py)
    assert "TRANSFER" not in region  # the old two-leg drawing is gone


def test_the_style_guide_shows_each_line_style_in_both_themes():
    assert "function sgMapLines()" in GUIDE and "sgMapLines()" in GUIDE.split("function legsSample()", 1)[1]
    for code in CODES:
        assert f".map-line-sample--{code} .map-line-sample__line" in CSS and f"stroke: var(--map-line-{code}-casing)" in CSS
    assert "stroke: var(--map-walk-line)" in CSS and "stroke-dasharray: 5 10" in CSS and "stroke-dasharray: 1 9" in CSS
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(", CSS.split("/* Style guide: the route lines", 1)[1].split(".overview-state__actions {", 1)[0])


# ---- the page's map in a browser -------------------------------------------------------------------------------------


def _run(tmp_path_factory, name, builder, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode({"TRANSIT": builder})) as base:
        return run_scenario("routemap", base, {"name": name, **config})["result"]


@pytest.fixture(scope="module")
def mixed_light(tmp_path_factory):
    return _run(tmp_path_factory, "mixedlight", stub.mixed, width=390)


@pytest.fixture(scope="module")
def casing_light(tmp_path_factory):
    return _run(tmp_path_factory, "casinglight", stub.casings, width=390)


@pytest.fixture(scope="module")
def casing_dark(tmp_path_factory):
    return _run(tmp_path_factory, "casingdark", stub.casings, width=390, dark=True)


def _norm(color: str) -> str:
    return color.strip().lstrip("#").upper()


def test_each_leg_kind_is_drawn_in_its_own_pattern(mixed_light):
    layers, tokens = mixed_light["layers"], mixed_light["tokens"]
    assert len(layers) == 9  # the approach, then eight legs, no casing in light for these lines
    approach, *legs = layers
    assert approach["dash"] == "5, 10" and _norm(approach["color"]) == _norm(tokens["walk"])
    kinds = ["walk", "bus", "walk", "ns", "ew", "walk", "bp", "walk"]
    for leg, kind in zip(legs, kinds):
        if kind == "walk":
            assert (leg["dash"], leg["weight"], _norm(leg["color"])) == ("5, 10", 3, _norm(tokens["walk"]))
        elif kind == "bus":
            assert (leg["dash"], leg["weight"], _norm(leg["color"])) == ("", 5, _norm(tokens["bus"]))
        elif kind in ("ns", "ew"):
            assert (leg["dash"], leg["weight"], _norm(leg["color"])) == ("", 6, _norm(tokens[kind]))
        else:  # the LRT is dotted
            assert (leg["dash"], leg["weight"], leg["cap"], _norm(leg["color"])) == ("1, 9", 6, "round", _norm(tokens[kind]))
    assert all(layer["points"] >= 2 for layer in layers)  # drawn from the decoded paths, not from two stops


def test_the_pins_are_board_change_exit_and_the_destination_flag(mixed_light):
    assert mixed_light["pins"] == ["BOARD", "CHANGE", "CHANGE", "CHANGE", "EXIT", "FLAG Destination"]
    assert not any("TRANSFER" in pin for pin in mixed_light["pins"])


def test_cc_gets_an_ink_casing_in_light_and_nothing_else_does(casing_light):
    layers, tokens = casing_light["layers"], casing_light["tokens"]
    wide = [layer for layer in layers if layer["weight"] == 10]
    assert len(wide) == 1 and _norm(wide[0]["color"]) == _norm(tokens["cc_casing"])
    index = layers.index(wide[0])
    assert layers[index + 1]["weight"] == 6 and _norm(layers[index + 1]["color"]) == _norm(tokens["cc"])  # the line sits on it
    assert [l["weight"] for l in layers].count(6) == 4 and casing_light["pins"][-2:] == ["EXIT", "FLAG Destination"]


def test_ne_dt_and_te_get_a_white_casing_in_dark_and_cc_does_not(casing_dark):
    layers, tokens = casing_dark["layers"], casing_dark["tokens"]
    wide = [layer for layer in layers if layer["weight"] == 10]
    assert len(wide) == 3 and {_norm(layer["color"]) for layer in wide} == {"FFFFFF"}
    colours = [_norm(layer["color"]) for layer in layers if layer["weight"] == 6]
    assert colours == [_norm(tokens[code]) for code in ("cc", "ne", "dt", "te")]
    for layer in wide:
        after = layers[layers.index(layer) + 1]
        assert after["weight"] == 6 and _norm(after["color"]) in {_norm(tokens[c]) for c in ("ne", "dt", "te")}

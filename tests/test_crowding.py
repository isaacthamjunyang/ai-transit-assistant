"""Bus crowding: the LTA Load field (SEA, SDA, LSD) is carried as a display-only label. A blank, missing or unknown value
is None. It never changes the probability. No live service is called."""

import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import catch_heuristic
from arrivals import fetch_arrivals
from test_arrivals import ACCOUNT_KEY, FETCHED, _client, _payload

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
SGT = timezone(timedelta(hours=8))


def _loads(values):
    payload = _payload()
    service = payload["Services"][0]
    for key, value in zip(("NextBus", "NextBus2", "NextBus3"), values):
        if value is _MISSING:
            service[key].pop("Load", None)
        else:
            service[key]["Load"] = value
    with _client(payload) as client:
        result = fetch_arrivals("08057", "36", client=client, account_key=ACCOUNT_KEY, now=FETCHED)
    return [bus["load"] for bus in result["buses"]]


_MISSING = object()


@pytest.mark.parametrize("code", ["SEA", "SDA", "LSD"])
def test_each_guide_value_is_carried(code):
    assert _loads([code, code, code]) == [code, code, code]


def test_blank_missing_and_unknown_values_are_none():
    assert _loads(["", _MISSING, "XYZ"]) == [None, None, None]
    assert _loads([None, 5, " sea "]) == [None, None, "SEA"]


def test_load_never_changes_the_probability():
    now = datetime(2026, 9, 29, 14, 54, 20, tzinfo=SGT)

    def scored(load):
        bus = {"position": "NextBus", "arrival_time": "2026-09-29T14:59:00+08:00", "monitored": True,
               "latitude": None, "longitude": None, "origin_code": None, "destination_code": None, "load": load}
        return catch_heuristic.score_buses(
            [bus], user_lat=1.3005, user_lon=103.8001, accuracy_m=18, stop_lat=1.3, stop_lon=103.8,
            services=[], routes=[], service_no="36", stop_code="08057", now=now,
        )[0]["probability"]

    base = scored(None)
    assert base is not None
    for code in ("SEA", "SDA", "LSD"):
        assert scored(code) == base


def test_the_page_shows_text_and_icon_from_one_place_and_the_plan_says_so():
    block = COPY.split("crowding: {", 1)[1].split("},", 1)[0]
    for key, text in (("SEA", "Seats Available"), ("SDA", "Standing Available"), ("LSD", "Crowded"),
                      ("unknown", "No Data")):
        assert f'{key}: "{text}"' in block
    assert 'var CROWD_TEXT = { SEA: "Seats Available", SDA: "Standing Available", LSD: "Crowded" };' in INDEX
    assert 'var CROWD_UNKNOWN_TEXT = "No Data";' in INDEX
    assert "setCrowd(document.getElementById(\"catch-load\"), hero);" in INDEX and 'id="catch-load"' in INDEX
    assert "**Bus crowding.**" in PLAN and "The Bus Arrival `Load` field is ignored" not in PLAN
    assert "Crowding unknown" not in INDEX + COPY + PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()  # the plan keeps its CRLF line endings


# ---- the colour tokens and their contrast ---------------------------------------------------------------------

THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
TOKENS = {"SEA": "--crowd-seats", "SDA": "--crowd-standing", "LSD": "--crowd-crowded", "UNKNOWN": "--crowd-nodata"}


def _block(which):
    """The light tokens (the first :root block) or the dark tokens (the prefers-color-scheme block)."""
    if which == "light":
        return THEME[:THEME.index(chr(10) + "}")]
    start = THEME.index("@media (prefers-color-scheme: dark)")
    return THEME[start:THEME.index(chr(10) + "  }", start)]


def _token(block, name):
    return re.search(name + r":\s*(#[0-9A-Fa-f]{6})", block).group(1)


def _lum(color):
    channels = [int(color[k:k + 2], 16) / 255 for k in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_each_state_has_a_token_in_theme_css_with_4_5_to_1_on_the_card(theme):
    block = _block(theme)
    card = _token(block, "--color-card")
    for token in TOKENS.values():
        colour = _token(block, token)
        assert _ratio(colour, card) >= 4.5, (theme, token, colour)  # the word; the icon needs 3:1
    # the same four tokens are repeated for the explicit data-theme switches
    for switch in ('[data-theme="light"]', '[data-theme="dark"]'):
        want = _block("dark" if "dark" in switch else "light")
        tail = THEME[THEME.rindex(":root" + switch):]
        for token in TOKENS.values():
            assert _token(tail, token) == _token(want, token), (switch, token)


def test_the_light_amber_is_darker_than_the_dark_theme_amber_and_the_four_states_are_distinct():
    light = _block("light")
    dark = _block("dark")
    assert _lum(_token(light, "--crowd-standing")) < _lum(_token(dark, "--crowd-standing"))
    colours = {_token(light, token) for token in TOKENS.values()}
    assert len(colours) >= 3  # seats, standing and the red pair
    for code, token in TOKENS.items():
        rule = CSS.split(f'.crowd-chip[data-load="{code}"] {{', 1)[1].split("}", 1)[0]
        assert f"color: var({token})" in rule
    assert not re.search(r"#[0-9A-Fa-f]{3,8}" + chr(92) + "b|rgb" + chr(92) + "(|hsl" + chr(92) + "(", CSS.split(".crowd-chip {", 1)[1].split(".bus-tile-card__arriving", 1)[0])


def test_the_icons_are_inline_svg_with_distinct_shapes_for_all_four_states():
    body = INDEX.split("var CROWD_ICONS = {", 1)[1].split("};", 1)[0]
    shapes = {}
    for code in ("SEA", "SDA", "LSD", "UNKNOWN"):
        svg = body.split(f"{code}: '", 1)[1].split("'", 1)[0]
        assert svg.startswith("<svg") and 'viewBox="0 0 24 24"' in svg and "currentColor" in svg
        shapes[code] = re.sub(r"\s+", " ", re.sub(r"<svg[^>]*>|</svg>", "", svg))
    assert len(set(shapes.values())) == 4
    assert "<circle" in shapes["UNKNOWN"] and "M9 9l6 6M15 9l-6 6" in shapes["UNKNOWN"]  # circle with a cross
    assert "M12 11.5L7.5 4M12 11.5l4.5-7.5" in shapes["LSD"]  # raised arms: not the circle with a cross
    assert shapes["UNKNOWN"] != shapes["LSD"]
    guide = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
    for code in ("SEA", "SDA", "LSD", "UNKNOWN"):
        assert f"{code}: " in guide.split("var SG_CROWD_ICONS = {", 1)[1].split("};", 1)[0]
    assert "theme-sample-dark" in guide.split("function crowdingSample()", 1)[1].split("function sgTrainAlert", 1)[0]


# ---- the real page --------------------------------------------------------------------------------------------

from page_runner import require_edge, run_scenario, running_app


def _page(tmp_path_factory, loads, width, dark, name):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), eta_minutes=[10.3, 16.3, 24.3], loads=loads) as base:
        return run_scenario("crowding", base, {"name": name, "width": width, "height": 800, "dark": dark},
                            timeout=300)["result"]


@pytest.fixture(scope="module", params=[(320, False), (360, True), (1280, False), (1280, True)],
                ids=["320-light", "360-dark", "1280-light", "1280-dark"])
def shown(request, tmp_path_factory):
    width, dark = request.param
    return _page(tmp_path_factory, ["SEA", "SDA", "LSD"], width, dark, f"crowd{width}{int(dark)}") | {"dark": dark}


@pytest.fixture(scope="module")
def silent(tmp_path_factory):
    return _page(tmp_path_factory, ["", "XYZ"], 360, False, "crowdnone")


def _rgb(color):
    return "rgb(%d, %d, %d)" % tuple(int(color[k:k + 2], 16) for k in (1, 3, 5))


def test_the_tiles_and_page_a_show_a_word_an_icon_and_the_state_colour(shown):
    tiles = shown["pageB"]["tiles"]
    assert [t["text"] for t in tiles] == ["Seats Available", "Standing Available", "Crowded"]
    assert all(t["icon"] for t in tiles)
    assert shown["pageA"]["catchShown"] is True and shown["pageA"]["catchText"] == "Seats Available"
    assert shown["pageA"]["catchIcon"] is True
    block = _block("dark" if shown["dark"] else "light")
    for tile, code in zip(tiles, ("SEA", "SDA", "LSD")):
        assert tile["code"] == code and tile["color"] == _rgb(_token(block, TOKENS[code])), (code, tile["color"])
    assert shown["pageA"]["catchColor"] == _rgb(_token(block, TOKENS["SEA"]))
    assert len({t["svg"] for t in tiles}) == 3  # three different shapes


def test_no_label_overflows_or_clips_and_the_tiles_stay_one_height(shown):
    tiles = shown["pageB"]["tiles"]
    assert shown["pageB"]["scrollWidth"] <= shown["pageB"]["innerWidth"]
    assert all(t["right"] <= shown["pageB"]["innerWidth"] for t in tiles)
    assert all(t["inside"] is True and t["clipped"] is False for t in tiles)
    assert len({round(t["height"], 1) for t in tiles}) == 1  # equal tile heights
    assert all(t["iconPx"] >= 16 for t in tiles)  # readable at 16 px
    assert shown["pageA"]["catchInside"] is True


def test_a_blank_or_unknown_value_reads_no_data_with_a_red_circle_cross_icon(silent):
    assert silent["pageA"]["catchShown"] is True and silent["pageA"]["catchText"] == "No Data"
    assert silent["pageA"]["catchIcon"] is True and silent["pageA"]["catchCode"] == "UNKNOWN"
    assert [t["text"] for t in silent["pageB"]["tiles"]] == ["No Data"] * 3
    assert all(t["icon"] and t["code"] == "UNKNOWN" for t in silent["pageB"]["tiles"])
    assert silent["pageB"]["loads"][:2] == [None, None]
    assert silent["pageB"]["tiles"][0]["color"] == _rgb(_token(_block("light"), "--crowd-nodata"))
    assert all(t["clipped"] is False and t["inside"] is True for t in silent["pageB"]["tiles"])
    assert len({round(t["height"], 1) for t in silent["pageB"]["tiles"]}) == 1


def test_the_probability_does_not_depend_on_the_load(shown, silent):
    assert shown["pageB"]["probability"] == silent["pageB"]["probability"]


def test_page_b_has_no_walk_line_and_page_a_has_at_most_the_one_in_the_pace_card(shown):
    assert shown["pageB"]["walkLines"] == 0
    assert shown["pageA"]["walkLines"] <= 1


def test_the_no_data_label_is_in_copy_the_page_and_the_style_guide():
    assert 'unknown: "No Data"' in COPY and 'var CROWD_UNKNOWN_TEXT = "No Data";' in INDEX
    guide = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
    assert '"UNKNOWN"' in guide and 'words[code === "UNKNOWN" ? "unknown" : code]' in guide
    assert "`No Data`" in PLAN and "Crowding unknown" not in guide

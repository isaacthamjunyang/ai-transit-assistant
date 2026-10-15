"""The style guide builds every sample with one script. A syntax error in it leaves the guide empty, so check it."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[1] / "static" / "styleguide.html"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_style_guide_script_has_no_syntax_error(tmp_path):
    scripts = re.findall(r"<script>(.*?)</script>", GUIDE.read_text(encoding="utf-8"), re.S)
    assert scripts
    for index, source in enumerate(scripts):
        path = tmp_path / f"guide_{index}.js"
        path.write_text(source, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, encoding="utf-8")
        assert done.returncode == 0, done.stderr[-600:]


# ---- the samples show only values the app can produce

def _guide_texts():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from page_runner import require_edge, run_scenario

    require_edge()
    return run_scenario("guidetexts", "", {"guide": GUIDE.resolve().as_uri()})["result"]


def test_every_style_guide_ring_point_stays_at_or_below_92_percent_and_shows_no_range():
    texts = _guide_texts()
    assert len(texts["points"]) > 15
    bad = [p for p in texts["points"] if p > 92]
    assert not bad, bad  # the ring is capped at 92 percent
    assert texts["ranges"] == [], texts["ranges"]  # a probability on screen is a point, never a range


def test_every_style_guide_leave_sentence_agrees_with_its_numbers():
    import re

    NB = "\u00a0"
    texts = _guide_texts()
    seen = {"by": 0, "now": 0}
    for card in texts["cards"]:
        match = re.search(r"The bus is (\d+) minutes? away, and you are ([\d.]+)" + NB + r"(m|km) from the stop", card)
        if match is None:
            continue
        e = int(match.group(1))
        metres = float(match.group(2)) * (1000 if match.group(3) == "km" else 1)
        kmh = re.search(r"([\d.]+)" + NB + "km/h", card)
        if " Leave by " in card:
            seen["by"] += 1
            speed = float(kmh.group(1)) / 3.6
            assert e * 60 > metres / speed + 195 - 12, card  # more than 60 s to leave-by (the 12 s covers km/h rounding)
            assert "It is advisable" not in card, card
        elif " Leave now to reach your " in card:
            seen["now"] += 1
            assert "It is advisable" not in card, card
            assert e >= 1 and (e == 1 or f"{e} minutes" in card), card  # leave now reads the minutes the tile shows
    assert seen["by"] >= 6 and seen["now"] >= 6, seen


def test_every_style_guide_leave_by_tile_shows_a_time_or_leave_now_never_both():
    import re

    texts = _guide_texts()
    tiles = [t for t in texts["tiles"] if t[0] == "Leave now" or re.fullmatch(r"\d{1,2}:\d\d\u00a0(AM|PM)", t[0])]
    assert len(tiles) >= 6
    for value, meta in tiles:
        # one short line, the walk minutes; no bus-away or in-n-min sentence under Leave by
        assert meta == "" or re.fullmatch(r"\d+.min walk", meta), (value, meta)


def test_every_style_guide_page_w_trend_line_agrees_with_its_state_line():
    texts = _guide_texts()
    samples = texts["walkSamples"]
    assert len(samples) >= 9
    seen = set()
    for state, trend in samples:
        if not trend:
            continue
        seen.add(trend)
        if trend == "Rising as you get closer":
            assert state == "On your way", (state, trend)
        elif trend == "Rising":
            assert state != "On your way", (state, trend)
        elif trend == "Falling as you move away":
            assert state == "Moving away from the stop", (state, trend)
        elif trend == "Falling as time passes":
            assert state != "Moving away from the stop", (state, trend)
        else:
            assert trend == "Steady", (state, trend)
    assert seen == {"Rising as you get closer", "Rising", "Falling as you move away", "Falling as time passes", "Steady"}
    assert ["Not moving", "Falling as time passes"] in samples  # the "Not moving, falling" sample


def test_every_style_guide_sensor_sample_matches_what_the_estimator_can_show():
    NBSP = "\u00a0"
    samples = _guide_texts()["sensorSamples"]
    assert len(samples) >= 5
    for sample in samples:
        rows = sample["rows"]
        if rows["Learned samples"] == "0":
            assert rows["Step length"] == "0.70" + NBSP + "m", rows  # no samples: the starting value, never 0.72
        if sample["why"]:
            assert sample["whyFirst"] is True and sample["icon"] is True, sample  # directly under the title, with an info icon
    near = [s for s in samples if s["why"] == "Near the stop"]
    assert near and all(s["rows"]["Walking pace"] == "4.3" + NBSP + "km/h · from GPS" for s in near)  # measured value and source kept
    assert not any("average pace" in s["rows"]["Walking pace"] for s in near)
    assert {s["why"] for s in samples if s["why"]} == {"Not walking yet", "No motion permission", "Near the stop"}


def test_every_style_guide_near_the_stop_sample_is_a_real_near_stop_state():
    NBSP = " "
    near = [s for s in _guide_texts()["sensorSamples"] if s["why"] == "Near the stop"]
    assert near
    for sample in near:
        match = re.fullmatch(r"(\d+)" + NBSP + r"m to the stop", sample["distance"])
        assert match and int(match.group(1)) <= 30, sample  # near the stop means within 30 m
        assert sample["state"] == "Arrived at the stop", sample
        assert sample["progress"] == 100 and sample["chip"] == "Range: 20" + NBSP + "m", sample  # full bar, zoom 19


def test_the_style_guide_shows_the_at_stop_card_and_tile():
    NB = " "
    texts = _guide_texts()
    assert "You are at the stop. You have 4 minutes to wait." in texts["cards"]
    assert "You are at the stop. You have 1 minute to wait." in texts["cards"]
    assert "You are at the stop. The bus is arriving now." in texts["cards"]
    tiles = [tuple(t) for t in texts["tiles"]]
    assert ("At the stop", "") in tiles  # no subline under "At the stop"
    assert not any(t[0] == "At the stop" and t[1] for t in tiles)
    for card in texts["cards"]:
        if card.startswith("You are at the stop"):
            assert "km/h" not in card and "Leave" not in card

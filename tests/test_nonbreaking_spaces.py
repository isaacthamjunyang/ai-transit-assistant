"""A number never splits from its unit (km/h, min) and a clock time never from AM or PM."""

import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import explain

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
EXPLAIN_SRC = (ROOT / "explain.py").read_text(encoding="utf-8")
NB = "\u00a0"
ESC = chr(92) + "u00a0"  # how the page and copy.js spell it in source
SGT = timezone(timedelta(hours=8))


def test_python_sentence_two_templates_keep_the_number_with_km_h():
    templates = list(explain.S1_SPEED.values())
    assert len(templates) == 3
    for text in templates:
        assert "{kmh}" + NB + "km/h" in text and "{kmh} km/h" not in text, text


def test_python_clock_keeps_the_time_with_am_or_pm():
    now = datetime(2026, 10, 5, 9, 0, tzinfo=SGT)
    for hours in (0, 1, 3, 5, 13, 15):
        text = explain.format_clock(now + timedelta(hours=hours, minutes=3), now)
        assert re.fullmatch(r"\d{1,2}:\d\d" + NB + r"(AM|PM)( \(tomorrow\))?", text), text
    assert " AM" not in explain.format_clock(now, now) and " PM" not in explain.format_clock(now, now)


def test_the_rendered_sentences_hold_the_no_break_spaces():
    now = datetime(2026, 10, 5, 9, 0, tzinfo=SGT)
    numbers = explain.build_numbers(
        bus_minutes=10, walk_minutes=4, chosen_action="wait", distance_m=300.0, walk_speed_used=1.25,
        walk_speed_source="gps", leave_by=(now + timedelta(seconds=600)).isoformat(),
        arrival_time=(now + timedelta(seconds=1200)).isoformat(), now=now)
    text = explain.card_text(numbers, band="ok", uncertain=False)
    assert "4.5" + NB + "km/h" in text and "9:10" + NB + "AM" in text and "9:20" + NB + "AM" in text
    assert "300" + NB + "m" in text


def test_copy_js_page_and_tile_strings_hold_the_no_break_spaces():
    for source in (COPY, INDEX):
        assert source.count("{kmh}" + ESC + "km/h") >= 3
        assert not re.search(r"(about|speed of) \{kmh\} km/h", source)  # the sentence templates only
    for name, expected in (
        ("leaveByIn", "in {n}" + ESC + "min · {w}" + ESC + "min walk"),
        ("leaveByInUnder", "in under 1" + ESC + "min · {w}" + ESC + "min walk"),
        ("leaveNowBusAway", "The bus is {e}" + ESC + "min away and the walk takes about {w}" + ESC + "min."),
        ("leaveNowBusArriving", "The bus is arriving now and the walk takes about {w}" + ESC + "min."),
    ):
        assert f'{name}: "{expected}"' in COPY, name
    for expected in (
        'var LEAVE_TILE_IN_MIN = "in {n}' + ESC + 'min · {w}' + ESC + 'min walk";',
        'var LEAVE_TILE_IN_UNDER = "in under 1' + ESC + 'min · {w}' + ESC + 'min walk";',
        'var LEAVE_TILE_BUS_AWAY = "The bus is {e}' + ESC + 'min away and the walk takes about {w}' + ESC + 'min.";',
        'var LEAVE_TILE_BUS_ARRIVING = "The bus is arriving now and the walk takes about {w}' + ESC + 'min.";',
    ):
        assert expected in INDEX, expected


def test_every_page_clock_joins_the_time_and_am_pm_with_a_no_break_space():
    # formatClock, leaveClockText and the 12-hour clock of formatTime (the arrival range is no longer drawn)
    assert 'parts.hm + "' + ESC + '" + parts.suffix' in INDEX
    assert INDEX.count('parts.hm + " " + parts.suffix') == 0
    assert "function formatRange" not in INDEX
    assert 'hour12 + ":" + minute + "' + ESC + '" + suffix' in INDEX
    assert not re.search(r'\.hm \+ " " \+', INDEX) and 'minute + " " + suffix' not in INDEX


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_clock_and_range_run_with_the_no_break_space():
    def between(text, start, end):
        return start + text.split(start, 1)[1].split(end, 1)[0]

    parts = between(INDEX, "function singaporeParts(date) {", "function pad2(value)")
    clock = between(INDEX, "function formatClock(iso, withTomorrow) {", "// Only the late wording")
    program = parts + clock + (
        'console.log(JSON.stringify([formatClock("2026-10-05T22:03:30+08:00", false),'
        ' leaveClockText("2026-10-05T22:03:30+08:00", Date.parse("2026-10-05T21:00:00+08:00"))]));'
    )
    program = "function leaveClockText(iso, nowMs) { var p = singaporeParts(new Date(iso)); return p.hm + \"" + ESC + "\" + p.suffix; }\n" + program
    done = subprocess.run(["node", "-e", program], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr[-500:]
    import json

    assert json.loads(done.stdout) == ["10:03" + NB + "PM", "10:03" + NB + "PM"]

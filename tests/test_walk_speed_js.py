"""The walking-speed estimator (static/walk-speed.js) with synthetic signals, run in headless Edge.

If Edge is not installed these tests skip and say so.
"""

import html
import json
import re
from pathlib import Path

import pytest

from edge_runner import dump_dom, file_url, find_edge

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "estimator_harness.html"
SCRIPT = ROOT / "static" / "walk-speed.js"
GROUPS = ["cadence", "gps", "learning", "fusion", "persistence", "permission", "lifecycle", "readout", "handheld", "octave"]


@pytest.fixture(scope="module")
def results():
    if find_edge() is None:
        pytest.skip("headless Edge is not installed, so the estimator browser tests did not run")
    dom = dump_dom(file_url(HARNESS), budget_ms=20000)
    match = re.search(r'<pre id="results">(.*?)</pre>', dom, re.S)
    assert match and match.group(1).strip(), "the harness wrote no results: " + dom[:400]
    return json.loads(html.unescape(match.group(1)))


@pytest.mark.parametrize("group", GROUPS)
def test_estimator_group(results, group):
    rows = [row for row in results if row["group"] == group]
    assert rows, f"no tests ran for {group}"
    failed = [f'{row["name"]}: {row["detail"]}' for row in rows if not row["ok"]]
    assert not failed, "\n".join(failed)


def test_every_group_is_run(results):
    assert {row["group"] for row in results} == set(GROUPS)
    assert len(results) >= 60


def test_the_estimator_is_the_only_file_that_uses_local_storage():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "localStorage" in source
    for name in ("index.html", "copy.js", "format-distance.js", "place-icons.js", "sw.js"):
        assert "localStorage" not in (ROOT / "static" / name).read_text(encoding="utf-8")


def test_the_estimator_has_no_remote_or_background_apis():
    source = SCRIPT.read_text(encoding="utf-8")
    for banned in ("serviceWorker", "fetch(", "XMLHttpRequest", "sendBeacon", "indexedDB", "sessionStorage",
                   "Sensor(", "Accelerometer", "console.", "style.", "setAttribute(\"style\""):
        assert banned not in source, banned
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", source)


def test_the_constants_block_has_the_agreed_starting_values():
    source = SCRIPT.read_text(encoding="utf-8")
    block = source.split("var CONSTANTS = {", 1)[1].split("};", 1)[0]
    expected = {
        "CADENCE_MIN": "1.2", "CADENCE_MAX": "2.8", "WINDOW_S": "8", "AUTOCORR_MIN": "0.3",
        "GPS_ACC_MAX_USE": "30", "GPS_ACC_MAX_LEARN": "15",
        "LEARN_SPEED_MIN": "0.7", "LEARN_SPEED_MAX": "2.0", "VEHICLE_SPEED_MIN": "2.2",
        "STEADY_CV_MAX": "0.15", "LEARN_MIN_STEADY_S": "15", "LEARN_ALPHA": "0.2",
        "STEP_LEN_PRIOR": "0.70", "STEP_LEN_MIN": "0.45", "STEP_LEN_MAX": "0.95",
        "CADENCE_MODE_MIN_SAMPLES": "3", "HOLD_STANDING_S": "30", "SMOOTH_TAU_S": "10",
        "SLEW_MPS_PER_POLL": "0.15", "REMEMBER_MIN_WALK_S": "60", "REMEMBER_MAX_AGE_DAYS": "30",
    }
    for name, value in expected.items():
        assert re.search(rf"\b{name}: {re.escape(value)},", block), name

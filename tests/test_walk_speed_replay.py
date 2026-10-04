"""Replay of two real iPhone recordings through the real estimator (tests/js/replay.js, run with Node).

The two fixtures in tests/fixtures/ come from one phone, with GPS accuracy 14 m:
- hand_walk_fixture.json: a brisk straight walk of about 100 m with the phone in the hand, screen up.
- pocket_walk_fixture.json: a straight walk of about 70 m with the phone loose in a trouser pocket, screen
  away from the leg (it was put into the pocket 1 to 2 s after the recording started).
Each holds the raw gravity-removed motion magnitude at 25 Hz (2250 values), one GPS speed per second (90 values)
and the accuracy. They contain no positions and no times of positions (contains_positions is false).
These tests are permanent: they are not debug code. Nothing in the replay mocks the cadence or detection logic.
"""

import json
import shutil
import statistics
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
REPLAY = ROOT / "tests" / "js" / "replay.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _replay(name: str) -> list[dict]:
    done = subprocess.run(
        ["node", str(REPLAY), str(FIXTURES / f"{name}_walk_fixture.json")],
        capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout)["rows"]


@pytest.fixture(scope="module")
def hand():
    return _replay("hand")


@pytest.fixture(scope="module")
def pocket():
    return _replay("pocket")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _walking(rows, a, b):
    return sum(int(r["walking"]) for r in rows[a : b + 1])


def _valid_cadences(rows, a, b):
    return [float(r["cadence"]) for r in rows[a : b + 1] if r["cad_ok"] == "1"]


def _share(rows, a, b, pick):
    window = rows[a : b + 1]
    return sum(1 for r in window if r["cad_pick_reason"] == pick) / len(window)


def test_the_fixtures_have_the_agreed_shape():
    for name in ("hand", "pocket"):
        data = json.loads((FIXTURES / f"{name}_walk_fixture.json").read_text(encoding="utf-8"))
        assert data["hz"] == 25 and len(data["raw_motion"]) == 2250 and len(data["gps_speed_mps"]) == 90
        assert data["gps_accuracy_m"] == 14 and data["contains_positions"] is False


# ---------------------------------------------------------------- hand, brisk pace

def test_hand_walking_is_detected_within_10_s_of_the_first_gps_speed(hand):
    first_speed = 12  # the first GPS speed of at least 0.7 m/s
    first_walking = next(i for i, r in enumerate(hand) if r["walking"] == "1")
    assert first_walking <= first_speed + 10, first_walking


def test_hand_walking_in_at_least_85_percent_of_seconds_20_to_71(hand):
    assert _walking(hand, 20, 71) >= 0.85 * 52, _walking(hand, 20, 71)


def test_hand_isolated_gps_spike_does_not_set_the_vehicle_veto(hand):
    assert hand[29]["gps"] == "2.20"
    for row in hand[28:40]:
        assert row["reason"] != "vehicle" and row["go_fail"] != "vehicle", (row["t"], row["reason"], row["go_fail"])
    assert hand[29]["walking"] == "1" and hand[30]["walking"] == "1"


def test_hand_cadence_median_is_2_07(hand):
    cadences = _valid_cadences(hand, 20, 71)
    assert len(cadences) >= 40
    assert statistics.median(cadences) == pytest.approx(2.07, abs=0.05)


def test_hand_stride_doubling_is_rare(hand):
    assert _share(hand, 12, 71, "stride_doubled") <= 0.10


def test_hand_speed_used_is_capped_and_reaches_1_3_by_45(hand):
    used = [_num(r["used"]) for r in hand]
    assert max(u for u in used if u is not None) <= 1.4
    assert used[45] is not None and used[45] >= 1.3, used[45]


# ---------------------------------------------------------------- pocket, loose trouser pocket

def test_pocket_walking_in_at_least_85_percent_of_seconds_24_to_74(pocket):
    assert _walking(pocket, 24, 74) >= 0.85 * 51, _walking(pocket, 24, 74)


def test_pocket_cadence_comes_from_the_doubled_stride_in_80_percent_of_seconds(pocket):
    assert _share(pocket, 24, 74, "stride_doubled") >= 0.80, _share(pocket, 24, 74, "stride_doubled")


def test_pocket_cadence_is_2_0(pocket):
    cadences = _valid_cadences(pocket, 24, 74)
    assert len(cadences) >= 40
    assert statistics.median(cadences) == pytest.approx(2.0, abs=0.06)
    assert sum(1 for c in cadences if abs(c - 2.0) <= 0.06) >= 0.9 * len(cadences)


def test_pocket_speed_used_is_within_15_percent_of_the_gps_mean_by_60(pocket):
    used = _num(pocket[60]["used"])
    assert used is not None and abs(used - 1.30) <= 0.15 * 1.30, used


def test_pocket_insertion_shock_and_stillness_are_never_walking(pocket):
    assert _walking(pocket, 0, 9) == 0


# ---------------------------------------------------------------- both

@pytest.mark.parametrize("which", ["hand", "pocket"])
def test_the_first_10_s_are_never_walking(which, hand, pocket):
    rows = hand if which == "hand" else pocket
    assert _walking(rows, 0, 9) == 0


def _stop_second(which: str) -> int:
    """The second from which the GPS speed reads below 0.3 m/s and stays there (after the walk)."""
    data = json.loads((FIXTURES / f"{which}_walk_fixture.json").read_text(encoding="utf-8"))
    speeds = data["gps_speed_mps"]
    return next(i for i in range(60, len(speeds)) if all(v < 0.3 for v in speeds[i:]))


@pytest.mark.parametrize("which", ["hand", "pocket"])
def test_walking_is_false_from_gps_still_reject_s_after_the_stop_to_the_end(which, hand, pocket):
    # The GPS speed first reads below 0.3 m/s at t=72 (hand) and t=75 (pocket). The motion rhythm can persist,
    # so walking may stay true for up to GPS_STILL_REJECT_S (5 s) after that, and is false from then on.
    rows = hand if which == "hand" else pocket
    stop = _stop_second(which)
    assert stop in (72, 75)
    assert _walking(rows, stop + 5, 89) == 0, [r["t"] for r in rows[stop + 5 :] if r["walking"] == "1"]


@pytest.mark.parametrize("which", ["hand", "pocket"])
def test_in_the_5_s_after_the_stop_the_mode_is_hold_and_the_speed_used_does_not_change(which, hand, pocket):
    # The real guarantee: walking may stay true for up to 5 s after a stop, but the speed is held, not updated.
    rows = hand if which == "hand" else pocket
    stop = _stop_second(which)
    window = rows[stop : stop + 5]
    assert all(r["mode"] == "hold" for r in window), [(r["t"], r["mode"]) for r in window]
    assert len({r["used"] for r in window}) == 1, [(r["t"], r["used"]) for r in window]
    assert _num(window[0]["used"]) is not None


@pytest.mark.parametrize("which", ["hand", "pocket"])
def test_no_second_has_a_speed_used_above_1_4(which, hand, pocket):
    rows = hand if which == "hand" else pocket
    assert all((_num(r["used"]) or 0) <= 1.4 for r in rows)

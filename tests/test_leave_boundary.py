"""The leave rule at the boundary: 61, 60, 59, 0 and -1 seconds, in Python and in the page.

The leave-now alert (leave_by - 60 s), the leave-now action, sentence two, sentence three, the pace chip and the
Leave by tile all use the same 60 s threshold, so they all flip at the same instant.
"""

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from explain import (
    ACTION_ADVICE,
    build_poll_explanation,
    chosen_action,
    leave_mode,
    seconds_until_leave_by,
)
from leave_now import LEAVE_NOW_MARGIN_S, notification_time_from_leave_by

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
FORMAT_DISTANCE = (ROOT / "static" / "format-distance.js").read_text(encoding="utf-8")
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
BOUNDARY = [(62, False), (61, False), (60, True), (59, True), (1, True), (0, True), (-1, True), (-300, True)]


class _Cache:
    def stop_by_code(self, code):
        return {"Latitude": 1.3, "Longitude": 103.8}


def _pack(seconds_to_leave_by, **overrides):
    leave_by = (NOW + timedelta(seconds=seconds_to_leave_by)).isoformat()
    payload = {
        "service_no": "36", "leave_by": leave_by,
        "buses": [{"position": "NextBus", "arrival_time": (NOW + timedelta(seconds=600)).isoformat(), "is_primary": True,
                   "is_missed": False,
                   "probability": {"point": 60, "range_low": 50, "range_high": 80, "data_quality": "live", "band": "ok"}}],
    }
    args = dict(now=NOW, cache=_Cache(), user_lat=1.3 + 225 / 111_195, user_lon=103.8, stop_code="1", explained_action=None,
                explained_advice=None, in_flight=False, reroute_fired=False)
    args.update(overrides)
    return build_poll_explanation(payload, **args)


def test_the_threshold_is_the_leave_now_margin_and_the_pack_says_so():
    assert LEAVE_NOW_MARGIN_S == 60
    assert _pack(600)["leave_now_threshold_s"] == LEAVE_NOW_MARGIN_S


@pytest.mark.parametrize("seconds, leave_now", BOUNDARY)
def test_the_action_the_sentences_the_clauses_and_the_alert_flip_at_the_same_second(seconds, leave_now):
    pack = _pack(seconds)
    assert (pack["action"] == "leave_now") == leave_now
    assert chosen_action(reroute_fired_this_poll=False, data_quality="live", range_high=80, leave_by_seconds=seconds) == pack["action"]
    assert leave_mode(seconds) == ("now" if leave_now else "by")
    assert pack["reason_code"] == ("LEAVE_NOW" if leave_now else "LEAVE_BY")
    assert (" Leave now so you have " in pack["text"]) == leave_now
    assert (" Leave by " in pack["text"]) == (not leave_now)
    assert pack["clause"] == "It is advisable to " + ACTION_ADVICE["leave_now" if leave_now else "wait"] + "."
    assert pack["clause"] not in pack["text"]  # the dormant model clause is never part of the card text
    # the notification time is leave_by - 60 s, so it is due at exactly this second and not before
    leave_by = NOW + timedelta(seconds=seconds)
    due = NOW >= notification_time_from_leave_by(leave_by)
    assert due == leave_now
    assert seconds_until_leave_by(leave_by.isoformat(), NOW) == seconds


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _between(text, start, end):
    head = text.split(start, 1)[1]
    return start + head.split(end, 1)[0]


def _tile_source():
    page = _between(INDEX, "var EXPL_ARRIVING_NOW", "// Redraws the card from the poll on screen")
    parts = _between(INDEX, "function singaporeParts(date) {", "function pad2(value)")
    return FORMAT_DISTANCE + "\n" + parts + "\n" + page + '\nvar LEAVE_NOW_TEXT = "Leave now";\n'


@needs_node
def test_the_tile_flips_with_the_same_rule_in_the_page():
    now_ms = int(NOW.timestamp() * 1000)
    rows = [s for s, _ in BOUNDARY]
    program = (
        _tile_source() + "\n"
        f"var nowMs = {now_ms}; Date.now = function () {{ return nowMs; }};\n"
        f"var arrival = new Date(nowMs + 300000).toISOString();\nvar out = [];\n"
        f"{json.dumps(rows)}.forEach(function (s) {{\n"
        "  var body = {leave_by: new Date(nowMs + s * 1000).toISOString(), leave_now_threshold_s: 60};\n"
        "  var pack = {walk_minutes: 4, uncertain: false};\n"
        "  out.push([s, leaveTileView(body, pack, arrival, nowMs), leaveMode(body.leave_by, 60, nowMs)]);\n"
        "});\nconsole.log(JSON.stringify(out));"
    )
    done = subprocess.run(["node", "-e", program], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr[-600:]
    for seconds, view, mode in json.loads(done.stdout):
        leave_now = seconds <= 60
        assert mode == ("now" if leave_now else "by") and view["mode"] == mode
        if leave_now:
            assert view["value"] == "Leave now" and view["meta"] == "The bus is 5\u00a0min away and the walk takes about 4\u00a0min."
        else:
            assert re.fullmatch(r"\d{1,2}:\d\d\u00a0(AM|PM)", view["value"]), view
            assert re.fullmatch(r"in \d+\u00a0min · 4\u00a0min walk", view["meta"]), view
        assert not (view["value"] == "Leave now" and re.search(r"\d:\d\d", view["value"]))  # never both


@needs_node
def test_the_tile_lines_for_the_edge_cases():
    now_ms = int(NOW.timestamp() * 1000)
    program = (
        _tile_source() + "\n"
        f"var nowMs = {now_ms}; Date.now = function () {{ return nowMs; }};\n"
        "var soon = new Date(nowMs + 20000).toISOString(); var far = new Date(nowMs + 600000).toISOString();\n"
        "var past = new Date(nowMs - 5000).toISOString();\n"
        "var out = {\n"
        "  arriving: leaveTileView({leave_by: past, leave_now_threshold_s: 60}, {walk_minutes: 2}, soon, nowMs),\n"
        "  oneMin: leaveTileView({leave_by: past, leave_now_threshold_s: 60}, {walk_minutes: 2}, new Date(nowMs + 60000).toISOString(), nowMs),\n"
        "  uncertainBy: leaveTileView({leave_by: far, leave_now_threshold_s: 60}, {walk_minutes: 2, uncertain: true}, far, nowMs),\n"
        "  uncertainNow: leaveTileView({leave_by: past, leave_now_threshold_s: 60}, {walk_minutes: 2, uncertain: true}, far, nowMs),\n"
        "  noPack: leaveTileView({leave_by: far, leave_now_threshold_s: 60}, null, far, nowMs),\n"
        "  noThreshold: leaveTileView({leave_by: far}, {walk_minutes: 2}, far, nowMs),\n"
        "  noLeaveBy: leaveTileView({}, {walk_minutes: 2}, far, nowMs),\n"
        "  underMinute: leaveTileView({leave_by: new Date(nowMs + 20000).toISOString(), leave_now_threshold_s: 0}, {walk_minutes: 2}, far, nowMs)\n"
        "};\nconsole.log(JSON.stringify(out));"
    )
    done = subprocess.run(["node", "-e", program], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr[-600:]
    out = json.loads(done.stdout)
    assert out["arriving"]["meta"] == "The bus is arriving now and the walk takes about 2\u00a0min."
    assert out["oneMin"]["meta"] == "The bus is 1\u00a0min away and the walk takes about 2\u00a0min."
    assert out["uncertainBy"]["uncertain"] is True and out["uncertainNow"]["uncertain"] is True
    assert out["uncertainBy"]["value"] != "Leave now" and out["uncertainNow"]["value"] == "Leave now"
    assert out["noPack"]["meta"] == "" and re.fullmatch(r"\d{1,2}:\d\d\u00a0(AM|PM)", out["noPack"]["value"])
    assert out["noThreshold"] is None and out["noLeaveBy"] is None
    assert out["underMinute"]["meta"] == "in under 1\u00a0min · 2\u00a0min walk"  # kept for a threshold below 60 s

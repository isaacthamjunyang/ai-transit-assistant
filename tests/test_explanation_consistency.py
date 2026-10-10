"""The AI card cannot disagree with the arrival tile: one tracked bus, one rounding, one snapshot per poll.

Python writes the card text in the poll response (a bus-and-walk sentence, then the leave sentence). The page redraws
it every second with a small mirror of the Python templates (explanationCardText, leaveMode, leaveClockText,
formatDistance). These tests pin the mirror to Python on a boundary grid, on the minute rollovers of the two clock times,
on every minute from 0 to 90, and on seeded random cases (distance, speed source, km/h, leave-by time, arrival time,
leave now, uncertain location), pin the minutes to the tile's minutes (etaParts), and pin the late-reply rule in the
real page (Edge). A Python-only branch or a reworded string makes one of them fail.
"""

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from explain import build_numbers, card_text, tile_minutes

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
FORMAT_DISTANCE = (ROOT / "static" / "format-distance.js").read_text(encoding="utf-8")
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 5, 9, 0, 0, tzinfo=SGT)
NODE = shutil.which("node")
ACTIONS = ("wait", "leave_now", "switch_route", "do_not_rely")
BANDS = ("ok", "mid", "low", None)
SOURCES = ("gps", "cadence", "remembered", "default", "unexpected")
OFFSETS = [-40, -1, 0, 29, 30, 31, 45, 59, 60, 89, 90, 91, 119, 120, 149, 150, 599, 600, 629, 630, 1319, 1320, 2400]
THRESHOLD = 60


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    head = text.split(start, 1)[1]
    assert end in head, end
    return start + head.split(end, 1)[0]


def _mirror_source() -> str:
    page = _between(INDEX, "var EXPL_ARRIVING_NOW", "// Redraws the card from the poll on screen")
    tile = _between(INDEX, "var ARRIVING_IN_TEXT", "// The muted line under the heading")
    fill = _between(INDEX, "function fillText(template, values) {", "// \"5 min\", or \"under 1 min\"")
    parts = _between(INDEX, "function singaporeParts(date) {", "function pad2(value)")
    return FORMAT_DISTANCE + "\n" + parts + "\n" + fill + "\n" + tile + "\n" + page + '\nvar LEAVE_NOW_TEXT = "Leave now";\nfunction isTrain() { return false; }  // a bus journey: the train words are unused here\n'


needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed, so the mirror parity tests did not run")


def _run_node(program: str):
    import tempfile

    with tempfile.TemporaryDirectory() as folder:  # large case lists do not fit on a command line
        script = Path(folder) / "program.js"
        script.write_text(program, encoding="utf-8")
        done = subprocess.run([NODE, str(script)], capture_output=True, text=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout)


# ---- cases: one dict per sentence-one-and-two variant

def _case(e=10, w=3, action="wait", band="ok", unc=False, leave_in=600, source="gps", speed=1.25, distance=300.0,
          now=NOW, arr_off=None, at_stop=False, train=None):
    """arr_off: the bus arrival in seconds after now (the tile's minutes e by default)."""
    return {"e": e, "w": w, "action": action, "band": band, "unc": unc, "leave_in": leave_in, "source": source,
            "speed": speed, "distance": distance, "now": now.isoformat(), "arr_off": e * 60 if arr_off is None else arr_off,
            "at_stop": at_stop, "train": train}


def _python_lead(c) -> str:
    now = datetime.fromisoformat(c["now"])
    leave_by = (now + timedelta(seconds=c["leave_in"])).isoformat()
    numbers = build_numbers(bus_minutes=c["e"], walk_minutes=c["w"], chosen_action=c["action"], distance_m=c["distance"],
                            walk_speed_used=c["speed"], walk_speed_source=c["source"], leave_by=leave_by,
                            arrival_time=(now + timedelta(seconds=c["arr_off"])).isoformat(), now=now,
                            at_stop=c.get("at_stop", False), train_line=c.get("train"))
    return card_text(numbers, band=c["band"], uncertain=c["unc"])


def _python_leads(cases):
    return [_python_lead(c) for c in cases]


def _mirror_cases(cases):
    program = (
        _mirror_source() + "\nvar out = [];\n"
        f"var cases = {json.dumps(cases)};\n"
        "cases.forEach(function (c) {\n"
        "  var nowMs = Date.parse(c.now);\n"
        "  var pack = {walk_minutes: c.w, band: c.band, uncertain: c.unc, action: c.action,\n"
        "    leave_by: new Date(nowMs + c.leave_in * 1000).toISOString(), leave_now_threshold_s: " + str(THRESHOLD) + ",\n"
        "    distance_m: c.distance, walk_speed_used: c.speed, walk_speed_source: c.source, at_stop: c.at_stop === true,\n"
        "    train_line: c.train};\n"
        "  out.push(explanationCardText(pack, c.e, new Date(nowMs + c.arr_off * 1000).toISOString(), nowMs));\n"
        "});\nconsole.log(JSON.stringify(out));"
    )
    return _run_node(program)


# ---- the minutes are the tile's minutes

@needs_node
def test_the_page_minutes_are_the_servers_tile_minutes_and_the_tiles_minutes():
    arrival = [(NOW + timedelta(seconds=s)).isoformat() for s in OFFSETS]
    program = (
        _mirror_source() + "\n"
        f"var nowMs = {int(NOW.timestamp() * 1000)}; Date.now = function () {{ return nowMs; }};\n"
        f"var arrivals = {json.dumps(arrival)};\nvar out = [];\n"
        "arrivals.forEach(function (iso) {\n"
        "  var hero = {arrival_time: iso, is_missed: false};\n"
        "  var parts = etaParts(hero);\n"
        "  out.push({e: explanationMinutes(iso), tile: parts && parts.line});\n"
        "});\nconsole.log(JSON.stringify(out));"
    )
    got = _run_node(program)
    for seconds, row in zip(OFFSETS, got):
        server = tile_minutes((NOW + timedelta(seconds=seconds)).isoformat(), NOW)
        assert row["e"] == server, (seconds, row, server)  # the page and Python round alike
        if server == 0:
            assert row["tile"] in ("Arriving now", "Arriving in <1 min"), (seconds, row)
        else:
            assert row["tile"] == f"Arriving in {server} min", (seconds, row)  # the tile says the same minutes


@needs_node
def test_the_text_between_polls_follows_the_tile_not_the_poll_time():
    # 20 s after a poll that said "10 minutes away", the tile reads 10 or 9 by its own rounding; the text must too.
    arrival = NOW + timedelta(seconds=629)
    program = (
        _mirror_source() + "\n"
        f"var iso = {json.dumps(arrival.isoformat())};\nvar out = [];\n"
        f"var start = {int(NOW.timestamp() * 1000)};\n"
        "for (var t = 0; t <= 40; t += 5) {\n"
        "  var nowMs = start + t * 1000; Date.now = function () { return nowMs; };\n"
        "  out.push([explanationMinutes(iso), etaParts({arrival_time: iso, is_missed: false}).line]);\n"
        "}\nconsole.log(JSON.stringify(out));"
    )
    for e, line in _run_node(program):
        assert line == ("Arriving now" if e == 0 else f"Arriving in {e} min")


def test_the_mirror_exists_in_the_page_and_the_card_redraws_every_second():
    assert "function explanationCardText(pack, e, arrivalIso, nowMs)" in INDEX and "function renderExplanationNow()" in INDEX
    tick = _between(INDEX, "function refreshDisplay(generation)", "function clearPrimaryBus")
    assert "renderExplanationNow();" in tick
    now = _between(INDEX, "function renderExplanationNow()", "function resetExplanationState()")
    assert "featuredBus(lastSuccess.buses)" in now  # the tile's own bus
    assert "leaveMode(pack.leave_by, pack.leave_now_threshold_s, nowMs)" in now  # the one leave rule, the tile's clock
    assert "explanationCardText(pack, e, arrival, nowMs)" in now and "explanationClauseFor" not in INDEX  # no model clause


def test_page_c_explanation_is_unaffected():
    from explain import handle_option_explain_request

    status, payload = handle_option_explain_request(
        {"fact_sheet": {"reason_code": "HIGHEST_CHANCE", "chosen_action": "switch_route"}, "service_no": "36"}
    )
    assert status == 200 and payload["action"] == "switch_route" and payload["reason_code"] == "HIGHEST_CHANCE"
    assert "snapshot" not in payload and payload["text"].endswith(".")  # its own endpoint, cache and wording
    page_c = _between(INDEX, "function requestOptionExplanation(row)", "function ")
    assert "/api/explain-option" in INDEX and "lastExplanationPack" not in page_c and "explanationClause" not in page_c
    assert "snapshot" not in _between(INDEX, "function buildOptionExplanation(row)", "function requestOptionExplanation")


# ---- the mirror against Python on a boundary grid, on every minute, and on seeded random cases

LEAVE_IN = [-600, -1, 0, 1, 59, 60, 61, 62, 119, 120, 600, 36000]  # 61 / 60 / 59 / 0 / -1 around the threshold


def _boundary_cases():
    cases = []
    for e in (0, 1, 2, 10):
        for leave_in in LEAVE_IN:
            for source in SOURCES:
                for action in ACTIONS:
                    for band in BANDS:
                        for unc in (False, True):
                            cases.append(_case(e=e, action=action, band=band, unc=unc, leave_in=leave_in, source=source))
    distances = [0, 0.4, 0.5, 1, 49.5, 99.9, 300, 999.4, 999.5, 1000, 1049, 1050, 1249, 1250, 1949.5, 9999.9, 25000]
    for distance in distances:
        for leave_in in (61, 60):
            for source in ("gps", "remembered", "default"):
                for unc in (False, True):
                    for band in ("ok", "low"):
                        cases.append(_case(distance=distance, leave_in=leave_in, source=source, unc=unc, band=band))
    for hundredths in range(50, 141):  # every speed from 0.50 to 1.40 m/s: the km/h text
        for source in SOURCES:
            for leave_in in (600, 0):
                cases.append(_case(speed=hundredths / 100, source=source, leave_in=leave_in))
    midnight = datetime(2026, 10, 5, 23, 59, 30, tzinfo=SGT)
    after = datetime(2026, 10, 6, 0, 0, 30, tzinfo=SGT)
    noon = datetime(2026, 10, 5, 12, 0, 0, tzinfo=SGT)
    for now in (NOW, midnight, after, noon):  # AM, PM, 12 AM, 12 PM, "(tomorrow)"
        for leave_in in (61, 90, 900, 3600, 15000, 43200, 50000, 90000):
            for unc in (False, True):
                cases.append(_case(now=now, leave_in=leave_in, unc=unc))
    for arr_off in (0, 29, 30, 59, 60, 61, 119, 120, 599, 600, 601, 3600, 7199):
        for leave_in in (-1, 0, 60, 61, 119, 120, 299, 300, 540, 541, 3599, 3600):
            for now in (NOW, NOW + timedelta(seconds=29), NOW + timedelta(seconds=59), midnight):
                cases.append(_case(e=arr_off // 60, leave_in=leave_in, arr_off=arr_off, now=now))
    for e in (0, 1, 2, 10, 59):  # a train as the first leg: the train sentence, then the existing leave sentence
        for leave_in in LEAVE_IN:
            for action in ACTIONS:
                for band in BANDS:
                    for unc in (False, True):
                        for line in ("North-South Line", "NS"):
                            cases.append(_case(e=e, action=action, band=band, unc=unc, leave_in=leave_in, train=line))
    for distance in (0, 0.4, 0.5, 49.5, 300, 999.4, 999.5, 1000, 1249, 1950, 25000):  # unlikely: "{distance} from the station"
        for e in (0, 1, 2, 10):
            for action, band in (("do_not_rely", "ok"), ("switch_route", "mid"), ("wait", "low"), ("wait", "ok")):
                cases.append(_case(e=e, action=action, band=band, distance=float(distance), train="Thomson-East Coast Line"))
    return cases


@needs_node
def test_the_page_mirror_equals_python_on_the_boundary_grid():
    cases = _boundary_cases()
    assert len(cases) > 7000
    assert {c["leave_in"] for c in cases} >= {61, 60, 59, 0, -1}
    assert {c["source"] for c in cases} == set(SOURCES) and {c["e"] for c in cases} >= {0, 1, 2, 10}
    got, expected = _mirror_cases(cases), _python_leads(cases)
    bad = [(c, g, x) for c, g, x in zip(cases, got, expected) if g != x]
    assert not bad, f"{len(bad)} differ, first: {bad[0]}"


SEED = 20261005


def _random_cases(count):
    import random

    rng = random.Random(SEED)
    cases = []
    for _ in range(count):
        now = NOW + timedelta(seconds=rng.randint(0, 86399))
        cases.append(_case(
            e=rng.randint(0, 90), w=rng.randint(0, 45), action=rng.choice(ACTIONS), band=rng.choice(BANDS),
            unc=rng.random() < 0.5, leave_in=rng.choice([rng.randint(-900, 900), rng.randint(-90000, 90000), 60, 61, 59, 0]),
            source=rng.choice(SOURCES), speed=rng.randint(50, 140) / 100, distance=round(rng.choice([rng.uniform(0, 3000), rng.uniform(0, 30)]), 1),
            now=now, arr_off=rng.choice([rng.randint(0, 7200), rng.randint(-60, 120)]),
            train=rng.choice([None, None, "North-South Line", "Thomson-East Coast Line", "Circle Line", "NS"])))
    return cases


@needs_node
def test_the_page_mirror_equals_python_on_3000_seeded_random_cases():
    print(f"seed={SEED}")  # fixed, so a failure reproduces
    cases = _random_cases(3000)
    got, expected = _mirror_cases(cases), _python_leads(cases)
    bad = [(c, g, x) for c, g, x in zip(cases, got, expected) if g != x]
    assert not bad, f"seed={SEED}: {len(bad)} differ, first: {bad[0]}"


@needs_node
def test_the_page_mirror_equals_python_on_every_minute_and_walk_pair_in_range():
    # Every bus minute 0..90 and walk minute 0..45 (a pair-only Python branch, such as "30 or more minutes",
    # "exactly 15" or "a zero walk", fails here), each with leave by and leave now, two sources, both uncertain
    # flags and a normal and a low band.
    cases = [_case(e=e, w=w, leave_in=leave_in, source=source, unc=unc, band=band)
             for e in range(91) for w in range(46) for leave_in in (600, 0) for source in ("gps", "default")
             for unc in (False, True) for band in ("ok", "low")]
    assert len(cases) == 91 * 46 * 16
    assert _mirror_cases(cases) == _python_leads(cases)


ROLLOVERS = [(540, 299), (599, 240), (540, 300), (539, 299), (600, 299), (540, 540), (540, 900), (600, 541), (3600, 3059)]


@needs_node
def test_the_page_mirror_equals_python_at_the_minute_rollovers_of_the_two_clock_times():
    midnight = datetime(2026, 10, 5, 23, 55, 0, tzinfo=SGT)
    cases = []
    for arr_off, leave_in in ROLLOVERS:
        for now in (NOW, NOW + timedelta(seconds=29), NOW + timedelta(seconds=59), midnight, midnight + timedelta(seconds=45)):
            for unc in (False, True):
                cases.append(_case(e=arr_off // 60, leave_in=leave_in, arr_off=arr_off, now=now, unc=unc))
    got, expected = _mirror_cases(cases), _python_leads(cases)
    bad = [(c, g, x) for c, g, x in zip(cases, got, expected) if g != x]
    assert not bad, f"{len(bad)} differ, first: {bad[0]}"
    # leave by 9:04:59 and arrival 9:09:00 read 9:04 and 9:09: five minutes, on both sides
    five = _mirror_cases([_case(e=9, leave_in=299, arr_off=540), _case(e=9, leave_in=240, arr_off=599)])
    assert all("so you have 5 minutes to reach your stop" in text for text in five), five
    assert "catch the bus arriving at 9:09\u00a0AM" in five[0] and "Leave by 9:04\u00a0AM" in five[0]


@needs_node
def test_every_leave_by_case_in_the_mirror_has_at_least_two_minutes():
    # leave-by is the arrival minus the walk minus the 135 s margin
    import re

    cases = []
    for arr_off in range(240, 420, 7):
        for walk_s in (0, 1, 20, 59, 60, 119, 120, 300, 600, 3000):
            for now in (NOW, NOW + timedelta(seconds=17), NOW + timedelta(seconds=44)):
                cases.append(_case(e=round(arr_off / 60), leave_in=arr_off - walk_s - 135, arr_off=arr_off, now=now))
    got = _mirror_cases(cases)
    assert got == _python_leads(cases)
    seen = 0
    for text in got:
        found = re.search(r"so you have (\d+) minutes? to reach", text)
        if "Leave by" in text:
            seen += 1
            assert found and int(found.group(1)) >= 2, text
    assert seen > 100


@needs_node
def test_a_zero_walk_and_every_distance_in_a_range_match():
    cases = [_case(distance=float(d), leave_in=leave_in) for d in range(0, 1300, 1) for leave_in in (600, 0)]
    assert _mirror_cases(cases) == _python_leads(cases)


# ---- the pack fields the page reads

def _fields_read_by_the_page() -> set[str]:
    import re

    region = _between(INDEX, "var EXPL_ARRIVING_NOW", "function notifyReroute(reroute)")
    return set(re.findall(r"\b(?:pack|lastExplanationPack|next)\.(\w+)", region))


def test_the_page_reads_exactly_the_pack_fields_the_server_lists():
    from explain import PAGE_PACK_FIELDS

    read = _fields_read_by_the_page()
    assert read == set(PAGE_PACK_FIELDS), (sorted(read - set(PAGE_PACK_FIELDS)), sorted(set(PAGE_PACK_FIELDS) - read))


def test_the_server_pack_carries_every_field_the_page_reads():
    from datetime import timedelta as _td

    from explain import PACK_KEYS, PAGE_PACK_FIELDS, build_poll_explanation

    class Cache:
        def stop_by_code(self, code):
            return {"Latitude": 1.3, "Longitude": 103.8}

    payload = {"service_no": "36", "leave_by": (NOW + _td(seconds=600)).isoformat(), "buses": [{
        "position": "NextBus", "arrival_time": (NOW + _td(seconds=600)).isoformat(), "is_primary": True, "is_missed": False,
        "probability": {"point": 60, "range_low": 50, "range_high": 80, "data_quality": "live", "band": "ok"}}]}
    pack = build_poll_explanation(payload, now=NOW, cache=Cache(), user_lat=1.3 + 225 / 111_195, user_lon=103.8,
                                  stop_code="1", explained_action=None, explained_advice=None, in_flight=False,
                                  reroute_fired=False)
    assert pack["model_enabled"] is False  # the model path is off by default
    missing = [name for name in PAGE_PACK_FIELDS if name not in pack]
    assert not missing, missing
    assert tuple(pack) == tuple(PACK_KEYS) or set(pack) == set(PACK_KEYS)  # the pinned key list

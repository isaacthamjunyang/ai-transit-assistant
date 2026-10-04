"""The AI card cannot disagree with the arrival tile: one tracked bus, one rounding, one snapshot per poll.

Python writes sentences one and two in the poll response. The page redraws them every second from the tile's own
minutes with a small mirror of the Python templates. These tests pin the mirror to Python, pin the minutes to the
tile's minutes (etaParts), and pin the late-reply rule in the real page (Edge).
"""

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from explain import build_numbers, lead_text, tile_minutes

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 5, 9, 0, 0, tzinfo=SGT)
NODE = shutil.which("node")
ACTIONS = ("wait", "leave_now", "switch_route", "do_not_rely")
CASES = [(e, w, a, band, unc) for e in (0, 1, 2, 10, 22, 40) for w in (1, 3, 12) for a in ACTIONS
         for band in ("ok", "mid", "low", None) for unc in (False, True)]
OFFSETS = [-40, -1, 0, 29, 30, 31, 45, 59, 60, 89, 90, 91, 119, 120, 149, 150, 599, 600, 629, 630, 1319, 1320, 2400]


def _between(text: str, start: str, end: str) -> str:
    assert start in text, start
    head = text.split(start, 1)[1]
    assert end in head, end
    return start + head.split(end, 1)[0]


def _mirror_source() -> str:
    page = _between(INDEX, "var EXPL_ARRIVING_NOW", "// Redraws the card from the poll on screen")
    tile = _between(INDEX, "var ARRIVING_IN_TEXT", "// The muted line under the heading")
    fill = _between(INDEX, "function fillText(template, values) {", "// \"5 min\", or \"under 1 min\"")
    return fill + "\n" + tile + "\n" + page


needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed, so the mirror parity tests did not run")


def _run_node(program: str):
    import tempfile

    with tempfile.TemporaryDirectory() as folder:  # large case lists do not fit on a command line
        script = Path(folder) / "program.js"
        script.write_text(program, encoding="utf-8")
        done = subprocess.run([NODE, str(script)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout)


@needs_node
def test_the_page_mirror_of_sentences_one_and_two_equals_python_for_every_variant():
    program = (
        _mirror_source() + "\nvar out = [];\n"
        f"var cases = {json.dumps(CASES)};\n"
        "cases.forEach(function (c) {\n"
        "  out.push(explanationLead({walk_minutes: c[1], band: c[3], uncertain: c[4], action: c[2]}, c[0]));\n"
        "});\nconsole.log(JSON.stringify(out));"
    )
    got = _run_node(program)
    expected = [lead_text(build_numbers(bus_minutes=e, walk_minutes=w, chosen_action=a), band=band, uncertain=unc)
                for e, w, a, band, unc in CASES]
    assert got == expected


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
    assert "function explanationLead(pack, e)" in INDEX and "function renderExplanationNow()" in INDEX
    tick = _between(INDEX, "function refreshDisplay(generation)", "function clearPrimaryBus")
    assert "renderExplanationNow();" in tick
    now = _between(INDEX, "function renderExplanationNow()", "function resetExplanationState()")
    assert "featuredBus(lastSuccess.buses)" in now  # the tile's own bus


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


# ---- the mirror against Python on a boundary grid and on seeded random cases

def _mirror_cases(cases):
    program = (
        _mirror_source() + "\nvar out = [];\n"
        f"var cases = {json.dumps(cases)};\n"
        "cases.forEach(function (c) {\n"
        "  out.push(explanationLead({walk_minutes: c[1], band: c[3], uncertain: c[4], action: c[2]}, c[0]));\n"
        "});\nconsole.log(JSON.stringify(out));"
    )
    return _run_node(program)


def _python_leads(cases):
    return [lead_text(build_numbers(bus_minutes=e, walk_minutes=w, chosen_action=a), band=band, uncertain=unc)
            for e, w, a, band, unc in cases]


def _boundary_cases():
    minutes = sorted({0, 1, 2, 3, 14, 15, 16, 29, 30, 31, 59, 60} | {10, 22, 40})
    walks_base = {0, 1, 2, 3, 14, 15, 16} | {12}
    cases = []
    for e in minutes:
        for w in sorted(walks_base | {e, max(0, e - 1), e + 1}):
            for action in ACTIONS:
                for band in ("ok", "mid", "low", None):
                    for unc in (False, True):
                        cases.append((e, w, action, band, unc))
    return cases


@needs_node
def test_the_page_mirror_equals_python_on_the_boundary_grid():
    cases = _boundary_cases()
    assert len(cases) > 4000
    assert {c[0] for c in cases} >= {0, 1, 2, 3, 14, 15, 16, 29, 30, 31, 59, 60}
    assert {c[1] for c in cases} >= {0, 1, 2, 3, 14, 15, 16}
    for e in (0, 1, 2, 3, 14, 15, 16, 29, 30, 31, 59, 60):  # w equal to e, e-1 and e+1 for each e
        assert {(e, max(0, e - 1)), (e, e), (e, e + 1)} <= {(c[0], c[1]) for c in cases}
    assert _mirror_cases(cases) == _python_leads(cases)


SEED = 20261005


@needs_node
def test_the_page_mirror_equals_python_on_3000_seeded_random_cases():
    import random

    print(f"seed={SEED}")  # fixed, so a failure reproduces
    rng = random.Random(SEED)
    cases = [(rng.randint(0, 90), rng.randint(0, 45), rng.choice(ACTIONS), rng.choice(("ok", "mid", "low", None)),
              rng.random() < 0.5) for _ in range(3000)]
    got, expected = _mirror_cases(cases), _python_leads(cases)
    bad = [(c, g, x) for c, g, x in zip(cases, got, expected) if g != x]
    assert not bad, f"seed={SEED}: {len(bad)} differ, first: {bad[0]}"


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

    from explain import PAGE_PACK_FIELDS, build_poll_explanation

    class Cache:
        def stop_by_code(self, code):
            return {"Latitude": 1.3, "Longitude": 103.8}

    payload = {"service_no": "36", "leave_by": (NOW + _td(seconds=600)).isoformat(), "buses": [{
        "position": "NextBus", "arrival_time": (NOW + _td(seconds=600)).isoformat(), "is_primary": True, "is_missed": False,
        "probability": {"point": 60, "range_low": 50, "range_high": 80, "data_quality": "live", "band": "ok"}}]}
    pack = build_poll_explanation(payload, now=NOW, cache=Cache(), user_lat=1.3 + 225 / 111_195, user_lon=103.8,
                                  stop_code="1", explained_action=None, explained_advice=None, in_flight=False,
                                  reroute_fired=False)
    missing = [name for name in PAGE_PACK_FIELDS if name not in pack]
    assert not missing, missing


@needs_node
def test_the_page_mirror_equals_python_on_every_minute_and_walk_pair_in_range():
    # Every (e, w) with e in 0..90 and w in 0..45, each with all four actions, bands and both uncertain flags, so a
    # Python-only branch on any single pair in that range fails here (the random test alone could miss a lone pair).
    cases = [(e, w, a, band, unc) for e in range(91) for w in range(46) for a in ACTIONS
             for band in ("ok", "mid", "low", None) for unc in (False, True)]
    assert len(cases) == 91 * 46 * 32
    assert _mirror_cases(cases) == _python_leads(cases)

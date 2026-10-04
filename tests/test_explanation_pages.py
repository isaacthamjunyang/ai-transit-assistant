"""Real poll payloads through the real page: the sentences the page draws equal the pack's own text.

Each case starts the real app with a fake LTA (and, for one case, a fired reroute decision), loads the real page,
takes a real poll, and compares the page's redraw of sentences one and two, with the clock set to the pack's own poll
time, with the text Python wrote. This is the end-to-end pin of the mirror in static/index.html (explanationLead,
explanationMinutes) to explain.py. Edge is needed; without it these tests skip.
"""

import pytest

from page_runner import require_edge, run_scenario, running_app

CASES = {
    "normal": {"etas": [10.3]},
    "uncertain": {"etas": [10.3]},
    "low": {"etas": [10.3]},
    "reroute": {"etas": [10.3], "stub": True},
    "missed": {"etas": [-1.0, 12.0]},
    "none": {"etas": [-1.0]},
}


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    require_edge()
    out = {}
    for name, case in CASES.items():  # one app at a time: the fake LTA is patched into the process
        with running_app(tmp_path_factory.mktemp(name), eta_minutes=case["etas"], reroute_stub=case.get("stub", False)) as base:
            out[name] = run_scenario("payloads", base, {"which": name})["result"]
    return out


@pytest.mark.parametrize("name", ["normal", "uncertain", "low", "reroute", "missed"])
def test_real_poll_payloads_render_the_same_sentences_as_the_pack(reports, name):
    report = reports[name]
    pack = report["pack"]
    assert pack is not None, report
    assert report["card"] == pack["text"]  # right after the poll the card shows Python's own text
    redrawn = report["redrawn"]
    assert redrawn["lead"] + " " + pack["clause"] == pack["text"], (redrawn, pack["text"])
    assert redrawn["text"] == pack["text"]  # the page's per-second redraw at the poll's instant equals it
    assert report["heroEta"] == pack["arrival_time"]  # the pack describes the bus the tile shows


def test_the_variants_in_the_real_payloads_are_the_ones_expected(reports):
    assert reports["normal"]["pack"]["action"] in ("wait", "leave_now")
    assert reports["normal"]["pack"]["text"].startswith("The bus is 10 minutes away.")
    assert reports["uncertain"]["pack"]["uncertain"] is True
    assert "Your location is uncertain" in reports["uncertain"]["pack"]["text"]
    low = reports["low"]["pack"]
    assert "catching this bus is unlikely" in low["text"] and (low["band"] == "low" or low["action"] == "do_not_rely")
    fired = reports["reroute"]["pack"]
    assert fired["action"] == "switch_route"
    assert fired["text"].startswith("The bus is 10 minutes away.") and "22 minutes" not in fired["text"]
    assert fired["text"].endswith("It is advisable to switch to another bus.")
    assert reports["missed"]["pack"]["text"].startswith("The bus is 12 minutes away.")


def test_with_no_tracked_bus_there_is_no_pack_and_the_card_is_empty(reports):
    report = reports["none"]
    assert report["pack"] is None and report["card"] == ""

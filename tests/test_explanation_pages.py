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
    "flip": {"etas": [10.3]},
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


@pytest.mark.parametrize("name", ["normal", "uncertain", "low", "reroute", "missed", "flip"])
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
    normal = reports["normal"]["pack"]
    assert normal["text"].startswith("The bus is 10 minutes away. You are ") and "you should leave by " in normal["text"]
    assert normal["leave_now_threshold_s"] == 60 and normal["walk_speed_source"] == "default"
    assert reports["uncertain"]["pack"]["uncertain"] is True
    assert "Your location is uncertain, so leave a little earlier than that to be safe." in reports["uncertain"]["pack"]["text"]         or "Your location is uncertain, so the walking time may be off." in reports["uncertain"]["pack"]["text"]
    low = reports["low"]["pack"]
    assert "catching this bus is unlikely" in low["text"] and (low["band"] == "low" or low["action"] == "do_not_rely")
    fired = reports["reroute"]["pack"]
    assert fired["action"] == "switch_route"
    assert fired["text"].startswith("The bus is 10 minutes away. You are ") and "22 minutes" not in fired["text"]
    assert "but catching this bus is unlikely." in fired["text"]
    assert fired["text"].endswith("It is advisable to switch to another bus.")
    assert reports["missed"]["pack"]["text"].startswith("The bus is 12 minutes away.")


def test_leave_by_passing_between_two_polls_flips_the_tile_the_card_the_chip_the_banner_and_the_alert_together(reports):
    import re

    rows = reports["flip"]["flip"]
    assert set(rows) == {"300", "62", "61", "60", "59", "1", "0", "-1"}
    for seconds, row in rows.items():
        leave_now = int(seconds) <= 60  # the server's threshold, 60 s: at 60 everything has flipped
        assert (row["tile"] == "Leave now") == leave_now, (seconds, row)
        assert (re.fullmatch(r"\d{1,2}:\d\d\u00a0(AM|PM)", row["tile"]) is not None) == (not leave_now), (seconds, row)  # never both
        assert ("should leave now" in row["card"]) == leave_now and ("should leave by " in row["card"]) == (not leave_now), row
        assert row["card"].endswith("leave now and walk to the bus stop." if leave_now else "wait for your leave-by alert."), row
        assert row["action"] == ("leave_now" if leave_now else "wait")
        assert row["banner"] is leave_now and row["notifications"] == (1 if leave_now else 0), (seconds, row)
        assert row["paceSlotShown"] == (leave_now and row["chipPossible"]), (seconds, row)
        if leave_now:
            assert row["detail"].startswith("The bus is ") and "the walk takes about" in row["detail"], row
        else:
            assert re.fullmatch(r"in \d+\u00a0min · \d+\u00a0min walk", row["detail"]), row


def test_with_no_tracked_bus_there_is_no_pack_and_the_card_is_empty(reports):
    report = reports["none"]
    assert report["pack"] is None and report["card"] == ""


def test_the_leave_by_tile_and_the_card_in_every_state_in_the_real_page(tmp_path):
    import re

    require_edge()
    with running_app(tmp_path, eta_minutes=[10.3]) as base:
        states = run_scenario("leaveshots", base, {})["result"]["states"]
    clock = r"\d{1,2}:\d\d\u00a0(AM|PM)"
    by, by_unc, now, now_unc = states["by"], states["byUncertain"], states["now"], states["nowUncertain"]
    assert re.fullmatch(clock, by["tile"]) and re.fullmatch(r"in \d+\u00a0min · \d+\u00a0min walk", by["detail"])
    assert by["cautionHidden"] is True and "should leave by " in by["card"] and "Your location is uncertain" not in by["card"]
    assert by_unc["cautionHidden"] is False and by_unc["caution"] == "Location uncertain: leave a bit earlier to be safe."
    assert by_unc["card"].endswith("Your location is uncertain, so leave a little earlier than that to be safe. "
                                   "It is advisable to wait for your leave-by alert.")
    assert now["tile"] == "Leave now" and now["detail"].startswith("The bus is ") and "the walk takes about" in now["detail"]
    assert now["cautionHidden"] is True and "should leave now." in now["card"]
    assert now["card"].endswith("It is advisable to leave now and walk to the bus stop.")
    assert now_unc["cautionHidden"] is False and now_unc["tile"] == "Leave now"
    assert "Your location is uncertain, so the walking time may be off." in now_unc["card"]
    assert "walking at your usual speed of 4.0\u00a0km/h, so you should leave now." in states["nowRemembered"]["card"]
    assert "walking at about 4.7\u00a0km/h, so you should leave now." in states["nowMeasured"]["card"]
    assert "You are " in states["unlikely"]["card"] and ", but catching this bus is unlikely." in states["unlikely"]["card"]
    assert "should leave" not in states["unlikely"]["card"]

"""Real poll payloads through the real page: the sentences the page draws equal the pack's own text.

Each case starts the real app with a fake LTA (and, for one case, a fired reroute decision), loads the real page,
takes a real poll, and compares the page's redraw of sentences one and two, with the clock set to the pack's own poll
time, with the text Python wrote. This is the end-to-end pin of the mirror in static/index.html (explanationCardText,
explanationMinutes) to explain.py. Edge is needed; without it these tests skip.
"""

import pytest

from page_runner import require_edge, run_scenario, running_app

# A clock time as the tile shows it. When the leave-by is after midnight (the real time of day decides) the page adds
# " (tomorrow)"; the expected text is taken from the page's own clock function, so these tests do not depend on the hour.
CLOCK = r"\d{1,2}:\d\d\u00a0(AM|PM)( \(tomorrow\))?"

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
    assert redrawn["lead"] == pack["text"], (redrawn, pack["text"])  # the page's two sentences equal Python's
    assert redrawn["text"] == pack["text"]  # the page's per-second redraw at the poll's instant equals it
    assert report["heroEta"] == pack["arrival_time"]  # the pack describes the bus the tile shows


def test_the_variants_in_the_real_payloads_are_the_ones_expected(reports):
    assert reports["normal"]["pack"]["action"] in ("wait", "leave_now")
    normal = reports["normal"]["pack"]
    assert normal["text"].startswith("The bus is 10 minutes away, and you are ")
    assert " Leave by " in normal["text"] or " Leave now to reach your stop in " in normal["text"]
    assert normal["leave_now_threshold_s"] == 60 and normal["walk_speed_source"] == "default"
    assert reports["uncertain"]["pack"]["uncertain"] is True
    assert "Location uncertain: leave a little earlier to be safe." in reports["uncertain"]["pack"]["text"]         or "Location uncertain: the walk time may be off." in reports["uncertain"]["pack"]["text"]
    low = reports["low"]["pack"]
    assert "catching this bus is unlikely" in low["text"] and (low["band"] == "low" or low["action"] == "do_not_rely")
    fired = reports["reroute"]["pack"]
    assert fired["action"] == "switch_route"
    assert fired["text"].startswith("The bus is 10 minutes away, and you are ") and "22 minutes" not in fired["text"]
    assert fired["text"].endswith(", but catching this bus is unlikely.")  # one sentence, nothing after it
    assert reports["missed"]["pack"]["text"].startswith("The bus is 12 minutes away, and you are ")


def _same_minutes(walk_line, card):
    """The walk line under the pace chip and the AI sentence state one number."""
    import re

    n = int(re.match(r"\d+", walk_line).group())
    phrase = "1 minute" if n == 1 else f"{n} minutes"
    assert f"reach your stop in {phrase}" in card.replace(chr(0xA0), " "), (walk_line, card)


def test_leave_by_passing_between_two_polls_flips_the_tile_the_card_the_chip_the_banner_and_the_alert_together(reports):
    import re

    rows = reports["flip"]["flip"]
    assert set(rows) == {"300", "62", "61", "60", "59", "1", "0", "-1"}
    for seconds, row in rows.items():
        leave_now = int(seconds) <= 60  # the server's threshold, 60 s: at 60 everything has flipped
        assert (row["tile"] == "Leave now") == leave_now, (seconds, row)
        assert (re.fullmatch(CLOCK, row["tile"]) is not None) == (not leave_now), (seconds, row)  # never both
        if not leave_now:
            assert row["tile"] == row["expectedClock"] and (" (tomorrow)" in row["tile"]) == row["expectedClock"].endswith("(tomorrow)")
        assert (" Leave now to reach your stop in " in row["card"]) == leave_now and (" Leave by " in row["card"]) == (not leave_now), row
        assert row["action"] == ("leave_now" if leave_now else "wait")
        assert row["banner"] is leave_now and row["notifications"] == (1 if leave_now else 0), (seconds, row)
        assert row["paceSlotShown"] is True, (seconds, row)  # the pace chip is on Page A in every action
        # the walk line under the pace chip: one short line, the walk minutes the AI sentence states
        assert re.fullmatch(r"\d+\u00a0min walk", row["detail"]), row
        _same_minutes(row["detail"], row["card"])


def test_with_no_tracked_bus_there_is_no_pack_and_the_card_is_empty(reports):
    report = reports["none"]
    assert report["pack"] is None and report["card"] == ""


def test_the_leave_by_tile_and_the_card_in_every_state_in_the_real_page(tmp_path):
    import re

    require_edge()
    with running_app(tmp_path, eta_minutes=[10.3]) as base:
        states = run_scenario("leaveshots", base, {})["result"]["states"]
    clock = CLOCK
    by, by_unc, now, now_unc = states["by"], states["byUncertain"], states["now"], states["nowUncertain"]
    assert re.fullmatch(clock, by["tile"]) and by["tile"] == by["expectedClock"]
    assert re.fullmatch(r"\d+\u00a0min walk", by["detail"])
    _same_minutes(by["detail"], by["card"])
    assert by["cautionHidden"] is True and " Leave by " in by["card"] and "Location uncertain" not in by["card"]
    assert by_unc["cautionHidden"] is False and by_unc["caution"] == "Location uncertain: leave a bit earlier to be safe."
    assert by_unc["card"].endswith(" Leave by " + by_unc["card"].split(" Leave by ", 1)[1])
    assert by_unc["card"].endswith("Location uncertain: leave a little earlier to be safe.")
    assert now["tile"] == "Leave now" and re.fullmatch(r"\d+\u00a0min walk", now["detail"])
    _same_minutes(now["detail"], now["card"])
    assert now["cautionHidden"] is True and " Leave now to reach your stop in 4 minutes and catch the bus arriving at " in now["card"]
    # the clock reads "12:04 AM (tomorrow)." in the last minutes before midnight
    tail = now["card"].replace(chr(0xA0), " ")
    assert tail.endswith((" AM.", " PM.", " AM (tomorrow).", " PM (tomorrow)."))
    assert now_unc["cautionHidden"] is False and now_unc["tile"] == "Leave now"
    assert now_unc["card"].endswith("Location uncertain: the walk time may be off.")
    assert "and walking at your usual speed of 4.0 km/h. Leave now" in states["nowRemembered"]["card"]
    assert "and walking at about 4.7 km/h. Leave now" in states["nowMeasured"]["card"]
    unlikely = states["unlikely"]["card"]
    assert unlikely.endswith(", but catching this bus is unlikely.") and "Leave" not in unlikely and "walking at" not in unlikely


def test_a_leave_by_tomorrow_reads_tomorrow_on_the_tile_and_in_sentence_two(tmp_path):
    # deterministic: the scenario sets a leave-by on the next Singapore day, so this does not depend on the real hour
    import re

    require_edge()
    with running_app(tmp_path, eta_minutes=[10.3]) as base:
        states = run_scenario("leaveshots", base, {})["result"]["states"]
    tomorrow = states["byTomorrow"]
    assert re.fullmatch(r"\d{1,2}:\d\d\u00a0AM \(tomorrow\)", tomorrow["tile"]) and tomorrow["tile"] == tomorrow["expectedClock"]
    assert "Leave by 2:00 AM (tomorrow) to reach your stop in " in tomorrow["card"]

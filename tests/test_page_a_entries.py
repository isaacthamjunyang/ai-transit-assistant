"""Page A renders only the new layout on every entry and at every probability: the first start (a low first poll no longer opens Page C),
a poll at 5, 25, 39, 40, 60, 81, 92 and 97 percent, and a second start after Back. The card, the alert (only when unlikely) and the two
buttons are there, and none of the old Page C card's strings. A train has the same card and neither the alert nor Other bus options.
360 and 1280 px, light and dark. No live API."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
PROBS = [5, 25, 39, 40, 60, 81, 92, 97]
COMBOS = [("l360", 360, 800, False), ("d1280", 1280, 900, True)]


@pytest.fixture(scope="module", params=COMBOS, ids=["360-light", "1280-dark"])
def runs(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    config = {"width": width, "height": height, "dark": dark, "probs": PROBS}
    out = {}
    with running_app(tmp_path_factory.mktemp("pel" + name), eta_minutes=[3.0]) as base:
        out["low"] = run_scenario("pageaentries", base, config, timeout=300)["result"]
    with running_app(tmp_path_factory.mktemp("peh" + name), eta_minutes=[10.3]) as base:
        out["high"] = run_scenario("pageaentries", base, config, timeout=300)["result"]
    with running_app(tmp_path_factory.mktemp("pet" + name), onemap=stub.by_mode({"TRANSIT": stub.train_first}), rail_table=_table(), lta_status=500) as base:
        out["train"] = run_scenario("pageaentries", base, config, timeout=300)["result"]
    return out


def _states(runs, kind):
    run = runs[kind]
    return [("first", run["first"]), ("restart", run["restart"])] + [(f"{point}%", run["fed"][str(point)]) for point in PROBS]


def _bus_states(runs):
    return [(f"{kind}/{name}", state) for kind in ("low", "high") for name, state in _states(runs, kind)]


def test_a_low_first_poll_shows_page_a_not_page_c(runs):
    first = runs["low"]["first"]
    assert first["ring"] == "5%" and first["pageA"] is True and first["pageCOpen"] is False and first["pageCShown"] is False, first["bodyClasses"]
    assert first["unlikelyNow"] is True and first["top"] == "live"


def test_every_entry_and_probability_has_the_new_card_and_none_of_the_old_layout(runs):
    for label, state in _bus_states(runs):
        assert state["pageA"] is True and state["pageCOpen"] is False and state["top"] == "live", label
        assert state["card"] and state["node"] and state["badge"] and state["to"] and state["to"].startswith("To "), label
        assert state["time"] and state["pill"] in ("live", "schedule only") and state["load"], label
        assert not any(state["old"][key] for key in ("chanceYour", "arrivingIn", "busArrives", "caption", "oldCard", "oldBtn", "oldWarn")), (label, state["old"])
        assert state["scrollWidth"] <= state["innerWidth"], label


def test_every_bus_state_has_both_buttons_and_the_alert_only_when_unlikely(runs):
    for label, state in _bus_states(runs):
        assert state["seeShown"] and state["seeText"] == "See bus arrival times" and state["seePulse"] is False and state["seeArrow"] is True, label
        assert state["otherShown"] and state["otherText"] == "Other bus options" and state["otherArrow"] is True, label
        assert state["otherPulse"] is False and "primary--icon" in state["otherClass"].split(), label  # blue with an arrow; neither pulses
        assert state["slotBanner"] is False, label  # the warning is drawn once, in the bar
        expected = state["unlikelyNow"]
        assert (state["alert"] == "Catching this bus is unlikely.") is expected and (state["alert"] is None) is (not expected), (label, state["alert"])


def test_the_alert_follows_the_rule_range_high_below_40(runs):
    for kind in ("low", "high"):
        fed = runs[kind]["fed"]
        for point in PROBS:
            assert (fed[str(point)]["alert"] is not None) is (point < 40), (kind, point)  # 39 shows it, 40 does not
            assert fed[str(point)]["ring"] == f"{point}%"


def test_the_restart_after_back_is_the_new_layout_again(runs):
    for kind in ("low", "high"):
        run = runs[kind]
        assert run["afterBack"]["top"] == "journey" and run["afterBack"]["monitoring"] is False
        restart = run["restart"]
        assert restart["pageA"] is True and restart["pageCOpen"] is False and restart["card"] and restart["otherShown"] and restart["seeShown"]
        assert not any(restart["old"][key] for key in ("chanceYour", "arrivingIn", "busArrives", "caption", "oldCard", "oldBtn", "oldWarn"))
    assert runs["low"]["restart"]["alert"] == "Catching this bus is unlikely." and runs["high"]["restart"]["alert"] is None


def test_a_train_has_the_same_card_and_neither_the_alert_nor_other_bus_options(runs):
    for label, state in _states(runs, "train"):
        assert state["train"] is True and state["pageA"] is True and state["pageCOpen"] is False, label
        assert state["card"] and state["node"] and state["badge"] and state["to"] and state["pill"] == "schedule only", label
        assert state["load"] is None or state["load"] == "", label  # a train has no crowding label
        assert state["seeShown"] and state["seeText"] == "See train times" and state["seePulse"] is False, label
        assert state["otherShown"] is False and state["alert"] is None and state["slotBanner"] is False, label
        assert not any(state["old"][key] for key in ("chanceYour", "arrivingIn", "busArrives", "caption", "oldCard", "oldBtn", "oldWarn")), (label, state["old"])


def test_the_old_layout_is_gone_from_the_page_the_css_the_copy_and_the_style_guide():
    for gone in ('id="reroute-current"', 'id="pc-title"', 'id="pc-see-arrivals"', 'id="pc-warn"', "updatePageCCurrent", "setCatchSub",
                 "CATCH_HEADING_PAGE_C_TEXT", 'openPageC("unlikely")'):
        assert gone not in INDEX, gone
    for gone in (".page-c-current", ".catch-card__sub {", ".catch-card__eta", ".catch-card__sep", ".catch-card__stop"):
        assert gone not in CSS, gone
    assert "chanceToCatchPageC" not in COPY and "Chance to catch your Bus" not in INDEX + COPY + GUIDE
    assert "sgCurrentBusCard" not in GUIDE and "sgSub(" not in GUIDE and "page-c-current" not in GUIDE
    assert "Page C's current-bus card keeps the earlier layout" not in PLAN and "the unlikely entry" not in PLAN.split("**Page C", 1)[1][:200]


def test_the_plan_and_the_style_guide_describe_the_entries():
    assert "Page A shows as usual, with `Catching this bus is unlikely.` and `Other bus options` in its bottom bar" in PLAN
    assert "Entry after `Other bus options` (tracking and polling continue)" in PLAN
    assert "sgPageCOther" in GUIDE and "otherOptions" in GUIDE
    assert re.search(r"Page A at 5%", GUIDE)
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()

"""A bus stop is shown by its name only: the five-digit code in brackets never reaches a screen, a notification, an
accessible name or a sentence. Codes stay in data, API responses, requests and URLs. MRT and LRT station codes stay.
No live service is called."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from config import display_stop_name
from leave_now import leave_now_notice
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
BUS_CODE = re.compile(r"\(\d{5}\)")


# ---- the one display function, in Python and in the page ----------------------------------------------------

@pytest.mark.parametrize("raw, shown", [
    ("Pebble Bay (90021)", "Pebble Bay"), ("Pebble Bay", "Pebble Bay"), ("Opp Toh Guan Rd (03011)", "Opp Toh Guan Rd"),
    ("Orchard Stn/Lucky Plaza  (09048) ", "Orchard Stn/Lucky Plaza"), ("", "Bus stop"), (None, "Bus stop"), ("90021", "Bus stop"),
    ("Bishan MRT Station (NS17)", "Bishan MRT Station (NS17)"),  # a station keeps its code
])
def test_display_stop_name(raw, shown):
    assert display_stop_name(raw) == shown


def test_the_page_has_one_display_function_and_no_place_joins_a_bus_stop_code_to_its_name():
    assert "function displayStopName(name)" in INDEX and INDEX.count("function displayStopName(") == 1
    assert 'replace(/\\s*\\(\\d{5}\\)/g, "")' in INDEX  # the same rule as config.display_stop_name
    for gone in ('+ " (" + confirmedDestinationStop.stop_code + ")"', '+ " (" + row.stop_code + ")"',
                 'var from = selectedBoardingStop.description || selectedBoardingStop.stop_code;'):
        assert gone not in INDEX, gone
    # only a station marker keeps its code on the map label
    assert INDEX.count('(isTrain() ? "<br>(" + escapeHtml(selectedBoardingStop.stop_code) + ")" : "")') == 2
    stop_label = INDEX.split("function stopLabel(name, code, leg) {", 1)[1].split("\n    }\n", 1)[0]
    assert "legIsRail(leg)" in stop_label and "displayStopName(name)" in stop_label  # only a station keeps its code


# ---- notifications and sentences written by the server ------------------------------------------------------

def test_the_leave_now_notification_and_the_reroute_message_carry_no_bus_stop_code():
    chance = {"point": 70, "range_low": 60, "range_high": 80, "data_quality": "live"}
    bus = {"is_primary": True, "is_missed": False, "position": "NextBus", "probability": chance}
    notice = leave_now_notice([bus], service_no="36", stop_code="90021", stop_name="Pebble Bay (90021)",
                              leave_by_iso="2026-10-08T16:00:00+08:00", notification_time="2026-10-08T15:59:00+08:00")
    assert notice["eligible"] is True
    assert notice["body"].startswith("Walk to Pebble Bay now to catch Bus 36.") and "90021" not in notice["body"]
    reroute_source = (ROOT / "reroute.py").read_text(encoding="utf-8")
    leave_source = (ROOT / "leave_now.py").read_text(encoding="utf-8")
    assert "at {display_stop_name(name)}." in reroute_source and "({code})." not in reroute_source
    assert "Walk to {display_stop_name(stop_name)} now" in leave_source and "({stop_code})" not in leave_source
    assert "({stop_code})" not in COPY and "({new_stop_code})" not in COPY
    assert "`Walk to {stop_name} now to catch Bus {service_no}." in PLAN
    assert "`Switched to Bus {new_service} at {new_stop_name}.`" in PLAN


def test_the_style_guide_and_copy_show_no_bus_stop_code():
    assert not BUS_CODE.search(GUIDE)
    assert not BUS_CODE.search(COPY)
    assert "(NS17)" in GUIDE or "NS17" in GUIDE or "(CC22)" in PLAN  # station codes are still shown somewhere


# ---- the rendered screens -------------------------------------------------------------------------------------

@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)], ids=["360-light", "1280-dark"])
def screens(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp("codes" + name), onemap=stub.by_mode({"TRANSIT": stub.bus_rail}),
                     lta_services={"18": [4.5]}) as base:
        return run_scenario("stopcodes", base, {"name": name, "width": width, "height": height, "dark": dark},
                            timeout=300)["result"]


def test_no_screen_shows_a_bus_stop_code_in_text_labels_or_accessible_names(screens):
    for key in ("overview", "pageA", "pageW", "pageB", "onWay"):
        shot = screens[key]
        for part in ("text", "names", "labels"):
            assert not BUS_CODE.search(shot[part]), (key, part, BUS_CODE.search(shot[part]))
    assert "Bef Toh Guan Rd" in screens["overview"]["text"]  # the bus stop is there, by name


def test_station_codes_still_appear(screens):
    assert "(NS17)" in screens["overview"]["text"]

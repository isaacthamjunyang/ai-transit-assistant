"""After "No, I missed it": the options in group order, planner routes, no threshold text, and the empty case.

The search runs against a fake cache with a stubbed loader and a stubbed planner (no live API call). The page
checks run the real page in headless Edge at 360 and 1280 px, fed option bodies directly."""

import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import main
import pt_plan
import pt_route
from lta_static import StopAndRouteCache
from nearby import EARTH_RADIUS_M
from page_runner import require_edge, run_scenario, running_app
from reroute import MISS_ROW_LIMIT, NORMAL_MARGIN, plan_options, plan_reroute

USES_REROUTE_PLANNER = True  # the planner helper is tested here with the OneMap call stubbed
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 15, 0, tzinfo=SGT)  # a Tuesday
LAT, LON = 1.3, 103.8
HERE, NEAR, ROAD, DEST = "90041", "90150", "90183", "99999"
ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
LEFT = "Bus 174 has left. Here are your other options."
NONE = "No other buses or routes are available right now."
THRESHOLD = ("improvement threshold", "low catch probability")


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _cache(closed=()):
    stops = []
    for code, metres in ((HERE, 0), (NEAR, 150), (ROAD, 180), (DEST, 3000)):
        lat, lon = _north(metres)
        stops.append({"BusStopCode": code, "Description": f"Stop {code}", "RoadName": "Rd", "Latitude": lat, "Longitude": lon})
    routes = []
    for service, codes in (("174", (HERE, NEAR)), ("36", (HERE,)), ("61", (NEAR,)), ("190", (ROAD,))):
        for code in codes:
            row = {"ServiceNo": service, "Direction": 1, "BusStopCode": code, "StopSequence": 1, "Distance": 0}
            if (service, code) in closed:
                row.update(WD_FirstBus="0500", WD_LastBus="0600", SAT_FirstBus="0500", SAT_LastBus="0600",
                           SUN_FirstBus="0500", SUN_LastBus="0600")
            routes.append(row)
        routes.append({"ServiceNo": service, "Direction": 1, "BusStopCode": DEST, "StopSequence": 9, "Distance": 3.0})
    return StopAndRouteCache(stops, routes, [])


def _bus(position, minutes, point, monitored=False):
    return {
        "position": position, "arrival_time": (NOW + timedelta(minutes=minutes)).isoformat(), "is_missed": False,
        "is_primary": False, "monitored": monitored, "latitude": LAT, "longitude": LON,
        "probability": {"point": point, "range_low": point, "range_high": min(92, point + 5),
                        "slack_seconds": 10, "data_quality": "live"},
    }


def _loaded(code, service, buses):
    return {"status": "ok", "stop_code": code, "service_no": service, "buses": buses}


def _search(loader, planner=None, current_buses=None, cache=None, after_miss=True):
    if current_buses is None:
        current_buses = [_bus("NextBus", 2, 76), _bus("NextBus2", 20, 60), _bus("NextBus3", 32, 50)]
    missed = datetime.fromisoformat(current_buses[0]["arrival_time"]).timestamp()
    dest_lat, dest_lon = _north(3000)
    return plan_options(
        cache=cache or _cache(), current=_loaded(HERE, "174", current_buses), user_lat=LAT, user_lon=LON,
        destination_stop_code=DEST, place_lat=dest_lat, place_lon=dest_lon, arrive_by=None, now=NOW,
        loader=loader, missed_eta_epoch=missed, planner=planner, after_miss=after_miss)


def _loader(table):
    def load(code, service):
        return _loaded(code, service, table.get((code, service), []))
    return load


def _everything(result):
    return list(result["cards"]) + result["rows"]


def test_the_same_service_comes_first_then_other_services_then_nearby_stops_each_by_arrival():
    loader = _loader({
        (HERE, "36"): [_bus("NextBus", 11, 40), _bus("NextBus2", 6, 90)],
        (NEAR, "174"): [_bus("NextBus", 4, 80)],
        (NEAR, "61"): [_bus("NextBus", 3, 85)],
    })
    result = _search(loader)
    rows = _everything(result)
    groups = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    assert {r["service_no"] for r in groups[1]} == {"174"} and all(r["stop_code"] == HERE for r in groups[1])
    assert {r["service_no"] for r in groups[2]} == {"36"}
    assert {r["stop_code"] for r in groups[3]} == {NEAR}
    # the alternatives are ordered by destination arrival (no estimate last), not by group
    keys = [(r["destination_arrival"] is None, r["destination_arrival"] or "", r["arrival_time"]) for r in result["rows"]]
    assert keys == sorted(keys)


def test_the_bus_that_left_is_not_listed_and_there_is_no_improvement_threshold():
    # the alternative is far below the missed bus's 76 + 15 and is still listed
    loader = _loader({(HERE, "36"): [_bus("NextBus", 6, 30)]})
    result = _search(loader)
    missed_at = (NOW + timedelta(minutes=2)).replace(microsecond=0).isoformat()
    assert all(r["arrival_time"] != missed_at for r in _everything(result))
    assert any(r["service_no"] == "36" and r["point"] == 30 for r in _everything(result))


def test_at_most_five_rows_are_listed_with_the_nearest_first_in_each_group():
    many = [_bus("NextBus", 5 + n, 60) for n in range(3)]
    loader = _loader({(HERE, "36"): many, (NEAR, "174"): many, (NEAR, "61"): many})
    result = _search(loader)
    assert len(result["rows"]) == MISS_ROW_LIMIT == 5
    keys = [(r["destination_arrival"] is None, r["destination_arrival"] or "", r["arrival_time"]) for r in result["rows"]]
    assert keys == sorted(keys)  # earliest destination arrival first, no estimate last


def test_a_planner_pair_the_plan_already_covers_is_looked_up_once():
    loader = _loader({(ROAD, "190"): [_bus("NextBus", 8, 65)]})
    calls = []
    result = _search(loader, planner=lambda: calls.append(1) or [(ROAD, "190")])
    assert calls == [1]
    assert len([r for r in _everything(result) if r["service_no"] == "190"]) == 1


def test_a_planner_route_beyond_a_direct_link_is_listed_and_hours_filter_it():
    # stop 90999 is in the cache and has service 190 on a route that reaches no destination stop directly
    stops = _cache().stops + [{"BusStopCode": "90999", "Description": "Elsewhere", "RoadName": "Rd",
                              "Latitude": _north(250)[0], "Longitude": LON}]
    routes = list(_cache().routes) + [
        {"ServiceNo": "190", "Direction": 1, "BusStopCode": "90999", "StopSequence": 1, "Distance": 0}]
    cache = StopAndRouteCache(stops, routes, [])
    loader = _loader({("90999", "190"): [_bus("NextBus", 8, 65)]})
    result = _search(loader, planner=lambda: [("90999", "190")], cache=cache)
    planned = [r for r in _everything(result) if r["stop_code"] == "90999"]
    assert len(planned) == 1 and planned[0]["group"] == 3
    assert planned[0]["point"] == 65 and planned[0]["leave_by"] is not None
    closed_routes = [dict(r) for r in routes]
    for row in closed_routes:
        if row["BusStopCode"] == "90999":
            row.update(WD_FirstBus="0500", WD_LastBus="0600", SAT_FirstBus="0500", SAT_LastBus="0600",
                       SUN_FirstBus="0500", SUN_LastBus="0600")
    shut = _search(loader, planner=lambda: [("90999", "190")], cache=StopAndRouteCache(stops, closed_routes, []))
    assert not [r for r in _everything(shut) if r["stop_code"] == "90999"]


def test_a_failing_planner_changes_nothing():
    loader = _loader({(HERE, "36"): [_bus("NextBus", 14, 50)]})

    def broken():
        raise RuntimeError("no service")

    with_failure = _search(loader, planner=broken)
    without = _search(loader)
    assert [r["id"] for r in _everything(with_failure)] == [r["id"] for r in _everything(without)]


def test_the_unlikely_entry_orders_by_destination_arrival_and_ignores_the_planner():
    loader = _loader({(HERE, "36"): [_bus("NextBus", 14, 50)], (ROAD, "190"): [_bus("NextBus", 8, 65)]})
    calls = []
    result = _search(loader, planner=lambda: calls.append(1) or [(ROAD, "190")], after_miss=False)
    assert calls == []
    keys = [(r["destination_arrival"] is None, r["destination_arrival"] or "", int(r["service_no"]))
            for r in result["rows"]]
    assert keys == sorted(keys)


def test_nothing_found_is_an_empty_result():
    result = _search(_loader({}), current_buses=[_bus("NextBus", 2, 76)])
    assert result["recommended"] is None and result["rows"] == []


def test_the_improvement_threshold_still_decides_the_automatic_switch_before_a_miss():
    assert NORMAL_MARGIN == 15
    primary = _bus("NextBus", 6, 20)
    primary["is_primary"] = True
    primary["probability"] = {"point": 20, "range_low": 10, "range_high": 30, "slack_seconds": -60,
                              "data_quality": "live"}
    # range_low 44 is below 30 + 15, so there is no switch; 45 passes
    for low, switched in ((44, False), (45, True)):
        other = _bus("NextBus2", 9, low + 2)
        other["probability"] = {"point": low + 2, "range_low": low, "range_high": low + 8, "slack_seconds": 90,
                                "data_quality": "live"}
        dest_lat, dest_lon = _north(3000)
        decision = plan_reroute(
            cache=_cache(), current=_loaded(HERE, "174", [primary, other]), user_lat=LAT, user_lon=LON,
            accuracy_m=5.0, location_timestamp=None, destination_stop_code=DEST, place_lat=dest_lat,
            place_lon=dest_lon, arrive_by=None, last_reroute_at=None, now=NOW, loader=None)
        assert decision["switched"] is switched
        if not switched:
            assert "no_better_option" not in decision


# ---- the planner helper (OneMap stubbed: no live call) -------------------------------------------------------

def _plan_result(*first_legs):
    """A planner answer: each bus first leg is one usable itinerary (`starts`, as plan_multi_leg returns them)."""
    return {"status": "ok", "starts": [
        {"boarding_stop_code": leg["boarding_stop_code"], "service_no": leg["service_no"],
         "after_boarding_minutes": 20.0} for leg in first_legs if leg.get("kind") == "bus"]}


def _start(dest_lat, dest_lon):
    return main._reroute_planner_starts(_cache(), LAT, LON, HERE, DEST, dest_lat, dest_lon, None, 1.2, NOW)


def test_the_planner_helper_keeps_only_routes_whose_first_leg_is_a_bus(monkeypatch):
    seen = []
    results = iter([
        _plan_result({"kind": "bus", "boarding_stop_code": NEAR, "service_no": "61"},
                     {"kind": "rail", "boarding_stop_code": "NS1", "service_no": ""}),
        _plan_result({"kind": "bus", "boarding_stop_code": NEAR, "service_no": "61"},
                     {"kind": "bus", "boarding_stop_code": ROAD, "service_no": "190"}),
    ])

    def fake(cache, **kw):
        seen.append(kw)
        return next(results)

    monkeypatch.setattr(pt_plan, "plan_multi_leg", fake)
    monkeypatch.setattr(main, "read_onemap_credentials", lambda: ("", "", ""))
    monkeypatch.setattr(main.demo, "destination_is_simulated", lambda: False)
    assert _start(*_north(3000)) == [(NEAR, "61", 20.0), (NEAR, "61", 20.0), (ROAD, "190", 20.0)]
    assert [kw["origin_stop_code"] for kw in seen] == [NEAR, ROAD]
    assert all(kw["priority"] == pt_plan.PRIORITY_BUS_ONLY for kw in seen)


def test_the_planner_helper_returns_nothing_when_onemap_is_unavailable(monkeypatch):
    def down(cache, **kw):
        raise pt_route.RouteUnavailable("timeout")

    monkeypatch.setattr(pt_plan, "plan_multi_leg", down)
    monkeypatch.setattr(main, "read_onemap_credentials", lambda: ("", "", ""))
    monkeypatch.setattr(main.demo, "destination_is_simulated", lambda: False)
    assert _start(*_north(3000)) == []


def test_the_planner_helper_is_skipped_in_demo_mode(monkeypatch):
    monkeypatch.setattr(main.demo, "destination_is_simulated", lambda: True)
    assert _start(*_north(3000)) == []


# ---- text and markup -------------------------------------------------------------------------------------------

def _function(name):
    start = INDEX.index(f"function {name}(")
    return INDEX[start:INDEX.index("\n    function ", start + 10)]


def test_the_strings_come_from_copy_js_and_are_mirrored_exactly():
    assert f'noOtherOptions: "{NONE}"' in COPY
    assert f'var NO_OTHER_OPTIONS = "{NONE}";' in INDEX
    assert 'busLeftNotice: "Bus {service} has left. Here are your other options."' in COPY


def test_no_threshold_text_after_a_miss():
    assert "noBetterText" not in INDEX and "NO_BETTER" not in INDEX and "improvement threshold" not in INDEX
    render = _function("renderPageC")
    assert "emptyMiss" in render and "noOptionsState()" in render and "NO_OTHER_OPTIONS" in render
    assert 'document.getElementById("pc-ride-apps")' in render
    assert 'id="pc-ride-apps" class="ride-apps" hidden' in INDEX


def test_the_plan_and_the_style_guide_say_so():
    assert NONE in PLAN
    assert "noOtherOptions" in GUIDE
    for needle in ("same service", "other services", "planner", "five rows", "service_hours"):
        assert needle in PLAN, needle


# ---- the real page (headless Edge, no request is made) ---------------------------------------------------------

@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)],
                ids=["360-light", "1280-dark"])
def report(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(name)) as base:
        return run_scenario("missedoptions", base, {"name": name, "width": width, "height": height, "dark": dark})["result"]


def test_with_options_the_left_text_leads_and_the_rows_keep_the_servers_order(report):
    shown = report["withOptions"]
    assert shown["notice"] == LEFT
    assert shown["none"] == "" and shown["ride"] is False
    services = [row["service"] for row in shown["rows"]]
    assert services == ["174", "174", "36", "61", "190"]
    assert not any(phrase in shown["page"] for phrase in THRESHOLD)
    assert shown["scrollWidth"] <= shown["innerWidth"]


def test_with_nothing_found_the_plain_text_and_the_ride_app_card_show(report):
    shown = report["empty"]
    assert shown["notice"] == NONE
    assert shown["none"] == "" and shown["rows"] == []
    assert shown["ride"] is True and shown["rideLinks"] == 5
    assert not any(phrase in shown["page"] for phrase in THRESHOLD)
    assert LEFT not in shown["page"]
    assert shown["scrollWidth"] <= shown["innerWidth"]


def test_the_entry_after_other_bus_options_has_its_own_notice_and_no_ride_apps(report):
    shown = report["unlikely"]
    assert shown["ride"] is False
    assert shown["notice"] == "Here are your other options."  # the entry after Other bus options: its own notice, no left text


# ---- the shared row format on Page C (item 4) and no bus stop code on screen (item 7)

def test_page_c_rows_use_the_shared_row_format(report):
    shown = report["withCard"]
    assert [row["service"] for row in shown["rows"]] == ["174", "174", "36", "61", "190"]
    for row in shown["rows"]:
        assert row["badgeBus"] is True  # the bus number badge, "Bus" for a screen reader
        assert row["to"] == "To Pebble Bay"  # the destination stop, its name only
        assert re.fullmatch(r"Arrives in (\d+ min|under 1 min)", row["when"].replace(chr(160), " ")), row["when"]
        assert row["ring"] and row["ring"] != "none"  # the marker's ring (grey for a bus)
        assert re.search(r"Reach destination by: \d{1,2}:\d{2}\s[AP]M", row["text"]), row["text"]
    (card,) = shown["cardRows"]
    assert card["badge"] == "36" and card["badgeBus"] is True and card["oldTitle"] is False
    assert card["line"].endswith("To Pebble Bay") and "90021" not in card["line"]
    assert re.fullmatch(r"Arrives in (\d+ min|under 1 min)", card["when"].replace(chr(160), " "))
    assert card["ring"] and card["ring"] != "none" and card["ringEl"] is True  # the chance ring stays
    assert card["leave"].startswith("Leave by: ")
    assert re.fullmatch(r"Reach destination by: \d{1,2}:\d{2} [AP]M( \(tomorrow\))?", card["destination"])
    assert card["tags"] == ["Highest catch probability"]
    assert card["sentences"] == 0
    assert card["button"].startswith("Switch to Bus 36 in ") and card["oldBlocks"] is False
    assert card["right"] <= shown["innerWidth"] and shown["scrollWidth"] <= shown["innerWidth"]


def test_page_c_shows_no_bus_stop_code(report):
    for key in ("withOptions", "withCard", "empty", "unlikely"):
        assert not re.search(r"\(\d{5}\)", report[key]["page"]), key


# ---- the none sentence has one gate (noOptionsState) ------------------------------------------------------------

SHORT = "Catching this bus is unlikely."
LONG = "Catching this bus is unlikely."  # one sentence now


def test_the_none_sentence_is_decided_in_one_function_and_the_strings_are_mirrored():
    gate = _function("noOptionsState")
    assert "pageC.loading || pageC.failed || !pageC.options" in gate and '"missed"' in gate
    assert f'currentWarning: "{SHORT}"' in COPY and "currentWarningNone" not in COPY and 'otherOptions: "Here are your other options."' in COPY
    assert f'var CURRENT_WARNING_TEXT = "{SHORT}";' in INDEX and "CURRENT_WARNING_NONE_TEXT" not in INDEX
    assert "currentWarningNone" not in GUIDE and "Other bus options" in PLAN and SHORT in PLAN


@pytest.fixture(scope="module", params=[("n360", 360, 800, False), ("n1280", 1280, 900, True)],
                ids=["360-light", "1280-dark"])
def states(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(name)) as base:
        return run_scenario("nonesentence", base, {"name": name, "width": width, "height": height, "dark": dark},
                            timeout=300)["result"]


def test_the_other_entry_says_here_are_your_options_and_the_none_sentence_only_after_a_completed_empty_search(states):
    empty = states["other_empty"]
    assert empty["notice"] == NONE and empty["occurrences"] == 1 and empty["none"] == "" and empty["ride"] is False  # no ride-app card
    assert empty["cards"] == 0 and empty["rows"] == 0
    found = states["other_found"]
    assert found["notice"] == "Here are your other options." and found["rows"] == 1 and found["occurrences"] == 0
    assert states["other_loading"]["notice"] == "Here are your other options." and states["other_loading"]["occurrences"] == 0
    failed = states["other_failed"]
    assert failed["notice"] is None and failed["occurrences"] == 0 and failed["ride"] is False
    assert failed["none"] == "Could not load other buses. Try the refresh button."


def test_missed_entry_shows_the_sentence_and_ride_apps_only_after_a_completed_empty_search(states):
    empty = states["missed_empty"]
    assert empty["notice"] == NONE and empty["occurrences"] == 1 and empty["ride"] is True
    found = states["missed_found"]
    assert found["notice"] == LEFT and found["occurrences"] == 0 and found["ride"] is False and found["rows"] == 1
    for name in ("missed_loading", "missed_failed"):
        assert states[name]["occurrences"] == 0 and states[name]["ride"] is False
        assert states[name]["notice"] == LEFT
    assert states["missed_failed"]["none"] == "Could not load other buses. Try the refresh button."


def test_no_state_overflows_the_page(states):
    assert all(state["scrollWidth"] <= state["innerWidth"] for state in states.values())

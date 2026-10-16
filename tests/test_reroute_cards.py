"""The reroute page's options: two metrics per option (bus arrival, destination arrival), one shared destination
function for every source, two recommended cards with fixed tags and sentences, and the ordered alternatives.
No live service is called: the loader and the planner are stubs and the page is fed bodies directly."""

import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import journey
import pt_plan
import recommend
from lta_static import StopAndRouteCache
from nearby import EARTH_RADIUS_M
from reroute import plan_options, rank_options

USES_BUS_TRAFFIC = True  # the peak factor is tested here with a pinned clock
SGT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
LAT, LON = 1.3, 103.8
HERE, NEAR, DEST = "90041", "90150", "99999"


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _iso(base, minutes):
    return (base + timedelta(minutes=minutes)).isoformat()


T0 = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)  # a Tuesday, off-peak


def _row(service, point, high=None, wait=5, dest=30, base=T0, rid=None):
    """An option row: `wait` minutes to the bus, `dest` minutes to the destination (None: no estimate)."""
    return {
        "id": rid or f"{service}|X|{wait}",
        "service_no": service,
        "stop_code": "X",
        "point": point,
        "range_low": max(0, point - 10),
        "range_high": point + 5 if high is None else high,
        "arrival_time": _iso(base, wait),
        "estimated_arrival": None if dest is None else _iso(base, dest),
        "destination_arrival": None if dest is None else _iso(base, dest),
        "distance_m": 0,
        "walk_m": 0,
    }


def _cards(rows, **kw):
    return rank_options(rows, kw.get("target"), "recommended", kw.get("after_miss", False))


def _tags(result):
    return [(card["service_no"], card["tags"]) for card in result["cards"]]


# ---- the cards ------------------------------------------------------------------------------------------------

def test_one_option_winning_both_tags_shows_one_card_with_both_and_next_best_fills_the_second_slot():
    rows = [_row("7", 80, wait=4, dest=20), _row("16", 60, wait=6, dest=30), _row("36", 50, wait=8, dest=25)]
    result = _cards(rows)
    assert _tags(result) == [("7", ["fastest", "highest_chance"]), ("16", ["next_best"])]
    assert [row["service_no"] for row in result["rows"]] == ["36"]  # the cards are not in the alternatives


def test_the_tags_go_to_different_cards_when_different_options_win():
    rows = [_row("7", 90, wait=9, dest=40), _row("16", 60, wait=3, dest=20), _row("36", 70, wait=5, dest=30)]
    result = _cards(rows)
    assert _tags(result) == [("16", ["fastest"]), ("7", ["highest_chance"])]
    assert [row["service_no"] for row in result["rows"]] == ["36"]


def test_fastest_ties_go_to_the_shorter_bus_wait_then_the_higher_chance():
    rows = [_row("7", 60, wait=9, dest=20), _row("16", 55, wait=4, dest=20), _row("36", 70, wait=4, dest=20)]
    assert _tags(_cards(rows))[0] == ("36", ["fastest", "highest_chance"])  # 36 and 16 tie on wait, 36 is likelier
    rows = [_row("7", 60, wait=9, dest=20), _row("16", 55, wait=4, dest=20), _row("36", 99, wait=12, dest=40)]
    assert _tags(_cards(rows))[0] == ("16", ["fastest"])  # the shorter wait beats the higher chance


def test_highest_chance_ties_go_to_the_earlier_destination_then_the_shorter_wait():
    rows = [_row("7", 70, wait=3, dest=30), _row("16", 70, wait=8, dest=25), _row("36", 50, wait=1, dest=10)]
    result = _cards(rows)
    assert _tags(result) == [("36", ["fastest"]), ("16", ["highest_chance"])]
    rows = [_row("7", 70, wait=3, dest=30), _row("16", 70, wait=8, dest=30), _row("36", 50, wait=1, dest=10)]
    assert _tags(_cards(rows))[1] == ("7", ["highest_chance"])  # equal destination: the shorter wait


def test_one_option_only_is_one_card_even_below_forty():
    result = _cards([_row("7", 20, high=30, dest=25)])
    assert _tags(result) == [("7", ["fastest", "highest_chance"])] and result["rows"] == []


def test_the_low_chance_gate_keeps_a_low_option_out_of_both_cards_and_in_the_alternatives():
    rows = [_row("7", 30, high=39, wait=2, dest=10), _row("16", 60, wait=6, dest=35), _row("36", 55, wait=8, dest=40)]
    result = _cards(rows)
    assert _tags(result) == [("16", ["fastest", "highest_chance"]), ("36", ["next_best"])]
    assert [row["service_no"] for row in result["rows"]] == ["7"] and result["rows"][0]["unlikely"] is True
    # two options, both low: no card at all, both listed
    low = _cards([_row("7", 30, high=39), _row("16", 25, high=35)])
    assert low["cards"] == [] and low["mode"] == "none" and len(low["rows"]) == 2


def test_the_next_best_never_comes_from_below_forty_while_another_exists():
    rows = [_row("7", 80, wait=4, dest=20), _row("16", 30, high=39, wait=6, dest=30)]
    result = _cards(rows)
    assert _tags(result) == [("7", ["fastest", "highest_chance"])]  # one card: no eligible option is left
    assert [row["service_no"] for row in result["rows"]] == ["16"]


def test_no_destination_estimate_shows_only_the_highest_catch_probability_card():
    rows = [_row("7", 80, dest=None), _row("16", 60, dest=None)]
    result = _cards(rows)
    assert _tags(result) == [("7", ["highest_chance"])]
    assert all(card["destination_arrival"] is None for card in result["cards"])
    # an estimate on a low-chance option does not give a Fastest card while an eligible option exists
    mixed = [_row("7", 80, dest=None), _row("16", 30, high=39, dest=10)]
    assert _tags(_cards(mixed)) == [("7", ["highest_chance"])]


def test_the_alternatives_sort_by_destination_arrival_with_no_estimate_last_and_keep_the_five_row_cap():
    rows = [_row(str(n), 40 + n, wait=n, dest=60 - n) for n in range(1, 10)] + [_row("77", 41, wait=1, dest=None)]
    result = _cards(rows, after_miss=True)
    assert len(result["rows"]) == 5
    keys = [(r["destination_arrival"] is None, r["destination_arrival"] or "") for r in result["rows"]]
    assert keys == sorted(keys)
    uncapped = _cards(rows, after_miss=False)
    assert len(uncapped["rows"]) == 8 and uncapped["rows"][-1]["service_no"] == "77"


def test_cards_carry_tags_only_no_sentence_and_no_removed_tags_remain():
    rows = [_row("7", 80, wait=4, dest=20), _row("16", 60, wait=6, dest=30)]
    for card in _cards(rows)["cards"]:
        assert card["tags"] and not {"reasons", "badges", "reason_code", "reason_text", "explanation"} & set(card)
    assert recommend.TAG_LABEL == {"fastest": "Fastest to destination", "highest_chance": "Highest catch probability",
                                   "next_best": "Next best"}
    assert not hasattr(recommend, "TAG_SENTENCE") and not hasattr(recommend, "tag_sentence")


def test_the_old_tags_and_reason_strings_are_gone_from_the_page_the_copy_and_the_guide():
    for gone in ("Highest chance on time", "Soonest bus", "Reach your destination quickly", "Better option found",
                 "Recommended option", "Fastest option", "Reach destination about", "Destination arrival {time}"):
        for text in (INDEX, COPY, GUIDE):
            assert gone not in text, gone
    page = INDEX.split("function buildOptionCard(row)", 1)[1].split("function destinationText", 1)[0]
    assert "AI_SPARK_SVG" not in page and "explanation" not in page and "badges" not in page


# ---- the one destination function ------------------------------------------------------------------------------

def test_the_function_adds_ride_with_the_factor_of_its_own_start_transfers_and_the_final_walk():
    off = datetime(2026, 9, 29, 10, 0, tzinfo=SGT)
    peak = datetime(2026, 9, 29, 7, 30, tzinfo=SGT)
    base = journey.destination_arrival(off, route_km=6.0, end_walk_metres=0)
    assert base == off + timedelta(minutes=20)
    assert journey.destination_arrival(peak, route_km=6.0, end_walk_metres=0) == peak + timedelta(minutes=25)
    with_extras = journey.destination_arrival(off, route_km=6.0, transfer_minutes=6, end_walk_metres=300)
    assert with_extras > base + timedelta(minutes=6)  # the final walk is added after the transfer minutes
    assert journey.destination_arrival(off) is None and journey.destination_arrival(off, route_km=None) is None


def test_a_next_bus_that_crosses_into_the_peak_window_gets_the_peak_ride():
    before = datetime(2026, 9, 29, 6, 58, tzinfo=SGT)
    after = datetime(2026, 9, 29, 7, 2, tzinfo=SGT)
    a = journey.destination_arrival(before, route_km=6.0)
    b = journey.destination_arrival(after, route_km=6.0)
    assert (a - before) == timedelta(minutes=20) and (b - after) == timedelta(minutes=25)
    weekend = datetime(2026, 10, 3, 7, 30, tzinfo=SGT)  # a Saturday: no factor
    assert journey.destination_arrival(weekend, route_km=6.0) - weekend == timedelta(minutes=20)


def test_a_planner_itinerary_is_shifted_to_the_real_boarding_time_and_never_earlier():
    board = datetime(2026, 9, 29, 10, 0, tzinfo=SGT)
    assert journey.destination_arrival(board, itinerary_minutes=34.0) == board + timedelta(minutes=34)
    assert journey.destination_arrival(board, itinerary_minutes=-5) == board  # never earlier than the boarding
    late = board + timedelta(minutes=9)  # the real bus is 9 minutes later: the whole itinerary moves with it
    assert journey.destination_arrival(late, itinerary_minutes=34.0) == late + timedelta(minutes=34)


def test_the_next_day_crosses_midnight_and_the_page_adds_tomorrow():
    board = datetime(2026, 9, 29, 23, 50, tzinfo=SGT)
    arrival = journey.destination_arrival(board, route_km=9.0)
    assert arrival.date() == (board + timedelta(days=1)).date()
    assert "formatClock(row.destination_arrival, true)" in INDEX  # "(tomorrow)" comes from formatClock(.., true)


def test_one_function_serves_every_option_source():
    import reroute

    assert INDEX.count("destination_arrival") >= 2 and "estimated_arrival + " not in INDEX
    source = Path(reroute.__file__).read_text(encoding="utf-8")
    assert source.count("destination_arrival(") == 1  # one call site: _candidate_from_bus, for every source
    assert "from journey import" in source and "destination_arrival," in source
    helper = source.split("def _candidate_from_bus(", 1)[1].split("def _iso_or_none", 1)[0]
    assert "destination_arrival(" in helper and "bus_ride_minutes" not in helper
    # no other module computes a destination time for the reroute options
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "destination_arrival(" not in main_source


# ---- the sources, end to end with stubbed loader and planner --------------------------------------------------

def _cache():
    stops = []
    for code, metres in ((HERE, 0), (NEAR, 150), (DEST, 3000)):
        lat, lon = _north(metres)
        stops.append({"BusStopCode": code, "Description": f"Stop {code}", "RoadName": "Rd", "Latitude": lat, "Longitude": lon})
    routes = []
    for service, code in (("174", HERE), ("36", HERE), ("61", NEAR)):
        routes.append({"ServiceNo": service, "Direction": 1, "BusStopCode": code, "StopSequence": 1, "Distance": 0})
        routes.append({"ServiceNo": service, "Direction": 1, "BusStopCode": DEST, "StopSequence": 9, "Distance": 3.0})
    return StopAndRouteCache(stops, routes, [])


def _bus(position, minutes, point, now):
    return {
        "position": position, "arrival_time": _iso(now, minutes), "is_missed": False, "is_primary": False,
        "monitored": True, "latitude": LAT, "longitude": LON,
        "probability": {"point": point, "range_low": point, "range_high": min(92, point + 5), "slack_seconds": 10,
                        "data_quality": "live"},
    }


def _loaded(code, service, buses):
    return {"status": "ok", "stop_code": code, "service_no": service, "buses": buses}


def _search(now, current_buses, table=None, planner=None, after_miss=True, cache=None):
    table = table or {}
    missed = datetime.fromisoformat(current_buses[0]["arrival_time"]).timestamp()
    dest_lat, dest_lon = _north(3000)
    return plan_options(
        cache=cache or _cache(), current=_loaded(HERE, "174", current_buses), user_lat=LAT, user_lon=LON,
        destination_stop_code=DEST, place_lat=dest_lat, place_lon=dest_lon, arrive_by=None, now=now,
        loader=lambda code, service: _loaded(code, service, table.get((code, service), [])),
        missed_eta_epoch=missed, planner=planner, after_miss=after_miss)


def _everything(result):
    return {row["id"]: row for row in list(result["cards"]) + result["rows"]}


def test_same_service_other_service_and_nearby_options_all_get_a_destination_time():
    now = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
    table = {(HERE, "36"): [_bus("NextBus", 7, 60, now)], (NEAR, "61"): [_bus("NextBus", 9, 55, now)]}
    current = [_bus("NextBus", 2, 76, now), _bus("NextBus2", 12, 60, now)]
    rows = _everything(_search(now, current, table))
    assert {r["service_no"] for r in rows.values()} == {"174", "36", "61"}
    for row in rows.values():
        assert row["destination_arrival"] is not None
        gap = datetime.fromisoformat(row["destination_arrival"]) - datetime.fromisoformat(row["arrival_time"])
        assert gap > timedelta(minutes=8)  # the ride (3 km at the shared speed) plus the end walk
    # the same route data gives the same ride for the next bus of the missed service and for another service
    same = next(r for r in rows.values() if r["service_no"] == "174")
    other = next(r for r in rows.values() if r["service_no"] == "36")
    ride = lambda r: datetime.fromisoformat(r["destination_arrival"]) - datetime.fromisoformat(r["arrival_time"])  # noqa: E731
    assert ride(same) == ride(other)


def test_both_entries_give_the_same_destination_time_for_the_same_bus():
    now = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
    current = [_bus("NextBus", 2, 76, now), _bus("NextBus2", 12, 60, now)]
    missed = _everything(_search(now, current, after_miss=True))
    unlikely = _everything(_search(now, current, after_miss=False))
    assert missed.keys() == unlikely.keys() and missed
    for key in missed:
        assert missed[key]["destination_arrival"] == unlikely[key]["destination_arrival"]


def test_a_same_service_bus_that_crosses_into_the_peak_gets_its_own_factor_not_the_current_buss():
    now = datetime(2026, 9, 29, 6, 50, tzinfo=SGT)
    current = [_bus("NextBus", 2, 76, now), _bus("NextBus2", 6, 70, now), _bus("NextBus3", 20, 60, now)]
    rows = sorted(_everything(_search(now, current)).values(), key=lambda r: r["arrival_time"])
    first, second = rows  # 06:56 is before the window, 07:10 is inside it
    ride = lambda r: datetime.fromisoformat(r["destination_arrival"]) - datetime.fromisoformat(r["arrival_time"])  # noqa: E731
    assert ride(second) > ride(first)
    # only the ride is stretched: 1.25 x of the ride part (the final walk is the same)
    assert ride(second) - ride(first) > timedelta(minutes=2)


def test_planner_routes_use_the_earliest_ending_itinerary_shifted_to_the_real_bus():
    now = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
    stops = _cache().stops + [{"BusStopCode": "90999", "Description": "Elsewhere", "RoadName": "Rd",
                              "Latitude": _north(250)[0], "Longitude": LON}]
    routes = list(_cache().routes) + [
        {"ServiceNo": "190", "Direction": 1, "BusStopCode": "90999", "StopSequence": 1, "Distance": 0}]
    cache = StopAndRouteCache(stops, routes, [])
    table = {("90999", "190"): [_bus("NextBus", 8, 65, now)]}
    current = [_bus("NextBus", 2, 76, now)]
    starts = [("90999", "190", 44.0), ("90999", "190", 31.5), ("90999", "190", None)]
    result = _search(now, current, table, planner=lambda: starts, cache=cache)
    planned = [r for r in _everything(result).values() if r["stop_code"] == "90999"]
    assert len(planned) == 1
    boards = datetime.fromisoformat(planned[0]["arrival_time"])
    assert datetime.fromisoformat(planned[0]["destination_arrival"]) == boards + timedelta(minutes=31.5)
    # a planner start with no minutes has no destination estimate (and is still listed)
    none = _search(now, current, table, planner=lambda: [("90999", "190")], cache=cache)
    only = [r for r in _everything(none).values() if r["stop_code"] == "90999"]
    assert len(only) == 1 and only[0]["destination_arrival"] is None


# ---- the planner's usable itineraries --------------------------------------------------------------------------

def test_starts_come_from_usable_itineraries_only_so_a_closed_later_leg_is_excluded_before_the_choice():
    import test_pt_plan as tp

    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    result = tp.plan(tp.Server(default=tp._late_itinerary([0, 1])), fixture="late", now=now)
    starts = result["starts"]
    services = {start["service_no"] for start in starts}
    assert "143" not in services  # its second bus (59) is closed, so the whole itinerary is gone
    assert all(isinstance(start["after_boarding_minutes"], float) and start["after_boarding_minutes"] >= 0
               for start in starts)


def test_several_itineraries_sharing_a_first_bus_all_appear_and_the_search_keeps_the_earliest_ending():
    import test_pt_plan as tp

    payload = tp.pool3()[1]
    result = tp.plan(tp.Server(default=(200, payload)), fixture="bus_mrt", rail=None)
    starts = result["starts"]
    shared = [s for s in starts if s["service_no"] == "199"]
    assert len(shared) >= 2  # two itineraries board bus 199
    stop = shared[0]["boarding_stop_code"]
    smallest = min(s["after_boarding_minutes"] for s in shared if s["boarding_stop_code"] == stop)
    # the reroute search reduces them to the smallest minutes per (stop, service)
    now = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
    assert smallest <= max(s["after_boarding_minutes"] for s in shared)
    assert pt_plan._starts([], 1.2) == []
    assert now


# ---- the page --------------------------------------------------------------------------------------------------

def test_the_page_mirrors_the_copy_and_shows_the_three_lines_in_order():
    for key, text in (("tagFastest", "Fastest to destination"), ("tagHighest", "Highest catch probability"),
                      ("tagNextBest", "Next best"), ("destination", "Reach destination by: {time}"),
                      ("leaveBy", "Leave by: {time}"), ("arrivesIn", "Arrives in {minutes}")):
        assert f'{key}: "{text}"' in COPY, key
    assert 'var TAG_TEXT = { fastest: "Fastest to destination", highest_chance: "Highest catch probability", '\
           'next_best: "Next best" };' in INDEX
    assert 'var DESTINATION_TEXT = "Reach destination by: {time}";' in INDEX
    assert 'var LEAVE_BY_TEXT = "Leave by: {time}";' in INDEX
    assert 'var ARRIVES_IN_TEXT = "Arrives in {minutes}";' in INDEX
    row = INDEX.split("function buildOptionRow(row)", 1)[1].split("// Page C: the options page", 1)[0]
    assert "destinationText(row)" in row and "optionWhenText(row)" in row
    card = INDEX.split("function buildOptionCard(row)", 1)[1].split("function buildOptionRow(row)", 1)[0]
    assert "destinationText(row)" in card and "buildSwitchButton(row)" in card and "row.reasons" not in card
    text = INDEX.split("function destinationText(row)", 1)[1].split("}\n", 1)[0]
    assert "row.destination_arrival" in text and 'return ""' in text  # no estimate: no destination line


def test_the_plan_describes_the_two_cards_the_tags_the_order_and_the_one_function():
    for needle in ("Fastest to destination", "Highest catch probability", "Next best", "Reach destination by: {time}",
                   "Arrives in {n} min", "Alternative options", "one shared function"):
        assert needle in PLAN, needle
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()


# ---- the real page (headless Edge, no request is made) ---------------------------------------------------------

from page_runner import require_edge, run_scenario, running_app  # noqa: E402


@pytest.fixture(scope="module", params=[("c360", 360, 800, False), ("c1280", 1280, 900, True)],
                ids=["360-light", "1280-dark"])
def page(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(name)) as base:
        return run_scenario("reroutecards", base, {"name": name, "width": width, "height": height, "dark": dark},
                            timeout=300)["result"]


def test_two_cards_each_with_its_tag_three_lines_in_order_and_switch_button(page):
    cards = page["two"]["cards"]
    assert [c["tags"] for c in cards] == [["Fastest to destination"], ["Highest catch probability"]]
    for card in cards:
        assert re.fullmatch(r"Arrives in (\d+ min|under 1 min)", card["when"])
        assert re.fullmatch(r"Reach destination by: \d{1,2}:\d{2} [AP]M( \(tomorrow\))?", card["destination"])
        assert re.fullmatch(r"Leave by: \d{1,2}:\d{2}\s[AP]M( \(tomorrow\))?", card["leave"])
        assert card["order"] == ["catch-card__when", "option-card__destination", "option-card__leave"]
        assert card["sentences"] == 0
        assert card["button"].startswith("Switch to Bus ") and card["ring"] is True
        assert card["right"] <= page["two"]["innerWidth"]
    assert page["two"]["heading"] == "Alternative options" and page["two"]["rows"] == 1
    assert page["two"]["scrollWidth"] <= page["two"]["innerWidth"]
    assert page["two"]["aiBlocks"] == 0 and page["two"]["pills"] == 0


def test_one_card_with_both_tags_and_the_next_best_second(page):
    cards = page["both"]["cards"]
    assert [c["tags"] for c in cards] == [["Fastest to destination", "Highest catch probability"], ["Next best"]]
    assert all(card["sentences"] == 0 for card in cards)


def test_one_option_is_one_card_with_both_tags(page):
    cards = page["single"]["cards"]
    assert len(cards) == 1 and cards[0]["tags"] == ["Fastest to destination", "Highest catch probability"]
    assert page["single"]["rows"] == 0


def test_no_estimate_has_no_destination_line_and_no_fastest_card(page):
    cards = page["noEstimate"]["cards"]
    assert [c["tags"] for c in cards] == [["Highest catch probability"]]
    assert cards[0]["destination"] is None
    assert cards[0]["order"] == ["catch-card__when", "option-card__leave"]  # no destination line
    assert page["noEstimate"]["rowDestinations"] == [None]


def test_the_next_day_destination_says_tomorrow(page):
    card = page["tomorrow"]["cards"][0]
    assert card["destination"].endswith(" (tomorrow)"), card["destination"]


def test_removed_tags_are_not_on_the_page(page):
    for key in ("two", "both", "single", "noEstimate", "tomorrow"):
        text = page[key]["text"]
        for sentence in ("should get you to your destination first", "has the highest chance of catching",
                         "has the next highest chance of catching"):
            assert sentence not in text, (key, sentence)
        for gone in ("Highest chance on time", "Soonest bus", "Better option found", "Recommended option",
                     "Reach your destination quickly", "AI Explanation", "Reach destination about"):
            assert gone not in text, (key, gone)


# ---- no real request: the endpoint with every outside call stubbed ---------------------------------------------

USES_REROUTE_PLANNER = True  # the planner helper runs here with plan_multi_leg stubbed


def test_the_options_endpoint_returns_cards_with_both_metrics_and_makes_no_outside_request(tmp_path, monkeypatch):
    import conftest
    import main
    import test_page_c_entry as entry

    client, params, _ = entry._poll_client(monkeypatch, tmp_path, high=30, point=20)
    planner_calls = []

    def fake_plan(cache, **kw):
        planner_calls.append(kw["origin_stop_code"])
        return {"status": "ok", "starts": [
            {"boarding_stop_code": kw["origin_stop_code"], "service_no": "18", "after_boarding_minutes": 21.0}]}

    monkeypatch.setattr(pt_plan, "plan_multi_leg", fake_plan)
    monkeypatch.setattr(main, "read_onemap_credentials", lambda: ("", "", ""))
    monkeypatch.setattr(main.demo, "destination_is_simulated", lambda: False)
    before = len(conftest.NETWORK_LEAKS)
    options = {k: params[k] for k in ("stop_code", "service_no", "lat", "lon", "destination_stop_code", "dest_lat", "dest_lon")}
    options["accuracy"] = 12
    with client:
        body = client.get("/api/reroute-options", params=options).json()
    assert body["status"] == "ok"
    result = body["options"]
    assert result["cards"] and result["recommended"] is result["cards"][0] or result["cards"][0]["id"] == result["recommended_id"]
    for row in result["cards"] + result["rows"]:
        assert "destination_arrival" in row and "arrival_time" in row
        assert not {"badges", "reason_code", "explanation"} & set(row)
    assert len(conftest.NETWORK_LEAKS) == before  # nothing tried to leave the machine

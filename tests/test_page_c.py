"""Page C: one probability per option named by its arrival, estimates from the single function, merged card."""

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import explain
import main
from catch_heuristic import score_buses
from journey import build_journey
from lta_static import StopAndRouteCache
from nearby import EARTH_RADIUS_M
from reroute import plan_options

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 15, 0, tzinfo=SGT)
LAT, LON = 1.3, 103.8
HERE, NEAR, FAR, DEST = "90041", "90150", "90183", "99999"
INDEX = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _cache():
    stops = []
    for code, name, metres in (
        (HERE, "Tanjong Rhu Stn Exit 2", 0),
        (NEAR, "Near stop", 150),
        (FAR, "Far stop", 183),
        (DEST, "Aft Sims Way", 3000),
    ):
        lat, lon = _north(metres)
        stops.append({"BusStopCode": code, "Description": name, "RoadName": "Rd", "Latitude": lat, "Longitude": lon})
    routes = []
    for code in (HERE, NEAR, FAR):
        routes.append({"ServiceNo": "11", "Direction": 1, "BusStopCode": code, "StopSequence": 1, "Distance": 0})
    routes.append({"ServiceNo": "11", "Direction": 1, "BusStopCode": DEST, "StopSequence": 9, "Distance": 3.0})
    return StopAndRouteCache(stops, routes, [])


def _bus(position, minutes, point, monitored=True):
    return {
        "position": position,
        "arrival_time": (NOW + timedelta(minutes=minutes)).isoformat(),
        "is_missed": False,
        "is_primary": False,
        "monitored": monitored,
        "latitude": LAT,
        "longitude": LON,
        "probability": {
            "point": point,
            "range_low": point,
            "range_high": min(92, point + 5),
            "slack_seconds": 10,
            "data_quality": "live",
        },
    }


def _loaded(code, service, buses):
    return {"status": "ok", "stop_code": code, "service_no": service, "buses": buses}


def _default_loader(code, service):
    return _loaded(code, service, [_bus("NextBus", 9, 92), _bus("NextBus2", 25, 60, monitored=False)])


def _search(arrive_by=None, current_buses=None, loader=_default_loader):
    if current_buses is None:
        current_buses = [_bus("NextBus", 2, 5), _bus("NextBus2", 19, 92), _bus("NextBus3", 30, 60, monitored=False)]
    missed = datetime.fromisoformat(current_buses[0]["arrival_time"]).timestamp()
    dest_lat, dest_lon = _north(3000)
    return plan_options(
        cache=_cache(),
        current=_loaded(HERE, "11", current_buses),
        user_lat=LAT,
        user_lon=LON,
        destination_stop_code=DEST,
        place_lat=dest_lat,
        place_lon=dest_lon,
        arrive_by=arrive_by,
        now=NOW,
        loader=loader,
        missed_eta_epoch=missed,
    )


def _all(result):
    return ([result["recommended"]] if result["recommended"] else []) + result["rows"]


def _tile(row, monitored=True, arrive_by=None):
    cache = _cache()
    dest_lat, dest_lon = _north(3000)
    bus = _bus("NextBus", 0, 90, monitored=monitored)
    bus["arrival_time"] = row["arrival_time"]
    bus["is_primary"] = True
    payload = {"buses": [bus]}
    main._attach_arrival_estimate(
        payload, cache=cache, now=NOW, user_lat=LAT, user_lon=LON, dest_lat=dest_lat, dest_lon=dest_lon,
        destination_stop_code=DEST, boarding_stop_code=row["stop_code"], service_no=row["service_no"],
        arrive_by=arrive_by, route_type=None, leg_index=None, leg1_ride_minutes=None, leg2_ride_minutes=None,
        leg1_direction=None,
    )
    return payload["arrival_estimate"]


def test_screenshot_case_has_no_duplicate_rows_and_never_shows_the_missed_arrival():
    result = _search()
    rows = _all(result)
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert len(rows) == 6  # the current stop's later arrivals and each alternate stop's two
    missed = (NOW + timedelta(minutes=2)).replace(microsecond=0).isoformat()
    assert all(row["arrival_time"] != missed for row in rows)
    assert result["recommended"]["id"] not in [row["id"] for row in result["rows"]]
    keys = [(-r["point"], r["estimated_arrival"], r["service_no"]) for r in result["rows"]]
    assert keys == sorted(keys)


def test_two_arrivals_of_one_service_at_one_stop_get_different_estimates():
    current = [_bus("NextBus", 1, 5), _bus("NextBus2", 6, 80), _bus("NextBus3", 19, 92)]
    rows = [row for row in _all(_search(current_buses=current)) if row["stop_code"] == HERE]
    assert len(rows) == 2
    first, second = sorted(rows, key=lambda r: r["arrival_time"])
    assert first["estimated_arrival"] < second["estimated_arrival"]


def test_schedule_only_arrivals_keep_the_planned_basis():
    current = [_bus("NextBus", 1, 5), _bus("NextBus2", 12, 60, monitored=False), _bus("NextBus3", 25, 60, monitored=False)]
    rows = [row for row in _all(_search(current_buses=current)) if row["stop_code"] == HERE]
    assert len(rows) == 2 and rows[0]["estimated_arrival"] == rows[1]["estimated_arrival"]


def test_the_card_the_tile_and_the_overview_agree_for_one_snapshot():
    for row in _all(_search()):
        if row["monitored"]:
            estimate = _tile(row)
            assert estimate["estimated_arrival"] == row["estimated_arrival"]
            assert estimate["basis"] == "live"
    render = INDEX.split("function renderNewJourney()", 1)[1].split("function leaveNewJourneyScreen", 1)[0]
    assert "row.estimated_arrival" in render  # the overview shows the row's own estimate


def test_without_a_live_arrival_the_tile_keeps_the_planned_estimate():
    dest_lat, dest_lon = _north(3000)
    planned = build_journey(_cache(), dest_lat, dest_lon, LAT, LON, DEST, boarding_stop_code=HERE, service_no="11", now=NOW)
    row = {"arrival_time": (NOW + timedelta(minutes=5)).isoformat(), "stop_code": HERE, "service_no": "11"}
    estimate = _tile(row, monitored=False)
    assert estimate["estimated_arrival"] == planned["arrival_point"] and estimate["basis"] == "planned"


def test_a_bus_that_leaves_before_the_user_can_reach_the_stop_is_not_eligible():
    far = _north(300)
    buses = [{"position": "NextBus", "arrival_time": (NOW + timedelta(seconds=60)).isoformat(), "monitored": True}]
    scored = score_buses(
        buses, user_lat=LAT, user_lon=LON, accuracy_m=10, stop_lat=far[0], stop_lon=far[1], services=[], routes=[],
        service_no="11", stop_code=HERE, now=NOW,
    )
    chance = scored[0]["probability"]
    assert chance["range_high"] < 40
    unreachable = dict(_bus("NextBus2", 5, 5), probability=chance)
    result = _search(loader=lambda code, service: _loaded(code, service, []), current_buses=[_bus("NextBus", 1, 5), unreachable])
    assert result["recommended"] is None and result["mode"] == "none"
    assert result["rows"][0]["unlikely"] is True


def test_a_late_option_stays_and_is_labelled_after_the_target():
    result = _search(arrive_by=NOW + timedelta(minutes=5))
    assert result["recommended"]["reason_code"] == "NONE_BY_TARGET"
    assert all(row["after_target"] for row in _all(result))


def test_the_recommended_row_carries_the_reason_sentence_only():
    row = _search()["recommended"]
    text = row["explanation"]["text"]
    assert text == row["reason_text"] and "It is advisable" not in text
    assert row["explanation"]["action"] == "switch_route"


def test_the_model_sees_the_reason_code_and_the_action_only():
    sheet = explain.build_option_fact_sheet("HIGHEST_CHANCE")
    assert set(sheet) == {"reason_code", "chosen_action"}
    request = explain.option_explanation_request(sheet)
    user = request["messages"][1]["content"]
    assert user == '{"reason_code":"HIGHEST_CHANCE","chosen_action":"switch_route"}'
    assert not any(ch.isdigit() for ch in user)
    assert "probability" not in request["messages"][0]["content"].lower()  # the prompt only states the 15-word limit
    assert explain.parse_option_fact_sheet({"reason_code": "HIGHEST_CHANCE", "chosen_action": "switch_route", "point": 5}) is None
    assert explain.parse_option_fact_sheet({"reason_code": "NOPE", "chosen_action": "switch_route"}) is None


def _raises_timeout(sheet, request):
    raise TimeoutError("slow")


def test_the_fixed_clause_shows_when_there_is_no_model_or_it_is_rejected():
    sheet = explain.build_option_fact_sheet("SHORTER_WALK")
    fixed = explain.deterministic_advice("switch_route")
    assert explain.produce_option_advice(sheet, api_key="")["advice"] == fixed
    for body in ({"advice": "run for this bus"}, {"advice": "leave now"}, {"advice": "switch to bus 5"}, {"nope": 1}):
        got = explain.produce_option_advice(sheet, complete=lambda s, r, b=body: {"status": 200, "body": b})
        assert got == {"advice": fixed, "source": "fallback"}
    good = explain.produce_option_advice(sheet, complete=lambda s, r: {"status": 200, "body": {"advice": "switch to the recommended bus"}})
    assert good["source"] == "model"
    status, payload = explain.handle_option_explain_request({"fact_sheet": sheet, "service_no": "7"}, complete=_raises_timeout)
    assert status == 200 and payload["text"].endswith("It is advisable to switch to another bus.")


def test_page_rows_show_stop_name_distance_and_arrival_minutes_without_next_bus():
    row = INDEX.split("function buildOptionRow(row)", 1)[1].split("function renderOptionRows", 1)[0]
    assert "row.stop_name" in row and "formatDistance(row.distance_m)" in row and "arrivalMinutes(row.arrival_time)" in row
    assert "Next Bus" not in INDEX.split("function optionRows()", 1)[1].split("function renderOptionCards", 1)[0]
    assert 'WALK_TO_TEXT = "Walk to {stop} ({distance})"' in INDEX


def test_the_banner_and_the_card_name_the_arrival_and_the_card_has_no_probability_text_line():
    assert "You're unlikely to catch the Bus {service} arriving in {minutes}" in INDEX
    assert "Bus {service} has left. Here are your other options." in INDEX
    card = INDEX.split("function buildOptionCard(kind, row)", 1)[1].split("function buildOptionRow", 1)[0]
    assert "Catch probability" not in card
    assert 'SWITCH_TO_TEXT = "Switch to Bus {service} in {minutes}"' in INDEX

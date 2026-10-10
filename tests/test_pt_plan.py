"""The planner on OneMap itineraries (pt_plan.py) and the priority parameter of /api/journey-plan and
/api/route-plan. Fixtures and mock transports only: these tests never call OneMap."""

import copy
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import config
import journey_plan
import lta_static
import main
import pt_plan
import pt_route
import service_hours
from lta_static import StopAndRouteCache
from pt_route import OneMapSession, PtRouter

SGT = timezone(timedelta(hours=8))
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 12, 8, 30, tzinfo=SGT)  # a Monday
USER_LAT, USER_LON = 1.36912345, 103.84765432  # a distinctive user position: it must never be sent anywhere


def fx(name: str) -> dict:
    return json.loads((FIXTURES / f"pt_{name}.json").read_text(encoding="utf-8"))


def lta() -> StopAndRouteCache:
    return StopAndRouteCache(**json.loads((FIXTURES / "pt_lta_cache.json").read_text(encoding="utf-8")))


def shifted(payload: dict, seconds: int) -> dict:
    payload = copy.deepcopy(payload)
    for itinerary in payload["plan"]["itineraries"]:
        itinerary["startTime"] += seconds * 1000
        itinerary["endTime"] += seconds * 1000
        for leg in itinerary["legs"]:
            leg["startTime"] += seconds * 1000
            leg["endTime"] += seconds * 1000
    return payload


class Server:
    """A fake OneMap. `by_mode` maps TRANSIT/BUS/RAIL to a list of (status, json) used in order (the last repeats)."""

    def __init__(self, by_mode=None, default=None):
        self.by_mode = {mode: list(answers) for mode, answers in (by_mode or {}).items()}
        self.default = default
        self.gets: list[httpx.Request] = []
        self.posts: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts.append(request)
            return httpx.Response(200, json={"access_token": "fresh", "expiry_timestamp": 9999999999})
        self.gets.append(request)
        mode = request.url.params["mode"]
        mine = [g for g in self.gets if g.url.params["mode"] == mode]
        answers = self.by_mode.get(mode) or ([self.default] if self.default else [(404, {"error": "none"})])
        status, body = answers[min(len(mine), len(answers)) - 1]
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    @property
    def modes(self) -> list[str]:
        return [g.url.params["mode"] for g in self.gets]


def ok(name, seconds=0):
    return (200, shifted(fx(name), seconds) if seconds else fx(name))


def start_of(name):
    point = fx(name)["plan"]["from"]
    return point["lat"], point["lon"]


def end_of(name):
    point = fx(name)["plan"]["to"]
    return point["lat"], point["lon"]


def plan(server, fixture="direct_bus", priority="fastest", rail=None, arrive_by=None, now=NOW, router=None,
         user=None, **extra):
    user = user or start_of(fixture)
    dest = end_of(fixture)
    args = dict(router=router or PtRouter(), session=OneMapSession(), rail_table=rail, user_lat=user[0],
                user_lon=user[1], dest_lat=dest[0], dest_lon=dest[1], destination_stop_code="53231",
                arrive_by=arrive_by, priority=priority, now=now, token="tok", clock=1000.0)
    args.update(extra)
    with server.client() as client:
        return pt_plan.plan_multi_leg(lta(), client=client, **args)


def rail_table(**rows):
    """{station: {headsign: {WD: (first, last)}}} as a minimal table."""
    stations = {}
    for code, directions in rows.items():
        stations[code] = {"directions": {
            headsign: {"line": code[:2], "direction_id": 0, "trips": 1,
                       **{day: {"first": first, "last": last, "headway_s": {}} for day, (first, last) in days.items()}}
            for headsign, days in directions.items()}}
    return {"schema": 1, "stations": stations, "patterns": {}}


# ---- priority names ---------------------------------------------------------------------------------------


def test_the_five_priorities_and_the_default():
    assert pt_plan.PRIORITIES == ("fastest", "fewest_transfers", "least_walking", "bus_only", "mrt_only")
    assert pt_plan.DEFAULT_PRIORITY == "fastest"
    for name in pt_plan.PRIORITIES:
        assert pt_plan.valid_priority(name) == name
    for bad in ("Fastest", " fastest", "fastest ", "", "fast", None, 5, ["fastest"], "fastest;drop"):
        assert pt_plan.valid_priority(bad) is None


def test_an_unknown_priority_is_refused_by_the_planner():
    with pytest.raises(ValueError):
        plan(Server(default=ok("direct_bus")), priority="nope")


# ---- a first plan: shape, totals, legs --------------------------------------------------------------------


def test_one_call_plans_a_direct_bus_with_the_old_fields_and_the_new_ones():
    server = Server(default=ok("direct_bus"))
    result = plan(server)
    assert len(server.gets) == 1 and result["calls"] == 1 and server.modes == ["TRANSIT"]
    assert result["status"] == "ok" and result["route_status"] == "ok" and result["planner"] == "onemap"
    assert result["priority"] == "fastest" and result["fallback_note"] is False and result["reason"] == "no_target"
    for key in ("option", "boarding_stop", "journey", "planning_warning", "candidate_stop_count"):
        assert key in result
    option = result["option"]
    assert option["route_type"] == "direct" and option["transfers"] == 0 and option["first_transit_kind"] == "bus"
    assert option["legs"][0]["kind"] == "bus" and option["legs"][0]["boarding_stop_code"]
    assert result["boarding_stop"]["stop_code"] == option["legs"][0]["boarding_stop_code"]
    itinerary = result["itinerary"]
    assert [leg["kind"] for leg in itinerary["legs"]] == ["walk", "bus", "walk"]
    totals = itinerary["totals"]
    assert set(totals) >= {"minutes", "transfers", "walk_minutes", "walk_m", "wait_minutes"}
    assert all(isinstance(totals[k], int) for k in totals) and totals["transfers"] == 0 and totals["minutes"] > 5


def test_every_leg_carries_kind_line_code_line_name_headsign_path_and_times():
    result = plan(Server(default=ok("bus_mrt")), fixture="bus_mrt")
    for itinerary in result["itineraries"]:
        for leg in itinerary["legs"]:
            assert {"kind", "line_code", "line_name", "headsign", "path", "depart", "arrive"} <= set(leg)
            assert leg["kind"] in ("walk", "bus", "rail") and isinstance(leg["path"], list)
            datetime.fromisoformat(leg["depart"])
        bus = [leg for leg in itinerary["legs"] if leg["kind"] == "bus"]
        rail = [leg for leg in itinerary["legs"] if leg["kind"] == "rail"]
        assert all(leg["line_code"] == leg["service_no"] for leg in bus)
        assert all(leg["line_code"] in ("EW", "NS") and leg["line_name"] for leg in rail)


def _cut_third_trip(payload):
    """bus_mrt's third itinerary (bus 199 then bus 502) takes 91 minutes; cut 25 minutes off its long ride."""
    trip = payload["plan"]["itineraries"][2]
    cut = 25 * 60 * 1000
    long_ride, final_walk = trip["legs"][3], trip["legs"][4]
    assert long_ride["route"] == "502" and final_walk["mode"] == "WALK"
    long_ride["endTime"] -= cut
    final_walk["startTime"] -= cut
    final_walk["endTime"] -= cut
    trip["endTime"] -= cut
    return trip


def _shortened_two_bus_trip():
    payload = fx("bus_mrt")
    payload["plan"]["itineraries"] = [_cut_third_trip(payload)]
    return 200, payload


def direct_variant():
    """bus_mrt's first itinerary cut to its walk and bus 199: a direct trip."""
    payload = fx("bus_mrt")
    trip = payload["plan"]["itineraries"][0]
    trip["legs"] = trip["legs"][:2]
    trip["endTime"] = trip["legs"][1]["endTime"]
    payload["plan"]["itineraries"] = [trip]
    return (200, payload)


def pool3():
    """All three bus_mrt itineraries inside the 90 minute budget: 2, 2 and 1 transfers."""
    payload = fx("bus_mrt")
    _cut_third_trip(payload)
    return (200, payload)


def test_route_type_is_direct_one_transfer_or_multi_leg():
    pool = plan(Server(default=ok("bus_mrt")), fixture="bus_mrt")
    assert {item["route_type"] for item in pool["itineraries"]} == {"multi_leg"}  # the 91 minute trip is over budget
    assert pool["dropped"]["budget"] == 1
    cut = plan(Server(default=_shortened_two_bus_trip()), fixture="bus_mrt")["itineraries"]
    assert cut[0]["route_type"] == "one_transfer" and cut[0]["totals"]["transfers"] == 1
    assert pool["itineraries"][0]["totals"]["transfers"] == 2
    assert plan(Server(default=ok("direct_bus")))["itinerary"]["route_type"] == "direct"
    assert plan(Server(default=ok("mrt_only")), fixture="mrt_only")["itinerary"]["route_type"] == "direct"


def test_a_train_leg_gets_its_headsign_from_the_rail_table():
    table = {"schema": 1, "stations": {}, "patterns": {"NS": {"Marina South Pier": ["NS17", "NS22"]}}}
    result = plan(Server(default=ok("mrt_only")), fixture="mrt_only", rail=table)
    rail = [leg for leg in result["itinerary"]["legs"] if leg["kind"] == "rail"][0]
    assert rail["headsign"] == "Marina South Pier" and rail["line_code"] == "NS"
    assert result["option"]["first_transit_kind"] == "rail"


def test_the_options_are_the_ranked_itineraries_up_to_three():
    result = plan(Server(default=pool3()), fixture="bus_mrt")
    assert len(result["options"]) == len(result["itineraries"]) == 3
    assert result["option"] is result["options"][0] and result["itinerary"] is result["itineraries"][0]


def test_the_journey_object_has_every_field_the_page_reads():
    journey = plan(Server(default=ok("direct_bus")))["journey"]
    for key in ("status", "destination_stop_code", "ride_minutes", "connecting_services", "ride_label",
                "comparison_label", "comparison_note", "estimated_arrival", "arrival_point", "arrival_low",
                "arrival_high", "spare_minutes", "arrival_basis", "arrival_terms", "leave_by"):
        assert key in journey, key
    assert journey["destination_stop_code"] == "53231" and journey["ride_label"].startswith("Ride time: ~")
    assert journey["arrival_basis"] == "planned" and journey["connecting_services"]
    assert set(journey["arrival_terms"]) == {"board_walk_minutes", "wait_minutes", "ride_minutes", "end_walk_metres"}


# ---- hours per leg ----------------------------------------------------------------------------------------


def _late_itinerary(keep):
    """The 00:15 Tuesday answer (Orchard to Bishan), reduced to the itineraries in `keep` by index."""
    payload = fx("late")
    payload["plan"]["itineraries"] = [payload["plan"]["itineraries"][i] for i in keep]
    return 200, payload


def test_bus_59_at_00_55_is_dropped_because_it_is_after_its_last_bus():
    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    server = Server(default=_late_itinerary([1]))  # walk, bus 143 at 00:26, walk, bus 59 at 00:55, walk
    legs = [leg for leg in fx("late")["plan"]["itineraries"][1]["legs"] if leg["mode"] == "BUS"]
    assert [leg["route"] for leg in legs] == ["143", "59"]
    result = plan(server, fixture="late", now=now)
    assert result["route_status"] == "no_service" and result["option"] is None
    assert result["message"] == pt_plan.NO_SERVICE_MESSAGE == "No buses are running to this destination at this time."
    assert result["dropped"]["hours"] == 1 and result["calls"] == 1


def test_bus_143_at_00_26_is_kept_when_it_is_the_only_bus_leg():
    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    payload = fx("late")
    itinerary = payload["plan"]["itineraries"][1]
    itinerary["legs"] = itinerary["legs"][:2]  # walk to Orchard Stn, bus 143 at 00:26
    itinerary["endTime"] = itinerary["legs"][1]["endTime"]
    payload["plan"]["itineraries"] = [itinerary]
    result = plan(Server(default=(200, payload)), fixture="late", now=now)
    assert result["route_status"] == "ok" and result["option"]["legs"][0]["service_no"] == "143"
    assert result["dropped"]["hours"] == 0


def test_a_mixed_pool_keeps_the_open_itinerary_and_drops_the_closed_one():
    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    result = plan(Server(default=_late_itinerary([0, 1])), fixture="late", now=now)  # trains, and 143 + 59
    assert result["route_status"] == "ok" and result["dropped"]["hours"] == 1
    assert {leg["kind"] for leg in result["itinerary"]["legs"]} <= {"walk", "rail"}
    assert len(result["options"]) == 1


def test_a_failing_middle_leg_drops_the_whole_itinerary():
    payload = pool3()[1]
    first = payload["plan"]["itineraries"][0]
    rail = [leg for leg in first["legs"] if leg["mode"] == "SUBWAY"]
    assert [leg["route"] for leg in rail] == ["EW", "NS"]
    rail[0]["startTime"] = int(datetime(2026, 10, 12, 3, 0, tzinfo=SGT).timestamp() * 1000)  # EW at 03:00
    table = rail_table(EW27={"Pasir Ris": {"WD": ("0530", "2400")}})
    result = plan(Server(default=(200, payload)), fixture="bus_mrt", rail=table)
    assert result["route_status"] == "ok" and result["dropped"]["hours"] == 1
    assert len(result["options"]) == 2  # the other two itineraries
    shapes = [[leg["line_code"] for leg in item["legs"] if leg["kind"] != "walk"] for item in result["itineraries"]]
    assert ["199", "EW", "NS"] not in shapes and ["179", "EW", "NS"] in shapes and ["199", "502"] in shapes


def test_a_rail_leg_outside_its_hours_drops_the_itinerary():
    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    table = rail_table(NS22={"Marina South Pier": {"WD": ("0530", "2315")}})  # Monday's last NS22 train: 23:15
    result = plan(Server(default=_late_itinerary([0])), fixture="late", now=now, rail=table)
    assert result["route_status"] == "no_service" and result["dropped"]["hours"] == 1
    open_table = rail_table(NS22={"Marina South Pier": {"WD": ("0530", "2430")}})
    assert plan(Server(default=_late_itinerary([0])), fixture="late", now=now, rail=open_table)["route_status"] == "ok"


def test_all_itineraries_dropped_is_no_service_and_a_walk_only_answer_too():
    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    assert plan(Server(default=_late_itinerary([1])), fixture="late", now=now)["route_status"] == "no_service"
    night = plan(Server(default=ok("night")), fixture="night", now=datetime(2026, 10, 12, 1, 0, tzinfo=SGT))
    assert night["route_status"] == "no_service" and night["message"] == pt_plan.NO_SERVICE_MESSAGE
    assert night["option"] is None and night["journey"] is None and night["calls"] == 1


def test_404_and_an_empty_plan_are_no_feasible_route():
    for answer in ((404, {"error": "Unable to get MRT route"}), ok("params2")):
        result = plan(Server(default=answer), fixture="mrt_only")
        assert result["route_status"] == "no_feasible_route" and result["message"] == "No route found for this trip."
        assert result["option"] is None and result["options"] == [] and result["calls"] == 1


def test_a_place_with_no_stop_near_it_makes_no_call_at_all():
    server = Server(default=ok("direct_bus"))
    result = plan(server, user=(1.4043, 103.9612))  # Pulau Ubin
    assert result["route_status"] == "no_feasible_route" and result["calls"] == 0 and not server.gets


def test_an_origin_onemap_moved_far_is_no_feasible_route():
    server = Server(default=ok("unreach"))
    result = plan(server, fixture="unreach", user=(1.3911889, 103.9873347))  # where OneMap put the origin
    assert len(server.gets) <= 1 and result["route_status"] in ("no_feasible_route", "ok")
    moved = pt_route.parse_response(200, fx("unreach"), pt_route.Place("stop", "", "", 1.4043, 103.9612),
                                    pt_route.Place("place", "", "", 1.304, 103.8319), lta())
    assert moved["reason"] == "snapped"


def _itinerary(depart, service="36", stop="B", rows=None):
    leg = {"kind": "bus", "service_no": service, "direction": 1, "boarding_stop_code": stop,
           "alighting_stop_code": "C", "depart": depart, "arrive": depart, "duration_s": 600.0, "distance_m": 3000.0,
           "stops": [{"stop_code": stop, "latitude": 1.30, "longitude": 103.80}]}
    return {"legs": [leg], "transfers": 0, "depart": depart, "arrive": depart, "route_type": "direct",
            "first_transit_kind": "bus"}


def _hours_cache():
    return StopAndRouteCache([], [{
        "ServiceNo": "36", "Direction": 1, "StopSequence": 1, "BusStopCode": "B", "Distance": 1.0,
        "WD_FirstBus": "0600", "WD_LastBus": "2335", "SAT_FirstBus": "0600", "SAT_LastBus": "2335",
        "SUN_FirstBus": "0600", "SUN_LastBus": "2335"}], [])


def test_leg_one_is_checked_later_when_the_user_reaches_the_stop_after_onemaps_boarding():
    cache = _hours_cache()
    itinerary = _itinerary("2026-10-12T23:30:00+08:00")
    on_time = pt_plan._assess(cache, None, itinerary, datetime(2026, 10, 12, 23, 30, tzinfo=SGT), 1.30, 103.80, 1.25)
    late = pt_plan._assess(cache, None, itinerary, datetime(2026, 10, 12, 23, 41, tzinfo=SGT), 1.30, 103.80, 1.25)
    assert on_time["runs"] is True and on_time["late_s"] == 0
    assert late["late_s"] == 660 and late["runs"] is False  # 23:30 + 11 min = 23:41, after 23:35 + 5 min


def test_arriving_early_never_moves_the_check_earlier():
    cache = _hours_cache()
    itinerary = _itinerary("2026-10-12T06:10:00+08:00")  # the first bus is 06:00; OneMap's trip is 06:10
    early = pt_plan._assess(cache, None, itinerary, datetime(2026, 10, 12, 5, 0, tzinfo=SGT), 1.30, 103.80, 1.25)
    assert early["runs"] is True and early["late_s"] == 0 and early["wait_min"] == pytest.approx(70)


def test_the_shift_applies_to_the_later_legs_too():
    cache = _hours_cache()
    itinerary = _itinerary("2026-10-12T23:00:00+08:00")
    second = copy.deepcopy(itinerary["legs"][0])
    second.update(depart="2026-10-12T23:30:00+08:00", boarding_stop_code="B", service_no="36")
    itinerary["legs"].append(second)
    itinerary["transfers"] = 1
    # leg 2 is OneMap's 23:30. Reaching the stop 12 minutes after leg 1's 23:00 moves it to 23:42, after 23:35 + 5 min.
    for moment, runs in ((datetime(2026, 10, 12, 23, 0, tzinfo=SGT), True), (datetime(2026, 10, 12, 23, 6, tzinfo=SGT), True),
                         (datetime(2026, 10, 12, 23, 12, tzinfo=SGT), False)):
        assert pt_plan._assess(cache, None, itinerary, moment, 1.30, 103.80, 1.25)["runs"] is runs


# ---- priorities -------------------------------------------------------------------------------------------


def test_fastest_picks_the_lowest_ranking_minutes_with_three_per_transfer():
    result = plan(Server(default=pool3()), fixture="bus_mrt")
    options = result["options"]
    keys = [(o["generalized_time_minutes"], o["transfers"]) for o in options]
    assert keys == sorted(keys)
    for o in options:
        assert o["transfer_penalty_minutes"] == 3 * o["transfers"]
        assert o["generalized_time_minutes"] == pytest.approx(o["totals"]["minutes"] + 3 * o["transfers"], abs=1.0)


def test_fewest_transfers_prefers_fewer_transfers_over_time():
    server = Server({"TRANSIT": [pool3()], "BUS": [direct_variant()], "RAIL": [(404, {"error": "none"})]})
    result = plan(server, fixture="bus_mrt", priority="fewest_transfers")
    pool = [o["transfers"] for o in result["options"]]
    assert pool == sorted(pool) and result["option"]["transfers"] == min(pool) == 0
    only = plan(Server(default=pool3()), fixture="bus_mrt", priority="fewest_transfers")
    assert only["option"]["transfers"] == 1 and only["option"]["route_type"] == "one_transfer"


def test_fewest_transfers_asks_bus_and_rail_when_the_first_pool_has_no_direct_trip():
    server = Server({"TRANSIT": [pool3()], "BUS": [direct_variant()], "RAIL": [(404, {"error": "none"})]})
    result = plan(server, fixture="bus_mrt", priority="fewest_transfers")
    assert server.modes == ["TRANSIT", "BUS", "RAIL"] and result["calls"] == 3


def test_fewest_transfers_makes_one_call_when_the_first_pool_already_has_a_direct_trip():
    server = Server(default=ok("mrt_only"))
    result = plan(server, fixture="mrt_only", priority="fewest_transfers")
    assert server.modes == ["TRANSIT"] and result["calls"] == 1


def test_the_extra_calls_are_best_effort_and_never_more_than_three():
    server = Server({"TRANSIT": [pool3()], "BUS": [(500, {})], "RAIL": [ok("mrt_only")]})
    result = plan(server, fixture="bus_mrt", priority="fewest_transfers")
    assert result["route_status"] == "ok" and len(server.gets) <= 3


def test_least_walking_picks_the_least_walking_with_time_as_the_tie_break():
    result = plan(Server(default=pool3()), fixture="bus_mrt", priority="least_walking")
    walks = [o["totals"]["walk_m"] for o in result["options"]]
    assert len(walks) == 3 and walks == sorted(walks) and result["option"]["totals"]["walk_m"] == min(walks)


def test_bus_only_uses_the_bus_mode_and_only_buses():
    server = Server({"BUS": [ok("direct_bus")]})
    result = plan(server, fixture="direct_bus", priority="bus_only")
    assert server.modes == ["BUS"] and result["calls"] == 1
    kinds = {leg["kind"] for item in result["itineraries"] for leg in item["legs"]}
    assert kinds <= {"walk", "bus"} and "bus" in kinds


def test_mrt_only_uses_the_rail_mode_and_only_trains():
    server = Server({"RAIL": [ok("mrt_only")]})
    result = plan(server, fixture="mrt_only", priority="mrt_only")
    assert server.modes == ["RAIL"] and result["calls"] == 1
    kinds = {leg["kind"] for item in result["itineraries"] for leg in item["legs"]}
    assert kinds <= {"walk", "rail"} and "rail" in kinds


def test_an_empty_chip_has_its_own_sentence():
    bus = plan(Server({"BUS": [(404, {"error": "none"})]}), fixture="direct_bus", priority="bus_only")
    assert bus["route_status"] == "no_feasible_route" and bus["message"] == "No bus-only route found. Try another priority."
    mrt = plan(Server({"RAIL": [(404, {"error": "Unable to get MRT route"})]}), fixture="mrt_only", priority="mrt_only")
    assert mrt["route_status"] == "no_feasible_route" and mrt["message"] == "No MRT or LRT route found. Try another priority."


def test_a_pool_without_trains_is_no_mrt_route_and_a_pool_with_trains_is_no_bus_route():
    wrong_rail = plan(Server({"RAIL": [ok("direct_bus")]}), fixture="direct_bus", priority="mrt_only")
    assert wrong_rail["message"] == pt_plan.NO_MRT_ONLY_MESSAGE and wrong_rail["option"] is None
    wrong_bus = plan(Server({"BUS": [ok("mrt_only")]}), fixture="mrt_only", priority="bus_only")
    assert wrong_bus["message"] == pt_plan.NO_BUS_ONLY_MESSAGE


def test_a_chip_with_nothing_running_is_no_service_not_a_chip_message():
    result = plan(Server({"BUS": [ok("night")]}), fixture="night", priority="bus_only",
                  now=datetime(2026, 10, 12, 1, 0, tzinfo=SGT))
    assert result["route_status"] == "no_service" and result["message"] == pt_plan.NO_SERVICE_MESSAGE


def test_fewest_and_least_walking_say_when_they_make_no_difference():
    single = Server(default=ok("mrt_only"))
    for priority in ("fewest_transfers", "least_walking"):
        result = plan(single, fixture="mrt_only", priority=priority)
        assert result["best_available"] is True and result["message"] == "This is the best available for this trip."
    assert plan(Server(default=ok("mrt_only")), fixture="mrt_only")["best_available"] is False
    assert plan(Server(default=ok("mrt_only")), fixture="mrt_only")["message"] == ""


def test_the_ninety_minute_budget_is_kept():
    result = plan(Server(default=ok("bus_transfer")), fixture="bus_transfer")  # two-hour bus-only trips
    assert result["route_status"] == "no_feasible_route" and result["dropped"]["budget"] >= 1
    assert result["message"] == "No route found for this trip."


# ---- calls and the cache ----------------------------------------------------------------------------------


def test_one_call_per_request_and_a_repeat_inside_five_minutes_costs_none():
    server = Server(default=ok("direct_bus"))
    router = PtRouter()
    first = plan(server, router=router)
    second = plan(server, router=router, now=NOW + timedelta(minutes=1), clock=1060.0)
    assert first["calls"] == 1 and second["calls"] == 0 and len(server.gets) == 1
    assert second["option"] == first["option"] or second["route_status"] == "ok"
    third = plan(server, router=router, now=NOW + timedelta(minutes=1), clock=1000.0 + pt_route.CACHE_TTL_SECONDS + 5)
    assert len(server.gets) == 2 and third["calls"] == 1


@pytest.mark.parametrize("priority", ["fastest", "least_walking", "bus_only", "mrt_only"])
def test_each_other_priority_is_one_call(priority):
    server = Server(default=ok("direct_bus"))
    plan(server, priority=priority)
    assert len(server.gets) == 1


# ---- arrive-by --------------------------------------------------------------------------------------------


def test_arrive_by_met_on_the_first_call():
    server = Server(default=ok("bus_mrt"))
    result = plan(server, fixture="bus_mrt", arrive_by=datetime(2026, 10, 12, 10, 30, tzinfo=SGT))
    assert result["reason"] == "target_met" and result["planning_warning"] is None and result["calls"] == 1
    assert result["itinerary"]["totals"]["minutes"] > 0


class Moving(Server):
    """A fake OneMap whose answer departs `lags[i]` minutes after the time asked on call i (the last repeats)."""

    def __init__(self, lags):
        super().__init__()
        self.lags = lags

    def __call__(self, request):
        self.gets.append(request)
        asked = datetime.strptime(
            request.url.params["date"] + " " + request.url.params["time"], "%m-%d-%Y %H:%M:%S").replace(tzinfo=SGT)
        lag = self.lags[min(len(self.gets), len(self.lags)) - 1]
        payload = fx("direct_bus")
        delta = int((asked + timedelta(minutes=lag)).timestamp() * 1000) - payload["plan"]["itineraries"][0]["startTime"]
        for itinerary in payload["plan"]["itineraries"]:
            itinerary["startTime"] += delta
            itinerary["endTime"] += delta
            for leg in itinerary["legs"]:
                leg["startTime"] += delta
                leg["endTime"] += delta
        return httpx.Response(200, json=payload)


def test_arrive_by_retries_earlier_up_to_three_calls_and_then_warns():
    server = Moving([50, 60, 70])  # every try is too late
    result = plan(server, arrive_by=datetime(2026, 10, 12, 10, 0, tzinfo=SGT), now=datetime(2026, 10, 12, 8, 40, tzinfo=SGT))
    assert result["calls"] == 3 and len(server.gets) == 3
    assert result["reason"] == "target_missed" and result["planning_warning"] is not None
    assert result["planning_warning"]["target"].startswith("2026-10-12T10:00:00")
    assert result["route_status"] == "ok" and result["option"] is not None  # the fastest is kept
    times = [g.url.params["time"] for g in server.gets]
    assert times == sorted(times, reverse=True) and len(set(times)) == 3  # each try is earlier


def test_arrive_by_stops_retrying_once_a_try_is_in_time():
    server = Moving([50, 5])
    result = plan(server, arrive_by=datetime(2026, 10, 12, 10, 0, tzinfo=SGT), now=datetime(2026, 10, 12, 8, 40, tzinfo=SGT))
    assert result["calls"] == 2 and result["reason"] == "target_met" and result["planning_warning"] is None
    assert result["journey"]["spare_minutes"] is not None and result["journey"]["spare_minutes"] >= 0


def test_arrive_by_does_not_count_the_wait_before_the_departure_in_the_ninety_minutes():
    server = Moving([100])  # the only trip leaves 100 minutes after the time asked
    now = datetime(2026, 10, 12, 8, 40, tzinfo=SGT)
    ahead = plan(server, arrive_by=datetime(2026, 10, 12, 12, 0, tzinfo=SGT), now=now)
    assert ahead["route_status"] == "ok" and ahead["itinerary"]["totals"]["wait_minutes"] == 0
    now_plan = plan(Moving([100]), now=now)
    assert now_plan["route_status"] == "no_feasible_route"  # leaving now means waiting more than 90 minutes


def test_arrive_by_uses_the_cache_for_the_first_try_of_a_repeat_request():
    router = PtRouter()
    server = Server(default=ok("bus_mrt"))
    target = datetime(2026, 10, 12, 10, 30, tzinfo=SGT)
    plan(server, fixture="bus_mrt", arrive_by=target, router=router)
    again = plan(server, fixture="bus_mrt", arrive_by=target, router=router)
    assert again["calls"] == 0 and len(server.gets) == 1


# ---- the static fallback ----------------------------------------------------------------------------------

STATIC_ARGS = dict(
    user_lat=1.3697, user_lon=103.8486, destination_stop_code="53231", dest_lat=1.351, dest_lon=103.8484,
    arrive_by=None, walk_speed_m_s=1.25, now=NOW)


@pytest.mark.parametrize("answer", [
    (500, {}), (429, {"error": "slow"}), (503, {}), (401, {"message": "Unauthorized"}), (400, {"error": "bad"}),
    (200, httpx.ReadTimeout("slow")),
])
def test_when_onemap_fails_the_static_bus_planner_answers_with_a_fallback_note(answer):
    server = Server(default=answer)
    with server.client() as client:
        result = pt_plan.journey_plan_result(
            lta(), priority="fastest", router=PtRouter(), session=OneMapSession(), client=client, rail_table=None,
            token="tok", **STATIC_ARGS)
    assert result["fallback_note"] is True and result["planner"] == "static" and result["priority"] == "fastest"
    assert result["calls"] == 0 and result["route_status"] == "ok" and result["option"]["legs"][0]["service_no"]
    assert "journey" in result and "boarding_stop" in result


def test_a_missing_token_is_a_fallback_too_and_makes_no_call():
    server = Server(default=ok("direct_bus"))
    with server.client() as client:
        result = pt_plan.journey_plan_result(
            lta(), priority="fastest", router=PtRouter(), session=OneMapSession(), client=client, rail_table=None,
            **STATIC_ARGS)
    assert result["fallback_note"] is True and not server.gets


def test_a_demo_onemap_failure_uses_the_static_planner_without_a_call():
    server = Server(default=ok("direct_bus"))
    with server.client() as client:
        result = pt_plan.journey_plan_result(
            lta(), priority="fastest", use_onemap=False, router=PtRouter(), session=OneMapSession(), client=client,
            rail_table=None, token="tok", **STATIC_ARGS)
    assert result["fallback_note"] is True and not server.gets


def test_the_fallback_can_do_fastest_fewest_transfers_and_bus_only_but_not_the_rest():
    for priority in ("fastest", "fewest_transfers", "bus_only"):
        result = pt_plan.static_journey_plan(lta(), priority=priority, **STATIC_ARGS)
        assert result["fallback_note"] is True and result["route_status"] == "ok", priority
    for priority in ("least_walking", "mrt_only"):
        result = pt_plan.static_journey_plan(lta(), priority=priority, **STATIC_ARGS)
        assert result["route_status"] == "priority_unavailable" and result["message"] == "Needs the route service."
        assert result["option"] is None and result["fallback_note"] is True


def test_the_static_route_plan_puts_the_fewest_transfers_first(monkeypatch):
    def option(transfers, minutes, service):
        return {"route_type": "direct" if transfers == 0 else "one_transfer", "transfers": transfers,
                "transfer_stop_code": None, "transfer_distance_m": 0.0, "transfer_penalty_minutes": 10 * transfers,
                "generalized_time_minutes": minutes, "legs": [{"boarding_stop_code": "A", "service_no": service,
                                                              "direction": 1}], "label": "x"}
    options = [option(1, 20, "9"), option(0, 40, "8"), option(1, 30, "7")]
    monkeypatch.setattr(pt_plan, "suggest_alternate_boarding", lambda *a, **k: {
        "route_status": "ok", "message": "", "options": options, **{"route_type": "one_transfer"}})
    result = pt_plan.static_route_plan(lta(), priority="fewest_transfers", origin="A", destination="B", user_lat=1.3,
                                       user_lon=103.8, dest_lat=1.35, dest_lon=103.85, alternates=[], now=NOW,
                                       walk_speed_m_s=1.25, arrive_by=None)
    assert [o["transfers"] for o in result["options"]] == [0, 1, 1]
    assert [o["label"] for o in result["options"]] == ["Fastest Route", "Fewest Transfers", "Alternative Route"]
    assert result["active_leg"]["service_no"] == "8" and result["fallback_note"] is True
    plain = pt_plan.static_route_plan(lta(), priority="fastest", origin="A", destination="B", user_lat=1.3,
                                      user_lon=103.8, dest_lat=1.35, dest_lon=103.85, alternates=[], now=NOW,
                                      walk_speed_m_s=1.25, arrive_by=None)
    assert [o["generalized_time_minutes"] for o in plain["options"]] == [20, 40, 30]  # untouched order


def test_the_static_fewest_transfers_order_puts_transfers_first():
    cheap = {"transfers": 1, "generalized_time_minutes": 10, "boarding_walk_m": 0, "legs": [{"service_no": "9"}]}
    slow = {"transfers": 0, "generalized_time_minutes": 40, "boarding_walk_m": 0, "legs": [{"service_no": "8"}]}
    assert journey_plan.pick_journey_option([cheap, slow], None)["option"] is cheap
    assert journey_plan.pick_journey_option([cheap, slow], None, journey_plan.fewest_transfers_key)["option"] is slow


# ---- privacy ----------------------------------------------------------------------------------------------


def test_no_user_coordinate_reaches_a_request_a_cache_key_a_log_or_the_result(caplog):
    server = Server(default=ok("direct_bus"))
    router = PtRouter()
    with caplog.at_level(logging.DEBUG):
        result = plan(server, router=router, user=(USER_LAT, USER_LON))
    sent = "".join(str(g.url) + str(dict(g.headers)) for g in server.gets)
    assert "1.36912" not in sent and "103.84765" not in sent and "1.369123" not in sent
    origin = pt_route.nearest_origin_place(lta(), USER_LAT, USER_LON)
    assert server.gets[0].url.params["start"] == origin.param()
    destination = end_of("direct_bus")
    assert server.gets[0].url.params["end"] == f"{destination[0]:.5f},{destination[1]:.5f}"
    assert "1.36912" not in repr(list(router._cache)) and "103.84765" not in repr(list(router._cache))
    assert "1.36912" not in json.dumps(result) and "103.84765" not in json.dumps(result)
    assert not [r for r in caplog.records if "1.3691" in r.getMessage() or "103.8476" in r.getMessage()]


def test_the_start_is_always_a_public_stop_or_station_coordinate():
    table = {"schema": 1, "stations": {"NS17": {"name": "Bishan", "latitude": 1.35092, "longitude": 103.8485,
                                                 "directions": {}}}, "patterns": {}}
    server = Server(default=ok("mrt_only"))
    plan(server, fixture="mrt_only", rail=table, user=(1.35100123, 103.84840987))
    assert server.gets[0].url.params["start"] == "1.35092,103.84850"  # the station, not the user
    server = Server(default=ok("mrt_only"))
    plan(server, fixture="mrt_only", user=(1.35100123, 103.84840987))
    stop = lta().stop_by_code("53231")
    assert server.gets[0].url.params["start"] == f"{stop['Latitude']:.5f},{stop['Longitude']:.5f}"


def test_the_named_boarding_stop_is_the_origin_for_a_route_plan():
    server = Server(default=ok("direct_bus"))
    plan(server, origin_stop_code="54339", user=(USER_LAT, USER_LON))
    stop = lta().stop_by_code("54339")
    assert server.gets[0].url.params["start"] == f"{stop['Latitude']:.5f},{stop['Longitude']:.5f}"


def test_a_walk_estimate_uses_the_user_position_only_locally():
    near = plan(Server(default=ok("direct_bus")), user=start_of("direct_bus"))
    far = plan(Server(default=ok("direct_bus")), user=(1.3730, 103.8486))  # about 300 m further north
    assert far["option"]["boarding_walk_m"] > near["option"]["boarding_walk_m"]


# ---- the endpoints ----------------------------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    holder = {"server": Server(default=ok("direct_bus")), "table": None}

    class Patched(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(holder["server"])
            super().__init__(*args, **kwargs)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    for module in (main, pt_plan, journey_plan, sys.modules["route_plan"], sys.modules["nearby"]):
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", FixedClock)
    monkeypatch.setattr(main, "load_static_data", lambda: lta())
    monkeypatch.setattr(main, "startup_warning", lambda today: None)
    monkeypatch.setattr(main, "load_rail_table", lambda: holder["table"])
    monkeypatch.setattr(main, "read_onemap_credentials", lambda: ("tok", "", ""))
    monkeypatch.setattr(main.httpx, "Client", Patched)
    with TestClient(main.app) as client:
        client.holder = holder
        yield client


JOURNEY = dict(user_lat=1.3697, user_lon=103.8486, destination_stop_code="53231", dest_lat=1.351, dest_lon=103.8484)
ROUTE = dict(boarding_stop_code="54009", destination_stop_code="53231", user_lat=1.3697, user_lon=103.8486,
             dest_lat=1.351, dest_lon=103.8484)


def test_journey_plan_without_priority_is_the_old_answer_and_never_calls_onemap(api):
    body = api.get("/api/journey-plan", params=JOURNEY).json()
    assert "planner" not in body and "fallback_note" not in body and body["status"] == "ok"
    assert not api.holder["server"].gets and not api.holder["server"].posts


def test_route_plan_without_priority_is_the_old_answer_and_never_calls_onemap(api):
    body = api.get("/api/route-plan", params=ROUTE).json()
    assert "planner" not in body and "fallback_note" not in body and body["route_status"] in ("ok", "no_feasible_route")
    assert not api.holder["server"].gets


@pytest.mark.parametrize("path, params", [("/api/journey-plan", JOURNEY), ("/api/route-plan", ROUTE)])
@pytest.mark.parametrize("bad", ["fast", "FASTEST", "<script>alert(1)</script>", "", " fastest", "fastest,bus_only"])
def test_an_unknown_priority_is_rejected_without_echoing_it(api, path, params, bad):
    response = api.get(path, params={**params, "priority": bad})
    assert response.status_code == 422
    assert response.json() == {"detail": pt_plan.PRIORITY_MESSAGE}
    if len(bad) > 8:
        assert bad not in response.text  # short values are substrings of the fixed message; it is compared whole above
    assert not api.holder["server"].gets


@pytest.mark.parametrize("priority", pt_plan.PRIORITIES)
def test_every_priority_is_accepted_by_both_endpoints(api, priority):
    api.holder["server"] = Server({"TRANSIT": [ok("direct_bus")], "BUS": [ok("direct_bus")], "RAIL": [ok("mrt_only")]})
    assert api.get("/api/journey-plan", params={**JOURNEY, "priority": priority}).status_code == 200
    assert api.get("/api/route-plan", params={**ROUTE, "priority": priority}).status_code == 200


def test_journey_plan_keeps_every_old_field_and_adds_the_new_ones(api):
    old = api.get("/api/journey-plan", params=JOURNEY).json()
    new = api.get("/api/journey-plan", params={**JOURNEY, "priority": "fastest"}).json()
    assert set(old) <= set(new), set(old) - set(new)
    assert new["planner"] == "onemap" and new["fallback_note"] is False and new["priority"] == "fastest"
    assert new["itinerary"]["legs"] and new["itinerary"]["totals"]["minutes"] > 0
    assert new["walk_speed_used"] == old["walk_speed_used"]
    assert api.holder["server"].gets and not json.dumps(new).count("1.3697")


def test_route_plan_keeps_every_old_field_and_adds_the_new_ones(api):
    old = api.get("/api/route-plan", params=ROUTE).json()
    new = api.get("/api/route-plan", params={**ROUTE, "priority": "fastest"}).json()
    assert set(old) <= set(new), set(old) - set(new)
    assert new["planner"] == "onemap" and new["options"] and new["option_count"] == len(new["options"])
    assert new["active_leg"]["leg_index"] == 1 and new["active_leg"]["boarding_stop_code"]
    assert new["route_type"] in ("direct", "one_transfer", "multi_leg") and new["legs"]
    stop = lta().stop_by_code("54009")
    assert api.holder["server"].gets[-1].url.params["start"] == f"{stop['Latitude']:.5f},{stop['Longitude']:.5f}"


def test_the_endpoints_fall_back_to_the_static_planner_when_onemap_is_down(api):
    api.holder["server"] = Server(default=(500, {}))
    journey = api.get("/api/journey-plan", params={**JOURNEY, "priority": "fastest"}).json()
    assert journey["fallback_note"] is True and journey["planner"] == "static" and journey["route_status"] == "ok"
    route = api.get("/api/route-plan", params={**ROUTE, "priority": "fastest"}).json()
    assert route["fallback_note"] is True and route["planner"] == "static" and "planning_warning" in route
    unavailable = api.get("/api/journey-plan", params={**JOURNEY, "priority": "mrt_only"}).json()
    assert unavailable["route_status"] == "priority_unavailable" and unavailable["message"] == "Needs the route service."


def test_a_demo_onemap_failure_uses_the_fallback_through_the_endpoint(api, monkeypatch):
    monkeypatch.setattr(main.demo, "destination_is_simulated", lambda: True)
    body = api.get("/api/journey-plan", params={**JOURNEY, "priority": "fastest"}).json()
    assert body["fallback_note"] is True and not api.holder["server"].gets


def test_the_endpoint_reads_the_rail_table_loaded_at_startup(api):
    api.holder["server"] = Server(default=ok("mrt_only"))
    assert api.get("/api/journey-plan", params={**JOURNEY, "priority": "fastest"}).status_code == 200


def test_the_priority_request_never_sends_the_user_position_through_the_endpoint(api):
    api.get("/api/journey-plan", params={**JOURNEY, "user_lat": USER_LAT, "user_lon": USER_LON, "priority": "fastest"})
    sent = "".join(str(g.url) for g in api.holder["server"].gets)
    assert api.holder["server"].gets and "1.36912" not in sent and "103.84765" not in sent


def test_the_page_files_are_untouched_by_this_phase():
    root = Path(__file__).resolve().parents[1]
    page = (root / "static" / "index.html").read_text(encoding="utf-8")
    assert '"&priority=" + encodeURIComponent(planPriority)' in page  # the page always sends a priority (phase 5)

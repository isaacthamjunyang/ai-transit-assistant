"""The bus traffic factor (a documented assumption): one shared function, chosen by the bus leg's start time, bus ride
minutes only. Every time here is pinned: a weekday is Wednesday 7 October 2026, the clock is passed in, and nothing
reads the machine time. The browser checks only whether the muted line shows, which does not depend on the clock.
No live API is called."""

import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

import bus_traffic
import config
import destination_stops as ds
import onemap_stub as stub
import pt_plan
import pt_route as pr
from catch_heuristic import score_buses
from page_runner import north, require_edge, run_scenario, running_app
from route_plan import plan_route
from test_pt_plan import Server, fx, lta, plan, shifted
from test_service_hours import PLACE, SAT, SUN, USER, WED, at, two_stop_cache, week
from test_train_pages import _table

USES_BUS_TRAFFIC = True  # tests/conftest.py otherwise runs every test with the factor at 1.0

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
NOTE = "Bus times can vary with traffic."
SGT = timezone(timedelta(hours=8))
HOLIDAY = date(2026, 12, 25)  # Christmas Day, a Friday
ORDINARY_FRIDAY = date(2026, 12, 18)


def _sgt(day: date, hhmm: str, seconds: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[2:]), seconds, tzinfo=SGT)


# ---- the factor: windows, days ---------------------------------------------------------------------------------


def test_the_constants_are_the_documented_assumptions():
    assert config.BUS_PEAK_FACTOR == 1.25
    assert config.BUS_PEAK_WINDOWS == ((time(7, 0), time(9, 0)), (time(17, 0), time(20, 0)))
    source = (ROOT / "config.py").read_text(encoding="utf-8")
    assert "documented assumptions, not measured traffic data" in source


@pytest.mark.parametrize("hhmm,expected", [
    ("0659", 1.0), ("0700", 1.25), ("0859", 1.25), ("0900", 1.0),
    ("1659", 1.0), ("1700", 1.25), ("1959", 1.25), ("2000", 1.0),
    ("0000", 1.0), ("1200", 1.0), ("2359", 1.0),
])
def test_the_factor_inside_and_outside_each_weekday_window(hhmm, expected):
    assert bus_traffic.bus_factor(_sgt(WED, hhmm)) == expected


@pytest.mark.parametrize("day", [SAT, SUN])
def test_a_weekend_is_never_in_a_window(day):
    assert bus_traffic.bus_factor(_sgt(day, "0800")) == 1.0 and bus_traffic.bus_factor(_sgt(day, "1800")) == 1.0


def test_a_public_holiday_is_never_in_a_window_but_the_same_weekday_is():
    assert HOLIDAY in config.PUBLIC_HOLIDAYS and ORDINARY_FRIDAY not in config.PUBLIC_HOLIDAYS
    assert bus_traffic.bus_factor(_sgt(HOLIDAY, "0800")) == 1.0
    assert bus_traffic.bus_factor(_sgt(ORDINARY_FRIDAY, "0800")) == 1.25


def test_the_time_is_read_in_singapore_whatever_zone_it_arrives_in():
    utc = timezone.utc
    assert bus_traffic.bus_factor(datetime(2026, 10, 6, 23, 30, tzinfo=utc)) == 1.25  # 07:30 on Wednesday in SGT
    assert bus_traffic.bus_factor(datetime(2026, 10, 7, 1, 0, tzinfo=utc)) == 1.0     # 09:00 SGT
    assert bus_traffic.bus_factor(datetime(2026, 10, 7, 8, 0)) == 1.25                 # a naive time is read as SGT


def test_the_minutes_are_scaled_and_none_stays_none():
    assert bus_traffic.bus_ride_minutes(20.0, _sgt(WED, "0800")) == pytest.approx(25.0)
    assert bus_traffic.bus_ride_minutes(20.0, _sgt(WED, "1000")) == 20.0
    assert bus_traffic.bus_ride_minutes(None, _sgt(WED, "0800")) is None


# ---- OneMap legs: chosen by the leg's own start; rail and walk unchanged -----------------------------------------


def _first_bus(payload: dict) -> dict:
    return next(leg for leg in payload["plan"]["itineraries"][0]["legs"] if leg["mode"] == "BUS")


def _at(name: str, when: datetime) -> dict:
    """The recorded answer moved in time so that its first bus leg starts at `when`."""
    payload = fx(name)
    return shifted(payload, int(when.timestamp()) - _first_bus(payload)["startTime"] // 1000)


def _parse(payload: dict) -> dict:
    start, end = payload["plan"]["from"], payload["plan"]["to"]
    origin = pr.Place("stop", "", "", start["lat"], start["lon"])
    target = pr.Place("place", "", "", end["lat"], end["lon"])
    return pr.parse_response(200, payload, origin, target, lta())


def _legs(result: dict, kind: str) -> list[dict]:
    return [leg for it in result["itineraries"] for leg in it["legs"] if leg["kind"] == kind]


@pytest.mark.parametrize("start,factor", [
    (_sgt(WED, "0859", 30), 1.25),  # starts inside the window and rides on past 09:00: the start decides
    (_sgt(WED, "0659", 0), 1.0),    # starts before the window and rides into it: the start decides
    (_sgt(WED, "1710", 0), 1.25),
    (_sgt(WED, "1000", 0), 1.0),
])
def test_a_bus_leg_takes_the_factor_of_the_time_it_starts(start, factor):
    bus = _legs(_parse(_at("direct_bus", start)), "bus")[0]
    assert bus["ride_minutes"] == pytest.approx(round(bus["duration_s"] / 60 * factor, 2), abs=0.011)
    assert bus["duration_s"] / 60 > 3  # long enough to cross a window edge in the two boundary cases


def test_rail_and_walking_are_unchanged_in_the_peak():
    result = _parse(_at("bus_mrt", _sgt(WED, "0800")))
    rail, walk, bus = _legs(result, "rail"), _legs(result, "walk"), _legs(result, "bus")
    assert rail and walk and bus
    for leg in rail:
        assert leg["ride_minutes"] == pytest.approx(round(leg["duration_s"] / 60, 2), abs=0.011)
    for leg in walk:
        assert "ride_minutes" not in leg
    for leg in bus:
        assert leg["ride_minutes"] == pytest.approx(round(leg["duration_s"] / 60 * 1.25, 2), abs=0.011)
    off = _parse(_at("bus_mrt", _sgt(WED, "1000")))
    assert [leg["duration_s"] for leg in _legs(off, "walk")] == [leg["duration_s"] for leg in walk]  # not scaled


def test_a_trip_that_starts_at_1650_gets_the_factor_of_the_leg_that_starts_at_1710():
    server = Server(default=(200, _at("direct_bus", _sgt(WED, "1710"))))
    result = plan(server, now=_sgt(WED, "1650"))
    bus = [leg for leg in result["itinerary"]["legs"] if leg["kind"] == "bus"][0]
    assert bus["ride_minutes"] == pytest.approx(round(bus["duration_s"] / 60 * 1.25, 2), abs=0.011)


# ---- the planner: totals, estimate, arrive-by -----------------------------------------------------------------


def _planned(start: datetime, lead_minutes: int = 20, **extra):
    server = Server(default=(200, _at("direct_bus", start)))
    return plan(server, now=start - timedelta(minutes=lead_minutes), **extra)


def test_the_totals_and_the_destination_estimate_carry_the_adjusted_minutes():
    peak, off = _planned(_sgt(WED, "0810")), _planned(_sgt(WED, "1010"))
    bus_peak = [leg for leg in peak["itinerary"]["legs"] if leg["kind"] == "bus"][0]
    extra = bus_peak["duration_s"] / 60 * 0.25
    gain = peak["itinerary"]["totals"]["minutes"] - off["itinerary"]["totals"]["minutes"]
    assert gain == pytest.approx(extra, abs=1.01)  # whole minutes: the totals are rounded up
    assert peak["journey"]["ride_minutes"] - off["journey"]["ride_minutes"] == pytest.approx(extra, abs=1.01)
    assert peak["option"]["generalized_time_minutes"] - off["option"]["generalized_time_minutes"] == pytest.approx(
        extra, abs=0.05)


def _user(itinerary: dict):
    stop = itinerary["legs"][1]["stops"][0]
    return stop["latitude"], stop["longitude"]


def test_the_arrive_by_check_uses_the_adjusted_ride():
    peak_it = _parse(_at("direct_bus", _sgt(WED, "0810")))["itineraries"][0]
    off_it = _parse(_at("direct_bus", _sgt(WED, "1010")))["itineraries"][0]
    cache = lta()
    peak = pt_plan._assess(cache, None, peak_it, _sgt(WED, "0750"), *_user(peak_it), 1.25, True)
    off = pt_plan._assess(cache, None, off_it, _sgt(WED, "0950"), *_user(off_it), 1.25, True)
    bus = [leg for leg in peak_it["legs"] if leg["kind"] == "bus"][0]
    late_peak = (peak["arrival"] - _sgt(WED, "0810")).total_seconds()
    late_off = (off["arrival"] - _sgt(WED, "1010")).total_seconds()
    assert late_peak - late_off == pytest.approx(bus["duration_s"] * 0.25, abs=1.0)
    assert peak["ride_min"] > off["ride_min"]


# ---- the static planner and the destination estimate -------------------------------------------------------------


def _static_ride(now: datetime) -> float:
    planned = plan_route(two_stop_cache(**week()), "B", "D", *USER, *PLACE, now=now)
    assert planned["route_status"] == "ok"
    return planned["options"][0]["legs"][0]["ride_minutes"]


def test_the_static_fallback_scales_route_km_over_18_kmh():
    peak, off = _static_ride(at(WED, "0800")), _static_ride(at(WED, "1000"))
    assert off == pytest.approx((3.5 - 1.0) / 18 * 60)
    assert peak == pytest.approx(off * 1.25)


def test_a_static_leg_that_starts_on_a_weekend_is_not_scaled():
    assert _static_ride(at(SAT, "0800")) == pytest.approx(_static_ride(at(WED, "1000")))


def test_the_destination_arrival_estimate_carries_the_factor_too():
    def card(now):
        body = ds.list_destination_stops(two_stop_cache(**week()), PLACE[0], PLACE[1], USER[0], USER[1],
                                         boarding_stop_code="B", service_no="36", now=now)
        return body["reachable_stops"][0]

    peak, off = card(at(WED, "0800")), card(at(WED, "1000"))
    assert peak["arrival_terms"]["ride_minutes"] == pytest.approx(off["arrival_terms"]["ride_minutes"] * 1.25)
    assert peak["arrival_terms"]["wait_minutes"] == off["arrival_terms"]["wait_minutes"]  # waiting is not scaled
    assert peak["arrival_terms"]["board_walk_minutes"] == off["arrival_terms"]["board_walk_minutes"]
    assert peak["rough_journey_minutes"] >= off["rough_journey_minutes"]


# ---- what the factor must not touch --------------------------------------------------------------------------------


def test_the_catch_probability_the_ring_and_the_at_stop_rule_do_not_use_the_factor(monkeypatch):
    now = at(WED, "0800")
    bus = {"position": "NextBus", "arrival_time": (now + timedelta(minutes=6)).isoformat(), "monitored": True,
           "latitude": None, "longitude": None, "origin_code": None, "destination_code": None}

    def score():
        return score_buses([dict(bus)], user_lat=1.3, user_lon=103.8, accuracy_m=10, stop_lat=1.3003, stop_lon=103.8,
                           services=[], routes=[], service_no="36", stop_code="08057", now=now,
                           location_timestamp=None)

    with_factor = score()
    monkeypatch.setattr(config, "BUS_PEAK_FACTOR", 1.0)
    assert score() == with_factor
    for name in ("catch_heuristic.py", "pace.py", "rail_arrivals.py", "walk_speed.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "bus_traffic" not in text and "BUS_PEAK" not in text, name


def test_every_caller_goes_through_the_one_function_and_nothing_else_does_the_math():
    code = sorted(ROOT.glob("*.py"))
    users = {p.name for p in code if "bus_ride_minutes(" in p.read_text(encoding="utf-8")}
    assert users == {"bus_traffic.py", "pt_route.py", "pt_plan.py", "route_plan.py", "destination_stops.py"}
    # every place a bus minute is made from the speed is routed (route_plan's _leg holds the scheduled minutes that
    # _attach_duration then passes through the function)
    for path in code:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "BUS_SPEED_KM_H" in line and not re.match(r"\s*(from |import |BUS_SPEED_KM_H =|BUS_SPEED_KM_H,$)", line):
                assert "bus_ride_minutes(" in line or (path.name == "route_plan.py" and '"ride_minutes"' in line), \
                    (path.name, number, line)
    text = (ROOT / "route_plan.py").read_text(encoding="utf-8")
    assert text.count("bus_ride_minutes(leg[\"ride_minutes\"], start)") == 1


# ---- words and the page --------------------------------------------------------------------------------------------


def test_the_note_is_in_copy_js_the_page_the_guide_and_the_plan_and_no_other_traffic_words():
    block = COPY.split("journeyOverview: {", 1)[1].split("\n  },", 1)[0]
    assert f'trafficNote: "{NOTE}"' in block
    assert f'<p id="overview-traffic-note" class="overview-note" hidden>{NOTE}</p>' in INDEX
    assert "jo.trafficNote" in GUIDE and "BUS_PEAK_FACTOR" in PLAN and NOTE in PLAN
    for name, text in (("copy.js", COPY), ("page", INDEX), ("guide", GUIDE)):
        strings = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
        words = [s for s in strings if re.search(r"\btraffic\b|\bcongestion\b|\brush hour\b", s, re.I)
                 and s != "overview-traffic-note"]  # the element id is not wording
        assert all(s == NOTE for s in words), (name, words)


def test_the_page_shows_the_note_only_for_a_route_with_a_bus_leg():
    body = INDEX.split("function renderOverviewSummary(data, hasBus) {", 1)[1].split("\n    }\n", 1)[0]
    assert "note.hidden = !hasBus;" in body and "fetch(" not in body
    assert "transit.some(function (leg) { return !legIsRail(leg); })" in INDEX


def _rail_only():
    station = stub.stop("BISHAN MRT STATION", "NS17", north(80))
    far = stub.stop("ORCHARD MRT STATION", "NS22", north(1900))
    return stub.answer(stub.itinerary(
        stub.walk(0, 3, 200, target=station),
        stub.ride("SUBWAY", "NS", "NORTH SOUTH LINE", 8, 22, station, far, between=4),
        stub.walk(22, 24, 90, origin=far)))


def _page(tmp_path_factory, name, builder):
    require_edge()
    builders = {"TRANSIT": builder, "BUS": builder, "RAIL": builder}
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode(builders), rail_table=_table()) as base:
        return run_scenario("trafficnote", base, {"name": name, "width": 390, "height": 844, "dark": False},
                            timeout=300)["result"]


def test_the_note_shows_under_the_summary_with_a_bus_leg_and_is_hidden_before_there_is_one(tmp_path_factory):
    report = _page(tmp_path_factory, "trafficbus", stub.bus_only)
    assert report["before"]["hidden"] is True
    ready = report["ready"]
    assert ready["summaryShown"] is True and ready["note"] == NOTE and ready["noteIsAfterSummary"] is True
    assert "bus" in ready["legKinds"] and ready["scrollWidth"] <= ready["innerWidth"]
    assert ready["inlineStyles"] is False


def test_the_note_is_hidden_on_a_rail_only_route(tmp_path_factory):
    report = _page(tmp_path_factory, "trafficrail", _rail_only)
    ready = report["ready"]
    assert ready["summaryShown"] is True and "bus" not in ready["legKinds"] and "rail" in ready["legKinds"]
    assert ready["note"] is None and ready["noteHidden"] is True

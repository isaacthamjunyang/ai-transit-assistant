"""Buses that are not in service at the travel time are not recommended: first and last bus windows by day type."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import service_hours
from destination_stops import list_destination_stops
from journey_plan import plan_journey
from lta_static import StopAndRouteCache
from nearby import nearby_boarding_stops
from reroute import _candidate_from_bus
from route_plan import plan_route
from service_hours import (
    LAST_BUS_GRACE_MINUTES,
    legs_run_at,
    missing_hours_count,
    reset_missing_hours_count,
    service_runs_at,
)
from test_journey import PLACE, USER, _service, _stop

ROOT = Path(__file__).resolve().parents[1]
SGT = timezone(timedelta(hours=8))
MESSAGE = "No service to this destination right now."
# 2026-10-07 is a Wednesday, 10-10 a Saturday, 10-11 a Sunday.
WED, THU, SAT, SUN = date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 10), date(2026, 10, 11)


def at(day: date, hhmm: str) -> datetime:
    return datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[2:]), tzinfo=SGT)


def row(service="36", code="B", seq=1, km=1.0, direction=1, **hours):
    base = {"ServiceNo": service, "Direction": direction, "StopSequence": seq, "BusStopCode": code, "Distance": km}
    base.update(hours)
    return base


def week(wd=("0500", "2300"), sat=("0600", "2330"), sun=("0700", "2200")):
    return {
        "WD_FirstBus": wd[0], "WD_LastBus": wd[1],
        "SAT_FirstBus": sat[0], "SAT_LastBus": sat[1],
        "SUN_FirstBus": sun[0], "SUN_LastBus": sun[1],
    }


def cache_of(routes, services=None, stops=None):
    stops = stops if stops is not None else [_stop("B", *USER, "Boarding"), _stop("D", *PLACE, "Dest")]
    return StopAndRouteCache(stops, routes, services if services is not None else [_service("36", "10-10")])


def two_stop_cache(**hours):
    return cache_of([row("36", "B", 1, 1.0, **hours), row("36", "D", 4, 3.5, **hours)])


@pytest.fixture(autouse=True)
def _count_from_zero():
    reset_missing_hours_count()


# ---- the day types

def test_weekday_window_first_and_last_bus_and_the_grace():
    cache = cache_of([row(**week())])
    assert not service_runs_at(cache, "36", "B", at(WED, "0459"))
    assert service_runs_at(cache, "36", "B", at(WED, "0500"))
    assert service_runs_at(cache, "36", "B", at(WED, "2259"))
    assert service_runs_at(cache, "36", "B", at(WED, "2300"))  # at the last bus
    assert service_runs_at(cache, "36", "B", at(WED, "2300") + timedelta(minutes=LAST_BUS_GRACE_MINUTES))  # the margin
    assert not service_runs_at(cache, "36", "B", at(WED, "2300") + timedelta(minutes=LAST_BUS_GRACE_MINUTES + 1))


def test_the_grace_is_a_small_named_constant():
    assert LAST_BUS_GRACE_MINUTES == 5


def test_saturday_window():
    cache = cache_of([row(**week())])
    assert not service_runs_at(cache, "36", "B", at(SAT, "0530"))  # a weekday would already run
    assert service_runs_at(cache, "36", "B", at(SAT, "0600"))
    assert service_runs_at(cache, "36", "B", at(SAT, "2330"))
    assert not service_runs_at(cache, "36", "B", at(SAT, "2336"))


def test_sunday_window():
    cache = cache_of([row(**week())])
    assert not service_runs_at(cache, "36", "B", at(SUN, "0659"))
    assert service_runs_at(cache, "36", "B", at(SUN, "0700"))
    assert service_runs_at(cache, "36", "B", at(SUN, "2205"))
    assert not service_runs_at(cache, "36", "B", at(SUN, "2206"))


def test_a_public_holiday_uses_the_sunday_window(monkeypatch):
    cache = cache_of([row(**week())])
    assert service_runs_at(cache, "36", "B", at(WED, "0600"))
    monkeypatch.setattr(service_hours, "PUBLIC_HOLIDAYS", frozenset({WED}))
    assert not service_runs_at(cache, "36", "B", at(WED, "0600"))  # the Sunday first bus is 0700
    assert service_runs_at(cache, "36", "B", at(WED, "0700"))


def test_a_dash_means_the_service_does_not_run_that_day_type():
    only_weekday = week()
    only_weekday.update({"SAT_FirstBus": "-", "SAT_LastBus": "-", "SUN_FirstBus": "-", "SUN_LastBus": "-"})
    cache = cache_of([row(**only_weekday)])
    assert service_runs_at(cache, "36", "B", at(WED, "1200"))
    assert not service_runs_at(cache, "36", "B", at(SAT, "1200"))
    assert not service_runs_at(cache, "36", "B", at(SUN, "1200"))


def test_the_singapore_time_is_used_whatever_zone_the_datetime_carries():
    cache = cache_of([row(**week())])
    la = timezone(timedelta(hours=-7))
    assert service_runs_at(cache, "36", "B", datetime(2026, 10, 7, 8, 0, tzinfo=la))  # 11:00 PM Wednesday in Singapore
    assert not service_runs_at(cache, "36", "B", datetime(2026, 10, 7, 8, 10, tzinfo=la))  # 11:10 PM in Singapore


# ---- windows across midnight

def test_a_window_that_crosses_midnight():
    cache = cache_of([row(**week(wd=("0500", "0030"), sat=("0600", "0100"), sun=("0700", "0015")))])
    assert service_runs_at(cache, "36", "B", at(WED, "2350"))
    assert service_runs_at(cache, "36", "B", at(THU, "0020"))  # still Wednesday's window
    assert service_runs_at(cache, "36", "B", at(THU, "0035"))  # the grace
    assert not service_runs_at(cache, "36", "B", at(THU, "0036"))
    assert not service_runs_at(cache, "36", "B", at(THU, "0200"))  # between the last and the first bus
    # Friday night runs into Saturday under Friday's (weekday) last bus; Saturday night into Sunday under Saturday's
    assert service_runs_at(cache, "36", "B", at(date(2026, 10, 10), "0020"))
    assert service_runs_at(cache, "36", "B", at(SUN, "0050"))
    assert not service_runs_at(cache, "36", "B", at(SUN, "0106"))


# ---- the 158A case: listed only in certain hours

def test_a_morning_only_service_is_dropped_at_11_40_pm():
    only_morning = week(wd=("0634", "0828"))
    only_morning.update({"SAT_FirstBus": "-", "SAT_LastBus": "-", "SUN_FirstBus": "-", "SUN_LastBus": "-"})
    cache = cache_of([row("158A", "B", 1, 1.0, **only_morning)])
    assert service_runs_at(cache, "158A", "B", at(WED, "0700"))
    assert not service_runs_at(cache, "158A", "B", at(WED, "2340"))
    assert not service_runs_at(cache, "158A", "B", at(SAT, "0700"))


def test_the_real_cached_158a_hours_drop_it_at_11_40_pm_on_a_weekday():
    path = ROOT / "cache" / "bus_routes.json"
    if not path.exists():
        pytest.skip("no cached BusRoutes on this machine")
    routes = [r for r in json.loads(path.read_text(encoding="utf-8")) if r["ServiceNo"] == "158A"]
    assert routes, "158A is in the cached routes"
    cache = StopAndRouteCache([], routes, [])
    stop = routes[0]["BusStopCode"]
    assert not service_runs_at(cache, "158A", stop, at(WED, "2340"))
    assert missing_hours_count() == 0  # real data has hours, so nothing was guessed


# ---- live data wins

def test_live_data_overrides_a_closed_schedule():
    cache = cache_of([row(**week())])
    assert not service_runs_at(cache, "36", "B", at(WED, "2340"))
    assert service_runs_at(cache, "36", "B", at(WED, "2340"), live=True)


def _bus(eta, monitored):
    return {
        "arrival_time": eta.isoformat(),
        "monitored": monitored,
        "probability": {"point": 80, "range_low": 70, "range_high": 90, "slack_seconds": 60, "data_quality": "live"},
    }


def _candidate(cache, bus, now, fetched_at="recent"):
    return _candidate_from_bus(
        cache, bus, stop_code="B", service_no="36", user_lat=USER[0], user_lon=USER[1],
        destination_stop_code="D", place_lat=PLACE[0], place_lon=PLACE[1], arrive_by=None, now=now,
        fetched_at=now.isoformat() if fetched_at == "recent" else fetched_at,
    )


def test_reroute_keeps_a_live_bus_outside_its_hours_and_drops_a_schedule_only_one():
    cache = two_stop_cache(**week(wd=("0600", "2300")))
    now = at(WED, "2330")
    eta = at(WED, "2345")
    assert _candidate(cache, _bus(eta, True), now) is not None  # live: in service
    assert _candidate(cache, _bus(eta, False), now) is None  # schedule only and the schedule says closed


def test_a_live_entry_overrides_the_schedule_only_when_the_lookup_is_recent():
    cache = two_stop_cache(**week(wd=("0600", "2300")))
    now = at(WED, "2330")
    bus = _bus(at(WED, "2345"), True)
    assert _candidate(cache, bus, now, fetched_at=(now - timedelta(seconds=60)).isoformat()) is not None
    assert _candidate(cache, bus, now, fetched_at=(now - timedelta(minutes=10)).isoformat()) is None  # old lookup
    assert _candidate(cache, bus, now, fetched_at=None) is None  # undated lookup is not proof
    assert service_hours.live_is_recent(now.isoformat(), now) and not service_hours.live_is_recent("junk", now)


def test_reroute_keeps_a_schedule_only_bus_inside_its_hours():
    cache = two_stop_cache(**week(wd=("0600", "2300")))
    found = _candidate(cache, _bus(at(WED, "1015"), False), at(WED, "1000"))
    assert found is not None and found["monitored"] is False


# ---- 11 and 158A at Tanjong Rhu Stn Exit 2 (90041), Friday 01:08 SGT, arrive-by 02:12 SGT

FRIDAY_0108 = datetime(2026, 10, 9, 1, 8, tzinfo=SGT)
FRIDAY_0212 = datetime(2026, 10, 9, 2, 12, tzinfo=SGT)


@pytest.fixture(scope="module")
def real_cache():
    path = ROOT / "cache" / "bus_routes.json"
    if not path.exists():
        pytest.skip("no cached LTA data on this machine")
    from lta_static import load_cache

    return load_cache()


@pytest.mark.parametrize("arrive_by", [None, FRIDAY_0212])
def test_bus_11_and_158a_at_90041_are_not_chosen_at_1_08_am_when_the_data_says_closed(real_cache, arrive_by):
    stop = real_cache.stop_by_code("90041")
    dest = real_cache.stop_by_code("80049")  # Aft Sims Way
    planned = plan_journey(
        real_cache, user_lat=stop["Latitude"], user_lon=stop["Longitude"], destination_stop_code="80049",
        dest_lat=dest["Latitude"], dest_lon=dest["Longitude"], arrive_by=arrive_by, now=FRIDAY_0108,
    )
    assert planned["route_status"] == "no_service" and planned["option"] is None and planned["journey"] is None
    chosen = planned.get("option") or {}
    assert not [leg for leg in chosen.get("legs", []) if leg["service_no"] in ("11", "158A")]
    for service in ("11", "158A"):
        assert not service_runs_at(real_cache, service, "90041", FRIDAY_0108)


def test_the_stop_lists_and_pinned_choices_at_90041_also_leave_11_and_158a_out(real_cache):
    stop = real_cache.stop_by_code("90041")
    dest = real_cache.stop_by_code("80049")
    nearby = nearby_boarding_stops(real_cache, stop["Latitude"], stop["Longitude"], now=FRIDAY_0108)
    assert not {"11", "158A"} & set(next(s for s in nearby if s["stop_code"] == "90041")["services"])
    for service in ("11", "158A"):
        listed = list_destination_stops(
            real_cache, dest["Latitude"], dest["Longitude"], stop["Latitude"], stop["Longitude"],
            boarding_stop_code="90041", service_no=service, now=FRIDAY_0108, arrive_by=FRIDAY_0212,
        )
        assert "80049" not in [card["stop_code"] for card in listed["reachable_stops"]], service


def test_the_shown_boarding_time_is_checked_too_when_the_arrive_by_is_soon():
    cache = two_stop_cache(**week(wd=("0600", "2300")))
    now = at(WED, "0550")
    # boarding would be about 05:55 (closed until 06:00) even though working back from 06:40 gives about 06:26
    soon = plan_route(cache, "B", "D", *USER, *PLACE, now=now, arrive_by=at(WED, "0640"))
    assert soon["route_status"] == service_hours.NO_SERVICE
    # planning ahead (the working-back time is more than an hour after the shown one): only that time counts
    ahead = plan_route(cache, "B", "D", *USER, *PLACE, now=now, arrive_by=at(WED, "0830"))
    assert ahead["route_status"] == "ok"


def test_a_pinned_service_that_is_closed_is_not_offered_either():
    cache = two_stop_cache(**week(wd=("0600", "0900")))
    listed = list_destination_stops(
        cache, PLACE[0], PLACE[1], USER[0], USER[1], boarding_stop_code="B", service_no="36", now=at(WED, "2340")
    )
    assert listed["reachable_stops"] == [] and listed["no_service"] is True


@pytest.mark.skip(reason="PENDING APPROVAL: proposed rule, not implemented. See PROJECT_PLAN.md Service hours.")
def test_pending_a_service_missing_from_a_successful_live_feed_is_dropped_even_if_the_schedule_runs():
    """Proposed: the live lookup for the stop loaded OK and lists other services but not this one -> drop it.
    Schedule only stays when the feed failed or returned nothing at all."""
    raise AssertionError("not implemented: waiting for approval")


# ---- the boarding time, not the request time

def test_the_route_is_checked_at_now_plus_the_walk_without_an_arrive_by():
    cache = two_stop_cache(**week(wd=("0600", "0900")))
    now = at(WED, "2330")
    closed = plan_route(cache, "B", "D", *USER, *PLACE, now=now)
    assert closed["route_status"] == service_hours.NO_SERVICE and closed["options"] == []
    morning = plan_route(cache, "B", "D", *USER, *PLACE, now=at(WED, "0700"))
    assert morning["route_status"] == "ok"


def test_with_an_arrive_by_the_boarding_time_works_back_from_it():
    cache = two_stop_cache(**week(wd=("0600", "0900")))
    now = at(WED, "2330")  # the request is at night, when the bus is closed
    early = plan_route(cache, "B", "D", *USER, *PLACE, now=now, arrive_by=at(THU, "0800"))
    assert early["route_status"] == "ok" and early["options"]  # boarding is about 07:45
    midday = plan_route(cache, "B", "D", *USER, *PLACE, now=now, arrive_by=at(THU, "1200"))
    assert midday["route_status"] == service_hours.NO_SERVICE  # boarding is about 11:45: closed


def test_a_transfer_leg_is_checked_at_its_own_later_boarding_time():
    cache = cache_of([row("A", "B", 1, 1.0, **week()), row("C", "D", 4, 3.5, **week(wd=("0600", "0900")))])
    legs = [
        {"service_no": "A", "boarding_stop_code": "B", "direction": 1, "ride_minutes": 30.0},
        {"service_no": "C", "boarding_stop_code": "D", "direction": 1, "ride_minutes": 5.0},
    ]
    assert legs_run_at(cache, legs, at(WED, "0820"), transfer_wait_minutes=5)  # leg 2 boards at 08:55
    assert not legs_run_at(cache, legs, at(WED, "0831"), transfer_wait_minutes=5)  # leg 2 boards at 09:06, past 09:00 + 5


# ---- no eligible bus

def test_auto_plan_says_no_service_when_every_route_is_closed():
    cache = two_stop_cache(**week(wd=("0600", "0900")))
    planned = plan_journey(
        cache, user_lat=USER[0], user_lon=USER[1], destination_stop_code="D",
        dest_lat=PLACE[0], dest_lon=PLACE[1], now=at(WED, "2340"),
    )
    assert planned["route_status"] == "no_service" and planned["option"] is None and planned["journey"] is None
    open_ = plan_journey(
        cache, user_lat=USER[0], user_lon=USER[1], destination_stop_code="D",
        dest_lat=PLACE[0], dest_lon=PLACE[1], now=at(WED, "0700"),
    )
    assert open_["route_status"] == "ok" and open_["option"] is not None


def test_a_destination_with_no_route_at_all_is_still_no_feasible_route():
    cache = cache_of([row("36", "B", 1, 1.0, **week())])
    planned = plan_journey(
        cache, user_lat=USER[0], user_lon=USER[1], destination_stop_code="D",
        dest_lat=PLACE[0], dest_lon=PLACE[1], now=at(WED, "1000"),
    )
    assert planned["route_status"] == "no_feasible_route"


def test_a_worse_route_is_not_shown_in_place_of_a_closed_one():
    fast_closed = [
        row("10", "B", 1, 1.0, **week(wd=("0600", "0900"))), row("10", "D", 3, 2.0, **week(wd=("0600", "0900"))),
        row("20", "B", 1, 1.0, **week()), row("20", "D", 9, 9.0, **week()),
    ]
    cache = cache_of(fast_closed, [_service("10", "10-10"), _service("20", "10-10")])
    night = plan_route(cache, "B", "D", *USER, *PLACE, now=at(WED, "2000"))
    assert [leg["service_no"] for leg in night["legs"]] == ["20"]  # the open one, labelled as it really is
    assert all(option["legs"][0]["service_no"] != "10" for option in night["options"])
    day = plan_route(cache, "B", "D", *USER, *PLACE, now=at(WED, "0700"))
    assert day["legs"][0]["service_no"] == "10"


def test_destination_options_drop_a_closed_service_and_flag_when_nothing_is_left():
    cache = two_stop_cache(**week(wd=("0600", "0900")))
    args = (cache, PLACE[0], PLACE[1], USER[0], USER[1])
    night = list_destination_stops(*args, now=at(WED, "2340"))
    assert night["no_service"] is True and night["reachable_stops"] == []
    assert any(card.get("no_service") for card in night["unreachable_stops"])
    day = list_destination_stops(*args, now=at(WED, "0700"))
    assert day["no_service"] is False and [card["stop_code"] for card in day["reachable_stops"]] == ["D"]
    pinned = list_destination_stops(*args, boarding_stop_code="B", service_no="36", now=at(WED, "2340"))
    assert pinned["reachable_stops"] == []  # a chosen but closed service is not offered either
    open_pinned = list_destination_stops(*args, boarding_stop_code="B", service_no="36", now=at(WED, "0700"))
    assert [card["stop_code"] for card in open_pinned["reachable_stops"]] == ["D"]


def test_the_destination_options_use_the_arrive_by_boarding_time():
    cache = two_stop_cache(**week(wd=("0600", "0900")))
    args = (cache, PLACE[0], PLACE[1], USER[0], USER[1])
    morning = list_destination_stops(*args, now=at(WED, "2340"), arrive_by=at(THU, "0800"))
    assert [card["stop_code"] for card in morning["reachable_stops"]] == ["D"]


def test_the_nearby_service_list_drops_a_service_that_is_closed_when_the_user_arrives():
    cache = cache_of([row("36", "B", 1, 1.0, **week(wd=("0600", "0900"))), row("77", "B", 1, 1.0, **week(wd=("0500", "0100")))])
    night = nearby_boarding_stops(cache, USER[0], USER[1], now=at(WED, "2340"))
    assert [stop["services"] for stop in night if stop["stop_code"] == "B"] == [["77"]]
    morning = nearby_boarding_stops(cache, USER[0], USER[1], now=at(WED, "0700"))
    assert [stop["services"] for stop in morning if stop["stop_code"] == "B"] == [["36", "77"]]


# ---- missing hours

def test_missing_hours_keep_the_service_and_are_counted():
    cache = cache_of([row("36", "B", 1, 1.0), row("77", "B", 1, 1.0, **week())])
    assert missing_hours_count() == 0
    assert service_runs_at(cache, "36", "B", at(WED, "0300"))  # no hours fields: eligible
    assert missing_hours_count() == 1
    assert not service_runs_at(cache, "77", "B", at(WED, "0300"))  # hours known and closed: not counted
    assert missing_hours_count() == 1
    assert service_runs_at(cache, "99", "B", at(WED, "0300"))  # a service with no row at all
    assert missing_hours_count() == 2


def test_unreadable_or_all_dash_hours_count_as_missing():
    junk = {"WD_FirstBus": "soon", "WD_LastBus": "late", "SAT_FirstBus": "-", "SAT_LastBus": "-", "SUN_FirstBus": "-", "SUN_LastBus": "-"}
    dashes = {key: "-" for key in week()}
    cache = cache_of([row("36", "B", 1, 1.0, **junk), row("77", "B", 1, 1.0, **dashes)])
    assert service_runs_at(cache, "36", "B", at(WED, "1200")) and service_runs_at(cache, "77", "B", at(WED, "1200"))
    assert missing_hours_count() == 2


def test_missing_hours_do_not_hide_a_route():
    cache = two_stop_cache()  # no hours anywhere
    planned = plan_route(cache, "B", "D", *USER, *PLACE, now=at(WED, "0300"))
    assert planned["route_status"] == "ok" and missing_hours_count() >= 1


# ---- one function everywhere, and the message

def test_every_place_that_picks_or_lists_buses_uses_the_one_function():
    for name in ("route_plan", "destination_stops", "nearby", "reroute"):
        source = (ROOT / f"{name}.py").read_text(encoding="utf-8")
        assert "from service_hours import" in source, name
    assert "legs_run_at(" in (ROOT / "route_plan.py").read_text(encoding="utf-8")
    assert "service_runs_at(" in (ROOT / "reroute.py").read_text(encoding="utf-8")
    assert "service_runs_at(" in (ROOT / "destination_stops.py").read_text(encoding="utf-8")
    assert "service_runs_at(" in (ROOT / "nearby.py").read_text(encoding="utf-8")


def test_no_other_module_reads_the_first_and_last_bus_fields():
    for path in ROOT.glob("*.py"):
        if path.name in ("service_hours.py", "lta_static.py"):
            continue
        text = path.read_text(encoding="utf-8")
        assert "FirstBus" not in text and "LastBus" not in text, path.name


def test_the_module_logs_and_stores_nothing():
    source = (ROOT / "service_hours.py").read_text(encoding="utf-8")
    for word in ("logging", "logger", "open(", "latitude", "lat,", "lon,"):
        assert word not in source, word


def test_the_message_is_in_copy_js_the_page_and_the_style_guide():
    copy = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    guide = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
    assert f'noService: "{MESSAGE}"' in copy
    assert MESSAGE in page and 'id="overview-no-service"' in page
    assert 'route_status === "no_service"' in page and 'setOverviewState("no-service")' in page
    assert "jo.noService" in guide and "sgOverviewState(\"no-service\")" in guide
    assert "arrive_by=" in page.split("function loadDestinationStops()", 1)[1].split("fetch(url)", 1)[0]


def test_the_plan_describes_the_service_hours_rule():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    assert "Service hours" in plan and MESSAGE in plan and "service_runs_at" in plan

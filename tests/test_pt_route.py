"""OneMap public transport routing client and parser. Fixtures only: these tests never call OneMap.

The fixtures in tests/fixtures/pt_*.json are trimmed copies of real answers for landmark trips
(no user coordinate was ever used). pt_lta_cache.json is the LTA stop/route data those trips touch."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

import lta_static
import onemap
import pt_route as pr
from nearby import haversine_m
from onemap import OneMapSession

FIXTURES = Path(__file__).parent / "fixtures"
SGT = pr.SGT
# The files of the original 11-answer measurement: 339 stop objects on 25 bus legs.
MEASURED = ["direct_bus", "bus_transfer", "mrt_only", "bus_mrt", "multi", "night", "arriveby", "late",
            "noroute", "early"]


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"pt_{name}.json").read_text(encoding="utf-8"))


def _lta() -> lta_static.StopAndRouteCache:
    return lta_static.StopAndRouteCache(**json.loads((FIXTURES / "pt_lta_cache.json").read_text(encoding="utf-8")))


def _places(payload: dict) -> tuple[pr.Place, pr.Place]:
    start, end = payload["plan"]["from"], payload["plan"]["to"]
    return (pr.Place("stop", "", "", start["lat"], start["lon"]),
            pr.Place("place", "", "", end["lat"], end["lon"]))


def _parse(name: str, status: int = 200) -> dict:
    payload = _fixture(name)
    origin, destination = _places(payload)
    return pr.parse_response(status, payload, origin, destination, _lta())


def _bus_legs(result: dict) -> list[dict]:
    return [leg for it in result["itineraries"] for leg in it["legs"] if leg["kind"] == pr.KIND_BUS]


# ---- polyline ----------------------------------------------------------------------------------------------


def test_polyline_decodes_the_reference_example():
    assert pr.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]


def test_polyline_of_a_real_bus_leg_starts_at_its_boarding_stop():
    raw = _fixture("direct_bus")["plan"]["itineraries"][0]["legs"][1]
    path = pr.decode_polyline(raw["legGeometry"]["points"])
    assert len(path) == raw["legGeometry"]["length"] == 46
    assert haversine_m(path[0][0], path[0][1], raw["from"]["lat"], raw["from"]["lon"]) < 20
    assert haversine_m(path[-1][0], path[-1][1], raw["to"]["lat"], raw["to"]["lon"]) < 30


@pytest.mark.parametrize("bad", ["", None, 5, "\x00"])
def test_polyline_bad_input_is_empty(bad):
    assert pr.decode_polyline(bad) == []


# ---- leg kinds ---------------------------------------------------------------------------------------------


def test_direct_bus_is_walk_bus_walk():
    result = _parse("direct_bus")
    assert result["status"] == pr.STATUS_OK
    first = result["itineraries"][0]
    assert [leg["kind"] for leg in first["legs"]] == ["walk", "bus", "walk"]
    bus = first["legs"][1]
    assert (bus["service_no"], bus["boarding_stop_code"], bus["alighting_stop_code"]) == ("50", "54339", "53231")
    assert bus["direction"] == 2 and bus["direction_matched"] and bus["stop_codes_known"]
    assert bus["stop_count"] == 5 and bus["ride_minutes"] == pytest.approx(6.8, abs=0.01)
    assert first["route_type"] == "direct" and first["transfers"] == 0
    assert first["first_transit_kind"] == pr.KIND_BUS
    assert bus["path"] and first["legs"][0]["path"]
    assert all({"stop_code", "description", "latitude", "longitude"} <= set(s) for s in bus["stops"])


def test_mrt_only_has_a_rail_leg_with_line_and_station_codes():
    first = _parse("mrt_only")["itineraries"][0]
    assert [leg["kind"] for leg in first["legs"]] == ["walk", "rail", "walk"]
    rail = first["legs"][1]
    assert (rail["line_code"], rail["mode"]) == ("NS", "SUBWAY")
    assert rail["line_name"] == "North South Line"
    assert (rail["boarding_stop_code"], rail["alighting_stop_code"]) == ("NS17", "NS22")
    assert rail["stop_count"] == 5 and [s["stop_code"] for s in rail["stops"]][0] == "NS17"
    assert rail["headsign"] is None and rail["direction"] is None  # the rail table does not exist yet
    assert first["first_transit_kind"] == pr.KIND_RAIL and first["route_type"] == "direct"


def test_lrt_is_a_tram_leg_with_a_bp_code_and_dt_is_a_subway_leg():
    first = _parse("lrt_dt")["itineraries"][0]
    rails = [leg for leg in first["legs"] if leg["kind"] == pr.KIND_RAIL]
    assert [(leg["mode"], leg["line_code"]) for leg in rails] == [("TRAM", "BP"), ("SUBWAY", "DT")]
    assert rails[0]["line_name"] == "Bukit Panjang LRT System"
    assert (rails[0]["boarding_stop_code"], rails[0]["alighting_stop_code"]) == ("BP11", "BP6")
    assert (rails[1]["boarding_stop_code"], rails[1]["alighting_stop_code"]) == ("DT1", "DT19")
    assert first["route_type"] == "multi_leg" and first["transfers"] == 1


def test_bus_then_mrt_and_a_line_change_with_a_walk_between():
    result = _parse("bus_mrt")
    kinds = [[leg["kind"] for leg in it["legs"]] for it in result["itineraries"]]
    assert kinds[0] == ["walk", "bus", "walk", "rail", "rail", "walk"]
    assert result["itineraries"][0]["first_transit_kind"] == pr.KIND_BUS
    assert result["itineraries"][0]["route_type"] == "multi_leg" and result["itineraries"][0]["transfers"] == 2
    assert result["itineraries"][2]["route_type"] == "one_transfer"  # 199 then 502
    multi = _parse("multi")["itineraries"][0]
    codes = [(leg["line_code"], leg["boarding_stop_code"]) for leg in multi["legs"] if leg["kind"] == "rail"]
    assert codes == [("NE", "NE17"), ("CC", "CC29"), ("EW", "EW21")]
    change = multi["legs"][3]  # CC22 to EW21 inside Buona Vista
    assert change["kind"] == "walk" and change["distance_m"] == pytest.approx(132, abs=1)


def test_waiting_is_the_gap_between_legs_and_times_are_singapore_time():
    first = _parse("bus_mrt")["itineraries"][0]
    legs = first["legs"]
    gap = datetime.fromisoformat(legs[3]["depart"]) - datetime.fromisoformat(legs[2]["arrive"])
    assert gap == timedelta(seconds=179)
    assert first["depart"].endswith("+08:00") and first["arrive"].endswith("+08:00")
    assert first["wait_s"] == 411


# ---- dropped and empty answers -----------------------------------------------------------------------------


def test_itineraries_with_a_bus_leg_under_60_seconds_are_dropped():
    result = _parse("bus_transfer")
    assert result["dropped"]["short_bus"] == 2
    assert result["status"] == pr.STATUS_OK and len(result["itineraries"]) == 1
    assert all(leg["duration_s"] >= pr.MIN_BUS_RIDE_SECONDS for leg in _bus_legs(result))
    raw = _fixture("bus_transfer")["plan"]["itineraries"]
    assert any(leg["mode"] == "BUS" and leg["duration"] < 60 for it in raw for leg in it["legs"])


@pytest.mark.parametrize("name", ["night", "early"])
def test_a_walk_only_answer_is_no_transit(name):
    result = _parse(name)
    assert result["status"] == pr.STATUS_NO_TRANSIT and result["reason"] == "walk_only"
    assert result["itineraries"] == [] and result["dropped"]["walk_only"] == 1
    assert _fixture(name)["plan"]["itineraries"][0]["transitTime"] == 0


def test_404_is_no_route():
    result = pr.parse_response(404, _fixture("noroute2"), *_places(_fixture("mrt_only")), None)
    assert result["status"] == pr.STATUS_NO_ROUTE and result["itineraries"] == []


def test_an_empty_plan_is_no_route():
    payload = _fixture("params2")
    assert payload["plan"]["itineraries"] == []
    result = pr.parse_response(200, payload, *_places(payload), None)
    assert result["status"] == pr.STATUS_NO_ROUTE and result["reason"] == "empty"
    assert pr.parse_response(200, {}, *_places(payload), None)["status"] == pr.STATUS_NO_ROUTE


def test_an_origin_that_onemap_moved_is_no_route():
    payload = _fixture("unreach")
    ubin = pr.Place("stop", "", "", 1.4043, 103.9612)  # Pulau Ubin, which OneMap moved to the mainland
    orchard = pr.Place("place", "", "", 1.304, 103.8319)
    moved = pr.parse_response(200, payload, ubin, orchard, _lta())
    assert moved["status"] == pr.STATUS_NO_ROUTE and moved["reason"] == "snapped"
    assert moved["snapped_m"] > 3000 and moved["itineraries"] == []
    start = payload["plan"]["from"]
    same = pr.parse_response(200, payload, pr.Place("stop", "", "", start["lat"], start["lon"]), orchard, _lta())
    assert same["status"] == pr.STATUS_OK


def test_a_destination_that_onemap_moved_is_no_route():
    payload = _fixture("mrt_only")
    origin, destination = _places(payload)
    far = pr.Place("place", "", "", destination.latitude + 0.01, destination.longitude)
    assert pr.parse_response(200, payload, origin, far, None)["reason"] == "snapped"


def test_a_200_with_an_error_text_is_unavailable():
    with pytest.raises(pr.RouteUnavailable):
        pr.parse_response(200, {"error": "something broke"}, *_places(_fixture("mrt_only")), None)


# ---- bus stop code and direction against the LTA cache ---------------------------------------------------


def test_every_bus_leg_matches_the_lta_cache_in_one_direction():
    """The 25 legs of the original measurement, from the subset of LTA routes in the fixtures."""
    cache = _lta()
    index = pr._bus_index(cache)
    legs = 0
    for name in MEASURED:
        for itinerary in _fixture(name).get("plan", {}).get("itineraries", []):
            for leg in itinerary["legs"]:
                if leg["mode"] != "BUS":
                    continue
                legs += 1
                direction, matched = pr._match_direction(
                    index, leg["route"], leg["from"]["stopCode"], leg["to"]["stopCode"])
                assert matched and direction in (1, 2), (name, leg["route"])
    assert legs == 25


def test_a_wrong_order_or_unknown_service_does_not_match():
    index = pr._bus_index(_lta())
    assert pr._match_direction(index, "50", "53231", "54339") == (None, False)  # against the direction
    assert pr._match_direction(index, "9999", "54339", "53231") == (None, False)


def test_a_loop_that_fits_both_directions_gives_no_direction():
    index = {"L": {1: {"A": [1, 5], "B": [3]}, 2: {"A": [2], "B": [4]}}}
    assert pr._match_direction(index, "L", "A", "B") == (None, True)


def test_parsed_legs_carry_the_match_flags():
    result = _parse("bus_mrt")
    legs = _bus_legs(result)
    assert legs and all(leg["direction_matched"] and leg["stop_codes_known"] for leg in legs)
    assert {leg["service_no"] for leg in legs} == {"199", "179", "502"}


LTA_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


@pytest.mark.skipif(not (LTA_CACHE_DIR / "bus_stops.json").is_file(), reason="needs the local LTA cache")
def test_all_339_stop_codes_and_25_legs_exist_in_the_real_lta_cache():
    """The measurement of 2026-10-09: 339 of 339 stop objects on 25 bus legs are LTA stop codes, and every
    leg's service passes both stops in one direction. Run against the real cache, not the fixture subset."""
    cache = lta_static.load_cache(LTA_CACHE_DIR)
    assert cache is not None
    index = pr._bus_index(cache)
    stops = legs = 0
    for name in MEASURED:
        for itinerary in _fixture(name).get("plan", {}).get("itineraries", []):
            for leg in itinerary["legs"]:
                if leg["mode"] != "BUS":
                    continue
                legs += 1
                for stop in [leg["from"], leg["to"], *(leg.get("intermediateStops") or [])]:
                    stops += 1
                    assert cache.stop_by_code(stop["stopCode"]) is not None, stop["stopCode"]
                assert pr._match_direction(index, leg["route"], leg["from"]["stopCode"], leg["to"]["stopCode"])[1]
    assert (stops, legs) == (339, 25)


# ---- the client --------------------------------------------------------------------------------------------

DEPART = datetime(2026, 10, 12, 8, 30, tzinfo=SGT)
ORIGIN = pr.Place("stop", "54009", "Ang Mo Kio Int", 1.37, 103.8486)
DESTINATION = pr.Place("place", "", "Bishan", 1.351, 103.8484)


class Server:
    """A fake OneMap. `answers` is a list of (status, json) used in order (the last one repeats)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.gets: list[httpx.Request] = []
        self.posts: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts.append(request)
            return httpx.Response(200, json={"access_token": "fresh-token", "expiry_timestamp": 9999999999})
        self.gets.append(request)
        status, body = self.answers[min(len(self.gets), len(self.answers)) - 1]
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _route(server, *, mode=pr.MODE_TRANSIT, router=None, budget=None, depart=DEPART, now=1000.0,
           token="manual-token", email="", password="", session=None, origin=ORIGIN, destination=DESTINATION):
    router = router or pr.PtRouter()
    with server.client() as client:
        return router.route(origin, destination, depart, mode, session=session or OneMapSession(),
                            client=client, budget=budget or pr.CallBudget.single(), lta_cache=_lta(),
                            token=token, email=email, password=password, now=now)


def _ok_answer(name="direct_bus"):
    return 200, _fixture(name)


def test_the_request_carries_only_the_two_public_points_and_the_search_fields():
    server = Server(_ok_answer())
    result = _route(server)
    assert result["status"] == pr.STATUS_OK and result["from_cache"] is False
    request = server.gets[0]
    assert str(request.url).startswith(pr.ROUTE_URL + "?")
    assert dict(request.url.params) == {
        "start": "1.37000,103.84860", "end": "1.35100,103.84840", "routeType": "pt", "date": "10-12-2026",
        "time": "08:30:00", "mode": "TRANSIT", "numItineraries": "3"}
    assert request.headers["Authorization"] == "manual-token"  # the token itself, no Bearer prefix


def test_the_user_position_is_used_to_pick_the_stop_and_is_never_sent():
    user_lat, user_lon = 1.36912345, 103.84765432
    origin = pr.nearest_origin_place(_lta(), user_lat, user_lon)
    assert origin is not None and origin.kind == "stop"
    stop = _lta().stop_by_code(origin.code)
    assert (origin.latitude, origin.longitude) == (stop["Latitude"], stop["Longitude"])
    server = Server(_ok_answer())
    _route(server, origin=origin)
    sent = str(server.gets[0].url) + str(server.gets[0].headers)
    assert "1.36912" not in sent and "103.84765" not in sent
    assert origin.param() in sent.replace("%2C", ",")
    assert not server.posts


def test_nearest_origin_considers_stations_and_a_distance_limit():
    station = {"code": "NS17", "name": "Bishan", "latitude": 1.35092, "longitude": 103.8485}
    pick = pr.nearest_origin_place(_lta(), 1.3509, 103.8484, stations=[station])
    assert (pick.kind, pick.code) == ("station", "NS17")
    assert pr.nearest_origin_place(_lta(), 1.2, 103.5) is None  # nothing within 1 km


@pytest.mark.parametrize("mode", ["TRANSIT", "BUS", "RAIL"])
def test_each_mode_is_sent_as_given(mode):
    server = Server(_ok_answer())
    result = _route(server, mode=mode)
    assert server.gets[0].url.params["mode"] == mode and result["mode"] == mode


def test_an_unknown_mode_is_refused_before_any_call():
    server = Server(_ok_answer())
    with pytest.raises(ValueError):
        _route(server, mode="WALK")
    assert not server.gets


def test_date_and_time_use_the_onemap_formats_in_singapore_time():
    server = Server(_ok_answer())
    utc = datetime(2026, 10, 12, 17, 5, 9, tzinfo=pr.timezone.utc)  # 01:05:09 on the 13th in Singapore
    _route(server, depart=utc)
    assert dict(server.gets[0].url.params)["date"] == "10-13-2026"
    assert dict(server.gets[0].url.params)["time"] == "01:05:09"


def test_a_401_refreshes_the_token_once_and_retries_without_using_budget():
    ok = _ok_answer()
    server = Server((401, {"message": "Unauthorized"}), ok)
    budget = pr.CallBudget.single()
    result = _route(server, budget=budget, token="stale", email="me@example.com", password="pw")
    assert result["status"] == pr.STATUS_OK
    assert len(server.posts) == 1 and len(server.gets) == 2 and budget.used == 1
    assert server.gets[1].headers["Authorization"] == "fresh-token"


def test_a_manual_token_that_is_rejected_is_replaced_from_the_account():
    server = Server((401, {"message": "Unauthorized"}), _ok_answer())
    result = _route(server, token="stale", email="me@example.com", password="pw")
    assert result["status"] == pr.STATUS_OK
    assert [g.headers["Authorization"] for g in server.gets] == ["stale", "fresh-token"]


def test_a_second_401_is_unavailable_and_the_token_is_not_in_the_error():
    server = Server((401, {"message": "Unauthorized"}))
    with pytest.raises(pr.RouteUnavailable) as caught:
        _route(server, token="", email="me@example.com", password="pw")
    assert len(server.posts) == 1  # one refresh, never a loop
    assert "fresh-token" not in str(caught.value) and "fresh-token" not in repr(caught.value)


def test_a_401_with_no_account_is_unavailable_without_a_refresh():
    server = Server((401, {"message": "Unauthorized"}))
    with pytest.raises(pr.RouteUnavailable) as caught:
        _route(server, token="manual-token")
    assert caught.value.status == "unavailable" and not server.posts and "manual-token" not in str(caught.value)


def test_no_token_and_no_account_is_unavailable_with_no_call():
    server = Server(_ok_answer())
    with pytest.raises(pr.RouteUnavailable):
        _route(server, token="")
    assert not server.gets


def test_the_session_keeps_a_refreshed_token_in_memory_only():
    session = OneMapSession()
    server = Server((401, {"message": "Unauthorized"}), _ok_answer())
    _route(server, token="stale", email="me@example.com", password="pw", session=session)
    assert session.token == "fresh-token"


def test_400_is_rejected_with_the_message():
    server = Server((400, {"error": "Date must be a valid calendar date in the format MM-DD-YYYY."}))
    with pytest.raises(pr.RouteRejected) as caught:
        _route(server)
    assert "MM-DD-YYYY" in caught.value.message


def test_404_is_no_route_not_an_exception():
    server = Server((404, {"error": "Unable to get MRT route"}))
    result = _route(server, mode=pr.MODE_RAIL)
    assert result["status"] == pr.STATUS_NO_ROUTE and result["reason"] == "not_found"


@pytest.mark.parametrize("answer, reason", [
    ((429, {"error": "slow down"}), "rate_limited"),
    ((500, {}), "http_error"),
    ((503, {}), "http_error"),
    ((200, {"error": "boom"}), "bad_answer"),
    ((200, {"plan": "x"}), None),
])
def test_other_failures_are_unavailable(answer, reason):
    server = Server(answer)
    if reason is None:
        assert _route(server)["status"] == pr.STATUS_NO_ROUTE  # a plan that is not an object is empty
        return
    with pytest.raises(pr.RouteUnavailable) as caught:
        _route(server)
    assert caught.value.reason == reason


@pytest.mark.parametrize("error, reason", [
    (httpx.ReadTimeout("slow"), "timeout"),
    (httpx.ConnectError("down"), "network"),
])
def test_timeouts_and_network_errors_are_unavailable(error, reason):
    with pytest.raises(pr.RouteUnavailable) as caught:
        _route(Server((200, error)))
    assert caught.value.reason == reason


def test_a_walk_only_answer_through_the_client_is_no_transit():
    origin, destination = _places(_fixture("night"))
    result = _route(Server(_ok_answer("night")), mode=pr.MODE_BUS, origin=origin, destination=destination)
    assert result["status"] == pr.STATUS_NO_TRANSIT


def test_nothing_is_logged_or_printed_by_the_module():
    source = (Path(pr.__file__)).read_text(encoding="utf-8")
    assert "logging" not in source and "print(" not in source


# ---- cache and budget --------------------------------------------------------------------------------------


def test_the_same_search_within_five_minutes_is_answered_from_memory():
    server = Server(_ok_answer())
    router = pr.PtRouter()
    first = _route(server, router=router, now=1000.0)
    budget = pr.CallBudget.single()
    again = _route(server, router=router, now=1000.0 + 299, budget=budget)
    assert len(server.gets) == 1 and again["from_cache"] is True and budget.used == 0
    assert again["itineraries"] == first["itineraries"]


def test_the_cache_expires_after_five_minutes():
    server = Server(_ok_answer())
    router = pr.PtRouter()
    _route(server, router=router, now=1000.0)
    _route(server, router=router, now=1000.0 + pr.CACHE_TTL_SECONDS + 1)
    assert len(server.gets) == 2


def test_the_cache_key_is_origin_destination_mode_and_a_five_minute_departure_bucket():
    server = Server(_ok_answer())
    router = pr.PtRouter()
    _route(server, router=router)
    _route(server, router=router, mode=pr.MODE_BUS)
    _route(server, router=router, depart=DEPART + timedelta(minutes=10))
    _route(server, router=router, destination=pr.Place("place", "", "Orchard", 1.304, 103.8319))
    assert len(server.gets) == 4
    _route(server, router=router, depart=DEPART + timedelta(minutes=1))
    assert len(server.gets) == 4  # same 5 minute bucket


def test_a_cached_answer_cannot_be_changed_by_the_caller():
    server = Server(_ok_answer())
    router = pr.PtRouter()
    first = _route(server, router=router)
    first["itineraries"].clear()
    assert _route(server, router=router)["itineraries"]


def test_the_cache_holds_a_bounded_number_of_answers():
    server = Server(_ok_answer())
    router = pr.PtRouter()
    for minute in range(pr.CACHE_MAX_ENTRIES + 10):
        _route(server, router=router, depart=DEPART + timedelta(minutes=5 * minute), now=1000.0 + minute)
    assert len(router._cache) <= pr.CACHE_MAX_ENTRIES


def test_a_single_budget_allows_one_call_and_the_extended_budget_three():
    assert pr.CallBudget.single().limit == 1 and pr.CallBudget.extended().limit == 3
    server = Server(_ok_answer())
    router = pr.PtRouter()
    budget = pr.CallBudget.single()
    _route(server, router=router, budget=budget)
    with pytest.raises(pr.BudgetExhausted):
        _route(server, router=router, budget=budget, mode=pr.MODE_BUS)
    assert len(server.gets) == 1  # the refused call never reached the network
    wide = pr.CallBudget.extended()
    for mode in (pr.MODE_TRANSIT, pr.MODE_BUS, pr.MODE_RAIL):
        _route(server, router=pr.PtRouter(), budget=wide, mode=mode)
    with pytest.raises(pr.BudgetExhausted):
        _route(server, router=pr.PtRouter(), budget=wide)


# ---- arrive-by search --------------------------------------------------------------------------------------


def _shifted(name: str, seconds: int) -> tuple[int, dict]:
    payload = copy.deepcopy(_fixture(name))
    delta = seconds * 1000
    for itinerary in payload["plan"]["itineraries"]:
        itinerary["startTime"] += delta
        itinerary["endTime"] += delta
        for leg in itinerary["legs"]:
            leg["startTime"] += delta
            leg["endTime"] += delta
    return 200, payload


def _search(server, target, estimate=70, earliest=None, budget=None):
    origin, destination = _places(_fixture("bus_mrt"))
    router = pr.PtRouter()
    with server.client() as client:
        return pr.search_arrive_by(
            router, origin, destination, target, estimate_minutes=estimate,
            earliest=earliest or datetime(2026, 10, 12, 6, 0, tzinfo=SGT), budget=budget,
            session=OneMapSession(), client=client, lta_cache=_lta(), token="manual-token", now=1000.0)


def test_arrive_by_first_asks_for_target_minus_estimate_minus_ten_minutes():
    server = Server(_shifted("bus_mrt", -3600))
    result = _search(server, datetime(2026, 10, 12, 10, 0, tzinfo=SGT), estimate=70)
    assert dict(server.gets[0].url.params)["time"] == "08:40:00"
    assert result["target_met"] is True and result["calls"] == 1


def test_arrive_by_picks_the_latest_departure_that_is_in_time():
    server = Server(_shifted("bus_mrt", 0))  # ends 09:42:28, 09:45:35, 10:10:49
    result = _search(server, datetime(2026, 10, 12, 9, 50, tzinfo=SGT))
    assert result["target_met"] is True
    assert result["itineraries"][0]["arrive"].startswith("2026-10-12T09:45:35")  # started 08:34:43, the latest in time
    assert all(it["arrive"] <= "2026-10-12T09:50:00+08:00" for it in result["itineraries"])


def test_arrive_by_moves_earlier_when_every_itinerary_is_late():
    server = Server(_shifted("bus_mrt", 0), _shifted("bus_mrt", -1200))
    result = _search(server, datetime(2026, 10, 12, 9, 40, tzinfo=SGT), estimate=60)
    assert result["target_met"] is True and result["calls"] == 2 and len(server.gets) == 2
    first, second = (dict(g.url.params)["time"] for g in server.gets)
    assert first == "08:30:00"
    # first answer ended 09:42:28 = 2:28 late, so the second try is 2:28 + 5:00 earlier
    assert second == "08:22:32"


def test_arrive_by_stops_at_three_calls_and_reports_the_target_missed():
    server = Server(_shifted("bus_mrt", 0))
    result = _search(server, datetime(2026, 10, 12, 9, 0, tzinfo=SGT), estimate=60)
    assert result["target_met"] is False and result["calls"] == 3 and len(server.gets) == 3
    assert result["itineraries"], "the fastest itinerary is still returned"


def test_arrive_by_stops_when_no_earlier_departure_exists():
    server = Server(_shifted("bus_mrt", 0))
    floor = datetime(2026, 10, 12, 8, 30, tzinfo=SGT)
    result = _search(server, datetime(2026, 10, 12, 9, 0, tzinfo=SGT), estimate=60, earliest=floor)
    assert result["target_met"] is False and result["calls"] == 1 and len(server.gets) == 1


def test_arrive_by_returns_the_failure_when_onemap_has_no_route():
    server = Server((404, {"error": "Unable to get MRT route"}))
    result = _search(server, datetime(2026, 10, 12, 10, 0, tzinfo=SGT))
    assert result["status"] == pr.STATUS_NO_ROUTE and result["target_met"] is False and result["calls"] == 1


def test_arrive_by_respects_a_smaller_budget():
    server = Server(_shifted("bus_mrt", 0))
    result = _search(server, datetime(2026, 10, 12, 9, 0, tzinfo=SGT), estimate=60, budget=pr.CallBudget(2))
    assert result["calls"] == 2 and len(server.gets) == 2

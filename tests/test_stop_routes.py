"""Every destination stop or station the traveller can pick gives a route, for every priority. The planner routes to the stop's point; an
itinerary that alights there (or within AT_STOP_M) is kept; one that alights up to WALK_TO_STOP_MAX_M away gets a walk row to the stop; and
when none does, the plan goes to the place itself with `destination_fallback` true. "No route" is only for a place OneMap cannot route
to at all. OneMap is stubbed; no live API."""

import pytest
import httpx

import onemap_stub as stub
from nearby import haversine_m
from page_runner import DEST, LON, north, running_app
from test_train_pages import _table
import pt_plan

PRIORITIES = ["fastest", "fewest_transfers", "least_walking", "bus_only", "mrt_only"]
PLACE = north(2150)
CHOSEN = north(2000)
USER = north(300)


def _rail():
    table = _table()
    directions = table["stations"]["NS17"]["directions"]
    table["stations"]["NS26"] = {"name": "Bencoolen", "latitude": CHOSEN[0], "longitude": CHOSEN[1], "directions": directions}
    return table


# (name, stop code, metres the stub's itinerary alights from the stop, expected walk-to-stop row, expected fallback)
CASES = [
    ("nearest stop, alights at it", DEST, 0, False, False),
    ("opposite-side stop, 30 m off", DEST, 30, True, False),
    ("station, 95 m from the place's side", "NS26", 95, True, False),
    ("stop with no exact alighting, 300 m off", DEST, 300, True, False),
    ("stop too far to walk to, 600 m off", DEST, 600, False, True),
    ("station too far to walk to, 900 m off", "NS26", 900, False, True),
]


def _table_for(metres):
    return {"TRANSIT": stub.alights_away(metres), "BUS": stub.alights_away(metres), "RAIL": stub.alights_away(metres, "rail")}


def _plan(base, code, priority, end=CHOSEN):
    return httpx.get(base + "/api/journey-plan", params={
        "user_lat": USER[0], "user_lon": LON, "destination_stop_code": code, "dest_lat": PLACE[0], "dest_lon": PLACE[1],
        "end_lat": end[0], "end_lon": end[1], "end_name": "Chosen Stop", "priority": priority}, timeout=60).json()


def _legs(body):
    return body["itinerary"]["legs"]


@pytest.mark.parametrize("priority", PRIORITIES)
@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_a_chosen_stop_always_gives_a_route(tmp_path, case, priority):
    name, code, metres, walk_row, fallback = case
    with running_app(tmp_path, onemap=stub.following_end(_table_for(metres)), rail_table=_rail()) as base:
        body = _plan(base, code, priority)
    assert body["route_status"] == "ok", (name, priority, body.get("route_status"), body.get("message"))
    assert body.get("destination_fallback", False) is fallback
    legs = _legs(body)
    assert legs[-1]["kind"] == "walk"
    if fallback:  # planned to the place itself: nothing is walked to the stop
        assert not [leg for leg in legs if leg.get("to_stop")]
    else:
        walks = [leg for leg in legs if leg["kind"] == "walk" and leg.get("to_stop")]
        assert bool(walks) is walk_row, [(leg["kind"], leg.get("to_stop")) for leg in legs]
        if walks:
            assert abs(walks[0]["distance_m"] - metres) < 3 and walks[0]["to_name"] == "Chosen Stop"
            assert legs[legs.index(walks[0]) + 1]["kind"] == "walk"  # then the final walk from the stop to the place
        final = legs[-1]
        assert abs(final["distance_m"] - haversine_m(CHOSEN[0], CHOSEN[1], PLACE[0], PLACE[1])) < 3  # from the stop, not from where it alighted


def test_the_limits_are_the_documented_ones():
    assert pt_plan.AT_STOP_M == 25.0 and pt_plan.WALK_TO_STOP_MAX_M == 400.0


@pytest.mark.parametrize("priority", PRIORITIES)
@pytest.mark.parametrize("metres", [0, 30, 399, 450, 900])
def test_a_stop_never_gives_no_route_when_the_place_itself_is_routable(tmp_path, metres, priority):
    with running_app(tmp_path, onemap=stub.following_end(_table_for(metres)), rail_table=_rail()) as base:
        to_place = httpx.get(base + "/api/journey-plan", params={
            "user_lat": USER[0], "user_lon": LON, "dest_lat": PLACE[0], "dest_lon": PLACE[1], "priority": priority}, timeout=60).json()
        to_stop = _plan(base, DEST, priority)
    assert to_place["route_status"] == "ok"  # the place alone is routable ...
    assert to_stop["route_status"] == "ok", (metres, priority, to_stop.get("route_status"))  # ... so the stop must be too


def test_no_route_is_only_when_the_place_has_no_transit_route(tmp_path):
    with running_app(tmp_path, onemap=stub.following_end({"TRANSIT": None, "BUS": None, "RAIL": None}), rail_table=_rail()) as base:
        body = _plan(base, DEST, "fastest")
    assert body["route_status"] != "ok" and not body.get("destination_fallback")


def test_skip_plans_directly_to_the_place(tmp_path):
    with running_app(tmp_path, onemap=stub.following_end(_table_for(0)), rail_table=_rail()) as base:
        body = httpx.get(base + "/api/journey-plan", params={
            "user_lat": USER[0], "user_lon": LON, "dest_lat": PLACE[0], "dest_lon": PLACE[1], "priority": "fastest"}, timeout=60).json()
    assert body["route_status"] == "ok" and not body.get("destination_fallback")

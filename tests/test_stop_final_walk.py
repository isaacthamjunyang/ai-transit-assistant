"""A destination stop or station the traveller picks: Your journey, for every priority, ends at that stop or station (every itinerary shown
alights at it or within AT_STOP_M of it) and then shows the final walk to the real destination. The OneMap stub answers like OneMap does
for a stop that is not the nearest way in: a faster itinerary that alights at an EARLIER stop (the "Bras Basah" of the report) and walks the
rest, and a slower one that rides on to the stop asked for. Before the fix the faster one won and its trailing walk was swapped for a walk
from the earlier stop straight to the place. No live API."""

import re
from datetime import datetime
from pathlib import Path

import pytest

import onemap_stub as stub
from nearby import haversine_m
from page_runner import ALT_STOP, DEST, ORIGIN, require_edge, run_scenario, running_app, north
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
PRIORITIES = ["fastest", "fewest_transfers", "least_walking", "bus_only", "mrt_only"]
PLACE = north(2150)  # "SCIS 1"
CHOSEN = north(2000)  # the chosen stop or station, 150 m from the place
EARLIER = north(1500)  # where the faster itinerary alights, 500 m short of it
NB = chr(0xA0)


def _rail():
    table = _table()
    directions = table["stations"]["NS17"]["directions"]
    table["stations"]["NS26"] = {"name": "Bencoolen", "latitude": CHOSEN[0], "longitude": CHOSEN[1], "directions": directions}
    table["stations"]["NS22"] = {"name": "Bras Basah", "latitude": EARLIER[0], "longitude": EARLIER[1], "directions": directions}
    return table


CASES = {
    "bus": ({"TRANSIT": stub.bus_via_other, "BUS": stub.bus_via_other, "RAIL": stub.train_via_other}, DEST),
    "station": ({"TRANSIT": stub.train_via_other, "BUS": stub.bus_via_other, "RAIL": stub.train_via_other}, "NS26"),
    # OneMap's mixed search alights short of the stop and only the bus search reaches it: the page-side retry finds it
    "retry": ({"TRANSIT": stub.bus_short_only, "BUS": stub.bus_via_other, "RAIL": stub.train_via_other}, DEST),
    # nothing reaches the stop within a walk (the stub alights 500 m short): the plan goes to the place, with an info alert saying so
    # the only itinerary alights 300 m from the stop: a walk row to the stop, then the walk on to the place
    "near": ({"TRANSIT": stub.alights_away(300), "BUS": stub.alights_away(300), "RAIL": stub.alights_away(300, "rail")}, DEST),
    "none": ({"TRANSIT": stub.bus_short_only, "BUS": stub.bus_short_only, "RAIL": stub.train_short_only}, DEST),
}


@pytest.fixture(scope="module", params=list(CASES))
def run(request, tmp_path_factory):
    name = request.param
    require_edge()
    table, code = CASES[name]
    kind = "station" if name == "station" else "bus"
    stops = [{"code": code, "name": "Opp Bencoolen Stn Exit B", "pos": CHOSEN, "kind": kind, "metres": 150, "minutes": 2},
             {"code": ALT_STOP, "name": "Second Stop", "pos": EARLIER, "kind": "bus", "metres": 650, "minutes": 9, "expectMetres": "650"}]
    with running_app(tmp_path_factory.mktemp("sfw" + name), onemap=stub.following_end(table), rail_table=_rail(), alt_stop=True) as base:
        result = run_scenario("stopfinal", base, {"width": 360, "height": 800, "dark": False, "stops": stops, "priorities": PRIORITIES,
                                                  "dest": DEST, "destPos": PLACE}, timeout=300)["result"]
    return name, code, result


def _end(url):
    return float(re.search(r"end_lat=([\d.]+)", url).group(1)), float(re.search(r"end_lon=([\d.]+)", url).group(1))


def _only(run, *names):
    name, code, result = run
    if name not in names:
        pytest.skip("not this case")
    return code, result


@pytest.mark.parametrize("priority", PRIORITIES)
def test_the_page_sends_the_chosen_stops_point_and_code_and_the_planner_routes_to_it(run, priority):
    name, code, result = run
    state = result["byPriority"][priority]
    url = state["requests"][-1]
    end_lat, end_lon = _end(url)
    assert abs(end_lat - CHOSEN[0]) < 1e-6 and abs(end_lon - CHOSEN[1]) < 1e-6  # the stop's own point, not the place
    assert f"destination_stop_code={code}" in url and f"priority={priority}" in url and "dest_lat=" in url


@pytest.mark.parametrize("priority", PRIORITIES)
def test_every_itinerary_shown_ends_at_the_chosen_stop_and_walks_on_to_the_place(run, priority):
    code, result = _only(run, "bus", "station", "retry")
    state = result["byPriority"][priority]
    body = state["body"]
    assert body["route_status"] == "ok"
    chosen_codes = {DEST, "NS26"}  # the codes of what sits at the chosen point (a bus stop, a station) in this stub
    assert body["allEnds"] and all(end in chosen_codes for end in body["allEnds"]), body["allEnds"]  # never the earlier stop (88888, NS22)
    assert ALT_STOP not in body["allEnds"] and "NS22" not in body["allEnds"]
    assert body["rideEnd"]["stop_code"] in chosen_codes
    assert haversine_m(body["rideEnd"]["latitude"], body["rideEnd"]["longitude"], CHOSEN[0], CHOSEN[1]) <= 150  # at the stop, within the threshold
    metres = haversine_m(CHOSEN[0], CHOSEN[1], PLACE[0], PLACE[1])
    assert body["kinds"][-1] == "walk" and abs(body["finalWalkM"] - metres) < 2 and body["lastTo"] == "Destination"  # then the walk to the place
    assert body["walkTotalM"] >= body["finalWalkM"] - 1
    ride, arrive = datetime.fromisoformat(body["rideArrive"]), datetime.fromisoformat(body["arrive"])
    assert abs((arrive - ride).total_seconds() - body["finalWalkS"]) < 2  # the arrival includes that walk


@pytest.mark.parametrize("priority", PRIORITIES)
def test_your_journey_shows_the_walk_from_the_stop_not_from_the_earlier_stop(run, priority):
    code, result = _only(run, "bus", "station", "retry")
    state = result["byPriority"][priority]
    assert state["state"] == "ready" and state["priority"] == priority
    rows = [row.replace(NB, " ") for row in state["rows"]]
    assert re.match(r"Walk 2 min150 m to SCIS 1", rows[-2]), rows[-2]  # 150 m from the stop; the earlier stop would give 650 m and 9 min
    assert rows[-1].startswith("Destination") and "SCIS 1" in rows[-1]


@pytest.mark.parametrize("priority", PRIORITIES)
def test_when_nothing_reaches_the_stop_the_plan_goes_to_the_place_with_an_info_alert(run, priority):
    code, result = _only(run, "none")
    state = result["byPriority"][priority]
    assert state["state"] == "ready" and state["body"]["route_status"] == "ok", state["state"]  # never "No route found"
    note = state["destNote"]
    assert note["hidden"] is False and "alert--info" in note["cls"].split()  # the shared info alert
    assert note["text"] == "No route to Opp Bencoolen Stn Exit B. Showing a route to SCIS 1."
    assert state["body"]["kinds"][-1] == "walk"


@pytest.mark.parametrize("priority", PRIORITIES)
def test_an_alighting_a_walk_away_gets_its_own_walk_row_to_the_stop_then_the_final_walk(run, priority):
    code, result = _only(run, "near")
    state = result["byPriority"][priority]
    assert state["state"] == "ready" and state["destNote"]["hidden"] is True  # a route to the stop: no fallback alert
    rows = [row.replace(NB, " ") for row in state["rows"]]
    assert re.match(r"Walk 4 min300 m to Opp Bencoolen Stn Exit B", rows[-3]), rows[-3]  # from where the ride ends to the stop
    assert re.match(r"Walk 2 min150 m to SCIS 1", rows[-2]), rows[-2]  # then from the stop to the place
    assert rows[-1].startswith("Destination")
    assert state["walkRows"] == state["walkTexts"] and state["walkingCell"].replace(NB, " ") == f"{sum(state['walkRows'])} min"


@pytest.mark.parametrize("priority", PRIORITIES)
def test_the_alert_is_shown_only_when_the_plan_fell_back(run, priority):
    name, code, result = run
    note = result["byPriority"][priority]["destNote"]
    assert note["hidden"] is (name != "none"), (name, note)


@pytest.mark.parametrize("priority", PRIORITIES)
def test_the_walking_figure_is_the_sum_of_the_walk_rows_shown(run, priority):
    code, result = _only(run, "bus", "station", "retry")
    state = result["byPriority"][priority]
    assert state["walkRows"] and state["walkRows"] == state["walkTexts"]  # the minutes kept on the rows are the minutes the rows say
    total = sum(state["walkRows"])
    assert state["walkingCell"].replace(NB, " ") == f"{total} min", (state["walkingCell"], state["walkRows"])
    assert f"{total} min" in state["summaryAria"].replace(NB, " ")  # the label that says it aloud uses the same number


def test_the_confirm_page_names_the_stop_or_station(run):
    code, result = _only(run, "bus", "station")
    name = run[0]
    confirm = result["confirm"]
    assert confirm["confirmStop"] == "Opp Bencoolen Stn Exit B" and confirm["place"] == "SCIS 1"
    assert confirm["confirmHeading"] == ("Destination stop" if name == "bus" else "Destination station")


def test_changing_the_choice_updates_the_confirm_page_the_request_and_the_journey_with_nothing_stale(run):
    code, result = _only(run, "bus")
    assert result["backToStops"]["top"] == "stops" and result["backToStops"]["place"] == "SCIS 1"
    assert result["confirm2"]["confirmStop"] == "Second Stop" and result["confirm2"]["confirmedCode"] is None  # the old confirmation is dropped
    assert result["confirm2"]["selectedCode"] == ALT_STOP
    (url,) = result["requests2"]
    end_lat, end_lon = _end(url)
    assert abs(end_lat - EARLIER[0]) < 1e-6 and f"destination_stop_code={ALT_STOP}" in url  # the new stop's point and code, not the old ones
    journey = result["journey2"]
    assert not result.get("timedOut") and journey["state"] == "ready" and journey["confirmedCode"] == ALT_STOP
    rows = [row.replace(NB, " ") for row in journey["rows"]]
    assert re.match(r"Walk 9 min650 m to SCIS 1", rows[-2]), rows[-2]  # the second stop's own walk to the place
    assert journey["walkRows"] == journey["walkTexts"] and journey["walkingCell"].replace(NB, " ") == f"{sum(journey['walkRows'])} min"
    assert journey["stack"] == ["home", "results", "stops", "confirm", "journey"]  # one clean history
    assert journey["place"] == "SCIS 1" and journey["pending"] == "SCIS 1"


def test_skip_still_plans_directly_to_the_place_and_the_planner_walks_to_a_chosen_stop_or_falls_back():
    assert '(destinationSkipped() ? "" : "&destination_stop_code="' in INDEX
    plan = (ROOT / "pt_plan.py").read_text(encoding="utf-8")
    assert "AT_STOP_M = 25.0" in plan and "WALK_TO_STOP_MAX_M = 400.0" in plan and "if ends_at_stop:" in plan and "_via_stop(" in plan
    assert '"destination_fallback": fallback' in plan and "ALIGHT_AT_STOP_M" not in plan
    assert "alights at that stop" in PLAN and "400 m" in PLAN and "No route to {stop}. Showing a route to {place}." in PLAN
    assert 'destinationFallback: "No route to {stop}. Showing a route to {place}."' in (ROOT / "static" / "copy.js").read_text(encoding="utf-8")


def test_one_function_gives_the_walking_figure():
    assert INDEX.count("function displayedWalkMinutes(list) {") == 1 and "summary.walking = displayedWalkMinutes(list);" in INDEX
    assert INDEX.count("function walkStep(kind, minutes, lines, edit) {") == 1 and 'item.setAttribute("data-walk-minutes", String(minutes));' in INDEX
    assert "walking = pendingItinerary.totals.walk_minutes;" in INDEX  # the server's total is only the starting value, replaced above
    assert "figure is the sum of the walk rows that are shown" in PLAN

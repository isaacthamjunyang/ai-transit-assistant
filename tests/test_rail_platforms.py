"""Platforms and loop-line directions: the builder reads platform_code from the GTFS, the leg carries the platform only
when exactly one platform serves the direction, and no exit is shown anywhere. Nothing here calls an API."""

import json
import re
from datetime import date
from pathlib import Path

import pytest

import build_rail_timetable as builder
import pt_route
import service_hours as sh
from test_rail_timetable import _csv, _hms

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 10)


def make_platform_gtfs(folder: Path) -> Path:
    """NS: Far End leaves on A and Home on B, except that at NS2 Far End uses both A and B (an interchange). TE1 is a
    terminus whose trains leave from two platforms. BP1 has a blank platform_code and BP2 has "A / D / E"."""
    folder.mkdir(parents=True, exist_ok=True)
    _csv(folder / "calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date",
         ["SERVICE_WD,1,1,1,1,1,0,0,20260101,20261231"])
    _csv(folder / "feed_info.txt", "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version",
         ["LTA,https://www.lta.gov.sg/,en,20250101,20261231,0.1"])
    _csv(folder / "routes.txt", "route_id,agency_id,route_short_name,route_long_name,route_type,route_color,route_text_color",
         ["R1,SMRT,NS,North-South Line,1,d62821,FFFFFF", "R3,SMRT,TE,Thomson-East Coast Line,1,9D5A25,FFFFFF",
          "R4,SMRT,BP,Bukit Panjang LRT,0,6E8270,FFFFFF"])
    _csv(folder / "stops.txt", "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,platform_code,parent_station", [
        "NS1_A,NS1,Alpha,1.30,103.80,0,A,", "NS1_B,NS1,Alpha,1.30,103.80,0,B,",
        "NS2_A,NS2,Beta,1.31,103.81,0,A,", "NS2_B,NS2,Beta,1.31,103.81,0,B,",
        "NS3_A,NS3,Gamma,1.32,103.82,0,A,", "NS3_B,NS3,Gamma,1.32,103.82,0,B,",
        "TE1_A,TE1,Delta,1.40,103.90,0,A,", "TE1_B,TE1,Delta,1.40,103.90,0,B,", "TE2_A,TE2,Echo,1.41,103.91,0,A,",
        "BP1_A,BP1,Foxtrot,1.50,104.00,0,,", "BP2_A,BP2,Golf,1.51,104.01,0,A / D / E,", "BP3_A,BP3,Hotel,1.52,104.02,0,A,",
    ])
    trips, times = [], []

    def add(trip_id, route, headsign, direction, minutes, stops):
        trips.append(f"{route},SERVICE_WD,{trip_id},{headsign},{direction},")
        for i, stop_id in enumerate(stops):
            at = _hms(minutes + 2 * i)
            times.append(f"{trip_id},{at},{at},{stop_id},{i + 1},")

    for i in range(6):
        add(f"far{i}", "R1", "Far End", 0, 330 + 6 * i, ["NS1_A", "NS2_A" if i % 2 == 0 else "NS2_B", "NS3_A"])
        add(f"home{i}", "R1", "Home", 1, 340 + 6 * i, ["NS3_B", "NS2_B", "NS1_B"])
        add(f"te{i}", "R3", "Echo Far", 0, 400 + 10 * i, ["TE1_A" if i % 2 == 0 else "TE1_B", "TE2_A"])
        add(f"bp{i}", "R4", "Loop A", 0, 500 + 10 * i, ["BP1_A", "BP2_A", "BP3_A"])
    _csv(folder / "trips.txt", "route_id,service_id,trip_id,trip_headsign,direction_id,block_id", trips)
    _csv(folder / "stop_times.txt", "trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign", times)
    return folder


@pytest.fixture(scope="module")
def table(tmp_path_factory):
    return builder.build_table(make_platform_gtfs(tmp_path_factory.mktemp("platform_gtfs")), TODAY)


def _platforms(table, code, headsign):
    return table["stations"][code]["directions"][headsign]["platforms"]


def test_one_platform_per_direction_is_recorded(table):
    assert _platforms(table, "NS1", "Far End") == ["A"]
    assert _platforms(table, "NS3", "Home") == ["B"]
    assert sh.rail_platform(table, "NS1", "Far End") == "A"
    assert sh.rail_platform(table, "NS3", "Home") == "B"


def test_two_platforms_for_one_direction_show_none(table):
    assert _platforms(table, "NS2", "Far End") == ["A", "B"]  # an interchange: both platforms serve the direction
    assert sh.rail_platform(table, "NS2", "Far End") is None
    assert _platforms(table, "TE1", "Echo Far") == ["A", "B"]  # a branch terminus whose trains use both
    assert sh.rail_platform(table, "TE1", "Echo Far") is None


def test_a_blank_or_list_platform_code_is_unknown_not_guessed(table):
    assert _platforms(table, "BP1", "Loop A") == []
    assert _platforms(table, "BP2", "Loop A") == []
    assert sh.rail_platform(table, "BP1", "Loop A") is None and sh.rail_platform(table, "BP2", "Loop A") is None


@pytest.mark.parametrize("args", [("NS99", "Far End"), ("NS1", "Nowhere"), ("NS1", None), ("NS1", "")])
def test_an_unknown_station_or_direction_has_no_platform(table, args):
    assert sh.rail_platform(table, *args) is None


def test_an_old_table_without_platforms_and_no_table_give_none():
    old = {"stations": {"NS1": {"directions": {"Far End": {"line": "NS", "direction_id": 0}}}}}
    assert sh.rail_platform(old, "NS1", "Far End") is None and sh.rail_platform(None, "NS1", "Far End") is None


def test_validation_rejects_a_bad_platform_list(table):
    bad = json.loads(json.dumps(table))
    bad["stations"]["NS1"]["directions"]["Far End"]["platforms"] = [""]
    problems = builder.validate_table(bad, TODAY, required_lines=("NS", "TE", "BP"), min_stations=5)
    assert any("platforms" in problem for problem in problems)


# ---- the leg -----------------------------------------------------------------------------------------------


def _leg(table):
    payload = json.loads((ROOT / "tests" / "fixtures" / "pt_mrt_only.json").read_text(encoding="utf-8"))
    start, end = payload["plan"]["from"], payload["plan"]["to"]
    origin = pt_route.Place("stop", "", "", start["lat"], start["lon"])
    destination = pt_route.Place("place", "", "", end["lat"], end["lon"])
    return pt_route.parse_response(200, payload, origin, destination, None, table)["itineraries"][0]["legs"][1]


def _ride_table(headsign, direction_id, platforms, loop=False):
    entries = {headsign: {"line": "NS", "direction_id": direction_id, "trips": 5, "platforms": platforms}}
    if loop:  # the headsigns that make a line a loop line
        entries.setdefault("Anticlockwise", {"line": "NS", "direction_id": 0})
        entries.setdefault("Clockwise", {"line": "NS", "direction_id": 1})
    return {"stations": {"NS17": {"directions": entries}},
            "patterns": {"NS": {headsign: ["NS16", "NS17", "NS18", "NS22", "NS28"]}}}


def test_the_leg_carries_the_platform_only_when_one_platform_serves_the_direction():
    assert _leg(_ride_table("Marina South Pier", 1, ["B"]))["platform"] == "B"
    assert _leg(_ride_table("Marina South Pier", 1, ["A", "B"]))["platform"] is None
    assert _leg(_ride_table("Marina South Pier", 1, []))["platform"] is None
    assert _leg(None)["platform"] is None


def test_an_ordinary_line_has_a_terminus_and_no_loop_word():
    leg = _leg(_ride_table("Marina South Pier", 1, ["B"]))
    assert leg["terminus"] == "Marina South Pier" and leg["circle_direction"] is None


@pytest.mark.parametrize("headsign, direction_id, word", [("Anticlockwise", 0, "anticlockwise"), ("Clockwise", 1, "clockwise")])
def test_a_loop_ride_names_its_way_round_and_has_no_terminus(headsign, direction_id, word):
    leg = _leg(_ride_table(headsign, direction_id, ["A"], loop=True))
    assert leg["circle_direction"] == word and leg["terminus"] is None and leg["platform"] == "A"


def test_a_loop_line_ride_with_a_station_headsign_has_both_the_way_round_and_the_terminus():
    leg = _leg(_ride_table("Stadium", 0, [], loop=True))
    assert leg["circle_direction"] == "anticlockwise" and leg["terminus"] == "Stadium" and leg["platform"] is None


def test_the_loop_words_come_from_the_table_by_line_and_direction_id():
    table = {"stations": {"CC1": {"directions": {"Anticlockwise": {"line": "CC", "direction_id": 0},
                                                 "Clockwise": {"line": "CC", "direction_id": 1},
                                                 "Stadium": {"line": "CC", "direction_id": 0}}}}}
    assert sh.rail_circle_direction(table, "CC", 0) == "anticlockwise"
    assert sh.rail_circle_direction(table, "CC", 1) == "clockwise"
    assert sh.rail_circle_direction(table, "NS", 0) is None  # not a loop line
    assert sh.rail_circle_direction(table, "CC", None) is None and sh.rail_circle_direction(None, "CC", 0) is None


def test_the_real_table_has_one_platform_for_the_measured_directions():
    real = sh.load_rail_table(ROOT / "cache")
    if real is None:
        pytest.skip("run build_rail_timetable.py first")
    assert sh.rail_platform(real, "NS24", "Jurong East") == "A" and sh.rail_platform(real, "NS24", "Marina South Pier") == "B"
    assert sh.rail_platform(real, "CC1", "Anticlockwise") is None  # both platforms serve it
    assert sh.rail_circle_direction(real, "CC", 0) == "anticlockwise" and sh.rail_circle_direction(real, "CC", 1) == "clockwise"


# ---- no exits anywhere -------------------------------------------------------------------------------------


def test_no_exit_text_in_copy_js_the_rail_row_code_or_the_style_guide_rail_rows():
    """No source says which exit a traveller should use, so none is shown. (Other "exit" words in the page are code names such
    as exitJourney, the EXIT map pin and real bus-stop names, none of them a station exit.)"""
    copy = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
    assert not re.search(r"exit", copy, re.IGNORECASE)
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    rail = page.split("function railDirectionText(leg)", 1)[1].split("// One row for a bus or train leg", 1)[0]
    assert not re.search(r"exit", rail, re.IGNORECASE)
    guide = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
    rows = guide.split("function sgRailLeg", 1)[1].split("function sgSelect", 1)[0]
    sample = guide.split("function legsSample()", 1)[1].split("document.getElementById(\"legs-sample-light\")", 1)[0]
    assert not re.search(r"exit", rows + sample, re.IGNORECASE)

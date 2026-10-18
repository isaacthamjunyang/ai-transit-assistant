"""Destination stop page: bus stops and MRT or LRT stations in one list, nearest walk first; station rows, rings and markers;
the chosen stop or station as the planner's end. Static data and mock transports only: nothing here calls an API."""

import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import destination_stops as ds
import main
import onemap_stub as stub
import pt_plan
import test_map_lines as tml
from nearby import haversine_m
from page_runner import north, require_edge, run_scenario, running_app
from test_pt_plan import (JOURNEY, NOW, Server, api, end_of, lta, ok, start_of)  # noqa: F401  (api is a fixture)

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
NB = " "
# a weekday at 10:00 in Singapore, so no test here depends on the machine clock (buses run, nothing is closed)
DAYTIME = datetime(2026, 10, 12, 10, 0, tzinfo=timezone(timedelta(hours=8)))
CODES = ["ns", "ew", "cg", "ne", "cc", "dt", "te", "bp", "sk", "pg", "ss"]


# ---- a small rail table ------------------------------------------------------------------------------------


def offset(point, north_m=0.0, east_m=0.0):
    return (point[0] + north_m / 111320.0, point[1] + east_m / (111320.0 * math.cos(math.radians(point[0]))))


LINES = {"NS": {"name": "North-South Line", "mode": "SUBWAY"}, "EW": {"name": "East-West Line", "mode": "SUBWAY"},
         "CC": {"name": "Circle Line", "mode": "SUBWAY"}, "BP": {"name": "Bukit Panjang LRT", "mode": "TRAM"},
         "DT": {"name": "Downtown Line", "mode": "SUBWAY"}}


def table_around(place, specs):
    """specs: [(code, name, north_m, east_m, interchange)] as a rail table with those stations."""
    stations = {}
    for code, name, north_m, east_m, interchange in specs:
        lat, lon = offset(place, north_m, east_m)
        stations[code] = {"name": name, "latitude": lat, "longitude": lon, "interchange": interchange, "directions": {}}
    return {"schema": 1, "lines": LINES, "stations": stations, "patterns": {}}


PLACE = (1.3512, 103.8484)
NEAR = table_around(PLACE, [
    ("NS5", "Alpha", 150, 0, None), ("EW9", "Beta", 0, 350, None), ("NS9", "Beta", 0, 350, "EW9"),
    ("BP2", "Gamma", -520, 0, None), ("CC3", "Far Away", 900, 0, None)])


# ---- the stations as places --------------------------------------------------------------------------------


def test_codes_of_one_interchange_group_are_one_station_with_every_line():
    places = {item["name"]: item for item in ds.station_places(NEAR)}
    assert places["Beta"]["codes"] == ["NS9", "EW9"] and [line["code"] for line in places["Beta"]["lines"]] == ["NS", "EW"]
    assert places["Beta"]["mode"] == "MRT" and places["Gamma"]["mode"] == "LRT"
    assert len(places) == 4  # Alpha, Beta (two codes), Gamma, Far Away


def test_an_mrt_and_an_lrt_station_with_one_name_close_together_are_one_place():
    table = table_around(PLACE, [("DT1", "Bukit Panjang", 0, 0, None), ("BP6", "Bukit Panjang", 40, 0, None)])
    places = ds.station_places(table)
    assert len(places) == 1 and places[0]["mode"] == "MRT" and [line["code"] for line in places[0]["lines"]] == ["DT", "BP"]


def test_the_real_table_gives_dhoby_ghaut_three_lines_and_one_row():
    import service_hours
    real = service_hours.load_rail_table()
    if real is None:
        pytest.skip("run build_rail_timetable.py first")
    cards = [card for _, card in ds.station_cards(real, 1.29869, 103.84611)]
    dhoby = [card for card in cards if card["stop_name"] == "Dhoby Ghaut"]
    assert len(dhoby) == 1 and [line["code"] for line in dhoby[0]["lines"]] == ["NS", "NE", "CC"]
    assert dhoby[0]["station_codes"] == ["NS24", "NE6", "CC1"] and dhoby[0]["station_mode"] == "MRT"


# ---- which stations, and the 1.5 km fallback ---------------------------------------------------------------


def test_every_station_within_600_m_is_offered_and_one_beyond_is_not():
    cards = ds.station_cards(NEAR, *PLACE)
    names = [card["stop_name"] for _, card in cards]
    assert sorted(names) == ["Alpha", "Beta", "Gamma"] and all(not card["beyond_radius"] for _, card in cards)


def test_with_none_within_600_m_the_single_nearest_within_1500_m_is_offered():
    table = table_around(PLACE, [("NS5", "Alpha", 900, 0, None), ("EW9", "Beta", 0, 1300, None), ("CC3", "Far", 2500, 0, None)])
    cards = ds.station_cards(table, *PLACE)
    assert [card["stop_name"] for _, card in cards] == ["Alpha"] and cards[0][1]["beyond_radius"] is True
    assert ds.station_cards(table_around(PLACE, [("CC3", "Far", 2500, 0, None)]), *PLACE) == []  # nothing within 1.5 km
    assert ds.station_cards(None, *PLACE) == [] and ds.station_cards({}, *PLACE) == []


def test_a_600_m_station_is_inside_and_a_station_card_has_no_reachability():
    table = table_around(PLACE, [("NS5", "Edge", 599, 0, None)])
    metres, card = ds.station_cards(table, *PLACE)[0]
    assert metres < 600 and card["kind"] == "station" and card["is_reachable"] is None
    assert card["connecting_services"] == [] and card["rough_journey_minutes"] is None and "no direct" not in str(card).lower()
    assert card["distance_m"] == int(metres + 0.5) and card["walk_minutes"] >= 1


# ---- one list, nearest first --------------------------------------------------------------------------------


def _listed(table, place=None):
    cache = lta()
    point = place or end_of("direct_bus")
    return ds.list_destination_stops(cache, point[0], point[1], *start_of("direct_bus"), rail_table=table,
                                  now=DAYTIME)


def test_bus_stops_and_stations_are_one_list_sorted_by_distance_ascending():
    point = end_of("direct_bus")
    table = table_around(point, [("NS5", "Alpha", 150, 0, None), ("EW9", "Beta", 0, 350, None), ("BP2", "Gamma", -520, 0, None)])
    listed = _listed(table, point)
    candidates = listed["candidates"]
    distances = [item["distance_m"] for item in candidates]
    assert distances == sorted(distances) and len(candidates) >= 4
    assert {item["kind"] for item in candidates} == {"bus", "station"}
    assert [item["stop_name"] for item in candidates if item["kind"] == "station"] == ["Alpha", "Beta", "Gamma"]
    assert all(item["kind"] == "bus" for item in listed["reachable_stops"] + listed["unreachable_stops"])
    buses = [item["stop_code"] for item in candidates if item["kind"] == "bus"]
    assert sorted(buses) == sorted(item["stop_code"] for item in listed["reachable_stops"] + listed["unreachable_stops"])


def test_a_tie_puts_the_bus_stop_first_then_the_code():
    point = end_of("direct_bus")
    cache = lta()
    first_bus = ds.list_destination_stops(cache, point[0], point[1], *start_of("direct_bus"), now=DAYTIME)["reachable_stops"][0]
    table = table_around((first_bus["lat"], first_bus["lon"]), [("NS5", "Same Spot", 0, 0, None)])
    listed = ds.list_destination_stops(cache, first_bus["lat"], first_bus["lon"], *start_of("direct_bus"),
                                    rail_table=table, now=DAYTIME)
    nearest = [item for item in listed["candidates"] if item["distance_m"] == min(i["distance_m"] for i in listed["candidates"])]
    assert nearest[0]["kind"] == "bus"


def test_without_a_rail_table_the_list_is_the_bus_stops_as_before():
    listed = _listed(None)
    shown = listed["reachable_stops"] + listed["unreachable_stops"]
    assert sorted(i["stop_code"] for i in listed["candidates"]) == sorted(i["stop_code"] for i in shown)
    assert all(i["kind"] == "bus" for i in listed["candidates"])
    distances = [i["distance_m"] for i in listed["candidates"]]
    assert distances == sorted(distances)


def _pin_clock(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return DAYTIME if tz is None else DAYTIME.astimezone(tz)

    for module in (main, ds):
        monkeypatch.setattr(module, "datetime", Fixed)


def test_the_endpoint_returns_the_candidates(monkeypatch):
    _pin_clock(monkeypatch)
    point = end_of("direct_bus")
    table = table_around(point, [("NS5", "Alpha", 150, 0, None)])
    monkeypatch.setattr(main, "load_static_data", lambda: lta())
    monkeypatch.setattr(main, "startup_warning", lambda today: None)
    monkeypatch.setattr(main, "load_rail_table", lambda: table)
    with TestClient(main.app) as client:
        body = client.get("/api/destination-stops", params={"dest_lat": point[0], "dest_lon": point[1],
                                                           "user_lat": 1.3697, "user_lon": 103.8486}).json()
    station = [item for item in body["candidates"] if item["kind"] == "station"][0]
    assert station["stop_name"] == "Alpha" and station["station_mode"] == "MRT" and station["lines"][0]["code"] == "NS"


# ---- the planner ends at the chosen stop or station ---------------------------------------------------------


STATION = offset(end_of("direct_bus"), 120, 0)


def test_the_planner_routes_to_the_chosen_point_and_adds_the_walk_to_the_place(api):
    place = end_of("direct_bus")
    params = {**JOURNEY, "dest_lat": place[0], "dest_lon": place[1], "destination_stop_code": "NS5", "priority": "fastest",
              "end_lat": STATION[0], "end_lon": STATION[1]}
    body = api.get("/api/journey-plan", params=params).json()
    sent = api.holder["server"].gets[-1].url.params["end"]
    assert sent == f"{STATION[0]:.5f},{STATION[1]:.5f}"  # the station, not the place
    assert body["journey"]["destination_stop_code"] == "NS5"  # the station's code in the journey terms
    legs = body["itinerary"]["legs"]
    assert legs[-1]["kind"] == "walk" and legs[-1]["to_name"] == "Destination"
    ride = [leg for leg in legs if leg["kind"] != "walk"][-1]["stops"][-1]
    to_stop = [leg for leg in legs if leg.get("to_stop")]  # the ride alights 120 m from the station: a walk row to it first
    assert len(to_stop) == 1 and abs(to_stop[0]["distance_m"] - haversine_m(ride["latitude"], ride["longitude"], STATION[0], STATION[1])) < 1.0
    assert abs(legs[-1]["distance_m"] - haversine_m(STATION[0], STATION[1], place[0], place[1])) < 1.0  # then the walk from the station
    assert body["option"]["totals"]["walk_m"] >= legs[-1]["distance_m"] - 1


def test_without_an_end_point_the_planner_still_routes_to_the_place(api):
    place = end_of("direct_bus")
    api.get("/api/journey-plan", params={**JOURNEY, "dest_lat": place[0], "dest_lon": place[1], "priority": "fastest"})
    assert api.holder["server"].gets[-1].url.params["end"] == f"{place[0]:.5f},{place[1]:.5f}"


@pytest.mark.parametrize("only", [{"end_lat": 1.35}, {"end_lon": 103.85}])
def test_one_end_coordinate_alone_is_refused(api, only):
    response = api.get("/api/journey-plan", params={**JOURNEY, "priority": "fastest", **only})
    assert response.status_code == 422 and "end_lat and end_lon" in response.json()["detail"]
    assert not api.holder["server"].gets


def test_the_route_plan_takes_the_same_end_point(api):
    place = end_of("direct_bus")
    route = {"boarding_stop_code": "54009", "destination_stop_code": "NS5", "user_lat": 1.3697, "user_lon": 103.8486,
             "dest_lat": place[0], "dest_lon": place[1], "priority": "fastest", "end_lat": STATION[0], "end_lon": STATION[1]}
    api.get("/api/route-plan", params=route)
    assert api.holder["server"].gets[-1].url.params["end"] == f"{STATION[0]:.5f},{STATION[1]:.5f}"


def test_the_bus_planner_fallback_keeps_using_the_place(api):
    api.holder["server"] = Server(default=(500, {}))
    place = end_of("direct_bus")
    body = api.get("/api/journey-plan", params={**JOURNEY, "dest_lat": place[0], "dest_lon": place[1], "priority": "fastest",
                                                "end_lat": STATION[0], "end_lon": STATION[1]}).json()
    assert body["planner"] == "static" and body["fallback_note"] is True


def test_a_stop_at_the_place_adds_no_walk_and_a_far_one_replaces_the_onemap_end_walk():
    stop = {"latitude": 1.3000, "longitude": 103.8000}
    ride = {"kind": "bus", "stops": [stop, stop], "arrive": "2026-10-12T08:40:00+08:00", "alighting_stop_name": "Stop X"}
    walk = {"kind": "walk", "distance_m": 12.0, "depart": "2026-10-12T08:40:00+08:00", "arrive": "2026-10-12T08:41:00+08:00"}
    itinerary = {"legs": [ride, walk], "arrive": "2026-10-12T08:41:00+08:00", "walk_m": 12.0}
    same = pt_plan._end_at_place(itinerary, 1.3000, 103.8000, 1.25)
    assert [leg["kind"] for leg in same["legs"]] == ["bus"]  # the stop is the place: OneMap's own walk to the stop goes, none is added
    far = pt_plan._end_at_place(itinerary, 1.3045, 103.8000, 1.25, "Home")
    assert far["legs"][-1]["kind"] == "walk" and far["legs"][-1]["to_name"] == "Home"
    assert 495 < far["legs"][-1]["distance_m"] < 505 and far["arrive"] == far["legs"][-1]["arrive"]
    assert [leg["kind"] for leg in far["legs"]] == ["bus", "walk"]


# ---- the rings: contrast from theme.css in both themes -----------------------------------------------------


def _lum(hex6):
    channels = [int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _ratio(a, b):
    high, low = sorted((_lum(a), _lum(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _mix(ring, card, share=0.18):
    return "".join(f"{round(int(ring[i:i + 2], 16) * share + int(card[i:i + 2], 16) * (1 - share)):02X}" for i in (0, 2, 4))


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("code", CODES)
def test_a_station_ring_is_3_to_1_on_the_card_and_the_map_or_has_a_casing_that_is(theme, code):
    tokens = tml._theme(theme)
    ring = tml._hex(tokens, f"--ring-{code}")
    casing_value = tml._resolve(tokens, tokens[f"--ring-{code}-casing"])
    casing = None if casing_value == "transparent" else casing_value.lstrip("#").upper()
    for background in ("--color-card", "--color-paper"):
        surface = tml._hex(tokens, background)
        if _ratio(ring, surface) < 3:
            assert casing is not None and _ratio(casing, surface) >= 3, (theme, code, background)
    tint = _mix(ring, tml._hex(tokens, "--color-card"))
    assert _ratio(tml._hex(tokens, "--color-ink"), tint) >= 4.5, (theme, code)  # the icon on the tile


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_neutral_ring_is_3_to_1_on_the_card_the_tile_and_the_map(theme):
    tokens = tml._theme(theme)
    ring = tml._hex(tokens, "--ring-neutral")
    for background in ("--color-card", "--color-paper", "--ring-neutral-tint"):
        assert _ratio(ring, tml._hex(tokens, background)) >= 3, (theme, background)
    assert _ratio(tml._hex(tokens, "--color-ink"), tml._hex(tokens, "--ring-neutral-tint")) >= 4.5


def test_ring_tokens_are_in_all_four_theme_blocks_and_the_page_sets_no_colour():
    assert THEME.count("--ring-ns:") == 4 and THEME.count("--ring-neutral:") == 4 and THEME.count("--ring-cc-tint:") == 4
    block = CSS.split("/* Destination list: the tile of a row.", 1)[1].split(".pill {", 1)[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", block)
    assert 'style="' not in INDEX.split("<script", 1)[0]


# ---- the page in a browser ----------------------------------------------------------------------------------


def _run(tmp_path_factory, name, table, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), rail_table=table) as base:
        return run_scenario("deststations", base, {"name": name, **config})["result"]


def _page_table():
    place = north(2000)
    return table_around(place, [
        ("NS5", "Alpha", 150, 0, None), ("EW9", "Beta", 0, 350, None), ("NS9", "Beta", 0, 350, "EW9"),
        ("BP2", "Gamma", -520, 0, None), ("CC3", "Far Away", 900, 0, None), ("CC4", "Casing Test", 0, -250, None)])


@pytest.fixture(scope="module")
def narrow_light(tmp_path_factory):
    return _run(tmp_path_factory, "dest_narrow", _page_table(), width=360, height=900, click="NS5")


@pytest.fixture(scope="module")
def wide_dark(tmp_path_factory):
    return _run(tmp_path_factory, "dest_wide", _page_table(), width=1280, height=900, dark=True, click="NS9", confirm=True)


@pytest.fixture(scope="module")
def beyond(tmp_path_factory):
    return _run(tmp_path_factory, "dest_beyond", table_around(north(2000), [("CC3", "Far Away", 900, 0, None)]), width=390)


def test_the_heading_and_the_info_note_say_stations_and_bus_stops(narrow_light):
    first = narrow_light["first"]
    assert first["title"] == "Nearby stops and stations"
    assert first["info"] == ("Stops and stations within 600 m, nearest first. "
                             "If none, the nearest within 1.5 km.")
    assert 'title: "Nearby stops and stations"' in COPY


def test_the_list_is_one_list_nearest_first_with_no_row_chosen(narrow_light):
    first = narrow_light["first"]
    rows = first["rows"]
    metres = [int(re.search(r"\((\d+)" + NB + "m\)", row["meta"]).group(1)) for row in rows if "(" in row["meta"]]
    assert metres == sorted(metres), metres
    assert [row["kind"] for row in rows][0] == "bus" and "station" in [row["kind"] for row in rows]
    assert [row["name"] for row in rows if row["kind"] == "station"] == ["Alpha", "Casing Test", "Beta", "Gamma"]
    assert "Far Away" not in [row["name"] for row in rows]  # 900 m: out of the radius while others are in
    assert not any(row["selected"] for row in rows) and all(row["pressed"] == "false" for row in rows) and first["selectedCode"] is None
    assert first["selectDisabled"] is False  # Select stop is enabled so it can say that nothing is chosen
    assert rows[0]["pill"] == "Best option" and all(row["pill"] is None for row in rows[1:])


def test_every_row_says_its_type_in_text_and_stations_show_every_line_badge_with_its_name(narrow_light):
    rows = narrow_light["first"]["rows"]
    for row in rows:
        assert row["label"] in ("Bus stop", "MRT station", "LRT station") and row["label"] in row["text"]
    alpha = [row for row in rows if row["name"] == "Alpha"][0]
    assert alpha["label"] == "MRT station" and [line["badge"] for line in alpha["lines"]] == ["NS"]
    assert alpha["lines"][0]["text"] == "NS North-South Line"
    beta = [row for row in rows if row["name"] == "Beta"][0]
    assert [line["badge"] for line in beta["lines"]] == ["NS", "EW"]  # every line, the first one rings the tile
    assert "dest-tile--ns" in beta["tileCls"] and "dest-tile--station" in beta["tileCls"]
    gamma = [row for row in rows if row["name"] == "Gamma"][0]
    assert gamma["label"] == "LRT station" and "dest-tile--bp" in gamma["tileCls"]
    bus = rows[0]
    assert bus["label"] == "Bus stop" and bus["lines"] == [] and "dest-tile--bus" in bus["tileCls"]


def test_no_row_says_no_direct_bus_and_every_row_is_listed(narrow_light, wide_dark):
    for run in (narrow_light, wide_dark):
        rows = run["first"]["rows"]
        assert [row["code"] for row in rows] == run["first"]["order"]  # every candidate, in the same order
        for row in rows:
            assert row["note"] is False and "no direct bus" not in row["text"].lower() and "transfer" not in row["text"].lower()


def test_a_station_ring_is_its_line_colour_and_a_bus_ring_is_grey(narrow_light, wide_dark):
    for run, theme in ((narrow_light, "light"), (wide_dark, "dark")):
        tokens = tml._theme(theme)
        rows = {row["name"]: row for row in run["first"]["rows"]}
        bus = [row for row in run["first"]["rows"] if row["kind"] == "bus"][0]
        grey = tml._hex(tokens, "--ring-neutral")
        assert _rgb(grey) in bus["tileRing"] and bus["tileBg"] == _rgb(tml._hex(tokens, "--ring-neutral-tint"))
        for name, code in (("Alpha", "ns"), ("Gamma", "bp")):
            ring = _rgb(tml._hex(tokens, f"--ring-{code}"))
            assert ring in rows[name]["tileRing"] and _rgb(grey) not in rows[name]["tileRing"]
            tint = _mix(tml._hex(tokens, f"--ring-{code}"), tml._hex(tokens, "--color-card"))
            assert all(abs(got - want) <= 1.5 for got, want in zip(_channels(rows[name]["tileBg"]), _channels(_rgb(tint))))
        assert rows["Alpha"]["tileBg"] != bus["tileBg"]  # a tint of the line, not the neutral tile


def _channels(css):
    """The three 0-255 channels of 'rgb(1, 2, 3)' or 'color(srgb 0.1 0.2 0.3)'."""
    numbers = [float(n) for n in re.findall(r"[\d.]+", css)]
    return numbers[:3] if css.startswith("rgb") else [n * 255 for n in numbers[:3]]


def _rgb(hex6):
    return "rgb({}, {}, {})".format(*(int(hex6[i:i + 2], 16) for i in (0, 2, 4)))


def test_a_selected_row_keeps_its_ring_and_its_own_outline(narrow_light):
    after = narrow_light["afterClick"]
    rows = after["rows"]
    chosen = [row for row in rows if row["selected"]]
    assert len(chosen) == 1 and chosen[0]["code"] == "NS5" and after["selectedCode"] == "NS5"
    before = {row["code"]: row for row in narrow_light["first"]["rows"]}
    assert chosen[0]["tileRing"] == before["NS5"]["tileRing"]  # the line ring does not change when selected
    assert chosen[0]["box"]["h"] == before["NS5"]["box"]["h"]  # and nothing changes size
    assert "is-selected" in chosen[0]["cls"] and chosen[0]["pressed"] == "true"


def test_the_map_has_a_marker_for_each_row_with_the_icon_the_ring_and_a_label(narrow_light, wide_dark):
    for run, theme in ((narrow_light, "light"), (wide_dark, "dark")):
        tokens = tml._theme(theme)
        markers = run["first"]["markers"]
        assert len(markers) == len(run["first"]["rows"])
        stations = [m for m in markers if "map-stop--station" in m["cls"]]
        buses = [m for m in markers if "map-stop--bus" in m["cls"]]
        assert stations and buses and all(m["icon"] > 0 for m in markers)
        assert all(m["label"].endswith(" MRT") or m["label"].endswith(" LRT") for m in stations)  # a text label that says what it is
        assert all(not (m["label"].endswith(" MRT") or m["label"].endswith(" LRT")) for m in buses)
        grey = _rgb(tml._hex(tokens, "--ring-neutral"))
        assert all(m["border"] == grey and m["borderWidth"] == "3px" for m in buses)
        ns = [m for m in stations if "map-stop--ring-ns" in m["cls"]]
        assert ns and all(m["border"] == _rgb(tml._hex(tokens, "--ring-ns")) for m in ns)  # the line's own colour


def test_the_selected_marker_has_the_selected_ring_and_the_station_ring_together(narrow_light):
    markers = narrow_light["afterClick"]["markers"]
    chosen = [m for m in markers if m["selected"]]
    assert len(chosen) == 1 and "map-stop--station" in chosen[0]["cls"] and "map-stop--ring-ns" in chosen[0]["cls"]
    assert chosen[0]["border"] == _rgb(tml._hex(tml._theme("light"), "--ring-ns"))  # the line ring stays
    assert _rgb(tml._hex(tml._theme("light"), "--map-selected-ring")) in chosen[0]["shadow"]  # the selected ring sits outside it


@pytest.mark.parametrize("run", ["narrow_light", "wide_dark"])
def test_the_list_fits_at_360_and_1280_in_both_themes(run, request):
    first = request.getfixturevalue(run)["first"]
    assert first["scrollWidth"] <= first["innerWidth"]
    assert all(row["box"]["right"] <= first["innerWidth"] for row in first["rows"])


def test_the_chosen_station_is_the_destination_and_its_point_is_the_planners_end(wide_dark):
    assert wide_dark["afterClick"]["selectedCode"] == "NS9"  # the first code of the group, NS before EW
    assert wide_dark["confirmScreen"]["heading"] == "Destination station"
    assert wide_dark["confirmScreen"]["edit"] == "Edit destination station"
    assert wide_dark["confirmScreen"]["name"] == "Beta"
    confirmed = wide_dark["confirmed"]
    assert confirmed["kind"] == "station" and confirmed["code"] == "NS9"
    request = wide_dark["planRequest"]
    assert "destination_stop_code=NS9" in request  # the station's code in the journey terms
    assert f"end_lat={confirmed['lat']}" in request.replace("%2E", ".") or "end_lat=" in request
    assert "end_lon=" in request and "dest_lat=" in request  # the place is still sent, for the walk from the station


def test_with_no_station_within_600_m_the_nearest_within_1500_m_is_the_only_station(beyond):
    first = beyond["first"]
    stations = [row for row in first["rows"] if row["kind"] == "station"]
    assert [row["name"] for row in stations] == ["Far Away"] and stations[0]["label"] == "MRT station"
    assert re.search(r"\(([89]\d\d)" + NB + "m\\)", stations[0]["meta"])  # about 900 m, past the 600 m radius
    metres = [int(m.group(1)) for row in first["rows"] if (m := re.search(r"\((\d+)" + NB + "m\\)", row["meta"]))]
    assert metres == sorted(metres)


# ---- the overview: the grey outline on bus markers and the bus number badge -------------------------------


def test_the_bus_number_badge_and_both_bus_markers_use_the_grey_outline_token():
    css = CSS.replace("\r\n", "\n")
    assert ".line-badge--bus {\n  border: 2px solid var(--ring-neutral);" in css
    leg = css.split(".journey-step--leg {", 1)[1].split("}", 1)[0]
    assert "--leg-ring: var(--ring-neutral);" in leg  # a bus leg's markers; a rail leg overrides it with its own line colour
    assert 'badge.className = "line-badge line-badge--bus";' in INDEX
    for code in CODES:
        rule = css.split(f".journey-step--rail-{code} {{", 1)[1].split("}", 1)[0]
        assert f"--leg-ring: var(--line-{code});" in rule  # rail markers unchanged


def test_the_overview_bus_markers_are_grey_in_a_browser(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("bus_grey"), onemap=stub.by_mode({"TRANSIT": stub.mixed})) as base:
        result = run_scenario("overviewlegs", base, {"name": "grey", "width": 1280, "height": 900})["result"]
    rows = result["first"]["rows"]
    bus = [row for row in rows if "journey-step--bus" in row["cls"]][0]
    grey = _rgb(tml._hex(tml._theme("light"), "--ring-neutral"))
    assert grey in bus["leg"]["startRing"] and grey in bus["leg"]["endRing"]
    assert bus["badge"]["cls"].endswith("line-badge--bus")
    ns = [row for row in rows if row["badge"] and row["badge"]["text"] == "NS"][0]
    assert grey not in ns["leg"]["startRing"]  # a rail leg keeps its own colour


# ---- the words and the guide --------------------------------------------------------------------------------


def test_the_new_strings_are_in_copy_js_and_the_page_character_for_character():
    stops = COPY.split("destinationStops: {", 1)[1].split("\n  },", 1)[0]
    for key, variable in {"busStop": "DEST_BUS_LABEL", "mrtStation": "DEST_MRT_LABEL", "lrtStation": "DEST_LRT_LABEL"}.items():
        copy_value = re.search(rf'\b{key}: "([^"]*)"', stops).group(1)
        assert re.search(rf'var {variable} = "{re.escape(copy_value)}";', INDEX), key
    confirm = COPY.split("confirmDestination: {", 1)[1].split("\n  },", 1)[0]
    assert 'destinationStation: "Destination station"' in confirm and 'editStation: "Edit destination station"' in confirm
    assert 'var DEST_STATION_HEADING = "Destination station";' in INDEX and 'var DEST_STATION_EDIT = "Edit destination station";' in INDEX


def test_the_style_guide_shows_bus_and_station_rows_and_markers_in_both_themes():
    section = GUIDE.split("function destRow(", 1)[1].split("document.getElementById(\"dest-sample-light\")", 1)[0]
    for needle in ("dest-tile--station", "dest-tile--bus", "stopsCopy.mrtStation", "stopsCopy.lrtStation", "stopsCopy.busStop",
                   "map-stop--ring-", "map-stop--bus", 'mode: "LRT"', 'lines: ["NS", "NE", "CC"]', "dest-stop-row__lines"):
        assert needle in section, needle
    assert 'getElementById("dest-sample-light")' in GUIDE and 'getElementById("dest-sample-dark")' in GUIDE
    assert "line-badge line-badge--bus" in GUIDE


def test_the_plan_describes_the_stations_the_rings_and_the_planner_end():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    for text in ("**Destination stops and stations.**", "Nearby stops and stations", "within 1.5 km",
                 "`--ring-neutral`", "`end_lat` and `end_lon`", "`Destination station`", "`beyond_radius`"):
        assert text in plan, text


def test_a_station_code_as_the_destination_stop_gives_null_ride_terms_not_an_error(monkeypatch):
    _pin_clock(monkeypatch)
    point = end_of("direct_bus")
    monkeypatch.setattr(main, "load_static_data", lambda: lta())
    monkeypatch.setattr(main, "startup_warning", lambda today: None)
    monkeypatch.setattr(main, "load_rail_table", lambda: None)
    with TestClient(main.app) as client:
        response = client.get("/api/journey", params={"dest_lat": point[0], "dest_lon": point[1], "user_lat": 1.3697,
                                                      "user_lon": 103.8486, "destination_stop_code": "NS5"})
    assert response.status_code == 200 and response.json()["ride_minutes"] is None


# ---- the confirm card -------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def confirm_bus(tmp_path_factory):
    from page_runner import DEST
    return _run(tmp_path_factory, "confirm_bus", _page_table(), width=390, click=DEST, confirm=True)


def test_the_confirm_card_has_one_info_message_for_every_destination_and_the_button_says_confirm(wide_dark, confirm_bus):
    one = "We'll find your best route and leave-by time."
    assert wide_dark["confirmScreen"]["info"] == one and confirm_bus["confirmScreen"]["info"] == one  # a station and a bus stop
    assert f'info: "{one}"' in COPY and f'<p id="confirm-info-text" class="alert__text">{one}</p>' in INDEX
    assert "infoStation" not in COPY and "CONFIRM_INFO" not in INDEX
    for old in ("check live bus arrivals", "calculate your catch probability", "Confirm and find buses"):
        assert old not in COPY and old not in INDEX and old not in GUIDE
    assert 'action: "Confirm"' in COPY and "<span>Confirm</span>" in INDEX


def test_the_confirm_row_of_a_station_has_the_train_icon_the_line_ring_and_every_badge(wide_dark):
    card = wide_dark["confirmScreen"]
    assert card["heading"] == "Destination station" and card["name"] == "Beta"
    assert "dest-tile--station" in card["tileCls"] and "dest-tile--ns" in card["tileCls"] and card["tileIsTrain"] is True
    assert _rgb(tml._hex(tml._theme("dark"), "--ring-ns")) in card["tileRing"]  # the first line's colour rings the tile
    assert card["linesShown"] is True and [line["badge"] for line in card["lines"]] == ["NS", "EW"]
    assert card["lines"][0]["text"] == "NS North-South Line" and card["lines"][1]["text"] == "EW East-West Line"


def test_the_confirm_row_of_a_bus_stop_keeps_the_bus_tile_and_shows_no_badges(confirm_bus):
    card = confirm_bus["confirmScreen"]
    assert card["heading"] == "Destination stop" and card["tileIsTrain"] is False and card["tileSvg"] > 0
    assert "dest-tile" not in card["tileCls"] and card["linesShown"] is False and card["lines"] == []


def test_the_style_guide_shows_the_station_confirm_card_with_the_one_info_message():
    section = GUIDE.split("Confirm card for a station", 1)[1].split("</div>\";", 1)[0]
    for needle in ("confirmCopy.destinationStation", "dest-tile--station dest-tile--ns", "DEST_TRAIN_ICON", "confirmCopy.info",
                   'dest-stop-row__lines'):
        assert needle in section, needle
    assert "infoStation" not in GUIDE

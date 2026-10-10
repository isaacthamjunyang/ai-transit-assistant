"""The train timetable: the builder (on a mini GTFS), rail_runs_at, rail_headway_seconds and rail_direction.

Nothing here calls DataMall. The builder tests write a small GTFS into tmp_path."""

import copy
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import build_rail_timetable as builder
import config
import service_hours as sh

SGT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 10)


# ---- a mini GTFS ------------------------------------------------------------------------------------------


def _hms(minutes: float) -> str:
    seconds = int(round(minutes * 60))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def _trip_rows(trip_id: str, minutes: float, codes: list[str], hop: float = 2.0) -> list[str]:
    return [
        f"{trip_id},{_hms(minutes + hop * i)},{_hms(minutes + hop * i)},{code}_A,{i + 1},"
        for i, code in enumerate(codes)
    ]


def make_gtfs(folder: Path) -> Path:
    """Line NS: Far End trips NS1-NS3, Home trips NS3-NS1, short workings "Mid"; line TE with a newer service."""
    folder.mkdir(parents=True, exist_ok=True)
    _csv(folder / "calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date", [
        "SERVICE_WD,1,1,1,1,1,0,0,20260101,20261231",
        "SERVICE_WE,0,0,0,0,0,1,0,20260101,20261231",
        "SERVICE_PH,0,0,0,0,0,0,1,20260101,20261231",
        "SERVICE_WD_NEW,1,1,1,1,1,0,0,20260705,20261231",
        "SERVICE_WD_20261009,1,1,1,1,1,0,0,20261009,20261009",
    ])
    _csv(folder / "feed_info.txt", "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version", [
        "Land Transport Authority,https://www.lta.gov.sg/,en,20250101,20261231,0.1"])
    _csv(folder / "routes.txt", "route_id,agency_id,route_short_name,route_long_name,route_type,route_color,route_text_color", [
        "R1,SMRT,NS,North-South Line,1,d62821,FFFFFF",
        "R2,SMRT,NS,North-South Line,1,d62821,FFFFFF",
        "R3,SMRT,TE,Thomson-East Coast Line,1,9D5A25,FFFFFF",
        "R4,SMRT,BP,Bukit Panjang LRT,0,6E8270,FFFFFF",
    ])
    _csv(folder / "stops.txt", "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,platform_code,parent_station", [
        "NS1,NS1,Alpha,1.30,103.80,1,,",
        "NS1_A,NS1,Alpha,1.30,103.80,0,A,",
        "NS1_EA,NS1,A,1.30,103.80,2,,NS1",
        "NS2_A,NS2,Beta,1.31,103.81,0,A,XX2",
        "NS3_A,NS3,Gamma,1.32,103.82,0,A,",
        "TE1_A,TE1,Delta,1.40,103.90,0,A,",
        "TE2_A,TE2,Echo,1.41,103.91,0,A,",
        "BP1_A,BP1,Foxtrot,1.50,104.00,0,A,",
        "BP2_A,BP2,Golf,1.51,104.01,0,A,",
    ])
    trips, times = [], []

    def add(trip_id, route, service, headsign, direction, minutes, codes):
        trips.append(f"{route},{service},{trip_id},{headsign},{direction},")
        times.extend(_trip_rows(trip_id, minutes, codes))

    far, home = ["NS1", "NS2", "NS3"], ["NS3", "NS2", "NS1"]
    for i in range(21):  # weekday 05:30 to 07:30 every 6 minutes
        add(f"wd{i}", "R1", "SERVICE_WD", "Far End", 0, 330 + 6 * i, far)
    add("wd_late", "R1", "SERVICE_WD", "Far End", 0, 24 * 60 + 14.5, far)  # 24:14:30 is past midnight
    add("wd_mid_early", "R2", "SERVICE_WD", "Mid", 0, 300, ["NS1", "NS2"])  # a short working before the first train
    add("wd_mid_late", "R2", "SERVICE_WD", "Mid", 0, 24 * 60 + 59, ["NS1", "NS2"])  # ...and after the last
    for i in range(20):
        add(f"wdh{i}", "R1", "SERVICE_WD", "Home", 1, 345 + 10 * i, home)
    for i in range(10):  # a one-day service that must be ignored
        add(f"special{i}", "R1", "SERVICE_WD_20261009", "Far End", 0, 180 + 6 * i, far)
    for i in range(10):  # Saturday 06:00 to 07:30 every 10 minutes
        add(f"we{i}", "R1", "SERVICE_WE", "Far End", 0, 360 + 10 * i, far)
    for i in range(5):  # Sunday, the last departs at exactly 22:00
        add(f"ph{i}", "R1", "SERVICE_PH", "Far End", 0, 480 + 210 * i, far)  # 08:00, 11:30, 15:00, 18:30, 22:00
    for i in range(5):  # TE: the old weekday service and the newer one that replaces it
        add(f"te_old{i}", "R3", "SERVICE_WD", "Echo Far", 0, 600 + 10 * i, ["TE1", "TE2"])
        add(f"te_new{i}", "R3", "SERVICE_WD_NEW", "Echo Far", 0, 700 + 10 * i, ["TE1", "TE2"])
    for i in range(4):
        add(f"bp{i}", "R4", "SERVICE_WD", "Loop A", 0, 600 + 15 * i, ["BP1", "BP2"])
    _csv(folder / "trips.txt", "route_id,service_id,trip_id,trip_headsign,direction_id,block_id", trips)
    _csv(folder / "stop_times.txt", "trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign", times)
    return folder


@pytest.fixture(scope="module")
def feed(tmp_path_factory):
    return make_gtfs(tmp_path_factory.mktemp("gtfs"))


@pytest.fixture(scope="module")
def table(feed):
    return builder.build_table(feed, TODAY)


def _day(table, code, headsign, day):
    return table["stations"][code]["directions"][headsign][day]


# ---- the builder ------------------------------------------------------------------------------------------


def test_lines_carry_the_name_the_mode_and_the_official_colours(table):
    assert table["lines"]["NS"] == {"name": "North-South Line", "mode": "SUBWAY", "color": "D62821", "text_color": "FFFFFF"}
    assert table["lines"]["BP"]["mode"] == "TRAM"  # an LRT, as OneMap names it
    assert set(table["lines"]) == {"NS", "TE", "BP"}


def test_first_and_last_train_keep_times_past_midnight(table):
    weekday = _day(table, "NS1", "Far End", "WD")
    assert weekday["first"] == "0530"
    assert weekday["last"] == "2415"  # 24:14:30 rounds up to the minute and stays past 24:00


def test_short_workings_count_for_nothing(table):
    weekday = _day(table, "NS1", "Far End", "WD")
    assert weekday["first"] != "0500" and weekday["last"] != "2459"  # the "Mid" trips at 05:00 and 24:59
    assert "Mid" not in table["stations"]["NS1"]["directions"]
    assert "Mid" not in table["patterns"]["NS"]


def test_day_types_come_from_the_calendar_and_one_day_services_are_ignored(table):
    assert _day(table, "NS1", "Far End", "SAT")["first"] == "0600"
    sunday = _day(table, "NS1", "Far End", "SUN")
    assert (sunday["first"], sunday["last"]) == ("0800", "2200")
    assert "SERVICE_WD_20261009" not in table["feed"]["services"]
    assert _day(table, "NS1", "Far End", "WD")["first"] != "0300"  # the one-day service started at 03:00


def test_the_newer_service_replaces_the_older_one_for_a_line(table):
    assert _day(table, "TE1", "Echo Far", "WD")["first"] == "1140"  # the new service, 11:40, not the old 10:00
    assert "SERVICE_WD_NEW" in table["feed"]["services"] and "SERVICE_WD" in table["feed"]["services"]


def test_headway_is_the_median_gap_by_departure_hour_and_breaks_are_left_out(table):
    headway = _day(table, "NS1", "Far End", "WD")["headway_s"]
    assert headway["5"] == 360 and headway["6"] == 360 and headway["7"] == 360
    assert "24" not in headway  # one lone departure after a long break has no gap
    assert all(seconds <= builder.MAX_HEADWAY_S for seconds in headway.values())
    assert _day(table, "NS1", "Far End", "SAT")["headway_s"]["6"] == 600


def test_a_train_cannot_be_boarded_at_the_end_of_its_trip(table):
    assert "Far End" in table["stations"]["NS1"]["directions"] and "Home" not in table["stations"]["NS1"]["directions"]
    assert "Home" in table["stations"]["NS3"]["directions"] and "Far End" not in table["stations"]["NS3"]["directions"]
    assert set(table["stations"]["NS2"]["directions"]) == {"Far End", "Home"}


def test_a_terminus_is_listed_without_a_direction_of_its_own(table):
    for code in ("TE2", "BP2"):  # the trips of their headsign end there, so nobody boards that headsign there
        assert table["stations"][code]["directions"] == {} and table["stations"][code]["name"]
    stray = copy.deepcopy(table)
    stray["stations"]["ZZ9"] = {"name": "Stray", "directions": {}}
    assert any("ZZ9 has no direction" in problem for problem in _valid(stray))


def test_patterns_list_the_stations_in_travel_order(table):
    assert table["patterns"]["NS"] == {"Far End": ["NS1", "NS2", "NS3"], "Home": ["NS3", "NS2", "NS1"]}


def test_station_names_points_and_interchange(table):
    assert table["stations"]["NS1"]["name"] == "Alpha"  # the station row, not the entrance "A"
    assert (table["stations"]["NS1"]["latitude"], table["stations"]["NS1"]["longitude"]) == (1.3, 103.8)
    assert table["stations"]["NS2"]["interchange"] == "XX2"
    assert table["stations"]["NS3"]["interchange"] is None
    row = table["stations"]["NS1"]["directions"]["Far End"]
    assert (row["line"], row["direction_id"]) == ("NS", 0) and row["trips"] > 0


def test_the_build_date_and_the_feed_dates_are_recorded(table):
    assert table["built"] == "2026-10-10" and table["schema"] == 1
    assert (table["feed"]["start_date"], table["feed"]["end_date"], table["feed"]["version"]) == ("20250101", "20261231", "0.1")
    assert table["source"] == "LTA DataMall GTFS Schedule (Train)"


def test_the_same_feed_gives_the_same_bytes(feed, tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for out in (first, second):
        builder.write_table(builder.build_table(feed, TODAY), out, TODAY, min_stations=3, required_lines=("NS",))
    assert first.read_bytes() == second.read_bytes()


def test_a_zip_gives_the_same_table_as_the_folder(feed, tmp_path):
    archive = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in feed.glob("*.txt"):
            handle.write(path, path.name)
    assert builder.build_table(archive, TODAY) == builder.build_table(feed, TODAY)


def test_an_expired_feed_is_refused_unless_allowed(feed):
    with pytest.raises(builder.BuildError, match="ended on 20261231"):
        builder.build_table(feed, date(2027, 1, 5))
    assert builder.build_table(feed, date(2027, 1, 5), allow_expired=True)["built"] == "2027-01-05"


def test_a_missing_file_is_a_build_error(feed, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    for path in feed.glob("*.txt"):
        if path.name != "stop_times.txt":
            (broken / path.name).write_bytes(path.read_bytes())
    with pytest.raises(builder.BuildError, match="stop_times.txt"):
        builder.build_table(broken, TODAY)


# ---- validation, temp file, backup ------------------------------------------------------------------------


def _valid(table):
    return builder.validate_table(table, TODAY, required_lines=("NS", "TE", "BP"), min_stations=7)


def test_a_good_table_has_no_problems(table):
    assert _valid(table) == []


@pytest.mark.parametrize("change, expect", [
    (lambda t: t.update(schema=2), "schema"),
    (lambda t: t.pop("patterns"), "missing key patterns"),
    (lambda t: t["lines"].pop("BP"), "line BP is missing"),
    (lambda t: t["lines"]["NS"].update(color="D6"), "official colours"),
    (lambda t: [t["stations"].pop(k) for k in ("NS1", "NS2")], "stations"),
    (lambda t: t["stations"]["NS1"]["directions"]["Far End"]["WD"].update(first="24:14"), "not HHMM"),
    (lambda t: t["stations"]["NS1"]["directions"]["Far End"]["WD"].update(last="2460"), "not HHMM"),
    (lambda t: t["stations"]["NS1"]["directions"]["Far End"]["WD"].update(last="0500", first="0530"), "before first"),
    (lambda t: t["stations"]["NS1"]["directions"]["Far End"]["WD"]["headway_s"].update({"5": 0}), "headway"),
    (lambda t: t["stations"]["NS1"]["directions"]["Far End"]["WD"]["headway_s"].update({"6": 99999}), "headway"),
    (lambda t: t["stations"]["NS1"]["directions"]["Far End"].update(line="ZZ"), "unknown line"),
    (lambda t: [t["stations"]["NS1"]["directions"]["Far End"].pop(d) for d in ("WD", "SAT", "SUN")], "no day type"),
    (lambda t: t["patterns"]["NS"].update({"Far End": ["NS1", "NS99"]}), "unknown stations"),
    (lambda t: t["feed"].update(end_date="20260101"), "ended"),
    (lambda t: t.update(built="yesterday"), "not a date"),
])
def test_validation_catches_each_kind_of_bad_table(table, change, expect):
    bad = copy.deepcopy(table)
    change(bad)
    problems = _valid(bad)
    assert problems and any(expect in problem for problem in problems), problems


def test_write_replaces_atomically_and_keeps_a_backup(feed, tmp_path):
    out = tmp_path / "cache" / "rail_timetable.json"
    limits = {"min_stations": 3, "required_lines": ("NS",)}
    builder.write_table(builder.build_table(feed, date(2026, 10, 9)), out, date(2026, 10, 9), **limits)
    assert out.exists() and not list(out.parent.glob("*.tmp")) and not out.with_name(out.name + ".bak").exists()
    first = out.read_bytes()
    builder.write_table(builder.build_table(feed, TODAY), out, TODAY, **limits)
    backup = out.with_name(out.name + ".bak")
    assert backup.read_bytes() == first and json.loads(out.read_text())["built"] == "2026-10-10"
    assert not list(out.parent.glob("*.tmp"))


def test_a_table_that_fails_validation_never_replaces_the_old_one(feed, tmp_path):
    out = tmp_path / "rail_timetable.json"
    good = builder.build_table(feed, TODAY)
    builder.write_table(good, out, TODAY, min_stations=3, required_lines=("NS",))
    before = out.read_bytes()
    bad = copy.deepcopy(good)
    bad["stations"]["NS1"]["directions"]["Far End"]["WD"]["first"] = "oops"
    with pytest.raises(builder.BuildError, match="not usable"):
        builder.write_table(bad, out, TODAY, min_stations=3, required_lines=("NS",))
    assert out.read_bytes() == before and not list(tmp_path.glob("*.tmp"))
    assert not out.with_name(out.name + ".bak").exists()  # the failed run did not even touch the backup


def test_the_command_line_writes_the_table_and_reports_its_size(feed, tmp_path, capsys):
    out = tmp_path / "t.json"
    code = builder.main([str(feed), "--out", str(out), "--today", "2026-10-10", "--min-stations", "3",
                         "--required-lines", "NS,TE,BP"])
    assert code == 0 and json.loads(out.read_text())["built"] == "2026-10-10"
    report = capsys.readouterr().out
    assert "7 stations, 6 directions" in report and "KB" in report and "built 2026-10-10" in report


def test_the_command_line_refuses_a_feed_that_is_too_small_and_a_missing_path(feed, tmp_path, capsys):
    out = tmp_path / "t.json"
    assert builder.main([str(feed), "--out", str(out), "--today", "2026-10-10"]) == 1  # default floors: 150 stations
    assert not out.exists() and "Not written" in capsys.readouterr().out
    assert builder.main([str(tmp_path / "nowhere"), "--out", str(out)]) == 1
    assert "makes no network call" in capsys.readouterr().out


def test_the_builder_never_touches_the_network_or_a_key():
    source = (ROOT / "build_rail_timetable.py").read_text(encoding="utf-8")
    for word in ("httpx", "requests", "urllib", "AccountKey", "LTA_ACCOUNT_KEY", "socket"):
        assert word not in source.replace("no network call", "")


# ---- rail_runs_at -----------------------------------------------------------------------------------------


def _entry(first, last, headway=None):
    return {"first": first, "last": last, "headway_s": headway or {}}


def hand_table():
    return {
        "schema": 1,
        "stations": {
            "NS17": {"directions": {
                "Marina South Pier": {"line": "NS", "direction_id": 1, "trips": 100,
                                      "WD": _entry("0548", "2415", {"5": 360, "7": 120, "8": 120, "24": 480}),
                                      "SAT": _entry("0543", "2335", {"8": 300}),
                                      "SUN": _entry("0608", "2335")},
                "Jurong East": {"line": "NS", "direction_id": 0, "trips": 90, "WD": _entry("0608", "2415", {"8": 150})},
            }},
            "NS18": {"directions": {"Empty": {"line": "NS", "direction_id": 1, "trips": 1}}},
        },
        "patterns": {"NS": {}},
    }


def at(y, m, d, hh, mm, tz=SGT):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


MSP = "Marina South Pier"


@pytest.fixture(autouse=True)
def _reset_counter():
    sh.reset_missing_rail_hours_count()
    yield


def test_first_train_boundary_has_no_margin_before_it():
    table = hand_table()
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 12, 5, 47))
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 12, 5, 48))
    assert sh.missing_rail_hours_count() == 0


def test_last_train_has_a_five_minute_grace_and_crosses_midnight():
    table = hand_table()
    # Monday's last train is 24:15 = Tuesday 00:15; 00:20 is the last allowed minute
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 12, 23, 59))
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 13, 0, 20))
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 13, 0, 21))
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 13, 3, 0))


def test_a_window_that_began_the_day_before_uses_that_days_type():
    table = hand_table()
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 17, 0, 10))  # Saturday 00:10 is Friday's WD window
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 18, 0, 10))  # Sunday 00:10: Saturday ended 23:35 (+5)
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 17, 23, 40))  # Saturday's own grace edge
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 17, 23, 41))


def test_saturday_and_sunday_use_their_own_first_train():
    table = hand_table()
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 17, 5, 42)) and sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 17, 5, 43))
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 18, 6, 7)) and sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 18, 6, 8))


def test_a_public_holiday_on_a_weekday_uses_the_sunday_row():
    table = hand_table()
    holiday = date(2026, 11, 9)  # Monday, in PUBLIC_HOLIDAYS
    assert holiday in config.PUBLIC_HOLIDAYS and holiday.weekday() == 0
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 11, 9, 5, 50))  # a normal Monday would run (05:48)
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 11, 9, 6, 8))
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 11, 9, 23, 40))
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 11, 10, 0, 10))  # the holiday window ended; Tuesday is not on yet
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 11, 10, 5, 48))
    assert sh.missing_rail_hours_count() == 0


def test_direction_can_be_a_headsign_any_case_a_direction_id_or_none():
    table = hand_table()
    when = at(2026, 10, 12, 5, 50)  # Jurong East starts at 06:08
    assert sh.rail_runs_at(table, "NS17", "marina south pier", when)
    assert not sh.rail_runs_at(table, "NS17", "Jurong East", when)
    assert sh.rail_runs_at(table, "NS17", 1, when) and not sh.rail_runs_at(table, "NS17", 0, when)
    assert sh.rail_runs_at(table, "NS17", None, when)  # any direction: Marina South Pier is running
    assert sh.rail_runs_at(table, "NS17", None, at(2026, 10, 12, 5, 0)) is False
    assert sh.missing_rail_hours_count() == 0


def test_a_direction_with_no_service_that_day_type_is_not_running_and_not_missing():
    table = hand_table()
    assert not sh.rail_runs_at(table, "NS17", "Jurong East", at(2026, 10, 18, 10, 0))  # Jurong East has no SUN row
    assert sh.missing_rail_hours_count() == 0


@pytest.mark.parametrize("table_, station, direction", [
    (hand_table(), "NS99", MSP),           # no such station
    (hand_table(), "NS17", "Nowhere"),     # no such direction
    (hand_table(), "NS18", "Empty"),       # a row with no day type
    (hand_table(), "NS17", 7),             # no such direction id
    (None, "NS17", MSP),                   # no table at all
    ({}, "NS17", MSP),
])
def test_a_missing_row_stays_eligible_and_is_counted(table_, station, direction):
    assert sh.rail_runs_at(table_, station, direction, at(2026, 10, 12, 3, 0)) is True
    assert sh.missing_rail_hours_count() == 1


def test_times_are_read_in_singapore_time():
    table = hand_table()
    utc = timezone.utc
    assert sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 11, 21, 48, utc))  # 05:48 on the 12th in Singapore
    assert not sh.rail_runs_at(table, "NS17", MSP, at(2026, 10, 11, 21, 47, utc))
    assert sh.rail_runs_at(table, "NS17", MSP, datetime(2026, 10, 12, 5, 48))  # a naive time is Singapore time


# ---- rail_headway_seconds ---------------------------------------------------------------------------------


def test_the_headway_comes_from_the_table_for_the_departure_hour():
    table = hand_table()
    assert sh.rail_headway_seconds(table, "NS17", MSP, at(2026, 10, 12, 8, 10)) == 120
    assert sh.rail_headway_seconds(table, "NS17", MSP, at(2026, 10, 12, 5, 59)) == 360
    assert sh.rail_headway_seconds(table, "NS17", MSP, at(2026, 10, 17, 8, 10)) == 300  # Saturday's own figure
    assert sh.rail_headway_seconds(table, "NS17", None, at(2026, 10, 12, 8, 10)) == 120  # the shortest of the two


def test_after_midnight_the_hour_belongs_to_yesterdays_timetable():
    table = hand_table()
    assert sh.rail_headway_seconds(table, "NS17", MSP, at(2026, 10, 13, 0, 10)) == 480  # Monday's hour 24
    assert sh.rail_headway_seconds(table, "NS17", MSP, at(2026, 10, 13, 1, 10)) == 420  # hour 25: no figure, off-peak


def test_the_fallback_is_300_s_in_the_weekday_peak_hours_and_420_s_otherwise():
    assert (config.RAIL_HEADWAY_PEAK_S, config.RAIL_HEADWAY_OFFPEAK_S) == (300, 420)
    assert config.RAIL_PEAK_HOURS == (7, 8, 17, 18, 19)
    for hh, mm, expect in [(6, 59, 420), (7, 0, 300), (8, 59, 300), (9, 0, 420), (12, 0, 420),
                           (16, 59, 420), (17, 0, 300), (19, 59, 300), (20, 0, 420), (23, 0, 420)]:
        assert sh.rail_headway_seconds(None, "NS17", MSP, at(2026, 10, 12, hh, mm)) == expect, (hh, mm)


def test_the_fallback_is_off_peak_on_weekends_and_holidays_and_when_the_figure_is_missing():
    assert sh.rail_headway_seconds(None, "NS17", MSP, at(2026, 10, 17, 8, 0)) == 420  # Saturday
    assert sh.rail_headway_seconds(None, "NS17", MSP, at(2026, 10, 18, 18, 0)) == 420  # Sunday
    assert sh.rail_headway_seconds(None, "NS17", MSP, at(2026, 11, 9, 8, 0)) == 420  # weekday holiday
    table = hand_table()
    assert sh.rail_headway_seconds(table, "NS17", MSP, at(2026, 10, 12, 18, 0)) == 300  # hour 18: none, peak
    assert sh.rail_headway_seconds(table, "NS17", MSP, at(2026, 10, 12, 11, 0)) == 420
    assert sh.rail_headway_seconds(table, "NS99", MSP, at(2026, 10, 12, 8, 0)) == 300  # unknown station
    assert sh.rail_headway_seconds(table, "NS17", "Nowhere", at(2026, 10, 12, 8, 0)) == 300


def test_the_headway_does_not_count_as_a_missing_hours_check():
    sh.rail_headway_seconds(None, "NS17", MSP, at(2026, 10, 12, 8, 0))
    assert sh.missing_rail_hours_count() == 0


# ---- rail_direction ---------------------------------------------------------------------------------------


def direction_table():
    def station(code, **trips):
        return {"directions": {h: {"line": "NS", "direction_id": 0 if h == "Jurong East" else 1, "trips": n}
                               for h, n in trips.items()}}
    return {
        "stations": {c: station(c, **{"Marina South Pier": 50, "Jurong East": 40}) for c in ("NS1", "NS2", "NS3", "NS4")},
        "patterns": {"NS": {"Marina South Pier": ["NS1", "NS2", "NS3", "NS4"],
                            "Jurong East": ["NS4", "NS3", "NS2", "NS1"]}},
    }


def test_the_direction_of_a_ride_follows_the_station_order():
    table = direction_table()
    assert sh.rail_direction(table, "NS", "NS2", "NS4") == ("Marina South Pier", 1)
    assert sh.rail_direction(table, "NS", "NS4", "NS2") == ("Jurong East", 0)
    assert sh.rail_direction(table, "NS", "NS1", "NS2") == ("Marina South Pier", 1)


@pytest.mark.parametrize("args", [
    ("NS", "NS2", "NS2"), ("NS", "NS2", "NS99"), ("NS", "NS99", "NS2"), ("XX", "NS1", "NS2"), ("", "NS1", "NS2"),
    ("NS", "", "NS2"), ("NS", "NS1", ""),
])
def test_an_unknown_ride_has_no_direction(args):
    assert sh.rail_direction(direction_table(), *args) is None


def test_no_table_or_no_patterns_has_no_direction():
    assert sh.rail_direction(None, "NS", "NS1", "NS2") is None
    assert sh.rail_direction({"stations": {}}, "NS", "NS1", "NS2") is None


def test_when_two_patterns_fit_the_busier_headsign_wins_then_the_name():
    table = direction_table()
    table["patterns"]["NS"]["Short"] = ["NS1", "NS2"]
    table["stations"]["NS1"]["directions"]["Short"] = {"line": "NS", "direction_id": 1, "trips": 99}
    assert sh.rail_direction(table, "NS", "NS1", "NS2") == ("Short", 1)  # 99 trips beat 50
    table["stations"]["NS1"]["directions"]["Short"]["trips"] = 50
    assert sh.rail_direction(table, "NS", "NS1", "NS2") == ("Marina South Pier", 1)  # tie: alphabetical


def test_a_loop_station_listed_twice_still_orders_the_ride():
    table = {"stations": {}, "patterns": {"BP": {"Loop": ["A", "B", "C", "A"]}}}
    assert sh.rail_direction(table, "BP", "A", "B") == ("Loop", 0)
    assert sh.rail_direction(table, "BP", "B", "A") == ("Loop", 0)  # B comes before the second A


# ---- the table in pt_route --------------------------------------------------------------------------------


def test_a_rail_leg_gets_its_headsign_from_the_table_and_none_without_one():
    import pt_route

    payload = json.loads((ROOT / "tests" / "fixtures" / "pt_mrt_only.json").read_text(encoding="utf-8"))
    start, end = payload["plan"]["from"], payload["plan"]["to"]
    origin = pt_route.Place("stop", "", "", start["lat"], start["lon"])
    destination = pt_route.Place("place", "", "", end["lat"], end["lon"])
    table = {
        "stations": {}, "patterns": {"NS": {"Marina South Pier": ["NS16", "NS17", "NS18", "NS22", "NS28"],
                                            "Jurong East": ["NS28", "NS22", "NS17", "NS16"]}},
    }
    rail = pt_route.parse_response(200, payload, origin, destination, None, table)["itineraries"][0]["legs"][1]
    assert (rail["boarding_stop_code"], rail["alighting_stop_code"]) == ("NS17", "NS22")
    assert (rail["headsign"], rail["direction"]) == ("Marina South Pier", 0)  # no row for NS17: direction id 0
    bare = pt_route.parse_response(200, payload, origin, destination, None)["itineraries"][0]["legs"][1]
    assert bare["headsign"] is None and bare["direction"] is None
    unknown = pt_route.parse_response(200, payload, origin, destination, None, {"patterns": {"EW": {}}})
    assert unknown["itineraries"][0]["legs"][1]["headsign"] is None


def test_the_router_passes_the_table_to_the_parser():
    import httpx
    import pt_route

    payload = json.loads((ROOT / "tests" / "fixtures" / "pt_mrt_only.json").read_text(encoding="utf-8"))
    start, end = payload["plan"]["from"], payload["plan"]["to"]
    table = {"stations": {}, "patterns": {"NS": {"Marina South Pier": ["NS17", "NS22"]}}}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        result = pt_route.PtRouter().route(
            pt_route.Place("stop", "", "", start["lat"], start["lon"]), pt_route.Place("place", "", "", end["lat"], end["lon"]),
            datetime(2026, 10, 12, 8, 30, tzinfo=SGT), session=pt_route.OneMapSession(), client=client,
            budget=pt_route.CallBudget.single(), rail_table=table, token="t", now=1.0)
    assert result["itineraries"][0]["legs"][1]["headsign"] == "Marina South Pier"


# ---- the real table (skipped when it has not been built) --------------------------------------------------

REAL = sh.load_rail_table(ROOT / "cache")
needs_table = pytest.mark.skipif(REAL is None, reason="run build_rail_timetable.py first")


@needs_table
def test_the_real_table_names_the_directions_of_the_measured_rides():
    for line, a, b, expect in [("NS", "NS17", "NS22", "Marina South Pier"), ("NS", "NS22", "NS17", "Jurong East"),
                               ("EW", "EW27", "EW14", "Pasir Ris"), ("EW", "EW21", "EW24", "Tuas Link"),
                               ("NS", "NS26", "NS22", "Jurong East"), ("DT", "DT1", "DT19", "Expo")]:
        assert sh.rail_direction(REAL, line, a, b)[0] == expect, (line, a, b)
    assert sh.rail_direction(REAL, "SS", "S1", "S3") is None  # Sentosa Express is not in the LTA feed


@needs_table
def test_the_real_table_matches_the_published_bishan_figures():
    row = REAL["stations"]["NS17"]["directions"]["Marina South Pier"]
    assert row["WD"]["first"] == "0548" and row["WD"]["last"] in ("2334", "2335")
    assert sh.rail_runs_at(REAL, "NS17", MSP, at(2026, 10, 12, 8, 30)) and not sh.rail_runs_at(REAL, "NS17", MSP, at(2026, 10, 12, 4, 0))
    assert 90 <= sh.rail_headway_seconds(REAL, "NS17", MSP, at(2026, 10, 12, 8, 10)) <= 300
    assert REAL["lines"]["NS"]["color"] == "D62821" and REAL["lines"]["CC"]["text_color"] == "000000"
    assert set(builder.REQUIRED_LINES) <= set(REAL["lines"])

"""Holiday list use, GET /api/data-status, the menu lines and the startup warning."""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import main
import service_hours
from lta_static import StopAndRouteCache
from service_hours import bus_data_date, service_runs_at, startup_warning

ROOT = Path(__file__).resolve().parents[1]
SGT = timezone(timedelta(hours=8))
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")


def _row():
    return StopAndRouteCache([], [{
        "ServiceNo": "36", "Direction": 1, "StopSequence": 1, "BusStopCode": "B", "Distance": 1.0,
        "WD_FirstBus": "0500", "WD_LastBus": "2300", "SAT_FirstBus": "0600", "SAT_LastBus": "2330",
        "SUN_FirstBus": "0900", "SUN_LastBus": "2100",
    }], [])


def _at(day, hhmm):
    return datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[2:]), tzinfo=SGT)


# ---- the holiday list

def test_config_imports_and_the_year_is_the_newest_year_in_the_list():
    assert isinstance(config.PUBLIC_HOLIDAYS, frozenset) and config.PUBLIC_HOLIDAYS
    assert all(isinstance(d, date) for d in config.PUBLIC_HOLIDAYS)
    assert config.PUBLIC_HOLIDAYS_YEAR == max(d.year for d in config.PUBLIC_HOLIDAYS) == 2027
    assert service_hours.PUBLIC_HOLIDAYS is config.PUBLIC_HOLIDAYS


@pytest.mark.parametrize("holiday", [date(2027, 2, 8), date(2026, 11, 9), date(2027, 3, 10)])
def test_a_listed_weekday_holiday_uses_the_sunday_window_and_the_next_day_does_not(holiday):
    assert holiday in config.PUBLIC_HOLIDAYS and holiday.weekday() < 5
    cache = _row()
    assert not service_runs_at(cache, "36", "B", _at(holiday, "0800"))  # Sunday first bus is 0900
    assert service_runs_at(cache, "36", "B", _at(holiday, "0900"))
    after = holiday + timedelta(days=1)
    if after not in config.PUBLIC_HOLIDAYS and after.weekday() < 5:
        assert service_runs_at(cache, "36", "B", _at(after, "0800"))  # a normal weekday: first bus 0500


def test_8_feb_2027_is_in_the_list_and_9_feb_is_a_normal_weekday():
    assert date(2027, 2, 8) in config.PUBLIC_HOLIDAYS and date(2027, 2, 9) not in config.PUBLIC_HOLIDAYS
    assert service_hours.day_type(date(2027, 2, 8)) == "SUN" and service_hours.day_type(date(2027, 2, 9)) == "WD"


# ---- the endpoint

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "load_static_data", lambda: StopAndRouteCache([], [], []))
    monkeypatch.setattr(main, "startup_warning", lambda today: None)
    with TestClient(main.app) as c:
        yield c


def _write_routes(directory: Path, when: datetime) -> None:
    path = directory / "bus_routes.json"
    path.write_text("[]", encoding="utf-8")
    os.utime(path, (when.timestamp(), when.timestamp()))


def test_the_endpoint_shape_and_the_singapore_date(client, tmp_path, monkeypatch):
    monkeypatch.setattr(service_hours, "CACHE_DIR", tmp_path)
    _write_routes(tmp_path, datetime(2026, 9, 29, 0, 30, tzinfo=SGT))  # still 28 Sep in UTC
    response = client.get("/api/data-status")
    assert response.status_code == 200
    assert response.json() == {"holidays_year": 2027, "bus_data_date": "2026-09-29", "rail_data_date": None}


def test_the_endpoint_reports_the_build_date_recorded_in_the_train_timetable(client, tmp_path, monkeypatch):
    monkeypatch.setattr(service_hours, "CACHE_DIR", tmp_path)
    (tmp_path / "rail_timetable.json").write_text(
        json.dumps({"schema": 1, "built": "2026-10-10", "stations": {}}), encoding="utf-8")
    body = client.get("/api/data-status").json()
    assert body["rail_data_date"] == "2026-10-10" and body["bus_data_date"] is None


def test_the_endpoint_returns_null_when_the_file_is_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(service_hours, "CACHE_DIR", tmp_path)
    body = client.get("/api/data-status").json()
    assert body == {"holidays_year": 2027, "bus_data_date": None, "rail_data_date": None}
    assert bus_data_date(tmp_path) is None and service_hours.rail_data_date(tmp_path) is None


@pytest.mark.parametrize("text", [
    "", "not json", "[]", '{"schema": 2, "built": "2026-10-10", "stations": {}}',
    '{"schema": 1, "built": "10 Oct", "stations": {}}', '{"schema": 1, "built": 5, "stations": {}}',
    '{"schema": 1, "built": "2026-10-10"}',
])
def test_an_unreadable_or_wrong_train_timetable_gives_a_null_date(tmp_path, text):
    (tmp_path / "rail_timetable.json").write_text(text, encoding="utf-8")
    assert service_hours.rail_data_date(tmp_path) is None


def test_the_endpoint_takes_no_input_and_returns_no_place(client):
    body = client.get("/api/data-status", params={"lat": "1.3", "lon": "103.8"}).json()
    assert set(body) == {"holidays_year", "bus_data_date", "rail_data_date"}
    assert body["bus_data_date"] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["bus_data_date"])
    assert body["rail_data_date"] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["rail_data_date"])


# ---- the startup warning

def test_no_warning_when_the_data_is_fresh_and_the_year_is_covered(tmp_path):
    _write_routes(tmp_path, datetime(2026, 9, 1, 12, 0, tzinfo=SGT))
    assert startup_warning(date(2026, 9, 30), tmp_path) is None  # 29 days


def test_the_age_limit_is_more_than_30_days(tmp_path):
    _write_routes(tmp_path, datetime(2026, 9, 1, 12, 0, tzinfo=SGT))
    assert startup_warning(date(2026, 10, 1), tmp_path) is None  # exactly 30 days
    warning = startup_warning(date(2026, 10, 2), tmp_path)  # 31 days
    assert warning and "31 days old" in warning and "2026-09-01" in warning


def test_a_year_past_the_holiday_list_warns(tmp_path):
    _write_routes(tmp_path, datetime(2028, 1, 2, 12, 0, tzinfo=SGT))
    warning = startup_warning(date(2028, 1, 3), tmp_path)
    assert warning and "ends in 2027" in warning and "now 2028" in warning
    assert startup_warning(date(2027, 12, 31), tmp_path) is None


def test_both_problems_make_one_sentence_and_a_missing_file_is_not_an_age_warning(tmp_path):
    _write_routes(tmp_path, datetime(2027, 6, 1, 12, 0, tzinfo=SGT))
    both = startup_warning(date(2028, 2, 1), tmp_path)
    assert both.count("Out of date:") == 1 and "days old" in both and "ends in 2027" in both
    empty = tmp_path / "none"
    empty.mkdir()
    assert startup_warning(date(2026, 10, 1), empty) is None


def test_startup_logs_one_warning_and_no_coordinates(monkeypatch, caplog):
    monkeypatch.setattr(main, "load_static_data", lambda: StopAndRouteCache([], [], []))
    monkeypatch.setattr(main, "startup_warning", lambda today: "Out of date: the bus data is 40 days old (written 2026-08-20).")
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        with TestClient(main.app):
            pass
    lines = [r.getMessage() for r in caplog.records if "Out of date" in r.getMessage()]
    assert len(lines) == 1 and not re.search(r"\d+\.\d{3,}", lines[0])


def test_startup_logs_nothing_when_there_is_no_problem(monkeypatch, caplog):
    monkeypatch.setattr(main, "load_static_data", lambda: StopAndRouteCache([], [], []))
    monkeypatch.setattr(main, "startup_warning", lambda today: None)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        with TestClient(main.app):
            pass
    assert not [r for r in caplog.records if "Out of date" in r.getMessage()]


# ---- the menu lines

def test_the_menu_has_the_two_lines_fetched_once_with_the_exact_text():
    assert 'id="menu-data-holidays"' in INDEX and 'id="menu-data-bus"' in INDEX
    for text in ('"Public holidays updated to "', '"Bus data updated "', '"Bus data date unknown"', '"/api/data-status"'):
        assert text in INDEX, text
    assert INDEX.count('fetch("/api/data-status")') == 1 and "menuDataRequested" in INDEX
    assert "loadMenuData();" in INDEX.split('getElementById("menu-open").addEventListener("click"', 1)[1][:400]
    for text in ('holidays: "Public holidays updated to {year}"', 'bus: "Bus data updated {date}"', 'busUnknown: "Bus data date unknown"'):
        assert text in COPY, text
    sheet = INDEX.split('id="menu-sheet"', 1)[1].split("</header>", 1)[0]
    assert sheet.rstrip().endswith("</div>") and sheet.index("menu-data") > sheet.index("demo-reset")  # at the bottom


ATTRIBUTION = "Contains information from LTA DataMall under the Singapore Open Data Licence v1.0"


def test_the_menu_has_the_train_timetable_and_attribution_lines_with_the_exact_text():
    assert 'id="menu-data-rail"' in INDEX and 'id="menu-data-attribution"' in INDEX
    for text in ('"Train timetable updated "', '"Train timetable date unknown"', ATTRIBUTION, "body.rail_data_date"):
        assert text in INDEX, text
    assert INDEX.count(ATTRIBUTION) == 1  # one constant, used by the success and the failure state
    for text in ('rail: "Train timetable updated {date}"', 'railUnknown: "Train timetable date unknown"',
                 f'attribution: "{ATTRIBUTION}"'):
        assert text in COPY, text
    sheet = INDEX.split('id="menu-sheet"', 1)[1].split("</header>", 1)[0]
    assert sheet.index("menu-data-bus") < sheet.index("menu-data-rail") < sheet.index("menu-data-attribution")
    assert "Train timetable updated 10 Oct 2026" in GUIDE and "Train timetable date unknown" in GUIDE
    assert ATTRIBUTION in GUIDE
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    assert "`Train timetable updated {d Mon yyyy}`" in plan and ATTRIBUTION in plan and "rail_data_date" in plan


def test_the_menu_lines_are_muted_small_hold_their_space_and_hide_on_journey_pages():
    line = CSS.split(".menu-data__line {", 1)[1].split("}", 1)[0]
    assert "color: var(--color-muted)" in line and "font-size: var(--type-caption)" in line and "min-height" in line
    hide = CSS.split("body.is-screen-journey .menu-data", 1)[1].split("}", 1)[0]
    for screen in ("is-screen-live", "is-screen-newjourney", "is-screen-onway"):
        assert screen in hide
    assert "display: none" in hide
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(|style=", line)


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_the_muted_text_has_4_5_to_1_on_the_menu_surface_in_light_and_dark():
    theme = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
    muted = re.findall(r"--color-muted:\s*(#[0-9A-Fa-f]{6})", theme)
    card = re.findall(r"--color-card:\s*(#[0-9A-Fa-f]{6})", theme)
    assert "background: var(--color-card)" in CSS.split(".menu-sheet {", 1)[1].split("}", 1)[0]
    for text, surface in zip(muted[:2], card[:2]):
        hi, lo = sorted((_luminance(text), _luminance(surface)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5


def test_the_style_guide_shows_the_lines_and_the_plan_describes_them():
    assert "Public holidays updated to 2027" in GUIDE and "Bus data updated 29 Sep 2026" in GUIDE
    assert "Bus data date unknown" in GUIDE and 'class="menu-data__line"' in GUIDE
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    assert "/api/data-status" in plan and "Public holidays updated to {year}" in plan and "more than 30 days old" in plan


# ---- the menu in a real browser (headless Edge): tests/js/scenarios/menudata.mjs

from page_runner import require_edge, run_scenario, running_app  # noqa: E402


def _menu(tmp_path_factory, fail):
    require_edge()
    with running_app(tmp_path_factory.mktemp("menudata"), eta_minutes=[10.3]) as base:
        return run_scenario("menudata", base, {"fail": fail})["result"]


@pytest.fixture(scope="module")
def menu_ok(tmp_path_factory):
    return _menu(tmp_path_factory, "")


@pytest.fixture(scope="module")
def menu_404(tmp_path_factory):
    return _menu(tmp_path_factory, "404")


@pytest.fixture(scope="module")
def menu_network(tmp_path_factory):
    return _menu(tmp_path_factory, "network")


def _visible(line):
    return (
        line["text"].strip() != "" and line["hidden"] is False and line["display"] != "none"
        and line["visibility"] == "visible" and float(line["opacity"]) == 1.0
        and line["height"] > 0 and line["width"] > 0 and line["clipped"] is False
    )


def test_home_menu_shows_the_train_timetable_and_attribution_lines(menu_ok):
    shown = menu_ok["afterOpen"]
    assert _visible(shown["rail"]) and _visible(shown["attribution"])
    assert re.fullmatch(r"Train timetable updated \d{1,2} [A-Z][a-z]{2} \d{4}|Train timetable date unknown",
                        shown["rail"]["text"])
    assert shown["attribution"]["text"] == ATTRIBUTION
    assert shown["rail"]["color"] == shown["bus"]["color"] == shown["attribution"]["color"]  # one muted style
    assert shown["boxBottom"] <= shown["sheetBottom"]


def test_home_menu_shows_both_lines_with_visible_text(menu_ok):
    shown = menu_ok["afterOpen"]
    assert shown["bodyClass"].find("is-screen-home") != -1 and shown["sheetHidden"] is False
    assert _visible(shown["holidays"]) and _visible(shown["bus"])
    assert shown["holidays"]["text"] == "Public holidays updated to 2027"
    assert re.fullmatch(r"Bus data updated \d{1,2} [A-Z][a-z]{2} \d{4}", shown["bus"]["text"])
    assert shown["holidays"]["color"] != shown["surface"] and shown["bus"]["color"] != shown["surface"]
    assert shown["boxBottom"] <= shown["sheetBottom"]  # inside the panel
    assert menu_ok["calls"] == 1 and menu_ok["callsAfterReopen"] == 1  # fetched once


@pytest.mark.parametrize("fixture", ["menu_404", "menu_network"])
def test_a_failed_fetch_shows_data_status_unavailable_in_the_same_muted_style(fixture, request, menu_ok):
    shown = request.getfixturevalue(fixture)["afterOpen"]
    assert shown["holidays"]["text"] == "Data status unavailable" and _visible(shown["holidays"])
    assert shown["holidays"]["color"] == menu_ok["afterOpen"]["holidays"]["color"]  # the same muted colour
    assert shown["holidays"]["fontSize"] == menu_ok["afterOpen"]["holidays"]["fontSize"]
    assert shown["bus"]["text"] == "" and shown["rail"]["text"] == ""  # one line says it, not three
    assert shown["attribution"]["text"] == ATTRIBUTION and _visible(shown["attribution"])  # the credit stays


def test_after_a_failure_the_next_menu_open_tries_again(menu_404, menu_network):
    assert menu_404["calls"] == 1 and menu_404["callsAfterReopen"] == 2
    assert menu_network["calls"] == 1 and menu_network["callsAfterReopen"] == 2


def test_the_failure_text_is_in_copy_js_the_page_and_the_style_guide():
    assert 'unavailable: "Data status unavailable"' in COPY
    assert INDEX.count('"Data status unavailable"') == 1 and "Data status unavailable" in GUIDE
    assert ".catch(showMenuDataUnavailable)" in INDEX

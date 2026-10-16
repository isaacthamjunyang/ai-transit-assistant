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


# ---- the menu: two rows, no data lines; the attribution lives in the "How it works" card

ATTRIBUTION = "Contains information from LTA DataMall under the Singapore Open Data Licence v1.0"
GONE = ("Public holidays updated", "Bus data updated", "Train timetable updated", "Bus data date unknown",
        "Train timetable date unknown", "Data status unavailable")


def test_the_menu_source_has_two_rows_and_no_data_lines():
    sheet = INDEX.split('id="menu-sheet"', 1)[1].split("</header>", 1)[0]
    assert sheet.count('class="menu-row"') == 2 and sheet.count("menu-row") == 2
    assert "Appearance" in sheet and "How it works" in sheet and 'id="demo-controls"' in sheet
    assert "menu-data" not in INDEX and "menu-data" not in CSS and "menu-data" not in GUIDE
    for text in GONE:
        assert text not in INDEX, text
        assert text not in COPY, text
        assert text not in GUIDE, text
    assert "loadMenuData" not in INDEX and 'fetch("/api/data-status")' not in INDEX


def test_the_attribution_is_one_string_in_copy_the_explainer_the_guide_and_the_plan():
    assert f'attribution: "{ATTRIBUTION}"' in COPY
    block = INDEX.split('id="first-run"', 1)[1].split('id="catch-bar"', 1)[0]
    assert ATTRIBUTION in block and block.rstrip().index("first-run-attribution") > block.index("first-run-next")
    assert INDEX.count(ATTRIBUTION) == 1
    assert "fr.attribution" in GUIDE and "first-run__attribution" in GUIDE
    rule = CSS.split(".first-run__card .first-run__attribution {", 1)[1].split("}", 1)[0]
    assert "color: var(--color-muted)" in rule and "font-size: var(--type-caption)" in rule
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(|style=", rule)
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    assert ATTRIBUTION in plan and "exactly two rows" in plan and "`GET /api/data-status` and the startup warnings stay" in plan


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_the_muted_text_has_4_5_to_1_on_the_card_surface_in_light_and_dark():
    theme = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
    muted = re.findall(r"--color-muted:\s*(#[0-9A-Fa-f]{6})", theme)
    card = re.findall(r"--color-card:\s*(#[0-9A-Fa-f]{6})", theme)
    assert "background: var(--color-card)" in CSS.split(".first-run__card {", 1)[1].split("}", 1)[0]
    for text, surface in zip(muted[:2], card[:2]):
        hi, lo = sorted((_luminance(text), _luminance(surface)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5


def test_the_data_status_endpoint_stays_and_is_documented():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    assert "GET /api/data-status" in plan and "more than 30 days old" in plan


# ---- the menu in a real browser (headless Edge): tests/js/scenarios/menudata.mjs

from page_runner import require_edge, run_scenario, running_app  # noqa: E402


@pytest.fixture(scope="module", params=[(360, False), (1280, True)], ids=["360-light", "1280-dark"])
def menu(request, tmp_path_factory):
    require_edge()
    width, dark = request.param
    with running_app(tmp_path_factory.mktemp("menudata"), eta_minutes=[10.3]) as base:
        return run_scenario("menudata", base, {"width": width, "height": 800, "dark": dark}, timeout=240)["result"]


def test_the_open_menu_has_exactly_two_rows_and_no_status_lines(menu):
    shown = menu["menu"]
    assert shown["sheetHidden"] is False
    assert shown["rows"] == ["Appearance", "How it works"]
    assert shown["dataBox"] is False and shown["demoShown"] is False
    for text in GONE:
        assert text not in shown["text"], text
    assert menu["calls"] == 0  # the page no longer asks for the status


def test_the_attribution_is_the_last_muted_line_inside_the_how_it_works_card(menu):
    card = menu["card"]
    assert card["text"] == ATTRIBUTION
    assert card["isLast"] is True and card["visible"] is True and card["inside"] is True
    assert card["belowActions"] is True
    assert card["color"] != card["bodyColor"]  # muted, not the primary text colour
    assert card["scrollWidth"] <= card["innerWidth"]

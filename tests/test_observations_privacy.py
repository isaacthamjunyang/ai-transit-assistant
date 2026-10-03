"""The observations log does not store the user's position or the GPS accuracy, and nothing the app
writes or returns for a valid request carries the coordinates."""

import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx
import pytest

import observations
from page_runner import north, running_app
from reroute import log_scored_poll

USER = north(300)
# The leading digits of the position as they appear in a query string or a log line.
USER_TEXT = (repr(USER[0])[:9], repr(USER[1])[:8])


def _rows(path: Path):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return list(connection.execute("SELECT * FROM observations ORDER BY id"))


def test_record_observation_writes_null_for_the_position_and_the_accuracy(tmp_path):
    path = tmp_path / "o.db"
    observations.record_observation(
        {
            "timestamp": "2026-10-03T10:00:00+08:00", "stop_code": "08057", "service": "36", "direction": 1,
            "eta": "2026-10-03T10:10:00+08:00", "monitored": 1, "bus_lat": 1.1, "bus_lon": 103.1,
            "user_lat": 1.2345678, "user_lon": 103.8765432, "gps_accuracy": 8.5, "walk_metres": 40,
            "slack_seconds": 5, "p": 55, "p_low": 40, "p_high": 70, "data_quality": "live",
            "reroute_fired": 0, "reroute_reason": "",
        },
        path,
    )
    row = _rows(path)[0]
    assert row["user_lat"] is None and row["user_lon"] is None and row["gps_accuracy"] is None
    # everything else is still written
    assert row["timestamp"] == "2026-10-03T10:00:00+08:00" and row["stop_code"] == "08057"
    assert row["service"] == "36" and row["direction"] == 1 and row["monitored"] == 1
    assert row["eta"] == "2026-10-03T10:10:00+08:00" and row["walk_metres"] == 40
    assert (row["bus_lat"], row["bus_lon"]) == (1.1, 103.1)
    assert (row["slack_seconds"], row["p"], row["p_low"], row["p_high"]) == (5, 55, 40, 70)
    assert row["data_quality"] == "live" and row["reroute_fired"] == 0 and row["reroute_reason"] == ""


def test_the_columns_stay_so_there_is_no_migration(tmp_path):
    path = tmp_path / "o.db"
    observations.record_observation({"timestamp": "t"}, path)
    with sqlite3.connect(path) as connection:
        names = [row[1] for row in connection.execute("PRAGMA table_info(observations)")]
    assert {"user_lat", "user_lon", "gps_accuracy"} <= set(names)


def test_log_scored_poll_with_a_position_writes_null(tmp_path):
    from test_reroute import DEST, ORIGIN, _current, _primary, _simple_cache

    bus = _primary()
    bus["latitude"], bus["longitude"] = 1.2, 103.2
    current = _current([bus])
    path = tmp_path / "o.db"
    ok = log_scored_poll(
        cache=_simple_cache(), current=current, bus=bus, user_lat=1.3, user_lon=103.8, accuracy_m=12,
        now=datetime(2026, 9, 29, 14, 0), reroute_fired=False, reroute_reason="",
        destination_stop_code=DEST, db_path=path,
    )
    assert ok
    row = _rows(path)[0]
    assert row["user_lat"] is None and row["user_lon"] is None and row["gps_accuracy"] is None
    assert row["walk_metres"] is not None and row["stop_code"] == ORIGIN and row["p"] is not None
    assert (row["bus_lat"], row["bus_lon"]) == (1.2, 103.2)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


APP_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error", "lta_static")


@contextmanager
def _capturing(capture):
    """Attach the capture to the app's own loggers (the test client's httpx logger is left out: it logs the
    test's own requests). It must run after the server is created: uvicorn resets its handlers then."""
    loggers = [logging.getLogger(name) for name in APP_LOGGERS]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(capture)
        logger.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels):
            logger.removeHandler(capture)
            logger.setLevel(level)


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    folder = tmp_path_factory.mktemp("privacy")
    capture = _Capture()
    with running_app(folder, log_level="info") as base, _capturing(capture):
        yield base, folder / "observations.db", capture


def _poll(base, **extra):
    params = {
        "stop_code": "01011", "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": 9.5,
        "location_timestamp": time.time(), "walk_speed": 1.1, "walk_speed_source": "gps",
    }
    params.update(extra)
    return httpx.get(base + "/api/arrivals", params=params, timeout=20)


def test_a_scored_poll_stores_no_position_and_keeps_the_other_columns(served):
    base, db, _capture = served
    assert _poll(base).status_code == 200
    rows = _rows(db)
    assert rows, "the poll wrote no row"
    row = rows[-1]
    assert row["user_lat"] is None and row["user_lon"] is None and row["gps_accuracy"] is None
    for column in ("timestamp", "stop_code", "service", "eta", "walk_metres", "p", "p_low", "p_high",
                   "slack_seconds", "data_quality"):
        assert row[column] is not None, column
    assert row["stop_code"] == "01011" and row["service"] == "18" and row["monitored"] == 1
    assert row["data_quality"] == "live"
    assert USER_TEXT[0] not in " ".join(str(value) for value in tuple(row))


def test_no_log_line_carries_the_position_or_the_speed(served):
    base, _db, capture = served
    _poll(base)
    _poll(base, location_timestamp=0)  # an old fix is still a valid request
    httpx.get(
        base + "/api/arrivals",
        params={"stop_code": "01011", "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": -3},
        timeout=20,
    )
    assert capture.lines, "no log line was captured, so the check proves nothing"
    joined = "\n".join(capture.lines)
    assert "/api/arrivals" in joined  # the access lines were captured
    for text in (USER_TEXT[0], USER_TEXT[1], "walk_speed", "location_timestamp"):
        assert text not in joined, text


def test_the_apps_own_error_responses_do_not_echo_coordinates(served):
    base, _db, _capture = served
    bad_accuracy = httpx.get(
        base + "/api/arrivals",
        params={
            "stop_code": "01011", "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": -3,
            "destination_stop_code": "99999", "dest_lat": USER[0], "dest_lon": USER[1],
        },
        timeout=20,
    )
    assert bad_accuracy.status_code == 422 and USER_TEXT[0] not in bad_accuracy.text
    other_invalid = _poll(base, accuracy="abc")  # the 422 handler leaves out the offending value
    assert other_invalid.status_code == 422
    assert USER_TEXT[0] not in other_invalid.text and USER_TEXT[1] not in other_invalid.text
    assert "abc" not in other_invalid.text and "input" not in other_invalid.json()["detail"][0]


def test_an_lta_failure_returns_no_coordinates_and_logs_none(tmp_path):
    capture = _Capture()
    with running_app(tmp_path, log_level="info", lta_status=500) as base, _capturing(capture):
        response = _poll(base)
    assert response.status_code == 503
    assert USER_TEXT[0] not in response.text and USER_TEXT[1] not in response.text
    assert capture.lines and USER_TEXT[0] not in "\n".join(capture.lines)

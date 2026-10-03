"""The 422 validation response keeps each error's type, loc and msg and leaves out the value the client sent.

Nothing about what is validated changes, only what the error response echoes back.
"""

import logging
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import arrivals
import demo
import lta_static
import observations
from main import app
from page_runner import make_cache, north, running_app

USER = north(300)
USER_TEXT = (repr(USER[0])[:9], repr(USER[1])[:8])


@pytest.fixture
def client(monkeypatch, tmp_path):
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(lta_static, "ENV_PATH", env)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    cache = make_cache()
    monkeypatch.setattr("main.load_static_data", lambda: cache)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: "test-account-key")
    demo.reset_to_live()
    with TestClient(app) as test_client:
        yield test_client
    demo.reset_to_live()


def _detail(response):
    assert response.status_code == 422
    return response.json()["detail"]


def test_a_non_numeric_latitude_keeps_type_loc_and_msg_and_drops_the_value(client):
    response = client.get("/api/arrivals", params={"stop_code": "01011", "service_no": "18", "lat": "abc", "lon": USER[1]})
    detail = _detail(response)
    assert detail == [{
        "type": "float_parsing",
        "loc": ["query", "lat"],
        "msg": "Input should be a valid number, unable to parse string as a number",
    }]
    assert "abc" not in response.text and "input" not in response.text and "ctx" not in response.text


def test_an_out_of_range_latitude_is_not_echoed(client):
    params = {"user_lat": 95.5, "user_lon": USER[1], "destination_stop_code": "99999", "dest_lat": 1.3, "dest_lon": 103.8}
    response = client.get("/api/journey-plan", params=params)
    assert _detail(response) == [{
        "type": "less_than_equal",
        "loc": ["query", "user_lat"],
        "msg": "Input should be less than or equal to 90",
    }]
    assert "95.5" not in response.text and "ctx" not in response.text and "input" not in response.text


def test_a_missing_parameter_still_names_the_right_field(client):
    response = client.get("/api/arrivals", params={"service_no": "18"})
    assert _detail(response) == [{"type": "missing", "loc": ["query", "stop_code"], "msg": "Field required"}]


def test_several_errors_are_all_reported_in_order_and_none_echoes_a_value(client):
    response = client.get(
        "/api/reroute-options",
        params={"stop_code": "01011", "service_no": "18", "lat": "1.30x", "lon": USER[1], "accuracy": -4,
                "destination_stop_code": "99999", "dest_lat": 1.3, "dest_lon": 103.8},
    )
    detail = _detail(response)
    assert [error["loc"] for error in detail] == [["query", "lat"], ["query", "accuracy"]]
    assert all(set(error) == {"type", "loc", "msg"} for error in detail)
    assert "1.30x" not in response.text and "-4" not in response.text


def test_a_bad_json_body_is_not_echoed_either(client):
    response = client.post("/api/explain", json=["secret-value-1.2345", {"lat": 1.2345}])
    detail = _detail(response)
    assert all(set(error) == {"type", "loc", "msg"} for error in detail)
    assert detail[0]["loc"] == ["body"]
    assert "secret-value" not in response.text and "1.2345" not in response.text


def test_a_valid_request_is_untouched(client):
    response = client.get("/api/arrivals", params={"stop_code": "01011", "service_no": "18"})
    assert response.status_code in (200, 503)  # not a validation error


class _FullCapture(logging.Handler):
    """Every record as the log would print it, with the traceback."""

    def __init__(self):
        super().__init__(logging.NOTSET)
        self.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


APP_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi", "uvicorn.protocol", "lta_static", "asyncio")


def _crash_and_capture(tmp_path, monkeypatch, level):
    """Run the app, raise an unhandled error inside a request that carries the position and the speed, and
    return what the client received and every log record (with its traceback) from the app's loggers."""
    capture = _FullCapture()
    logs = [logging.getLogger(name) for name in APP_LOGGERS]

    def explode(*args, **kwargs):
        raise RuntimeError("unexpected failure inside the arrivals request")

    with running_app(tmp_path, log_level=level) as base:
        monkeypatch.setattr("main.fetch_arrivals", explode)
        for logger in logs:
            logger.addHandler(capture)
        try:
            response = httpx.get(
                base + "/api/arrivals",
                params={
                    "stop_code": "01011", "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": 9.5,
                    "location_timestamp": time.time(), "walk_speed": 1.23, "walk_speed_source": "gps",
                },
                timeout=20,
            )
            time.sleep(0.3)
        finally:
            for logger in logs:
                logger.removeHandler(capture)
    return response, "\n".join(capture.lines)


# What would reveal a value. The traceback prints source lines, so a parameter NAME can appear (for example
# `walk_speed_m_s=speed`); only a value or a query-string pair counts.
LEAKS = (USER_TEXT[0], USER_TEXT[1], "1.23", "accuracy=9.5", "walk_speed=", "location_timestamp=", "lat=1.", "lon=103")


@pytest.mark.parametrize("level", ["info", "debug"])
def test_an_unhandled_exception_logs_and_returns_no_coordinates_or_speed(tmp_path, monkeypatch, level):
    response, text = _crash_and_capture(tmp_path, monkeypatch, level)
    assert response.status_code == 500
    assert response.text == "Internal Server Error"  # a plain 500: no detail, no coordinates
    assert "Exception in ASGI application" in text and "RuntimeError" in text, "the traceback was not captured"
    assert "/api/arrivals" in text  # the access line is there, with its query string removed
    for value in LEAKS:
        assert value not in text, value


def test_trace_level_logging_carries_no_coordinates_or_speed(tmp_path, monkeypatch):
    """At uvicorn's trace level its message logger prints the whole ASGI scope; the filter strips the query."""
    response, text = _crash_and_capture(tmp_path, monkeypatch, "trace")
    assert response.status_code == 500
    assert "ASGI [" in text, "no trace-level record was captured, so the check proves nothing"
    for value in LEAKS:
        assert value not in text, value


def test_trace_level_records_stay_readable_with_the_path_and_the_other_parameters(tmp_path, monkeypatch):
    _response, text = _crash_and_capture(tmp_path, monkeypatch, "trace")
    started = [line for line in text.split("\n") if "Started scope=" in line and "'/api/arrivals'" in line]
    assert started, "the request's Started record is missing"
    line = started[0]
    assert "'path': '/api/arrivals'" in line and "'method': 'GET'" in line
    assert "'query_string': b'stop_code=01011&service_no=18'" in line  # only the private parameters are gone
    assert "'raw_path': b'/api/arrivals'" in line
    assert "Send" in text and "Raised exception" in text and "HTTP connection made" in text


def test_the_asgi_filter_cleans_a_copy_and_keeps_the_rest_of_the_scope():
    from access_log_filter import StripAsgiQuery, clean_asgi_value

    scope = {
        "type": "http", "path": "/api/arrivals", "raw_path": b"/api/arrivals?lat=1.3026&lon=103.8&stop_code=01011",
        "query_string": b"stop_code=01011&lat=1.3026&lon=103.8&accuracy=9.5&walk_speed=1.23&service_no=18",
        "headers": "<...>", "client": ("127.0.0.1", 5), "method": "GET",
    }
    cleaned = clean_asgi_value(scope)
    assert cleaned["query_string"] == b"stop_code=01011&service_no=18"
    assert cleaned["raw_path"] == b"/api/arrivals?stop_code=01011"
    assert cleaned["path"] == "/api/arrivals" and cleaned["headers"] == "<...>" and cleaned["method"] == "GET"
    assert cleaned["client"] == ("127.0.0.1", 5)
    assert b"lat=1.3026" in scope["query_string"] and b"lat=1.3026" in scope["raw_path"]  # the original is untouched
    record = logging.LogRecord("uvicorn.asgi", 5, __file__, 1, "%s [%d] Started scope=%s", ("x", 1, scope), None)
    assert StripAsgiQuery().filter(record) is True
    assert "1.3026" not in record.getMessage() and "stop_code=01011" in record.getMessage()
    assert clean_asgi_value({"query_string": b"lat=1&lon=2"})["query_string"] == b""
    assert clean_asgi_value("not a dict") == "not a dict"


def test_every_uvicorn_request_logger_has_its_filter_installed():
    import access_log_filter

    for name in access_log_filter.FILTERED_LOGGERS:
        kinds = {type(item).__name__ for item in logging.getLogger(name).filters}
        assert {"StripPrivateQuery", "StripAsgiQuery"} <= kinds, name
    # uvicorn has no "uvicorn.protocol" logger in this version: nothing logs there to filter
    assert "uvicorn.protocol" not in access_log_filter.FILTERED_LOGGERS

"""Deployment readiness (Render): the health route, the files a host needs, and writes that must not fail a request on a read-only
or ephemeral disk. No live API."""

import logging
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import access_log_filter
import arrivals
import demo
import lta_static
import observations
from main import app
from page_runner import make_cache

ROOT = Path(__file__).resolve().parents[1]


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


def test_healthz_answers_ok_with_nothing_else(client):
    response = client.get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert "set-cookie" not in response.headers


def test_healthz_needs_no_key_and_makes_no_network_call(client, monkeypatch):
    import httpx

    def refuse(*args, **kwargs):
        raise AssertionError("the health check must not call out")

    monkeypatch.setattr(httpx.Client, "get", refuse)
    monkeypatch.setattr(httpx.Client, "post", refuse)
    for name in ("LTA_ACCOUNT_KEY", "OPENAI_API_KEY", "ONEMAP_TOKEN", "ONEMAP_EMAIL", "ONEMAP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert client.get("/healthz").json() == {"status": "ok"}


def test_the_pages_scripts_and_styles_are_served(client):
    assert client.get("/").status_code == 200
    page = client.get("/").text
    for name in re.findall(r'<script src="([^"]+)"', page) + re.findall(r'<link rel="stylesheet" href="([^":]+)"', page):
        assert client.get("/" + name).status_code == 200, name


def test_the_access_log_filter_still_strips_the_users_position(caplog):
    access_log_filter.install()
    logger = logging.getLogger("uvicorn.access")
    seen = []

    class Grab(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = Grab()
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET",
                    "/api/arrivals?stop_code=01011&service_no=18&lat=1.3&lon=103.8&accuracy=8&walk_speed=1.2", "1.1", 200)
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/healthz", "1.1", 200)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    assert "stop_code=01011" in seen[0] and "lat=" not in seen[0] and "lon=" not in seen[0] and "walk_speed" not in seen[0]
    assert "/healthz" in seen[1]


def test_an_unwritable_observations_log_never_fails_the_caller(tmp_path, caplog):
    missing = tmp_path / "no-such-folder" / "observations.db"  # the folder does not exist: sqlite cannot open the file
    observations._write_warned = False
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        observations.record_observation({"timestamp": "2026-01-01T00:00:00+08:00", "reroute_fired": False}, missing)
        observations.record_observation({"timestamp": "2026-01-01T00:00:01+08:00", "reroute_fired": False}, missing)
    assert not missing.exists()
    assert sum("observations log is not writable" in r.getMessage() for r in caplog.records) == 1  # said once, not on every poll


def test_a_writable_observations_log_still_stores_the_row(tmp_path):
    path = tmp_path / "observations.db"
    observations.record_observation({"timestamp": "2026-01-01T00:00:00+08:00", "stop_code": "01011", "reroute_fired": True}, path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT stop_code, reroute_fired, user_lat FROM observations").fetchall()
    connection.close()
    assert rows == [("01011", 1, None)]


def test_requirements_are_production_only_and_complete():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    names = {line.split("==")[0].strip().lower() for line in text.splitlines() if line.strip() and not line.startswith("#")}
    assert {"fastapi", "uvicorn", "httpx", "openai"} <= names  # openai is imported lazily by explain.py
    assert "pytest" not in names
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in dev and "pytest==" in dev


def test_env_example_holds_placeholders_only():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        assert value in ("", "false"), name  # nothing that could be a key, a token or a password
    names = {line.partition("=")[0] for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()}
    assert {"LTA_ACCOUNT_KEY", "OPENAI_API_KEY", "OPENAI_MODEL", "ONEMAP_EMAIL", "ONEMAP_PASSWORD", "ONEMAP_TOKEN", "DEMO_MODE",
            "AI_EXPLANATION_ENABLED"} <= names


def test_the_four_cache_files_are_tracked_and_nothing_secret_is_in_them():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in ("bus_stops.json", "bus_routes.json", "bus_services.json", "rail_timetable.json"):
        assert f"!cache/{name}" in ignore and (ROOT / "cache" / name).is_file()
        assert not re.search(r"account[_ ]?key|password|api[_-]key", (ROOT / "cache" / name).read_text(encoding="utf-8"), re.I)
    assert "cache/*" in ignore


def test_deploy_files_exist_and_name_the_pieces():
    assert re.fullmatch(r"3\.\d+\.\d+", (ROOT / ".python-version").read_text(encoding="utf-8").strip())
    deploy = (ROOT / "DEPLOY.md").read_text(encoding="utf-8")
    for text in ("uvicorn main:app --host 0.0.0.0 --port $PORT", "/healthz", "PYTHON_VERSION", "LTA_ACCOUNT_KEY", "ONEMAP_EMAIL",
                 "pip install -r requirements.txt"):
        assert text in deploy, text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Data sources and attribution" in readme and "LTA DataMall" in readme and "OneMap" in readme

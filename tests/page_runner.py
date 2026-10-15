"""Run the real app and drive its real page in headless Edge, for the browser tests.

The app runs in a thread of the test process with a small fixed stop cache and a fake LTA, so no
network call to LTA happens. Leaflet still loads from unpkg (the page's own dependency); a test that
cannot load the page skips and says why.
"""

import json
import math
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import uvicorn

import arrivals
import demo
import explain
import lta_static
import observations
import train_alerts
from edge_runner import find_edge
from lta_static import StopAndRouteCache
from nearby import EARTH_RADIUS_M

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "js" / "page_driver.mjs"
SGT = timezone(timedelta(hours=8))
LAT = 1.3
LON = 103.8
ORIGIN = "01011"
DEST = "99999"


def north(metres: float) -> tuple[float, float]:
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def make_cache() -> StopAndRouteCache:
    dest_lat, dest_lon = north(2000)
    stops = [
        {"BusStopCode": ORIGIN, "Description": "Origin", "RoadName": "Orchard Rd", "Latitude": LAT, "Longitude": LON},
        {"BusStopCode": DEST, "Description": "Destination", "RoadName": "Orchard Rd", "Latitude": dest_lat, "Longitude": dest_lon},
    ]
    routes = [
        {"ServiceNo": "18", "Direction": 1, "BusStopCode": ORIGIN, "StopSequence": 1, "Distance": 0},
        {"ServiceNo": "18", "Direction": 1, "BusStopCode": DEST, "StopSequence": 5, "Distance": 3},
    ]
    services = [{
        "ServiceNo": "18", "Direction": 1, "OriginCode": ORIGIN, "DestinationCode": DEST,
        "AM_Offpeak_Freq": "10-10", "AM_Peak_Freq": "10-10", "PM_Peak_Freq": "10-10", "PM_Offpeak_Freq": "10-10",
    }]
    return StopAndRouteCache(stops, routes, services)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def running_app(tmp_path: Path, eta_minutes: float | list = 10.3, log_level: str = "warning", lta_status: int = 200,
                reroute_stub: bool = False, onemap=None, rail_table: dict | None = None,
                lta_services: dict | None = None, lta_log: list | None = None, train_alerts_payload: dict | None = None,
                alerts_log: list | None = None, alerts_status: int = 200,
                loads: list | None = None):
    """The real FastAPI app on a local port, with the fake cache and a fake LTA.

    eta_minutes is one number (one bus) or a list (NextBus, NextBus2, NextBus3). With reroute_stub the reroute
    decision of every poll is a fired one for another bus, so the real poll pipeline (scoring, action, explanation
    pack) runs with a reroute that fires; the reroute search itself is the only stubbed part."""
    from main import app

    patches = pytest.MonkeyPatch()
    cache = make_cache()
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    patches.setattr(lta_static, "ENV_PATH", env)
    # explain imported ENV_PATH by name, so the line above does not reach it: without these two lines the page's
    # /api/explain used the real .env key and called the real OpenAI, and a model clause could arrive in the middle of
    # an assertion. With no key a browser test never calls OpenAI: the fixed clause is what the page shows.
    patches.setattr(explain, "ENV_PATH", env)
    patches.delenv("OPENAI_API_KEY", raising=False)

    patches.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    # OneMap: with no `onemap` stub the app has no token, so the planner uses the bus planner (fallback) and no OneMap
    # call is made. With a stub, routing answers come from it: onemap(mode) returns the answer body, or None for a 404.
    patches.setattr("main.read_onemap_credentials", lambda: ("stub-token", "", "") if onemap else ("", "", ""))
    patches.setattr("main.load_rail_table", lambda: rail_table)
    patches.delenv("DEMO_MODE", raising=False)
    patches.setattr("main.load_static_data", lambda: cache)
    patches.setattr(arrivals, "read_account_key", lambda: "test-account-key")
    patches.setattr(train_alerts, "read_account_key", lambda: "test-account-key")
    train_alerts.clear_cache()
    real_get = httpx.Client.get
    etas = list(eta_minutes) if isinstance(eta_minutes, (list, tuple)) else [eta_minutes]
    if reroute_stub:
        def fired_decision(**kwargs):
            now = kwargs["now"]
            better = (now + timedelta(minutes=22)).replace(microsecond=0)
            return {
                "switched": True,
                "reroute": {
                    "service_no": "99", "stop": {"stop_code": DEST, "description": "Destination", "distance_m": 150,
                                                 "walk_minutes": 2, "services": ["99"]},
                    "arrival_time": better.isoformat(), "eta_epoch": better.timestamp(),
                    "destination_stop_code": DEST, "reroute_reason": "Bus 99 is a better option.",
                    "notification_title": "Better option", "notification_body": "Open the app to switch.",
                },
                "winner_score": {"point": 63, "range_low": 55, "range_high": 70, "data_quality": "live",
                                 "walk_minutes": 2},
                "alternatives": [], "options": {"rows": [], "recommended": None},
            }

        patches.setattr("main.plan_reroute", fired_decision)

    def fake_get(self, url, *args, **kwargs):
        if "routingsvc/route" in str(url):
            body = onemap(kwargs.get("params", {}).get("mode")) if onemap else None
            return httpx.Response(200, json=body) if body is not None else httpx.Response(404, json={"error": "none"})
        if "onemap.gov.sg" in str(url):  # nothing else may reach OneMap from a test
            return httpx.Response(503, json={})
        if str(url).endswith("/TrainServiceAlerts"):  # scripted: no alerts unless the test gives a payload
            if alerts_log is not None:
                alerts_log.append({"params": dict(kwargs.get("params") or {}), "has_key": "AccountKey" in (kwargs.get("headers") or {})})
            if alerts_status != 200:
                return httpx.Response(alerts_status, json={})
            return httpx.Response(200, json=train_alerts_payload or {
                "odata.metadata": "scripted", "value": {"Status": 1, "AffectedSegments": [], "Message": []}})
        if "/v3/BusArrival" in str(url):
            if lta_log is not None:
                lta_log.append(dict(kwargs.get("params") or {}))  # the query only: never a key, never a header
            if lta_status != 200:
                return httpx.Response(lta_status, json={})

            def shaped(number, minutes_list):
                item = {"ServiceNo": number}
                for index, (name, minutes) in enumerate(zip(("NextBus", "NextBus2", "NextBus3"), minutes_list)):
                    eta = (datetime.now(SGT) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
                    item[name] = {"EstimatedArrival": eta, "Monitored": 1, "Latitude": "", "Longitude": "",
                                  "OriginCode": "", "DestinationCode": ""}
                    if loads is not None and number == "18" and index < len(loads):
                        item[name]["Load"] = loads[index]  # scripted crowding; absent unless the test gives it
                return item

            services = [shaped("18", etas)] + [shaped(number, minutes) for number, minutes in (lta_services or {}).items()]
            return httpx.Response(200, json={"Services": services})
        return real_get(self, url, *args, **kwargs)

    patches.setattr(httpx.Client, "get", fake_get)
    demo.reset_to_live()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level=log_level))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_until_serving(server, base)
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        patches.undo()
        demo.reset_to_live()
        arrivals._peek_handoff.clear()  # a peek the overview made and no Start ever used must not reach the next test
        arrivals.clear_remembered_arrivals()
        arrivals.clear_later_arrivals()
        train_alerts.clear_cache()


def _wait_until_serving(server, base: str, limit_s: float = 30.0) -> None:
    """Ready means the server started AND answers a request, not a fixed number of sleeps."""
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        if server.started:
            try:
                if httpx.get(base + "/api/demo", timeout=2.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
        time.sleep(0.05)
    raise RuntimeError("the app did not start")


def require_edge() -> str:
    edge = find_edge()
    if edge is None:
        pytest.skip("headless Edge is not installed, so the page browser tests did not run")
    return edge


def _run_driver(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run the node driver; on a timeout or any error kill it AND the Edge it started (the whole process tree)."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        out, err = process.communicate(timeout=timeout)
    except BaseException:
        _kill_tree(process.pid)
        process.communicate()
        raise
    finally:
        if process.poll() is None:
            _kill_tree(process.pid)
    return subprocess.CompletedProcess(command, process.returncode, out, err)


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


def run_scenario(name: str, base_url: str, extra: dict | None = None, timeout: float = 240.0) -> dict:
    """Run tests/js/scenarios/<name>.mjs against the running app and return what it reported."""
    edge = require_edge()
    config = {
        "base": base_url,
        "lat": LAT, "lon": LON, "dest": DEST, "origin": ORIGIN,
        "userNorth": north(300),
        "destPos": north(2000),
        **(extra or {}),
    }
    scenario = ROOT / "tests" / "js" / "scenarios" / f"{name}.mjs"
    completed = _run_driver(["node", str(DRIVER), edge, str(scenario), json.dumps(config)], timeout)
    marker = "@@RESULT@@"
    line = next((row for row in completed.stdout.splitlines() if row.startswith(marker)), None)
    if line is None:
        raise AssertionError("the browser scenario printed no result: " + completed.stdout[-500:] + completed.stderr[-500:])
    report = json.loads(line[len(marker):])
    if not report.get("ok"):
        text = report.get("error", "")
        if "leaflet" in text.lower() or "L is not defined" in text or "timed out waiting for: " in text and "start-journey" in text:
            pytest.skip("the page could not load (Leaflet from unpkg needs the network): " + text[:200])
        raise AssertionError(text + "\nconsole: " + "\n".join(report.get("consoleLines", [])))
    return report

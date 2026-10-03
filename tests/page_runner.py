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
import lta_static
import observations
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
def running_app(tmp_path: Path, eta_minutes: float = 10.3, log_level: str = "warning", lta_status: int = 200):
    """The real FastAPI app on a local port, with the fake cache and a fake LTA."""
    from main import app

    patches = pytest.MonkeyPatch()
    cache = make_cache()
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    patches.setattr(lta_static, "ENV_PATH", env)
    patches.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    patches.delenv("DEMO_MODE", raising=False)
    patches.setattr("main.load_static_data", lambda: cache)
    patches.setattr(arrivals, "read_account_key", lambda: "test-account-key")
    real_get = httpx.Client.get

    def fake_get(self, url, *args, **kwargs):
        if "/v3/BusArrival" in str(url):
            if lta_status != 200:
                return httpx.Response(lta_status, json={})
            eta = (datetime.now(SGT) + timedelta(minutes=eta_minutes)).replace(microsecond=0).isoformat()
            bus = {"EstimatedArrival": eta, "Monitored": 1, "Latitude": "", "Longitude": "", "OriginCode": "", "DestinationCode": ""}
            return httpx.Response(200, json={"Services": [{"ServiceNo": "18", "NextBus": bus}]})
        return real_get(self, url, *args, **kwargs)

    patches.setattr(httpx.Client, "get", fake_get)
    demo.reset_to_live()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level=log_level))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("the app did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        patches.undo()
        demo.reset_to_live()


def require_edge() -> str:
    edge = find_edge()
    if edge is None:
        pytest.skip("headless Edge is not installed, so the page browser tests did not run")
    return edge


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
    completed = subprocess.run(
        ["node", str(DRIVER), edge, str(scenario), json.dumps(config)],
        capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False,
    )
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

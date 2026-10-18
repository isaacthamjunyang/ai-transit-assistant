"""Record the scenes: for each one start the real app on a local port with the real static data and the sample trip (world.py), drive it
in headless Edge at 390x844 CSS px (device scale 3), write assets/<NN>-<name>.webm, then stop the app and the browser.

The only network traffic allowed from the page is OpenStreetMap's tile server (see driver.mjs); LTA and OneMap are scripted.

usage: run_capture.py [scene numbers, e.g. 01 05]   (no argument: every scene)"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

import world

world.patch_runner()

import page_runner  # noqa: E402
from edge_runner import find_edge  # noqa: E402
from page_runner import _run_driver, running_app  # noqa: E402

HERE = Path(__file__).resolve().parent
SCENES = {}


def scene(number: str, name: str, arrivals=None, clock=None, **app):
    SCENES[number] = {"name": name, "arrivals": arrivals, "clock": clock, "app": app}


# live bus times for the two services the trip uses (minutes from now); the LTA Load codes give Seats / Standing / Crowded
BUSES = world.arrivals_patch({"49": [10.3, 16.3, 24.3], "335": [10.3, 16.3, 24.3]}, {"49": ["SEA", "SDA", "LSD"], "335": ["SEA", "SDA", "LSD"]})
LIVE = dict(onemap=world.onemap, rail_table=world.RAIL, lta_status=200)

# LTA's train service alert answer, scripted: a disruption on the East-West Line between the two real stations of the trip
DISRUPTION = {
    "odata.metadata": "scripted",
    "value": {"Status": 2, "AffectedSegments": [{"Line": "EWL", "Direction": "Both", "Stations": "EW26,EW25,EW24", "FreePublicBus": "",
                                                  "FreeMRTShuttle": "", "MRTShuttleDirection": ""}],
              "Message": [{"Content": "1700hrs : EWL - No train service between Lakeside and Jurong East due to a signal fault. "
                                      "Free bus service is available.", "CreatedDate": "2026-01-01 17:00:00"}]},
}

scene("01", "home", BUSES, **LIVE)
scene("02", "stops", BUSES, **LIVE)
scene("03", "theme", BUSES, **LIVE)
scene("04", "overview", BUSES, **LIVE)
scene("05", "arrivals", BUSES, **LIVE)
scene("06", "mrt", BUSES, **LIVE)
# scene 07 runs on a frozen clock (21:00:00) and a bus 8.0 minutes away, so the app's own rules give a bus at 9:08 PM
PAGE_A_BUSES = world.arrivals_patch({"49": [8.0, 15.0, 22.0], "335": [8.0, 15.0, 22.0]}, {"49": ["SEA", "SDA", "LSD"], "335": ["SEA", "SDA", "LSD"]})
scene("07", "pagea", PAGE_A_BUSES, clock=(21, 0, 0), **LIVE)
scene("00", "probe", PAGE_A_BUSES, clock=(21, 0, 0), **LIVE)
scene("08", "walk", BUSES, **LIVE)
scene("09", "getoff", BUSES, **LIVE)
scene("10", "pagec", BUSES, **LIVE)
scene("11", "nomode", BUSES, onemap=world.walk_only, rail_table=world.RAIL, lta_status=200)
scene("12", "alert", BUSES, train_alerts_payload=DISRUPTION, **LIVE)


def main(wanted: list[str]) -> int:
    edge = find_edge()
    if edge is None:
        print("Headless Edge was not found: install Microsoft Edge (or set the path find_edge() looks for).")
        return 2
    numbers = wanted or sorted(n for n in SCENES if n != "00")
    results = []
    for number in numbers:
        spec = SCENES[number]
        patches = pytest.MonkeyPatch()
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, running_app(Path(tmp), **spec["app"]) as base:
                frozen = world.freeze_clock(patches, *spec["clock"]) if spec["clock"] else None
                if spec["arrivals"]:
                    spec["arrivals"](patches, (lambda: frozen) if frozen else None)  # after the harness's own LTA fake, so it answers first
                config = {"base": base, "lat": world.LAT, "lon": world.LON, "dest": world.BUS_ALIGHT, "origin": world.BOARD,
                          "userNorth": list(world.PHONE), "places": world.PLACES, "number": number, "clockMs": int(frozen.timestamp() * 1000) if frozen else None, "name": f"{number}-{spec['name']}"}
                command = ["node", str(HERE / "driver.mjs"), edge, str(HERE / "scenes" / f"{number}-{spec['name']}.mjs"), json.dumps(config)]
                done = _run_driver(command, 600)
                patches.undo()  # before the harness undoes its own patches
        finally:
            patches.undo()
        line = next((row for row in done.stdout.splitlines() if row.startswith("@@RESULT@@")), None)
        report = json.loads(line[len("@@RESULT@@"):]) if line else {"ok": False, "error": done.stdout[-400:] + done.stderr[-400:]}
        print(number, spec["name"], "ok" if report.get("ok") else "FAILED")
        print(json.dumps(report.get("result") if report.get("ok") else report.get("error"), indent=1))
        results.append(report)
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

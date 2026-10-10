# ai-transit-assistant

AI-powered Singapore bus catch assistant for the AI Lodge Hackathon. The app is meant to help someone decide whether they can catch a bus and when to leave.

This repository is being built one step at a time. The page asks for your location, shows nearby boarding stops, and can monitor live arrivals for one stop and one service. When your location is available, each bus card also shows a catch probability computed in Python. You can also search for a destination place, choose a destination bus stop, and see a journey form with ride time, an arrive-by check, and a leave-by clock. While that journey is open, the page can send a leave-now browser notification. An AI Explanation card states the numbers Python already computed.

## Requirements

- Python 3.11 or newer
- Windows
- A web browser

## Setup

The project already includes a virtual environment at `.venv`. Use that environment.

In PowerShell, from the project folder:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you do not already have a local `.env` file, create one from the example:

```powershell
Copy-Item .env.example .env
```

`.env` is gitignored. Put your LTA DataMall key in `LTA_ACCOUNT_KEY`. The server reads that value to download static stops, routes, and service frequencies, and to request live arrivals. It does not send the key to the browser.

Destination search uses OneMap. `ONEMAP_TOKEN` is optional. If it is missing, rejected, or a generated token has expired, the server can request a fresh token with `ONEMAP_EMAIL` and `ONEMAP_PASSWORD`. The token stays in memory. The page calls this server only.

After you select a place, the page lists LTA bus stops within 600 m of that place. A stop is reachable when the cached routes show a direct bus from your selected boarding stop, or, if you have not selected one, from a boarding stop within 400 m of you. Up to three other stops are shown but cannot be confirmed. The trip estimate uses the cached route distance at 18 km/h and the cached service frequency. It is not a catch probability. After you confirm a stop, the journey form asks for an arrive-by time. If the route distance is unusable, the ride time stays unavailable and the arrive-by comparison is not made. Leave-by uses the live bus ETA, the slow walk to the boarding stop, and a 45-second buffer. A leave-now notification can fire 60 seconds before that leave-by time while this tab is open. If that bus becomes a poor catch, the page can switch to a better direct bus and keep the same destination stop. The explanation card uses those same numbers.

## Run

With the virtual environment activated:

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. You should see the Bus Catch Assistant home page.

On startup the server looks for `cache/bus_stops.json`, `cache/bus_routes.json`, and `cache/bus_services.json`.

- If those files are already a valid cache, the server uses them and does not download again. The log warns that current static LTA updates were not fetched. That warning is about the static cache, not live arrivals.
- If no valid cache exists, the server downloads BusStops, BusRoutes, and BusServices from LTA DataMall and writes those files.
- If that first download fails, the server stops and reports the static data as unavailable. It does not invent stops or frequencies.

### Train timetable (optional, for MRT and LRT legs)

`cache/rail_timetable.json` holds the first and last train and the headway for every station, direction and day type. It is built from the LTA train GTFS (DataMall guide 2.31, `GTFSScheduleTrain`). The command makes no network call and needs no key: download the zip yourself, unzip it into a folder, then run

    .venv\Scripts\python build_rail_timetable.py tmp\gtfs_train

The folder (or a .zip) is the first argument. `--out` changes the target, `--today YYYY-MM-DD` sets the build date, `--allow-expired` builds from a feed whose end date has passed. The table is written to a temporary file, checked, and only then moved into place; the old one is kept as `rail_timetable.json.bak`, and a table that fails the checks never replaces it. Without the file the server still runs: train legs have no direction and use the fallback headway of 300 s in the weekday peak and 420 s otherwise. Rebuild it monthly and when LTA announces a change. The menu shows the build date and `Contains information from LTA DataMall under the Singapore Open Data Licence v1.0`.

The map uses Leaflet and OpenStreetMap. Distances are straight-line, not a walking route. After you choose a stop and one service, the page polls live arrivals every 20 seconds and shows the catch probability returned by the server. A fresh poll also updates the leave-by clock. A stale or unavailable arrival does not keep a precise leave-by time.

## Multi-leg journey

After a boarding stop is selected and a destination stop is confirmed, the page asks `/api/route-plan` for a bus route that starts at that boarding stop. The planner uses the cached stops, routes, and service frequencies. It does not call OneMap, OpenAI, or live arrivals. A direct route is one service from that stop to the confirmed destination stop. A one-transfer route changes to a second service at the same stop code. The chosen route is the lowest estimated journey time. A transfer adds a 10-minute ranking penalty and does not add a measured wait to leave-by or arrive-by. The catch chance, leave-by time, notification, and explanation describe only the leg in progress. The second bus stays a future leg, with no catch percentage, until you press `Start Next Leg`. That button is the only way the second leg becomes active. It clears the previous leg's reroute clock, pinned bus, notification memory, and explanation baseline, then the existing arrival poll scores the transfer stop and the second service. A one-transfer trip shows `Arrive-by check: N/A`. Automatic reroute stays off during that first leg and can run again on the second leg. If no direct or one-transfer connection exists, the page says: No direct or 1-transfer bus connection available for this trip. If a connection exists but its route distance cannot be timed, the page says: Route found, but travel time could not be estimated.

## Demo Mode

Demo Mode stays off unless `DEMO_MODE` is exactly `true`. An unset value, a blank value, `TRUE`, `True`, `1`, and `yes` all keep the normal live app. The page cannot turn Demo Mode on with a URL, a control, or saved browser state.

Set it for the process, then start the server:

```powershell
$env:DEMO_MODE = "true"
uvicorn main:app --host 127.0.0.1 --port 8000
```

A `DEMO_MODE=true` line in `.env` does the same thing. Any other value in that line leaves the app live.

While it is on, the page shows a `SIMULATED DEMO MODE` banner and a collapsible `Demo Controls` panel. Open the panel, choose one of the seven scenarios, and click `Run Scenario`. Click `Reset to Live` to drop the fixture. The banner and the panel stay, and the next provider call is live again. Reloading the page also drops the selected scenario. It does not turn Demo Mode off.

Arrival scenarios need a selected boarding stop and service, because they ride the normal 20-second poll. `Run Scenario` also requests one poll immediately when monitoring is already on.

- `LTA API Timeout / Proxy Error` fails the next Bus Arrival call. The page shows the usual unavailable state.
- `Stale Data Poll` returns a successful arrival whose age is greater than 120 seconds. The app still treats data older than 60 seconds as stale.
- `Schedule-Only / Monitored = 0` scores a schedule-only bus with the normal formula, including the published-frequency adjustment and the 60% high-end cap.
- `GPS Fix/Age Penalty` keeps the live arrival and substitutes a fix worse than 100 m and older than 60 seconds.
- `Auto-Reroute Opportunity` supplies arrival times that the normal reroute rules can switch. It needs a confirmed destination stop and a real fix that is already precise and fresh, because an uncertain fix still blocks a reroute.
- `OneMap Zero Results / API Error` affects the next destination search only. The first run returns no matches. Click `Run Scenario` again for the unavailable search error.
- `Unsafe / Contradictory OpenAI Output` affects the next explanation only. The first run uses blocked wording, the next run uses a contradictory reply, and the run after that simulates a timeout longer than 3 seconds. Each one still goes through the explanation checks and shows the usual fallback sentence.

A card that is showing fixture data is marked `[SIMULATED]`. Providers that are not part of the selected scenario stay live.

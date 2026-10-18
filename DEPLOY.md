# Deploying Just-In-Time on Render

A Python web service on Render's free tier. Names of settings only: never put a key in this file or in the repository.

## 0. Before you push

The server needs the static LTA bus data and the train timetable at start-up. They are small public files in `cache/`, and
`.gitignore` now lets exactly these four through (everything else in `cache/` stays ignored):

- `cache/bus_stops.json`, `cache/bus_routes.json`, `cache/bus_services.json` (about 8 MB together)
- `cache/rail_timetable.json`

Without them a fresh Render instance has no disk to fall back on: with no `LTA_ACCOUNT_KEY` it stops at start-up
("LTA static data is unavailable"), and with a key it downloads about a hundred pages on every cold start. Add them yourself
(nothing in this repo commits for you):

```
git add .gitignore cache/bus_stops.json cache/bus_routes.json cache/bus_services.json cache/rail_timetable.json
git add requirements.txt requirements-dev.txt .python-version DEPLOY.md README.md .env.example main.py observations.py tests/test_deploy.py
git commit -m "Deployable on Render"
git push
```

## 1. Create the service

1. Render dashboard, **New**, **Web Service**, connect your GitHub account and pick this repository.
2. **Language**: Python 3. **Branch**: the one you pushed.
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. **Instance type**: Free.
6. **Advanced, Health Check Path**: `/healthz`

## 2. Python version

The app needs Python 3.10 or newer (the libraries require it) and was tested on 3.14.7. `.python-version` in the repository
root pins `3.14.7`. You can also set it in Render: **Environment**, add `PYTHON_VERSION` = `3.14.7`. If Render does not offer that
exact version, choose the newest 3.13.x it lists (not tested here).

## 3. Environment variables (Render, Environment tab)

| Name | Needed? | What it does |
|---|---|---|
| `LTA_ACCOUNT_KEY` | Yes | LTA DataMall key: live bus arrivals, train service alerts, and the first-boot download if `cache/` is missing |
| `ONEMAP_EMAIL`, `ONEMAP_PASSWORD` | Yes, unless you set a token | Lets the server get a OneMap token for destination search, reverse geocoding and routing |
| `ONEMAP_TOKEN` | Optional | A OneMap token instead of email and password (they expire; the server renews with email and password) |
| `OPENAI_API_KEY` | Optional | Only for the written explanations |
| `AI_EXPLANATION_ENABLED` | Optional | `true` turns the model path on; anything else (the default) keeps it off |
| `OPENAI_MODEL` | Optional | Model name for the explanations (default `gpt-4o-mini`) |
| `DEMO_MODE` | Leave unset | Exactly `true` shows the simulated-demo banner and controls; never set it on a public service |
| `PYTHON_VERSION` | Optional | See section 2 |

Render sets `PORT` itself. Set the keys as **secret** values in Render's dashboard; the app never writes them to disk, logs or
responses.

## 4. Deploy and check

1. Press **Create Web Service** and watch the logs. A line like "Using cached static LTA bus stops and routes" is normal: it is the
   committed data being used.
2. Open `https://<your-service>.onrender.com/healthz`. It must show `{"status":"ok"}`.
3. Open the root URL: the Just-In-Time home page loads and asks for your location (HTTPS is on, so the browser allows it).
4. Open `/api/data-status`: it reports how current the bus and train data are.
5. Search for a place (needs the OneMap settings) and plan a route; pick a stop and watch live arrivals (needs the LTA key).

## 5. What to expect on the free tier

- The service **sleeps after about 15 minutes without traffic**. The next visit is a **cold start** of roughly a minute while
  Render wakes the instance and the app loads about 8 MB of data. Render's health check does not keep it awake.
- The disk is **ephemeral**. `observations.db` (the scored-poll log; it never stores your position) is lost on every restart or
  redeploy. If the disk cannot be written at all, the app skips the row and logs one warning; it never fails a request over it.
- Free instances have a monthly hour allowance and limited memory and CPU; check Render's current pricing page.

## 6. Privacy notes

- The app's own log strips your position and walking speed from request lines. **Render's proxy logs can still record full
  URLs**, query strings included. Do not share those logs.
- The page loads Leaflet from unpkg and map tiles from OpenStreetMap. OpenStreetMap's tile servers have a usage policy that does
  not suit heavy public traffic; for more than a demo, use a tile provider you have an agreement with.

## 7. Refreshing the data

- Bus stops, routes and services are a snapshot. To refresh: delete the three `cache/bus_*.json` files locally, run the app once with
  `LTA_ACCOUNT_KEY` set (it downloads and writes them), commit the new files and push.
- The train timetable is built from LTA's GTFS train feed: see "Train timetable" in the README.

## 8. If it does not start

- Log says "LTA static data is unavailable: LTA_ACCOUNT_KEY is missing and no local cache exists": the `cache/` files were not
  committed and no key is set. Commit them (section 0) or set `LTA_ACCOUNT_KEY`.
- Build fails on the Python version: set `PYTHON_VERSION` to one Render lists (section 2).
- Health check keeps failing: open `/healthz` directly; it needs no key and no data, so a failure means the app did not start.

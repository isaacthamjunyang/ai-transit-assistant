# Just-In-Time demo video

A vertical (1080 x 1920, 30 fps) demo of about 60 seconds, built with [Remotion](https://www.remotion.dev/) from real captures of the app.
Nothing here edits the app. Everything is under `video/`.

## Commands (run inside `video/`)

- `npm install` once.
- `npm run capture` records the twelve scenes into `assets/` (add scene numbers to record only some: `npm run capture -- 05 07`).
- `npm run preview` opens Remotion Studio.
- `npm run render` writes `out/just-in-time.mp4` (H.264). With `assets/music.mp3` it has music; without it the render is muted and
  says so.
- `npm run render:music` does the same into `out/just-in-time-music.mp4`, so a muted and a music version can sit side by side.
- `npm run typecheck` checks the TypeScript.

## How it is built

- **Capture** (`capture/`): the real app runs on a local port inside the existing test harness (`tests/page_runner.py`, a scripted
  OneMap, scripted LTA arrivals and a scripted train alert) on the app's real static data (`cache/`): real stop names and codes, real
  bus services, real MRT stations. One sample trip, from a made-up phone position near Lakeside to a made-up saved place "School"
  by Jurong East (`capture/world.py`). The only network traffic the page may use is OpenStreetMap map tiles (fixed zoom, only the
  tiles a scene shows, fetched once by the browser with a normal browser User-Agent and kept in `assets/tiles-cache/`, git-ignored);
  Leaflet is served from `node_modules`. Everything else is blocked. Headless Edge at
  390 x 844 CSS px, device scale 3, scripted touches. A loop of full-resolution screenshots is resampled to 30 fps and encoded to
  WebM (VP9) with the ffmpeg that ships with Remotion. Every server and browser it starts is stopped when a scene ends.
- **Theme**: `scripts/read-theme.mjs` reads the colours and the font from `static/theme.css` into `src/generated/theme.json`
  (the video has no palette of its own).
- **Timing**: every duration, easing, scene cut point and playback rate is in `src/constants.ts`. The captions, the hook text, the end
  card links (`{GITHUB_URL}`, `{APP_URL}`) and the optional audio file name are there too.
- **Music**: none is included and none is downloaded. Put a royalty-free track at `assets/music.mp3`: it is mixed in at volume 0.35
  with a 1 s fade in and a 2 s fade out, looped if it is shorter than the video and cut if it is longer. The numbers are in
  `src/constants.ts`.

Scene 07 runs on a frozen clock: the server's clock (every app module that reads `datetime.now()`) and the page's clock both stand at
9:00:00 PM and the sample bus is 8.0 minutes away, so the app's own rules give a bus at 9:08 PM and a Leave by time from the phone's
distance (leave by = bus time - walk - 135 s). `capture/world.py` (`freeze_clock`) and `capture/driver.mjs` (`freezeClock`) do it
without touching the app.

## Honesty

MRT times are described as scheduled only; only bus arrivals are called live. The get-off alert is shown with "Works while the app is
open". A small line under the phone says the captures use sample data. No flashing; captions are burned-in text.

## Licence

Remotion is source-available under its own licence, not an open-source one. Check https://www.remotion.pro/license for the current
terms (individuals and small teams are generally free; larger companies need a company licence).

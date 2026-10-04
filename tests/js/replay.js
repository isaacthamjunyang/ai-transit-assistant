/* Replays a recorded walk (tests/fixtures/*.json) through the real estimator, with a fake clock.
   Usage: node tests/js/replay.js <fixture.json>
   The raw motion values go in as motion events at 25 Hz (t = i / 25 s), one GPS fix per second
   (speed from the fixture, accuracy from the fixture, a fresh timestamp). The trace records the same
   columns as the debug trace, one row per second. Prints {header, constants, rows} as JSON.
   Nothing here mocks the cadence or the detection logic. */
"use strict";
const fs = require("fs");
const path = require("path");
const W = require(path.join(__dirname, "..", "..", "static", "walk-speed.js"));

const fixture = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const hz = fixture.hz;
const raw = fixture.raw_motion;
const speeds = fixture.gps_speed_mps;
const accuracy = fixture.gps_accuracy_m;
const seconds = fixture.seconds;

let now = 0;
const store = {
  "bus-catch-step-length": JSON.stringify({
    length: fixture.expected.learned_step_length_at_start_m, count: 3, savedAt: 0
  })
};
const storage = {
  getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); }
};
const est = W.createEstimator({
  win: null, nav: null, now: () => now, storage,
  timers: { set: () => 1, clear: () => {} }
});

est.traceStart();
for (let k = 0; k < seconds; k++) {
  for (let i = k * hz; i < (k + 1) * hz; i++) {
    const t = (i / hz) * 1000;
    now = t;
    est.ingestMotion({ t, acceleration: { x: raw[i], y: 0, z: 0 } });
  }
  now = (k + 1) * 1000;
  est.ingestFix({ t: now, lat: 1.3, lon: 103.8, accuracy, speed: speeds[k] });
  est.tick(now);
}
const lines = est.traceText().split("\n");
const header = lines[1].split(",");
const rows = lines.slice(2).map((line) => {
  const cells = line.split(",");
  const row = {};
  header.forEach((name, i) => { row[name] = cells[i]; });
  return row;
});
process.stdout.write(JSON.stringify({ constants: lines[0], header, rows }));

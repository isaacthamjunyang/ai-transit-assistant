import { poll, toLive } from "./common.mjs";

// Page W with Sensor details OPEN, in the cases of the walking speed: measured from GPS, from your steps (a normal
// cadence and a stride-doubled one, from the real estimateCadence), and no speed measured (Not walking yet, Near the
// stop, No motion permission). With config.shots a screenshot per case is written there (config.dark picks the theme).
const ROWS = `({
  rows: ["pace", "gpsSpeed", "gpsAccuracy", "cadence", "stepLength", "samples"].map(function (k) { return document.getElementById("walk-sensor-" + k).textContent; }),
  why: document.getElementById("walk-sensor-why").textContent, whyHidden: document.getElementById("walk-sensor-why").hidden,
  expanded: document.getElementById("walk-sensors-toggle").getAttribute("aria-expanded"), open: !document.getElementById("walk-sensors-panel").hidden,
  state: document.getElementById("walk-state").textContent,
  whyBeforeRows: !!(document.getElementById("walk-sensor-why").compareDocumentPosition(document.querySelector(".walk-sensors__list")) & Node.DOCUMENT_POSITION_FOLLOWING),
  whyIsFirstInPanel: document.getElementById("walk-sensors-panel").firstElementChild === document.getElementById("walk-sensor-why"),
  whyFont: parseFloat(getComputedStyle(document.getElementById("walk-sensor-why")).fontSize),
  captionFont: (function () { var e = document.createElement("p"); e.className = "note"; document.body.appendChild(e); var f = parseFloat(getComputedStyle(e).fontSize); e.remove(); return f; })(),
  bodyFont: parseFloat(getComputedStyle(document.getElementById("walk-sensor-pace")).fontSize),
  whyIcon: !!document.getElementById("walk-sensor-why").querySelector("svg.icon"),
  whySilent: !document.getElementById("walk-sensor-why").closest("[aria-live]") && !document.getElementById("walk-sensor-why").hasAttribute("aria-live")
})`;

export default async function (h) {
  const out = { cases: {} };
  const theme = h.config.dark ? "dark" : "light";
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  await h.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 1500, deviceScaleFactor: 1, mobile: true });
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  await h.sleep(500);
  // the REAL estimator: GPS-only walking gives a measured speed, the server answers source gps, then two polls near the
  // stop latch the estimator off. The last smoothed speed is still sent, so the walking pace keeps its value and source.
  await h.eval("document.getElementById('walk-sensors-toggle').click(); true");
  out.fresh = await h.eval(ROWS);
  await h.eval("__sim.start({ gps: true, gpsSpeed: 1.2, gpsAcc: 8, mode: 'still' }); true");
  await h.until("paceEstimator.snapshot().walking", 60000, "GPS-only walking");
  await poll(h);
  out.beforeLatch = Object.assign(await h.eval(ROWS), await h.eval("({ source: serverWalkSource, used: serverWalkSpeed, pollValue: paceEstimator.pollValue(), status: paceEstimator.status() })"));
  await h.eval("paceEstimator.noteNearStop(true); paceEstimator.noteNearStop(true); syncPaceEstimator(); renderWalkPage(); true");
  await poll(h);
  await h.sleep(300);
  out.afterLatch = Object.assign(await h.eval(ROWS), await h.eval("({ source: serverWalkSource, used: serverWalkSpeed, pollValue: paceEstimator.pollValue(), status: paceEstimator.status(), snapshot: paceEstimator.snapshot(), query: walkSpeedQuery() })"));
  await h.eval("__sim.stop(); true");
  // a real near-stop state: the user is 12 m from the stop (Arrived, full progress bar, map at zoom 19), the estimator
  // latched off, so the Sensor details show "Near the stop" with the frozen measured pace
  await h.eval(`userLat = ${h.config.lat} + 12 / 111195; userLon = ${h.config.lon}; userAccuracy = 8; userLocationTimestamp = Date.now(); __geo.set({ lat: userLat, lon: userLon, acc: 8 }); true`);
  await poll(h);  // the server sees the fix 12 m from the stop and answers near_stop, which is what makes the state Arrived
  await h.sleep(2200);
  out.nearStopPage = await h.eval(`({
    distance: document.querySelector(".walk-status__distance").textContent, state: document.getElementById("walk-state").textContent,
    progress: document.querySelector(".walk-progress").value, zoom: map.getZoom(), why: document.getElementById("walk-sensor-why").textContent,
    pace: document.getElementById("walk-sensor-pace").textContent, open: !document.getElementById("walk-sensors-panel").hidden
  })`);
  if (h.config.shots) {
    await h.eval("window.scrollTo(0, 0); true");
    await h.sleep(250);
    await h.screenshot(`${h.config.shots}/pageW-sensors-nearstop-${theme}-390.png`);
  }
  // the real estimator's cadence: a normal in-range rhythm, and a stride-only rhythm that is doubled
  out.cadence = await h.eval(`(function () {
    var fs = 25, normal = [], stride = [];
    for (var i = 0; i < fs * 8; i++) {
      var t = i / fs, phase = (t * 1.8) % 1;
      normal.push(3 * (phase < 0.5 ? Math.pow(Math.sin(Math.PI * phase / 0.5), 2) : 0));
      stride.push(Math.sin(2 * Math.PI * 1.0 * t) + 0.05 * Math.sin(2 * Math.PI * 7 * t));
    }
    var n = WalkSpeed.estimateCadence(normal, fs), s = WalkSpeed.estimateCadence(stride, fs);
    window.__cad = { normal: n.cadence, stride: s.cadence };
    return { normal: n.cadence, normalPick: n.pick, stride: s.cadence, stridePick: s.pick };
  })()`);
  const setup = (code) => h.eval(`(function () {
    var status = { running: true, wanted: true, latched: false, motion: "on", permission: "granted", stopReason: null };
    paceEstimator.status = function () { return status; };
    walkChanceSource.nearStop = false;
    ${code}
    renderWalkPage();
    document.getElementById("walk-sensors").scrollIntoView();
  })(); true`);
  // A rescore or poll that is already on its way carries the speed an earlier case injected and would write the server's
  // echo of it over the next case. No new request is sent while the cases are read.
  await h.eval("walkRescoreTick = function () {}; requestArrivals = function () {}; true");
  await h.sleep(1500);
  const cases = {
    gps: "serverWalkSource = 'gps'; serverWalkSpeed = 1.3; paceEstimator.snapshot = function () { return { gpsSpeed: 1.3, gpsAccuracy: 8, cadence: window.__cad.normal, stepLength: 0.72, stepCount: 4 }; };",
    steps: "serverWalkSource = 'cadence'; serverWalkSpeed = 1.2; paceEstimator.snapshot = function () { return { gpsSpeed: null, gpsAccuracy: 12, cadence: window.__cad.normal, stepLength: 0.67, stepCount: 6 }; };",
    stridesteps: "serverWalkSource = 'cadence'; serverWalkSpeed = 1.35; paceEstimator.snapshot = function () { return { gpsSpeed: null, gpsAccuracy: 12, cadence: window.__cad.stride, stepLength: 0.68, stepCount: 6 }; };",
    notwalking: "serverWalkSource = 'default'; serverWalkSpeed = 1.25; paceEstimator.snapshot = function () { return { gpsSpeed: null, gpsAccuracy: 8, cadence: null, stepLength: 0.70, stepCount: 0 }; };",
    nopermission: "serverWalkSource = 'default'; serverWalkSpeed = 1.25; status.permission = 'denied'; status.motion = 'off'; paceEstimator.snapshot = function () { return { gpsSpeed: 1.0, gpsAccuracy: 8, cadence: null, stepLength: 0.70, stepCount: 0 }; };"
  };
  for (const [name, code] of Object.entries(cases)) {
    await setup(code);
    await h.sleep(250);
    out.cases[name] = await h.eval(ROWS);
    if (h.config.shots) {
      await h.screenshot(`${h.config.shots}/pageW-sensors-${name}-${theme}-390.png`);
    }
  }
  return out;
}

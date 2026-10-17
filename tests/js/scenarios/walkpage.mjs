import { poll, toLive } from "./common.mjs";

// Page W in the real page: navigation, the state machine, the map markers, the watch, the rescore and Sensor details.
const SNAP = `(function () {
  var text = function (id) { var el = document.getElementById(id); return el ? el.textContent : null; };
  var slot = document.getElementById("walk-map-slot");
  var count = function (selector) { return slot ? slot.querySelectorAll(selector).length : 0; };
  var you = null;
  map.eachLayer(function (layer) { if (layer.options && layer.options.icon && layer.options.icon.options.className && layer.options.icon.options.className.indexOf("walk-you") !== -1) { you = layer.getLatLng(); } });
  var c = map.getCenter();
  return {
    top: screenStack[screenStack.length - 1], stack: screenStack.slice(),
    pageW: document.body.classList.contains("is-page-w"), pageA: document.body.classList.contains("is-page-a"),
    walkHidden: document.getElementById("walk-page").hidden,
    title: text("walk-title"), distance: text("walk-distance"), minutes: text("walk-minutes"), state: text("walk-state"),
    ring: text("walk-ring-text"), arrives: text("walk-arrives-time"), arrivesHidden: document.getElementById("walk-arrives").hidden, rangeElement: !!document.getElementById("walk-range"), cardText: document.getElementById("walk-ring").closest(".walk-chance").textContent, trend: text("walk-trend"), trendHidden: document.getElementById("walk-trend").hidden,
    heading: text("walk-chance-title"), progress: document.getElementById("walk-progress").value,
    mapInSlot: !!(slot && mapElement.parentNode === slot), you: count(".walk-you"), stop: count(".map-stop--live"),
    line: count(".walk-line"), accuracy: count(".walk-accuracy"), youLatLng: you ? [you.lat, you.lng] : null,
    center: [c.lat, c.lng], zoom: map.getZoom(), wedgeHidden: (function () { var w = slot && slot.querySelector(".walk-wedge"); return w ? w.classList.contains("is-hidden") : null; })(),
    watching: __geo.watching(), watchCalls: __geo.state.watchCalls, clearCalls: __geo.state.clearCalls, ownWatch: walkWatchId !== null,
    estimatorRunning: paceEstimator.status().running, bar: !document.getElementById("see-arrivals-bar").hidden,
    sensorsOpen: !document.getElementById("walk-sensors-panel").hidden
  };
})()`;

export default async function (h) {
  const out = {};
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  const stopLat = h.config.lat, stopLon = h.config.lon;
  const north = h.config.userNorth;
  out.pageA = await h.eval(`({ row: document.getElementById("walk-open").textContent.trim().replace(/\s+/g, " "),
    hasPaceLine: !!document.getElementById("catch-pace-line"),
    hasCaption: !!document.getElementById("catch-caption"), top: screenStack[screenStack.length - 1] })`);
  out.requestsBefore = await h.eval("__requests.length");

  // A to W
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  await h.sleep(300);
  out.open = await h.eval(SNAP);

  // the ring and the server's numbers
  out.chance = await h.eval("(function () { var hero = featuredBus(lastSuccess.buses); return { point: hero.probability.point, low: hero.probability.range_low, high: hero.probability.range_high, clock: formatClock(hero.arrival_time, false) }; })()");

  // state machine: approaching, not moving (direct fixes with explicit times), arrived (the server's near_stop)
  const seq = async (list) => {
    await h.eval(`walkSamples = []; walkLastFixT = null; userLocationTimestamp = null; true`);
    const states = [];
    for (const [ago, metresNorth, speed] of list) {
      await h.eval(`walkOnFix({ t: Date.now() - ${ago}, lat: ${stopLat} + ${metresNorth} / 111195, lon: ${stopLon}, accuracy: 8, heading: 180, speed: ${speed} }); true`);
      states.push(await h.eval("document.getElementById('walk-state').textContent"));
    }
    return states;
  };
  await h.eval("walkChanceSource.nearStop = false; true");
  out.approaching = await seq([[8000, 300, 1.3], [4000, 299, 1.3], [0, 291, 1.3]]);
  out.approachingAfter = await h.eval(SNAP);
  out.notMoving = await seq([[8000, 300, 0], [4000, 300, 0], [0, 299, 0]]);
  out.movingAway = await seq([[10000, 300, 1.3], [0, 330, 1.3]]);
  out.noFixText = await h.eval("userLat = null; userLon = null; renderWalkPage(); document.getElementById('walk-state').textContent");
  await seq([[0, 300, 1.3]]);

  // markers move, and the map is not re-fitted after a pan
  await h.eval("walkOnFix({ t: Date.now(), lat: " + stopLat + " + 300 / 111195, lon: " + stopLon + ", accuracy: 8, heading: 180, speed: 1.3 }); true");
  await h.eval("walkFitState = { done: false, distance: null }; walkUserMoved = false; renderWalkPage(); true");
  out.fitted = await h.eval(SNAP);
  await h.eval("mapElement.dispatchEvent(new Event('mousedown')); liveProgrammatic = true; map.setView([" + stopLat + " + 0.02, " + stopLon + " + 0.02], 14, { animate: false }); liveProgrammatic = false; true");
  out.panned = await h.eval(SNAP);
  await h.eval("walkOnFix({ t: Date.now() + 1000, lat: " + stopLat + " + 120 / 111195, lon: " + stopLon + ", accuracy: 8, heading: 180, speed: 1.3 }); true");
  out.afterPan = await h.eval(SNAP);
  await h.eval("document.getElementById('walk-recentre').click(); true");
  out.recentred = await h.eval(SNAP);

  // the arrow wedge: shown with a heading and a speed above 0.5 m/s, hidden without a heading
  out.wedgeMoving = out.recentred.wedgeHidden;
  await h.eval("walkOnFix({ t: Date.now() + 2000, lat: " + stopLat + " + 110 / 111195, lon: " + stopLon + ", accuracy: 8, heading: null, speed: 1.3 }); true");
  out.wedgeNoHeading = (await h.eval(SNAP)).wedgeHidden;
  await h.eval("walkOnFix({ t: Date.now() + 3000, lat: " + stopLat + " + 100 / 111195, lon: " + stopLon + ", accuracy: 8, heading: 90, speed: 0.2 }); true");
  out.wedgeSlow = (await h.eval(SNAP)).wedgeHidden;

  // arrived: a fix at the stop and the server's near_stop flag
  await h.eval("walkOnFix({ t: Date.now() + 4000, lat: " + stopLat + " + 10 / 111195, lon: " + stopLon + ", accuracy: 8, heading: 180, speed: 1.2 }); true");
  await poll(h);
  await h.sleep(200);
  out.arrived = await h.eval(SNAP);
  out.nearStopFlag = await h.eval("lastSuccess.near_stop");

  // Sensor details
  await h.eval("walkChanceSource.nearStop = false; paceEstimator.snapshot = function () { return { gpsSpeed: 1.3, gpsAccuracy: 8, cadence: 1.9, stepLength: 0.72, stepCount: 4 }; }; true");
  out.sensorsClosed = await h.eval(SNAP);
  await h.eval("document.getElementById('walk-sensors-toggle').click(); true");
  out.sensorsOpen = await h.eval(`({ open: !document.getElementById("walk-sensors-panel").hidden, expanded: document.getElementById("walk-sensors-toggle").getAttribute("aria-expanded"),
    rows: ["pace", "gpsSpeed", "gpsAccuracy", "cadence", "stepLength", "samples"].map(function (k) { return document.getElementById("walk-sensor-" + k).textContent; }),
    why: document.getElementById("walk-sensor-why").textContent, whyHidden: document.getElementById("walk-sensor-why").hidden, source: serverWalkSource })`);

  // the trend from consecutive server values, shown only after a change of 2 points or more
  out.trendSeq = {};
  const setState = (state) => h.eval(`(function () {
    var end = userLocationTimestamp || Date.now();
    walkChanceSource.nearStop = false;
    var d = { onway: [300, 280], away: [300, 320], still: [300, 300] }[${JSON.stringify(state)}];
    walkSamples = [{ t: end - 12000, d: d[0] }, { t: end, d: d[1] }];
    walkLastFixT = userLocationTimestamp;
    walkTrend = { anchor: null, text: null, calm: 0 };
    renderWalkPage();
  })(); true`);
  for (const state of ["onway", "away", "still"]) {
    await setState(state);
    out.trendSeq[state] = [];
    for (const point of [60, 61, 64, 64, 64, 60]) {
      await h.eval(`walkSamples = walkSamples.slice(); walkNotePoll({ near_stop: false, buses: [Object.assign({}, featuredBus(lastSuccess.buses), { probability: Object.assign({}, featuredBus(lastSuccess.buses).probability, { point: ${point}, range_low: ${point} - 5, range_high: ${point} + 5 }) })] }); true`);
      out.trendSeq[state].push(await h.eval(`({ ring: document.getElementById("walk-ring-text").textContent, cardText: document.getElementById("walk-ring").closest(".walk-chance").textContent, trend: document.getElementById("walk-trend").textContent, hidden: document.getElementById("walk-trend").hidden, state: document.getElementById("walk-state").textContent })`));
    }
  }
  await h.eval("walkNotePoll(lastSuccess); true");
  // Demo Mode shows the [SIMULATED] tag
  out.simulatedOff = await h.eval("document.getElementById('walk-simulated').hidden");
  await h.eval("document.getElementById('demo-banner').hidden = false; renderWalkPage(); true");
  out.simulatedOn = await h.eval("!document.getElementById('walk-simulated').hidden");
  await h.eval("document.getElementById('demo-banner').hidden = true; renderWalkPage(); true");
  // poor accuracy: a big accuracy circle that never fills the map, and the existing uncertain-location card
  await h.eval("walkOnFix({ t: Date.now() + 5000, lat: " + stopLat + " + 200 / 111195, lon: " + stopLon + ", accuracy: 150, heading: null, speed: null }); true");
  await poll(h);
  out.poorAccuracy = await h.eval(`(function () {
    var size = map.getSize();
    var mpp = 156543.03392 * Math.cos(userLat * Math.PI / 180) / Math.pow(2, map.getZoom());
    return { radius: walkAccuracy.getRadius(), cap: Math.min(size.x, size.y) * 0.3 * mpp, accuracy: userAccuracy,
      card: !document.getElementById("location-card").hidden, cardTitle: document.getElementById("location-card-title").textContent };
  })()`);
  await h.eval("walkOnFix({ t: Date.now() + 6000, lat: " + stopLat + " + 150 / 111195, lon: " + stopLon + ", accuracy: 8, heading: null, speed: null }); true");
  // stale data keeps the layout: the ring reads Unavailable
  out.staleRing = await h.eval("displayFrozen = true; renderWalkPage(); var r = { ring: document.getElementById('walk-ring-text').textContent, arrivesHidden: document.getElementById('walk-arrives').hidden, arrives: document.getElementById('walk-arrives-time').textContent, pill: document.getElementById('walk-pill-text').textContent }; displayFrozen = false; renderWalkPage(); r");

  // the rescore: about every 5 s, only while Page W is open and visible; no position in any other new request
  await h.eval("walkLastRescoreAt = 0; walkRescoreBusy = false; true");
  const before = await h.eval("__requests.length");
  await h.eval("walkRescoreTick(); true");
  await h.sleep(500);
  out.rescoreUrls = await h.eval(`__requests.slice(${before}).filter(function (u) { return u.indexOf('/api/rescore') === 0; })`);
  await h.eval("walkRescoreTick(); true");
  out.rescoreSecondCall = await h.eval(`__requests.slice(${before}).filter(function (u) { return u.indexOf('/api/rescore') === 0; }).length`);
  await h.eval("__setHidden(true); walkLastRescoreAt = 0; walkRescoreBusy = false; true");
  const hiddenBefore = await h.eval("__requests.length");
  await h.eval("walkRescoreTick(); true");
  await h.sleep(300);
  out.rescoreWhileHidden = await h.eval(`__requests.slice(${hiddenBefore}).filter(function (u) { return u.indexOf('/api/rescore') === 0; }).length`);
  out.timerWhileHidden = await h.eval("walkRescoreTimer !== null");
  await h.eval("__setHidden(false); true");
  out.timerWhenVisible = await h.eval("walkRescoreTimer !== null");

  // the page's own watch: only when the estimator's watch is not feeding fixes; options high accuracy
  out.watchWithEstimator = await h.eval("({ own: walkWatchId !== null, watching: __geo.watching() })");
  await h.eval("paceJourneyActive = false; syncPaceEstimator(); syncWalkPage(); true");
  await h.sleep(200);
  out.watchOwn = await h.eval("({ own: walkWatchId !== null, watching: __geo.watching(), options: __geo.state.watchOptions.slice(-1)[0], estimator: paceEstimator.status().running })");
  await h.eval("__setHidden(true); true");
  out.watchHidden = await h.eval("({ own: walkWatchId !== null, watching: __geo.watching() })");
  await h.eval("__setHidden(false); true");
  out.watchShown = await h.eval("({ own: walkWatchId !== null, watching: __geo.watching() })");

  // A to W to B, and Back
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 5000, "Page B");
  out.pageB = await h.eval(SNAP);
  await h.eval("requestBack(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Back to Page W");
  out.backToW = await h.eval(SNAP);
  await h.eval("requestBack(); true");
  await h.until("screenStack[screenStack.length - 1] === 'live'", 5000, "Back to Page A");
  out.backToA = await h.eval(SNAP);
  out.dialogOpen = await h.eval("!document.getElementById('leave-dialog').hidden");

  // the end of tracking stops the page's watch and timer
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W again");
  await h.eval("paceJourneyActive = false; syncPaceEstimator(); syncWalkPage(); true");
  await h.sleep(150);
  out.beforeEnd = await h.eval("({ own: walkWatchId !== null, timer: walkRescoreTimer !== null })");
  await h.eval("stopTracking(); true");
  out.afterEnd = await h.eval("({ own: walkWatchId !== null, timer: walkRescoreTimer !== null, watching: __geo.watching() })");

  out.requestsAll = await h.eval("__requests.slice()");
  out.storageKeys = await h.eval("Object.keys(localStorage).filter(function (k) { return k !== 'bus-catch-first-run-v2'; })");
  return out;
}

import { poll, toLive } from "./common.mjs";

// The approved Page W design (tmp/design/pagew-v2.html) in the real page: the order of its parts, the states, the distance
// card, the chance card, the back button and the sensor details. config: width, dark, kind ("bus" | "train").
const GEOM = `(function () {
  var box = function (el) { var r = el.getBoundingClientRect(); return { top: Math.round((r.top + window.scrollY) * 10) / 10, left: r.left, right: r.right, height: Math.round(r.height * 10) / 10, width: Math.round(r.width * 10) / 10 }; };
  var id = function (name) { return document.getElementById(name); };
  return {
    back: box(id("walk-back")), title: box(id("walk-title")), ring: box(id("walk-ring")), chance: box(document.querySelector(".walk-chance")),
    status: box(document.querySelector(".walk-status")), map: box(id("walk-map-slot")), sensors: box(id("walk-sensors")),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

const STATE = `(function () {
  var cs = function (el, prop) { return getComputedStyle(el)[prop]; };
  var id = function (name) { return document.getElementById(name); };
  var alertEl = id("walk-state-alert");
  var kind = ["neutral", "info", "success", "warning", "error"].filter(function (k) { return alertEl.classList.contains("alert--" + k); });
  var value = id("walk-distance-value"), label = id("walk-distance-label");
  return {
    text: id("walk-state").textContent, kind: kind, alertIcon: !!alertEl.querySelector(".alert__icon") && alertEl.querySelector(".alert__icon").childNodes.length > 0,
    isAlert: alertEl.classList.contains("alert"), alertBg: cs(alertEl, "backgroundColor"), alertColor: cs(id("walk-state"), "color"), alertBorder: cs(alertEl, "borderTopColor"),
    distance: id("walk-distance").textContent, value: value.textContent, label: label.textContent,
    valueSize: parseFloat(cs(value, "fontSize")), valueWeight: cs(value, "fontWeight"), labelSize: parseFloat(cs(label, "fontSize")),
    valueColor: cs(value, "color"), band: cs(document.querySelector(".walk-band"), "backgroundColor"), bandIcon: cs(document.querySelector(".walk-band__icon"), "color"),
    minutes: id("walk-minutes").textContent.trim(), minutesIcon: !!id("walk-minutes").querySelector(".icon"),
    progress: id("walk-progress").value, progressHeight: id("walk-progress").getBoundingClientRect().height,
    geom: ${GEOM}
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = { states: {} };
  await toLive(h, { permission: "granted", width: c.width, height: 800, dark: c.dark });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  await h.sleep(500);

  // the page's parts, in order
  out.order = await h.eval(`(function () {
    var ids = ["walk-back", "walk-title", "walk-ring", "walk-state-alert", "walk-map-slot", "walk-sensors"];
    var nodes = ids.map(function (n) { return document.getElementById(n); });
    return nodes.every(function (n, i) { return i === 0 || !!(nodes[i - 1].compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING); });
  })()`);
  out.globalBack = await h.eval(`getComputedStyle(document.getElementById("back-bar")).display`);
  out.backButton = await h.eval(`(function (el) { var s = getComputedStyle(el), r = el.getBoundingClientRect();
    return { background: s.backgroundColor, color: s.color, border: s.borderTopColor, borderWidth: s.borderTopWidth, radius: s.borderTopLeftRadius,
      w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10, label: el.getAttribute("aria-label"), tag: el.tagName }; })(document.getElementById("walk-back"))`);
  out.menuButton = await h.eval(`(function (el) { var s = getComputedStyle(el), r = el.getBoundingClientRect();
    return { background: s.backgroundColor, color: s.color, border: s.borderTopColor, borderWidth: s.borderTopWidth, radius: s.borderTopLeftRadius,
      w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 }; })(document.getElementById("menu-open"))`);
  out.title = await h.eval(`(function (el) { var s = getComputedStyle(el); return { size: parseFloat(s.fontSize), weight: s.fontWeight, text: el.textContent }; })(document.getElementById("walk-title"))`);

  // the six states
  const target = await h.eval(`(function () { var s = selectedBoardingStop; return [Number(s.lat !== undefined ? s.lat : s.latitude), Number(s.lon !== undefined ? s.lon : s.longitude)]; })()`);
  const [stopLat, stopLon] = target;
  const setState = (name) => h.eval(`(function () {
    var end = userLocationTimestamp || Date.now();
    walkChanceSource.nearStop = false;
    var d = { onway: [300, 280], away: [300, 320], still: [300, 300] }[${JSON.stringify(name)}];
    if (d) { walkSamples = [{ t: end - 12000, d: d[0] }, { t: end, d: d[1] }]; }
    if (${JSON.stringify(name)} === "checking") { walkSamples = [{ t: end - 3000, d: 300 }, { t: end, d: 299 }]; }
    if (${JSON.stringify(name)} === "arrived") { walkChanceSource.nearStop = true; }
    walkLastFixT = userLocationTimestamp;
    walkTrend = { anchor: null, text: null, calm: 0 };
    renderWalkPage();
  })(); true`);
  await h.eval(`walkOnFix({ t: Date.now(), lat: ${stopLat} + 300 / 111195, lon: ${stopLon}, accuracy: 8, heading: 180, speed: 1.3 }); true`);
  for (const name of ["onway", "checking", "away", "still", "arrived"]) {
    await setState(name);
    await h.sleep(120);
    out.states[name] = await h.eval(STATE);
  }
  // waiting: no fix at all
  await h.eval(`(function () { window.__saved = [userLat, userLon]; userLat = null; userLon = null; renderWalkPage(); })(); true`);
  out.states.waiting = await h.eval(STATE);
  await h.eval(`userLat = window.__saved[0]; userLon = window.__saved[1]; true`);
  await setState("onway");

  // a long distance still fits the big number (the widest text, at the narrowest width)
  await h.eval(`walkOnFix({ t: Date.now() + 500, lat: ${stopLat} + 12500 / 111195, lon: ${stopLon}, accuracy: 8, heading: 180, speed: 1.3 }); true`);
  await h.sleep(150);
  out.far = await h.eval(`(function () { var v = document.getElementById("walk-distance-value"), b = document.querySelector(".walk-band");
    return { text: v.textContent, valueRight: v.getBoundingClientRect().right, bandRight: b.getBoundingClientRect().right,
      scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }; })()`);
  await h.eval(`walkOnFix({ t: Date.now() + 1000, lat: ${stopLat} + 300 / 111195, lon: ${stopLon}, accuracy: 8, heading: 180, speed: 1.3 }); true`);
  await setState("onway");

  // the chance card: the vehicle marker and badge, the time under its label
  out.vehicle = await h.eval(`(function () {
    var leg = document.getElementById("walk-leg"), node = document.getElementById("walk-node"), line = document.getElementById("walk-line");
    var label = document.querySelector("#walk-arrives .catch-card__arrives-label").getBoundingClientRect(), time = document.getElementById("walk-arrives-time").getBoundingClientRect();
    var ring = document.getElementById("walk-ring").getBoundingClientRect();
    var tokens = getComputedStyle(document.documentElement);
    return { cls: leg.className, ringShadow: getComputedStyle(node).boxShadow, nodeSvg: !!node.querySelector("svg"), badge: line.textContent.trim(),
      badgeClass: line.firstElementChild ? line.firstElementChild.className : "", timeBelowLabel: time.top >= label.bottom - 1,
      timeSize: parseFloat(getComputedStyle(document.getElementById("walk-arrives-time")).fontSize), ringSize: ring.width,
      neutral: tokens.getPropertyValue("--ring-neutral").trim(), ns: tokens.getPropertyValue("--line-ns").trim(),
      pill: document.getElementById("walk-pill-text").textContent, ringText: document.getElementById("walk-ring-text").textContent,
      title: document.getElementById("walk-chance-title").textContent };
  })()`);

  // one rescore first, so the trend has a value to compare with when the chance rises on arrival
  await h.eval(`walkTrend = { anchor: null, text: null, calm: 0 }; walkLastRescoreAt = 0; walkRescoreTick(); true`);
  await h.sleep(1200);
  // arrived at the stop: within 30 m, the server's near_stop answer, and the trend with its icon
  await h.eval(`(function () {
    var lat = ${stopLat} + 12 / 111195, lon = ${stopLon};
    __geo.set({ lat: lat, lon: lon, acc: 8 });
    walkOnFix({ t: Date.now() + 5000, lat: lat, lon: lon, accuracy: 8, heading: null, speed: null });
  })(); true`);
  try {
    await h.until(`document.getElementById("walk-state").textContent.indexOf("Arrived") === 0`, 12000, "the Arrived state");
  } catch (e) { /* recorded below */ }
  await h.sleep(900);
  out.arrived = await h.eval(`(function () {
    var t = document.getElementById("walk-trend"), cs = getComputedStyle(t);
    return { state: document.getElementById("walk-state").textContent, ring: document.getElementById("walk-ring-text").textContent,
      trendShown: !t.hidden && t.getClientRects().length > 0, trendText: document.getElementById("walk-trend-text").textContent, trendIcon: !!t.querySelector("svg"),
      trendColor: cs.color, trendClass: t.className, progress: document.getElementById("walk-progress").value };
  })()`);

  // Sensor details: opening it moves nothing above it
  await setState("onway");
  const before = await h.eval(GEOM);
  await h.eval(`paceEstimator.snapshot = function () { return { gpsSpeed: 1.3, gpsAccuracy: 8, cadence: 1.9, stepLength: 0.72, stepCount: 4 }; }; true`);
  await h.eval(`document.getElementById("walk-sensors-toggle").click(); true`);
  await h.sleep(200);
  out.sensors = await h.eval(`(function () {
    var cs = function (el, p) { return getComputedStyle(el)[p]; };
    var toggle = document.getElementById("walk-sensors-toggle"), why = document.getElementById("walk-sensor-why");
    return { open: !document.getElementById("walk-sensors-panel").hidden, expanded: toggle.getAttribute("aria-expanded"),
      toggleHeight: toggle.getBoundingClientRect().height, toggleSize: parseFloat(cs(toggle, "fontSize")), toggleWeight: cs(toggle, "fontWeight"),
      whyIsAlert: why.classList.contains("alert") && why.classList.contains("alert--info"), whyShown: !why.hidden, whyText: document.getElementById("walk-sensor-why-text").textContent,
      whyIcon: why.querySelector(".alert__icon") ? why.querySelector(".alert__icon").childNodes.length > 0 : false,
      rows: ["pace", "gpsSpeed", "gpsAccuracy", "cadence", "stepLength", "samples"].map(function (k) { return document.getElementById("walk-sensor-" + k).textContent; }),
      scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
  })()`);
  const after = await h.eval(GEOM);
  out.sensorShift = { before, after };
  return out;
}

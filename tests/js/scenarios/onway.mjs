import { openHome, planOverview, tapStart } from "./common.mjs";

// The On your way screen: progress, the "Next:" line and the "Get off" alert, driven in the real page.
// config: mode ("progress" | "alert" | "fallback" | "privacy" | "ends" | "layout"), width, height, dark, bus (a bus first
// journey), notify ("granted" | "default"), stages (minutes from planning, "progress"), shots (a folder for screenshots).
// The page clock is skewed with Date.now() so the schedule can be walked through without waiting.

const SNAP = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#on-way-timeline > li"), function (li) {
    return {
      cls: li.className, text: text(li), done: !!li.querySelector(".step-node--done"),
      nodes: li.querySelectorAll(".step-node").length, bar: !!li.querySelector(".journey-step__bar"),
      badge: li.querySelector(".line-badge") ? text(li.querySelector(".line-badge")) : null,
      titles: Array.prototype.map.call(li.querySelectorAll(".journey-step__title"), text)
    };
  });
  var next = document.getElementById("on-way-next");
  var alertBox = document.getElementById("on-way-alert");
  return {
    rows: rows, next: next.hidden ? null : text(next),
    alert: alertBox.hidden ? null : text(document.getElementById("on-way-alert-text")),
    alertVisible: !alertBox.hidden && getComputedStyle(alertBox).display !== "none",
    watching: __geo.watching(), reading: onWayReading, reads: __geo.state.getCalls, timer: onWayTimer != null, over: onWayState ? onWayState.over : null,
    screen: screenStack[screenStack.length - 1],
    privacy: document.getElementById("on-way-privacy").hidden ? null : text(document.getElementById("on-way-privacy")),
    open: document.getElementById("on-way-open-note").hidden ? null : text(document.getElementById("on-way-open-note")),
    notes: (window.__notes || []).slice(), asked: window.__asked || 0,
    title: text(document.getElementById("on-way-title")), planNew: !document.getElementById("on-way-plan-new").hidden,
    arrive: !!document.querySelector("#on-way .arrive-box"),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    endMs: onWayState ? onWayState.endMs : null, now: Date.now()
  };
})()`;

async function toOnWay(h, c, opts = {}) {
  if (!opts.reuse) {
    await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  }
  await h.eval(`if (window.__skewed) { window.__skew = 0; }  // a new trip starts on the real clock again
    window.__notes = [];
    window.__asked = 0;
    var Fake = function (title) { window.__notes.push(String(title)); };
    Fake.permission = ${JSON.stringify(c.notify || "granted")};
    Fake.requestPermission = function () { window.__asked += 1; return Promise.resolve("denied"); };
    window.Notification = Fake;
    true`);
  await planOverview(h);
  await tapStart(h);
  await h.until(c.bus ? "lastSuccess && !entryPending" : "lastSuccess && !entryPending", 15000, "the first poll");
  await h.sleep(300);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 5000, "Page B");
  await h.sleep(300);
  if (opts.demo) {
    await h.eval("document.getElementById('demo-banner').hidden = false; true");
  }
  if (opts.noPosition) {
    await h.eval("__geo.setMode('fail'); true");  // every read of the position fails from here on
  } else {
    // the phone is far (5 km) from every stop when it is on the screen, so nothing fires before a test moves it
    await h.eval(`__geo.set({ lat: ${c.userNorth[0]} - 0.045, lon: ${c.userNorth[1]}, acc: 8 }); true`);
  }
  await h.eval(`if (!window.__skewed) {
      window.__skewed = true;
      window.__skew = 0;
      var realNow = Date.now.bind(Date);
      Date.now = function () { return realNow() + window.__skew; };
    }
    true`);
  await h.eval("document.getElementById('catch-yes').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'onway'", 5000, "the On your way screen");
  await h.sleep(300);
}

// a point `metres` south of (lat, lon): along a meridian the page's own haversine gives exactly that distance
const SOUTH = `function south(point, metres) {
  return { lat: point[0] - metres / (6371000 * Math.PI / 180), lon: point[1] };
}`;

async function legTarget(h, index) {
  return h.eval(`(function () {
    var step = onWayState.steps.filter(function (s) { return s.type === "transit"; })[${index}];
    var stops = legLatLngs(step.leg);
    return { target: stops[stops.length - 1], endMs: step.endMs, startMs: step.startMs, code: step.leg.alighting_stop_code };
  })()`);
}

async function skewTo(h, epochMs) {
  await h.eval(`window.__skew = ${epochMs} - (Date.now() - window.__skew); true`);
}

async function tick(h) {
  await h.eval("onWayTick(); true");
}

// the phone is `metres` south of the target (8 m east besides: a longitude no stop has); the page reads it on its next read
async function pushAt(h, target, metres, extra = {}) {
  await h.eval(`${SOUTH}
    var p = south(${JSON.stringify(target)}, ${metres});
    __geo.set({ lat: p.lat, lon: p.lon + 0.00007, acc: ${extra.acc ?? 8} });
    onWayReadAt = 0;
    onWayTick();
    true`);
  await h.sleep(120);
}

export default async function (h) {
  const c = h.config;
  const out = {};
  if (c.mode === "noplan") {
    // a bus chosen from its service chip: no itinerary and no route plan, so no leg details
    await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
    await h.eval(`window.__notes = [];
      var Fake = function (title) { window.__notes.push(String(title)); };
      Fake.permission = "granted";
      window.Notification = Fake;
      selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
      confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination"};
      selectedBoardingStop = {stop_code: "${c.origin}", description: "Origin", services: ["18"], latitude: ${c.lat}, longitude: ${c.lon}};
      true`);
    await h.eval("chooseService('18'); true");
    await h.until("monitoringActive === true && lastSuccess && !entryPending", 15000, "the first poll");
    out.noPlan = await h.eval("({ plan: activeRoutePlan, itinerary: pendingItinerary })");
    await h.eval("pushScreen('arrivals'); true");
    await h.until("!document.getElementById('catch-bar').hidden", 10000, "the catch question");
    out.reads = await h.eval("__geo.state.getCalls");
    out.sentBefore = await h.eval("__sent.length");
    await h.eval("document.getElementById('catch-yes').click(); true");
    await h.until("screenStack[screenStack.length - 1] === 'onway'", 5000, "the On your way screen");
    out.reads0 = await h.eval("__geo.state.getCalls");
    out.t0 = await h.eval(SNAP);
    // the phone is at the stop, the clock is long past: still no alert, still no read
    await h.eval(`__geo.set({ lat: ${c.lat}, lon: ${c.lon}, acc: 8 }); onWayReadAt = 0; onWayTick(); true`);
    await h.sleep(300);
    await h.eval("window.__skew = 0; var real = Date.now.bind(Date); Date.now = function () { return real() + 30 * 60000; }; onWayTick(); true");
    await h.sleep(300);
    out.later = await h.eval(SNAP);
    out.reads1 = await h.eval("__geo.state.getCalls");
    out.sentAfter = await h.eval("__sent.slice(" + out.sentBefore + ").map(function (e) { return e.url + ' ' + e.body; })");
    out.firstRow = await h.eval(`(function () {
      var li = document.querySelector("#on-way-timeline > li");
      return { cls: li.className, nodes: li.querySelectorAll(".step-node").length, bar: !!li.querySelector(".journey-step__bar"),
        titles: Array.prototype.map.call(li.querySelectorAll(".journey-step__title"), function (e) { return e.textContent.trim(); }),
        badge: li.querySelector(".line-badge").textContent.replace(/[ \\t\\r\\n]+/g, " ").trim(),
        text: li.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() };
    })()`);
    return out;
  }

  if (c.mode === "progress") {
    await toOnWay(h, c);
    out.t0 = await h.eval(SNAP);
    out.timerRuns = await h.eval("onWayTimer != null");
    out.stages = [];
    const base = await h.eval("Date.now() - window.__skew");
    for (const minutes of c.stages) {
      await skewTo(h, base + minutes * 60000);
      await tick(h);
      const snap = await h.eval(SNAP);
      snap.minutes = minutes;
      out.stages.push(snap);
    }
    return out;
  }

  if (c.mode === "alert") {
    await toOnWay(h, c);
    out.t0 = await h.eval(SNAP);
    const first = await legTarget(h, 0);
    out.first = first;
    out.readOptions = await h.eval("__geo.state.options.map(function (o, i) { return { maximumAge: o.maximumAge, timeout: o.timeout, high: __geo.state.highs[i] }; })");
    out.startReads = await h.eval("__geo.state.getCalls");
    await pushAt(h, first.target, 401);
    out.at401 = await h.eval(SNAP);
    await pushAt(h, first.target, 399);
    out.at399 = await h.eval(SNAP);
    await pushAt(h, first.target, 300);
    await pushAt(h, first.target, 399);
    out.again = await h.eval(SNAP);
    await h.eval("document.getElementById('on-way-alert-dismiss').click(); true");
    out.dismissed = await h.eval(SNAP);
    await pushAt(h, first.target, 120);
    out.afterDismiss = await h.eval(SNAP);
    if (c.second) {
      const second = await legTarget(h, 1);
      out.second = second;
      await skewTo(h, second.startMs + 60000);
      await tick(h);
      await pushAt(h, second.target, 401);
      out.second401 = await h.eval(SNAP);
      await pushAt(h, second.target, 399);
      out.second399 = await h.eval(SNAP);
    }
    return out;
  }

  if (c.mode === "fallback") {
    await toOnWay(h, c, { noPosition: true });
    const first = await legTarget(h, 0);
    out.first = first;
    out.noFix = await h.eval(SNAP);
    await skewTo(h, first.endMs - 150000);
    await tick(h);
    out.at150 = await h.eval(SNAP);
    await skewTo(h, first.endMs - 119000);
    await tick(h);
    out.at119 = await h.eval(SNAP);
    // a usable position wins over the clock: a far, accurate fix read a little before the 2 minute mark, then the
    // clock passes it; no alert while that fix says the stop is far away
    await h.eval("document.getElementById('on-way-alert-dismiss').click(); onWayState.alerted = {}; __geo.setMode('ok'); true");
    await skewTo(h, first.endMs - 130000);
    await pushAt(h, first.target, 5000);
    out.farFixEarly = await h.eval(SNAP);
    await skewTo(h, first.endMs - 105000);
    await tick(h);
    out.farFix = await h.eval(SNAP);
    // a poor fix (500 m of accuracy) is no position: the clock decides again
    await pushAt(h, first.target, 5000, { acc: 500 });
    out.poorFix = await h.eval(SNAP);
    return out;
  }

  if (c.mode === "privacy") {
    await toOnWay(h, c);
    out.layout = await h.eval(SNAP);
    out.before = await h.eval("({ userLat: userLat, userLon: userLon, sent: __sent.length, requests: __requests.length })");
    const first = await legTarget(h, 0);
    const pushed = [];
    for (const metres of [2000, 900, 399, 120]) {
      await pushAt(h, first.target, metres);
      pushed.push(await h.eval("({ lat: __geo.state.current.lat, lon: __geo.state.current.lon })"));
    }
    out.pushed = pushed;
    out.reads = await h.eval("__geo.state.getCalls");
    await h.sleep(2500);  // real one-second ticks run too
    await h.eval("__setHidden(true); true");
    await h.eval("__setHidden(false); true");
    await pushAt(h, first.target, 50);
    pushed.push(await h.eval("({ lat: __geo.state.current.lat, lon: __geo.state.current.lon })"));
    await skewTo(h, out.layout.endMs + 5000);
    await tick(h);
    out.after = await h.eval("({ userLat: userLat, userLon: userLon, sent: __sent.slice(" + out.before.sent + "), requests: __requests.slice(" + out.before.requests + ") })");
    out.stores = await h.eval(`(function () {
      var dump = {};
      try { dump.local = JSON.stringify(Object.assign({}, window.localStorage)); } catch (e) { dump.local = ""; }
      try { dump.session = JSON.stringify(Object.assign({}, window.sessionStorage)); } catch (e) { dump.session = ""; }
      dump.cookie = document.cookie;
      dump.href = location.href;
      return dump;
    })()`);
    out.final = await h.eval(SNAP);
    return out;
  }

  if (c.mode === "ends") {
    out.runs = {};
    const conditions = ["planNew", "hidden", "pagehide", "end", "back", "demo"];
    for (let i = 0; i < conditions.length; i += 1) {
      const which = conditions[i];
      await toOnWay(h, c, { reuse: i > 0, demo: which === "demo" });
      const run = { start: await h.eval(SNAP) };
      const first = await legTarget(h, 0);
      if (which === "planNew") {
        await h.eval("document.getElementById('on-way-plan-new').click(); true");
      } else if (which === "hidden") {
        await h.eval("__setHidden(true); true");
        run.whileHidden = await h.eval(SNAP);
        await h.eval("__setHidden(false); true");
        run.shownAgain = await h.eval(SNAP);
        await h.eval("requestBack(); true");
      } else if (which === "pagehide") {
        await h.eval("window.dispatchEvent(new Event('pagehide')); true");
      } else if (which === "end") {
        await skewTo(h, run.start.endMs + 2000);
        await tick(h);
      } else if (which === "back") {
        await h.eval("requestBack(); true");
      } else if (which === "demo") {
        await pushAt(h, first.target, 399);
        run.demoPush = await h.eval(SNAP);
        await skewTo(h, first.endMs - 60000);
        await tick(h);
        run.demoClock = await h.eval(SNAP);
        await h.eval("document.getElementById('on-way-plan-new').click(); document.getElementById('demo-banner').hidden = true; true");
      }
      await h.sleep(200);
      run.readsAtEnd = await h.eval("__geo.state.getCalls");
      if (which !== "demo") {
        await pushAt(h, first.target, 399);  // a late tick and a fresh position must not wake anything
      }
      run.end = await h.eval(SNAP);
      run.geoCalls = await h.eval("({ watch: __geo.state.watchCalls, clear: __geo.state.clearCalls })");
      if (which === "pagehide" || which === "end") {
        await h.eval("requestBack(); true");
      }
      out.runs[which] = run;
      await h.sleep(200);
    }
    return out;
  }

  if (c.mode === "layout") {
    await toOnWay(h, c);
    out.t0 = await h.eval(SNAP);
    const first = await legTarget(h, 0);
    await pushAt(h, first.target, 399);
    await h.sleep(200);
    out.alert = await h.eval(SNAP);
    out.colors = await h.eval(`(function () {
      var box = document.getElementById("on-way-alert");
      var s = getComputedStyle(box);
      var icon = box.querySelector(".alert-row__icon svg");
      return { bg: s.backgroundColor, color: s.color, hasIcon: !!icon, iconW: icon ? icon.getBoundingClientRect().width : 0,
        text: box.querySelector("#on-way-alert-text").textContent.length > 0, bodyBg: getComputedStyle(document.body).backgroundColor };
    })()`);
    if (c.shots) {
      await h.screenshot(`${c.shots}/onway-${c.name || "a"}-alert.png`);
    }
    const base = await h.eval("Date.now() - window.__skew");
    await skewTo(h, first.endMs + 1000);
    await tick(h);
    out.ticked = await h.eval(SNAP);
    if (c.shots) {
      await h.screenshot(`${c.shots}/onway-${c.name || "a"}-ticked.png`);
    }
    return out;
  }
  throw new Error("unknown mode " + c.mode);
}

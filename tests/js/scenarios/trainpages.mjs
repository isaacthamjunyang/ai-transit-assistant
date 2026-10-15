import { openHome, planOverview, tapStart } from "./common.mjs";

// A train as the first leg, on the real page: Pages W, A and B, the missed-train card and the on-your-way overview.
// config: width, height, dark, answer ("yes" | "no" | none), bus (a bus first journey, for the words that must not change),
// shots (a folder for screenshots).
const A = `(function () {
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  var hero = lastSuccess && lastSuccess.buses ? featuredBus(lastSuccess.buses) : null;
  return {
    top: screenStack[screenStack.length - 1], isTrain: isTrain(), service: selectedService,
    pill: text("catch-pill-text"), title: text("catch-title"), line: text("catch-line"), when: text("catch-when"), legClass: document.getElementById("catch-leg").className,
    nodeRing: getComputedStyle(document.getElementById("catch-node")).boxShadow, ring: text("catch-ring-text"),
    hasSub: !!document.getElementById("catch-sub"), hasCaption: !!document.getElementById("catch-caption"), pace: text("pace-slot"), paceHidden: document.getElementById("pace-slot").hidden,
    ringLabel: document.getElementById("catch-ring").getAttribute("aria-label"),
    arrives: text("catch-arrives"), hasLabel: !!document.querySelector("#catch-arrives .catch-card__arrives-label"), notLive: !!document.getElementById("catch-not-live"),
    tileLeaveLabel: text("tile-leave-label"), tileLeave: text("tile-leave-by"), tileLeaveMeta: shown("tile-leave-detail") ? text("tile-leave-detail") : null,
    geo: (function () {
      function box(el) { if (!el) { return null; } var r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }
      return { ring: box(document.getElementById("catch-ring")), leg: box(document.getElementById("catch-leg")),
        arrives: box(document.getElementById("catch-arrives")), tile: box(document.getElementById("tile-leave")),
        tiles: box(document.getElementById("leave-tiles")) };
    })(),
    tileDepartsLabel: text("tile-arrival-label"), tileDeparts: text("tile-arrival"), tileRange: shown("tile-arrival-range"),
    missRow: !!document.getElementById("if-you-miss"), aiBadge: !!document.getElementById("ai-badge"), tileNote: !!document.getElementById("tile-row"),
    ai: shown("ai-explanation") ? text("ai-explanation-text") : null,
    bar: shown("see-arrivals-bar") ? text("see-arrivals-bar") : null, catchBar: shown("catch-bar"), barTitle: text("catch-bar-title"),
    unlikelyBanner: shown("unlikely-banner"), catchWarning: shown("catch-warning"), pageC: document.body.classList.contains("is-page-c"),
    walkRow: text("walk-open"), scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    hero: hero ? { monitored: hero.monitored, quality: hero.probability && hero.probability.data_quality, atStop: hero.probability && hero.probability.at_stop,
      point: hero.probability && hero.probability.point, high: hero.probability && hero.probability.range_high } : null,
    body: lastSuccess ? { leg_kind: lastSuccess.leg_kind, headsign: lastSuccess.headsign, next: lastSuccess.next_departures, notLiveText: lastSuccess.not_live_text,
      leaveNow: lastSuccess.leave_now, notifications: lastSuccess.notifications, reroute: lastSuccess.reroute, headway: lastSuccess.headway_s } : null
  };
})()`;

const B = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  var badge = document.querySelector("#live-bus-title .line-badge");
  var bg = badge ? getComputedStyle(badge) : null;
  return {
    top: screenStack[screenStack.length - 1], pageB: document.body.classList.contains("is-page-b"),
    card: shown("live-tracking"), title: text(document.getElementById("live-bus-title")),
    badge: badge ? { text: badge.textContent, cls: badge.className, bg: bg.backgroundColor, color: bg.color } : null,
    to: text(document.getElementById("live-bus-to")), then: shown("live-then") ? text(document.getElementById("live-then")) : null,
    pill: text(document.getElementById("live-bus-pill-text")), label: shown("next-buses-label") ? text(document.getElementById("next-buses-label")) : null,
    next: Array.prototype.map.call(document.querySelectorAll("#next-buses > li"), text),
    cells: { live: text(document.getElementById("status-live-text")), monitored: text(document.getElementById("status-monitored-text")) },
    question: shown("catch-bar") ? text(document.getElementById("catch-bar-title")) : null, seeBar: shown("see-arrivals-bar"),
    yes: shown("catch-yes"), no: shown("catch-no"), scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

const W = `(function () {
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  var stop = document.querySelector("#walk-map-slot .map-stop--live");
  return {
    top: screenStack[screenStack.length - 1], pageW: document.body.classList.contains("is-page-w"),
    title: text("walk-title"), distance: text("walk-distance"), minutes: text("walk-minutes"), state: text("walk-state"),
    heading: text("walk-chance-title"), ring: text("walk-ring-text"), arrives: text("walk-arrives"),
    marker: stop ? { html: stop.innerHTML.indexOf("rect") !== -1, label: stop.textContent, hasTrain: stop.innerHTML.indexOf("M7 19") !== -1 || stop.innerHTML === "" ? true : stop.innerHTML.indexOf("<svg") !== -1 } : null,
    bar: !document.getElementById("see-arrivals-bar").hidden, barText: text("see-arrivals-bar"),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

const END = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  var missed = document.getElementById("train-missed");
  return {
    top: screenStack[screenStack.length - 1], missedShown: shown("train-missed"),
    left: shown("train-missed-left") ? text(document.getElementById("train-missed-left")) : null,
    heading: shown("train-missed-heading") ? text(document.getElementById("train-missed-heading")) : null,
    rows: Array.prototype.map.call(document.querySelectorAll("#train-missed-rows > li"), text),
    buttons: Array.prototype.map.call(missed.querySelectorAll("button"), text),
    switchButtons: document.querySelectorAll(".reroute-switch, #reroute-switch, [data-switch]").length,
    planNew: shown("train-missed-plan-new"), pageCShown: shown("page-c"), catchBar: shown("catch-bar"), seeBar: shown("see-arrivals-bar"),
    barTitle: text(document.getElementById("catch-bar-title")),
    arrivalCard: shown("arrival-card"), tiles: shown("leave-tiles"), monitoring: monitoringActive,
    requests: __requests.filter(function (u) { return u.indexOf("/api/reroute-options") === 0; }).length,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

const ONWAY = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#on-way-timeline > li"), function (li) {
    var node = li.querySelector(".step-node");
    return { cls: li.className, text: text(li), badge: li.querySelector(".line-badge") ? li.querySelector(".line-badge").textContent : null,
      iconColor: node ? getComputedStyle(node).color : null, iconBg: node ? getComputedStyle(node).backgroundColor : null };
  });
  return { top: screenStack[screenStack.length - 1], shown: !document.getElementById("on-way").hidden, rows: rows,
    monitoring: monitoringActive, scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`window.__notes = [];
    var Fake = function (title) { window.__notes.push(String(title)); };
    Fake.permission = "granted";
    window.Notification = Fake;
    true`);
  await planOverview(h);
  out.startDisabled = await h.eval("document.getElementById('start-journey').disabled");
  out.overviewRows = await h.eval("document.querySelectorAll('#overview-timeline > li').length");
  await tapStart(h);
  await h.until(c.bus ? "lastSuccess && !entryPending" : "lastSuccess && lastSuccess.leg_kind === 'rail' && !entryPending", 15000, "the first poll");
  await h.until("!explanationInFlight", 15000, "the explanation to settle");
  await h.sleep(500);
  out.pageA = await h.eval(A);
  if (c.shots) { await h.screenshot(`${c.shots}/train-a-${c.name || "a"}.png`); }

  // no leave-now and no 5-minute notification: force a bus-like eligible answer and a 4 minute train
  out.notes = c.bus ? null : await h.eval(`(function () {
    var body = JSON.parse(JSON.stringify(lastSuccess));
    var hero = featuredBus(body.buses);
    body.leave_now = { bus_id: hero.arrival_time, eligible: true, title: "Leave now", body: "Go", range_high: 90 };
    body.notification_time = new Date(Date.now() + 1000).toISOString();
    hero.arrival_time = new Date(Date.now() + 4 * 60000).toISOString();
    lastSuccess = body;
    syncLeaveNow(body);
    maybeFiveMinuteReminder(body);
    return { notes: window.__notes.slice(), banner: leaveNowBanner.shown === true };
  })()`);
  if (!c.bus) {
    await h.eval("requestArrivals(monitorGeneration); true");
    await h.sleep(600);
  }

  // Page W
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  await h.sleep(500);
  out.pageW = await h.eval(W);
  if (c.shots) { await h.screenshot(`${c.shots}/train-w-${c.name || "w"}.png`); }
  await h.eval("walkChanceSource = { chance: walkChanceSource.chance, nearStop: true }; renderWalkPage(); true");
  out.pageWArrived = await h.eval(W);
  await h.eval("walkChanceSource = { chance: walkChanceSource.chance, nearStop: false }; walkLastRescoreAt = 0; walkRescoreTick(); true");
  await h.sleep(800);

  // back to A, then Page B
  await h.eval("history.back(); true");
  await h.until("screenStack[screenStack.length - 1] === 'live'", 5000, "Page A");
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 5000, "Page B");
  await h.sleep(500);
  out.pageB = await h.eval(B);
  if (c.shots) { await h.screenshot(`${c.shots}/train-b-${c.name || "b"}.png`); }

  out.requests = await h.eval(`__requests.filter(function (u) { return /^\\/api\\/(arrivals|rescore|journey|reroute|reroute-options|explain)/.test(u); })`);
  out.allRequests = await h.eval("__requests.slice()");

  if (c.answer === "no" && !c.bus) {
    // the train has gone 60 s ago: the next departures are projected from the headway
    await h.eval(`activeRoutePlan.legs[0].depart = new Date(Date.now() - 60000).toISOString(); requestArrivals(monitorGeneration); true`);
    await h.until("lastSuccess && lastSuccess.left_text", 10000, "the left text");
    out.leftText = await h.eval("lastSuccess.left_text");
    await h.eval("document.getElementById('catch-no').click(); true");
    await h.sleep(600);
    out.missed = await h.eval(END);
    if (c.shots) { await h.screenshot(`${c.shots}/train-missed-${c.name || "m"}.png`); }
    await h.eval("document.getElementById('train-missed-plan-new').click(); true");
    await h.sleep(400);
    out.afterPlanNew = await h.eval("({ top: screenStack[screenStack.length - 1], monitoring: monitoringActive, shown: !document.getElementById('train-missed').hidden })");
  }
  if (c.answer === "no" && c.bus) {
    // a bus: the missed card is Page C; the question bar's words stay the bus words
    await h.eval("document.getElementById('catch-no').click(); true");
    await h.until("document.body.classList.contains('is-page-c') || missedMode", 10000, "the missed bus card");
    await h.sleep(500);
    out.busMissed = await h.eval("({ barTitle: document.getElementById('catch-bar-title').textContent, isTrain: isTrain(), pageC: document.body.classList.contains('is-page-c') })");
  }
  if (c.answer === "yes") {
    await h.eval("document.getElementById('catch-yes').click(); true");
    await h.sleep(600);
    out.onWay = await h.eval(ONWAY);
    if (c.shots) { await h.screenshot(`${c.shots}/train-onway-${c.name || "y"}.png`); }
  }
  out.notesAfter = await h.eval("window.__notes.slice()");
  return out;
}

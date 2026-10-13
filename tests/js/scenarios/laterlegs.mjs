import { openHome, planOverview, tapStart } from "./common.mjs";

// Live next-bus times for later bus legs, on the real page. The journey is bus 18, then later legs (the stub decides which).
// config: width, height, dark, shots (a folder). The test server records every BusArrival query (lta_log).
const ROWS = `(function () {
  function text(el) { return el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim(); }
  return Array.prototype.map.call(document.querySelectorAll("#overview-timeline > li"), function (li) {
    return { cls: li.className, lines: Array.prototype.map.call(li.querySelectorAll(".journey-step__body > p"), text), text: text(li) };
  });
})()`;

const LATER = `__requests.filter(function (u) { return u.indexOf("/api/arrivals/later?") === 0; })`;

async function later(h) {
  return h.eval(LATER);
}

async function waitLater(h, count) {
  await h.until(`${LATER}.length >= ${count} && Object.keys(laterPending).every(function (k) { return !laterPending[k]; })`, 15000,
    "the later-leg lookup");
  await h.sleep(300);
}

export default async function (h) {
  const out = {};
  await openHome(h, { dark: h.config.dark, width: h.config.width, height: h.config.height });
  await planOverview(h);
  await h.sleep(600);
  out.beforeStart = { requests: await later(h), rows: await h.eval(ROWS), cap: await h.eval("LATER_CAP") };
  await tapStart(h);
  if (h.config.mode === "rail") {
    await h.sleep(800);
    out.afterStart = { requests: await later(h) };
    await h.eval("laterActiveIndex = function () { return 9; }; laterAt = {}; maybeLookupLater(); true");
    await waitLater(h, 1);
    out.reachAll = { requests: await later(h) };
    return out;
  }
  await waitLater(h, 1);
  out.afterStart = { requests: await later(h) };
  // Back from the live page asks to leave (which ends tracking), so the overview list is drawn in place and read from the DOM.
  out.stackAfterStart = await h.eval("screenStack.slice()");
  await h.eval("renderJourneyOverview(); true");
  await h.sleep(300);
  out.overview = { rows: await h.eval(ROWS), requests: await later(h) };
  if (h.config.shots) {
    await h.screenshot(`${h.config.shots}/laterlegs-${h.config.name || "x"}.png`);
  }
  // cadence: an immediate second call is held back, one after 61 s is allowed
  await h.eval("maybeLookupLater(); maybeLookupLater(); true");
  await h.sleep(500);
  out.immediate = await later(h);
  await h.eval("laterAt = {}; laterCache = {}; maybeLookupLater(); true");
  await waitLater(h, out.immediate.length + 1);
  out.afterWait = await later(h);
  out.labels = await h.eval(`[-10, 10, 25, 40, 100, 600].map(function (s) { return laterLiveText(new Date(Date.now() + s * 1000).toISOString()); })`);
  out.firstBus = await h.eval(`[10, 300].map(function (s) {
    var leg = {kind: "bus", service_no: "18", boarding_stop_code: "A", boarding_stop_name: "A", alighting_stop_code: "B",
      alighting_stop_name: "B", stop_count: 2, ride_minutes: 3};
    return transitRow(leg, 0, {monitored: true, arrival_time: new Date(Date.now() + s * 1000).toISOString()}).textContent.replace(/\\s+/g, " ");
  })`);
  // the cap and the shared stop: five synthetic later bus legs, as if the user were far along
  await h.eval(`laterActiveIndex = function () { return 9; };
    var leg = function (stop, svc) { return {kind: "bus", boarding_stop_code: stop, service_no: svc, boarding_stop_name: stop, alighting_stop_code: "Z", alighting_stop_name: "Z"}; };
    pendingItinerary = {legs: [leg("S0", "1"), leg("S1", "11"), leg("S1", "12"), leg("S2", "13"), leg("S3", "14"), leg("S4", "15")]};
    laterAt = {}; laterCache = {}; true`);
  out.capped = await h.eval("laterLegsNow().map(function (l) { return l.service_no; })");
  const before = (await later(h)).length;
  await h.eval("maybeLookupLater(); true");
  await h.sleep(800);
  out.capRequests = (await later(h)).slice(before);
  // Demo Mode, a hidden page, off the pages, after tracking ends
  const gates = {};
  for (const [name, setup, undo] of [
    ["demo", "document.getElementById('demo-banner').hidden = false;", "document.getElementById('demo-banner').hidden = true;"],
    ["offpage", "screenStack.push('stops');", "screenStack.pop();"],
  ]) {
    await h.eval(`${setup} laterAt = {}; laterCache = {}; true`);
    const n = (await later(h)).length;
    await h.eval("maybeLookupLater(); true");
    await h.sleep(400);
    gates[name] = (await later(h)).length - n;
    await h.eval(`${undo} true`);
  }
  await h.eval("laterAt = {}; laterCache = {}; stopTracking(); true");
  const n = (await later(h)).length;
  await h.eval("maybeLookupLater(); true");
  await h.sleep(400);
  gates.afterEnd = (await later(h)).length - n;
  out.gates = gates;
  return out;
}

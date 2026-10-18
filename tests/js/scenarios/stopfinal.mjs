import { openHome } from "./common.mjs";

// The destination stop or station the traveller picks: the planner is asked to end at that point, and Your journey ends with the walk
// from the stop to the place, for each priority. Then Back from Confirm, another stop, Select stop: nothing stale.
// config: width, height, dark, dest, destPos, stops ([{code, name, pos, kind, minutes}...] first, then the second), priorities.
const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#overview-timeline > .journey-step, #overview-timeline > li"), function (li) { return text(li); });
  var summary = document.getElementById("overview-summary");
  var walkRows = Array.prototype.map.call(document.querySelectorAll("#overview-timeline [data-walk-minutes]"), function (row) { return Number(row.getAttribute("data-walk-minutes")); });
  var walkTexts = Array.prototype.map.call(document.querySelectorAll("#overview-timeline .journey-step"), function (row) { var m = text(row).match(/^Walk (\\d+) min/); return m ? Number(m[1]) : null; }).filter(function (v) { return v !== null; });
  return { top: screenStack[screenStack.length - 1], stack: screenStack.slice(), rows: rows, summary: text(summary), state: overviewState, priority: planPriority,
    walkRows: walkRows, walkTexts: walkTexts, walkingCell: text(document.getElementById("summary-walking")), summaryAria: summary.getAttribute("aria-label"),
    confirmStop: text(document.getElementById("confirm-stop-name")), confirmHeading: text(document.getElementById("confirm-stop-heading")),
    destNote: (function () { var n = document.getElementById("overview-destination-note"); return n ? { hidden: n.hidden, text: text(document.getElementById("overview-destination-note-text")), cls: n.className } : null; })(),
    confirmedCode: confirmedDestinationStop ? confirmedDestinationStop.stop_code : null, selectedCode: selectedDestinationStop ? selectedDestinationStop.stop_code : null,
    pending: typeof pendingDestination !== "undefined" && pendingDestination ? pendingDestination.label : null,
    place: selectedDestination ? selectedDestination.label : null };
})()`;

function stopArgs(stop) {
  return JSON.stringify({ stop_code: stop.code, stop_name: stop.name, road_name: "Rd", lat: stop.pos[0], lon: stop.pos[1], distance_m: stop.metres,
    walk_minutes: stop.minutes, is_reachable: true, connecting_services: ["18"], kind: stop.kind, station_mode: stop.kind === "station" ? "MRT" : "",
    station_codes: stop.kind === "station" ? [stop.code] : [] });
}

export default async function (h) {
  const c = h.config;
  const out = { byPriority: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "SCIS 1", label_display: "SCIS 1", address: "1 Road", address_display: "1 Road"};
    pendingDestination = selectedDestination; pushScreen("results"); pushScreen("stops"); true`);
  await h.sleep(400);
  const first = c.stops[0];
  await h.eval(`selectDestinationStop(${stopArgs(first)}); document.getElementById("select-destination-stop").click(); true`);
  await h.sleep(300);
  out.confirm = await h.eval(READ);
  await h.eval(`document.getElementById("confirm-destination-stop").click(); true`);
  await h.until("screenStack[screenStack.length - 1] === 'journey'", 8000, "the journey");
  await h.until("document.getElementById('overview-skeleton').hidden", 20000, "the plan");
  await h.sleep(300);
  for (const priority of c.priorities) {
    await h.eval(`(function () { var select = document.getElementById("priority-select"); select.value = ${JSON.stringify(priority)}; select.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
    await h.sleep(200);
    await h.until(`document.getElementById("overview-skeleton").hidden && planPriority === ${JSON.stringify(priority)}`, 20000, "the plan for " + priority);
    await h.sleep(300);
    const state = await h.eval(READ);
    state.requests = await h.eval(`__requests.filter(function (u) { return u.indexOf("/api/journey-plan") === 0 && u.indexOf("priority=${priority}") !== -1; })`);
    // the planner's own answer for that request: the legs, the totals and the arrival
    state.body = await h.eval(`fetch(${JSON.stringify(state.requests[state.requests.length - 1])}).then(function (r) { return r.json(); }).then(function (b) {
      var legs = b.itinerary ? b.itinerary.legs : [];
      var transit = legs.filter(function (l) { return l.kind !== "walk"; });
      var last = legs[legs.length - 1];
      return { route_status: b.route_status, kinds: legs.map(function (l) { return l.kind; }), finalWalkM: last && last.kind === "walk" ? last.distance_m : null,
        finalWalkS: last && last.kind === "walk" ? last.duration_s : null, rideArrive: transit.length ? transit[transit.length - 1].arrive : null,
        arrive: b.itinerary ? b.itinerary.arrive : null, walkTotalM: b.option && b.option.totals ? b.option.totals.walk_m : null,
        totalMinutes: b.option && b.option.totals ? b.option.totals.minutes : null, lastTo: last ? last.to_name : null,
        allEnds: (b.itineraries || []).map(function (it) { var t = it.legs.filter(function (l) { return l.kind !== "walk"; }); return t.length ? t[t.length - 1].alighting_stop_code : null; }),
        rideEnd: transit.length ? transit[transit.length - 1].stops[transit[transit.length - 1].stops.length - 1] : null }; })`);
    out.byPriority[priority] = state;
  }
  // change the choice: Back from the journey and from Confirm, another stop, Select stop, Confirm
  const second = c.stops[1];
  await h.eval("requestBack(); true"); await h.sleep(400);
  await h.eval("requestBack(); true"); await h.sleep(400);
  out.backToStops = await h.eval(READ);
  await h.eval(`selectDestinationStop(${stopArgs(second)}); document.getElementById("select-destination-stop").click(); true`);
  await h.sleep(300);
  out.confirm2 = await h.eval(READ);
  await h.eval(`__requests.length = 0; document.getElementById("confirm-destination-stop").click(); true`);
  await h.until("screenStack[screenStack.length - 1] === 'journey'", 8000, "the journey again");
  try {
    await h.until(`overviewState === "ready" && document.getElementById("overview-timeline").textContent.indexOf("${second.expectMetres}") !== -1`, 8000, "the plan for the second stop");
  } catch (error) {
    out.timedOut = true;
  }
  await h.sleep(300);
  out.journey2 = await h.eval(READ);
  out.requests2 = await h.eval(`__requests.filter(function (u) { return u.indexOf("/api/journey-plan") === 0; })`);
  out.direct2 = await h.eval(`fetch(__requests.filter(function (u) { return u.indexOf("/api/journey-plan") === 0; })[0]).then(function (r) { return r.json(); }).then(function (b) { return { route_status: b.route_status, reason: b.reason, planner: b.planner, status: b.status, dropped: b.dropped, legs: b.itinerary ? b.itinerary.legs.map(function (l) { return l.kind + ":" + (l.distance_m || ""); }) : null }; })`);
  return out;
}

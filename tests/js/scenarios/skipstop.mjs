import { openHome } from "./common.mjs";

// Skip on the destination stops page, and the stop path for comparison. config: width, height, dark, path ("skip" | "stop"), dest, destPos.
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  function box(el) { if (!el || el.getClientRects().length === 0) { return null; } var r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; }
  var skip = document.getElementById("skip-stop"), back = document.getElementById("back-home"), bar = document.getElementById("back-bar");
  var ss = getComputedStyle(skip), rootStyle = getComputedStyle(document.documentElement);
  var rows = Array.prototype.map.call(document.querySelectorAll("#overview-timeline .journey-step"), function (li) { return text(li); });
  return { top: screenStack[screenStack.length - 1], stack: screenStack.slice(),
    skip: { shown: shown("skip-stop"), text: text(skip), rect: box(skip), barBg: getComputedStyle(bar).backgroundColor, tokenFill: rootStyle.getPropertyValue("--action-yes").trim(), border: ss.borderTopColor, borderWidth: ss.borderTopWidth, bg: ss.backgroundColor, color: ss.color, weight: ss.fontWeight,
      radius: ss.borderTopLeftRadius, lines: Math.round(skip.getBoundingClientRect().height / parseFloat(ss.lineHeight || "20")) },
    back: box(back), bar: box(bar), barShown: shown("back-bar"),
    confirm: { place: text(document.getElementById("confirm-place-name")), stopSection: shown("confirm-stop-section"), rule: shown("confirm-stop-rule"), stopName: text(document.getElementById("confirm-stop-name")),
      screen: shown("destination-confirm") },
    overview: { rows: rows, destinationRow: rows.length ? rows[rows.length - 1] : null, hasStopRow: rows.some(function (r) { return r.indexOf("Destination stop") !== -1; }), state: typeof overviewState === "string" ? overviewState : null },
    walkRows: Array.prototype.map.call(document.querySelectorAll("#overview-timeline [data-walk-minutes]"), function (row) { return Number(row.getAttribute("data-walk-minutes")); }),
    walkTexts: Array.prototype.map.call(document.querySelectorAll("#overview-timeline .journey-step"), function (row) { var m = text(row).match(/^Walk (\\d+) min/); return m ? Number(m[1]) : null; }).filter(function (v) { return v !== null; }),
    walkingCell: text(document.getElementById("summary-walking")), summaryAria: document.getElementById("overview-summary").getAttribute("aria-label"),
    destStopCode: destStopCode(), skipped: destinationSkipped(), confirmedStop: confirmedDestinationStop ? confirmedDestinationStop.stop_code : null,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Pebble Bay Plaza", label_display: "Pebble Bay Plaza", address: "1 Pebble Road", address_display: "1 Pebble Road"};
    pendingDestination = selectedDestination; pushScreen("results"); pushScreen("stops"); true`);
  await h.sleep(500);
  out.stops = await h.eval(READ);
  if (c.path === "skip") {
    await h.eval(`document.getElementById("skip-stop").click(); true`);
  } else {
    await h.eval(`selectDestinationStop({ stop_code: "${c.dest}", stop_name: "Destination", road_name: "Rd", lat: ${c.destPos[0]}, lon: ${c.destPos[1]}, distance_m: 80, walk_minutes: 2, is_reachable: true, connecting_services: ["18"], kind: "bus" });
      document.getElementById("select-destination-stop").click(); true`);
  }
  await h.sleep(400);
  out.confirm = await h.eval(READ);
  await h.eval(`document.getElementById("confirm-destination-stop").click(); true`);
  await h.until("screenStack[screenStack.length - 1] === 'journey'", 8000, "the journey screen");
  await h.until("document.getElementById('overview-skeleton').hidden", 20000, "the plan");
  await h.sleep(500);
  out.journey = await h.eval(READ);
  out.plan = await h.eval(`__requests.filter(function (u) { return u.indexOf("/api/journey-plan") === 0; })`);
  // Back from the journey goes to Confirm, and Back from Confirm to the stops page
  await h.eval(`requestBack(); true`);
  await h.sleep(500);
  out.backOnce = await h.eval(`({ top: screenStack[screenStack.length - 1], stack: screenStack.slice() })`);
  await h.eval(`requestBack(); true`);
  await h.sleep(500);
  out.backTwice = await h.eval(`({ top: screenStack[screenStack.length - 1], stack: screenStack.slice() })`);
  // forward again to the journey, then Edit destination
  await h.eval(`if (screenStack[screenStack.length - 1] === "stops") { ${c.path === "skip" ? 'document.getElementById("skip-stop").click();' : 'document.getElementById("select-destination-stop").click();'} } true`);
  await h.sleep(400);
  await h.eval(`document.getElementById("confirm-destination-stop").click(); true`);
  await h.until("screenStack[screenStack.length - 1] === 'journey'", 8000, "the journey screen again");
  await h.until("document.getElementById('overview-skeleton').hidden", 20000, "the plan again");
  await h.sleep(300);
  out.again = await h.eval(`({ top: screenStack[screenStack.length - 1], stack: screenStack.slice() })`);
  await h.eval(`(function () {
    var button = document.getElementById("overview-edit-destination-service") && document.getElementById("overview-edit-destination-service").getClientRects().length ? document.getElementById("overview-edit-destination-service")
      : document.getElementById("overview-edit-destination") && document.getElementById("overview-edit-destination").getClientRects().length ? document.getElementById("overview-edit-destination") : document.querySelector('.journey-step__edit[aria-label="Edit destination"]');
    if (button) { button.click(); }
    return true;
  })()`);
  await h.sleep(600);
  out.edit = await h.eval(`({ top: screenStack[screenStack.length - 1], stack: screenStack.slice() })`);
  return out;
}

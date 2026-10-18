import { openHome } from "./common.mjs";

// Every filled primary button the page can draw, with its computed look: weight, size, shadow, blur, opacity, smoothing, colour and fill.
// The dynamic ones are created first: Page C's Switch buttons (fed option bodies directly) and the saved-place panel's buttons.
// config: width, height, dark.
function row(id, service, wait, destMinutes, point, tags) {
  const at = new Date(Date.now() + wait * 60000).toISOString();
  const dest = new Date(Date.now() + destMinutes * 60000).toISOString();
  return { id, service_no: service, stop_code: "90041", stop_name: "Here", point, band: point >= 50 ? "ok" : "low", range_low: point - 5, range_high: point + 5,
    arrival_time: at, estimated_arrival: dest, destination_arrival: dest, distance_m: 0, walk_m: 0, at_current_stop: true, next_of_same_service: false,
    monitored: true, group: 2, tags: tags, unlikely: false, after_target: false, recommended: tags.length > 0, leave_by: at };
}

const READ = `(function () {
  function parse(c) { var m = c.match(/rgba?\\(([^)]+)\\)/); if (m) { var p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2]]; }
    m = c.match(/color\\(srgb ([^)]+)\\)/); if (m) { var q = m[1].split(/[ \\/]+/).map(Number); return [q[0] * 255, q[1] * 255, q[2] * 255]; } return null; }
  function lum(c) { var f = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]; }
  function ratio(a, b) { var x = lum(a), y = lum(b); return Math.round((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) * 100) / 100; }
  var root = getComputedStyle(document.documentElement), blue = root.getPropertyValue("--color-primary").trim();
  var seen = [];
  Array.prototype.forEach.call(document.querySelectorAll("button.primary, .button--primary, #demo-run"), function (el) {
    var s = getComputedStyle(el), label = el.querySelector("span");
    var ls = label ? getComputedStyle(label) : null;
    seen.push({ id: el.id || null, text: el.textContent.replace(/\\s+/g, " ").trim(), cls: el.className, weight: s.fontWeight, size: parseFloat(s.fontSize), shadow: s.textShadow,
      smoothing: s.webkitFontSmoothing, opacity: s.opacity, filter: s.filter, labelOpacity: ls ? ls.opacity : null, labelFilter: ls ? ls.filter : null,
      color: s.color, bg: s.backgroundColor, blueToken: blue, disabled: el.disabled || el.getAttribute("aria-disabled") === "true",
      ratio: ratio(parse(s.color), parse(s.backgroundColor)), h: el.getBoundingClientRect().height, shown: el.getClientRects().length > 0 });
  });
  return { buttons: seen, blue: blue };
})()`;

export default async function (h) {
  const c = h.config;
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  // Page C's Switch buttons
  const options = { mode: "winner", entry: "recommended", recommended: row("a", "16", 3, 20, 69, ["fastest"]), cards: [row("a", "16", 3, 20, 69, ["fastest"]), row("b", "7", 8, 30, 92, ["highest_chance"])], rows: [row("p", "36", 9, 40, 50, [])] };
  await h.eval(`confirmedDestinationStop = { stop_code: "90021", stop_name: "Pebble Bay", lat: 1.3, lon: 103.8 };
    screenStack.push("live"); document.getElementById("page-c").hidden = false; lastKnownPoint = 76;
    pageC = { entry: "other", loading: false, failed: false, noBuses: false, options: ${JSON.stringify(options)}, missedEpoch: null, fetchedAt: Date.now() };
    syncPageCClasses(); renderPageC(); true`);
  await h.sleep(200);
  const out = { pageC: await h.eval(READ) };
  await h.eval(`closePageC(); resetScreens(); true`);
  // the saved-place panel (Search, Save) and a delete confirmation
  await h.eval(`localStorage.setItem("bus-catch-saved-places-v1", JSON.stringify({ v: 1, places: [{ id: "s1", name: "Home", address: "1 Home Road", latitude: 1.3, longitude: 103.8 }] })); renderSavedPlaces(); true`);
  await h.eval(`document.querySelector('#quick-picks [data-saved-action="add"]').click(); true`);
  await h.sleep(200);
  out.addPanel = await h.eval(READ);
  await h.eval(`document.querySelector('#quick-picks [data-saved-action="toggle-edit"]').click(); true`);
  await h.eval(`document.querySelector("#quick-picks .saved-chip__badge").click(); true`);
  await h.sleep(200);
  out.deletePanel = await h.eval(READ);
  return out;
}

import { toLive } from "./common.mjs";

// The approved Page B design (tmp/design/pageb-v2.html), for a bus and a train: the title row, the vehicle card, one row per
// arrival, the map and the question bar, in the live, no-data (bus only) and stale states. The scenario is read three times:
// fresh, with the data stale (and the display frozen), and fresh again. config: width, height, dark.
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  function r(el) { if (!el) { return null; } var b = el.getBoundingClientRect(); return { left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height }; }
  function parse(c) {
    var m = c.match(/rgba?\\(([^)]+)\\)/);
    if (m) { var p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = c.match(/color\\(srgb ([^)]+)\\)/);
    if (m) { var q = m[1].split(/[ \\/]+/).map(Number); return [q[0] * 255, q[1] * 255, q[2] * 255, q.length > 3 ? q[3] : 1]; }
    return null;
  }
  function bgOf(el) { while (el) { var c = parse(getComputedStyle(el).backgroundColor); if (c && c[3] > 0.5) { return c; } el = el.parentElement; } return [255, 255, 255, 1]; }
  function lum(c) { var f = c.slice(0, 3).map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]; }
  function ratio(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function textRatio(el) { return el ? Math.round(ratio(parse(getComputedStyle(el).color), bgOf(el)) * 100) / 100 : null; }
  function shadowColor(el) { var m = getComputedStyle(el).boxShadow.match(/(rgba?\\([^)]+\\)|color\\(srgb [^)]+\\))/); return m ? parse(m[1]) : null; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#next-buses > li"), function (li) {
    var crowd = li.querySelector(".crowd-chip"), arriving = li.querySelector(".bus-tile-card__arriving");
    var minutes = li.querySelector(".bus-tile-card__minutes"), service = li.querySelector(".bus-tile-card__service");
    var sel = li.classList.contains("is-selected"), shadow = shadowColor(li);
    return { rect: r(li), selected: sel, text: text(li), minutes: text(minutes), service: text(service), kids: li.children.length,
      crowd: crowd ? { text: text(crowd), code: crowd.getAttribute("data-load"), icon: !!crowd.querySelector("svg"), ratio: textRatio(crowd.querySelector(".crowd-chip__text")) } : null,
      arriving: arriving ? { text: text(arriving), icon: !!arriving.querySelector("svg"), ratio: textRatio(arriving) } : null,
      minutesRatio: textRatio(minutes), serviceRatio: textRatio(service), side: !!li.querySelector(".bus-tile-card__side"),
      outlineRatio: shadow ? Math.round(ratio(shadow, bgOf(li.parentElement)) * 100) / 100 : null, outlineOnRow: shadow ? Math.round(ratio(shadow, bgOf(li)) * 100) / 100 : null,
      bg: getComputedStyle(li).backgroundColor, border: getComputedStyle(li).borderTopWidth, shadow: getComputedStyle(li).boxShadow };
  });
  var node = document.getElementById("live-node"), vehicle = document.getElementById("live-vehicle");
  var ring = shadowColor(node);
  var pill = document.getElementById("live-bus-pill");
  var yes = document.getElementById("catch-yes"), no = document.getElementById("catch-no");
  return {
    top: screenStack[screenStack.length - 1], pageB: document.body.classList.contains("is-page-b"),
    title: text(document.getElementById("live-bus-to")), titleTag: document.getElementById("live-bus-to").tagName, titleRect: r(document.getElementById("live-bus-to")),
    back: r(document.getElementById("live-back")), backBar: getComputedStyle(document.getElementById("back-bar")).display,
    vehicle: r(vehicle), vehicleIsCard: vehicle.classList.contains("card"), vehicleClass: vehicle.className,
    node: r(node), ringRatio: ring ? Math.round(ratio(ring, bgOf(vehicle)) * 100) / 100 : null, ringShadow: getComputedStyle(node).boxShadow,
    badge: text(document.getElementById("live-bus-title")), badgeRect: r(document.getElementById("live-bus-title")),
    pill: text(document.getElementById("live-bus-pill-text")), pillClass: pill.className, pillRect: r(pill), pillRatio: textRatio(pill),
    refresh: r(document.getElementById("live-refresh")), label: shown("next-buses-label") ? text(document.getElementById("next-buses-label")) : null,
    rows: rows, map: r(document.getElementById("live-map-slot")),
    markers: { flag: !!document.querySelector("#live-map-slot .map-dest-live"), stop: !!document.querySelector("#live-map-slot .map-stop--live"),
      range: !!document.querySelector("#live-map-slot .map-range"), full: shown("live-full-route"), fullText: text(document.getElementById("live-full-route")),
      fullRect: r(document.getElementById("live-full-route")), user: !!document.querySelector("#live-map-slot .user-marker") },
    bar: shown("catch-bar") ? { rect: r(document.getElementById("catch-bar")), title: text(document.getElementById("catch-bar-title")),
      yes: { text: text(yes), rect: r(yes), ratio: textRatio(yes), icon: !!yes.querySelector("svg") }, no: { text: text(no), rect: r(no), ratio: textRatio(no), icon: !!no.querySelector("svg") } } : null,
    stale: shown("quality-banner") ? { text: text(document.getElementById("quality-banner-title")), isAlert: document.getElementById("quality-banner").classList.contains("alert"),
      kind: document.getElementById("quality-banner").className, rect: r(document.getElementById("quality-banner")), ratio: textRatio(document.getElementById("quality-banner-title")) } : null,
    walkLine: shown("walk-open") || /\\d+ min walk/.test(document.body.innerText), pace: shown("pace-slot"),
    body: document.body.innerText.replace(/\\s+/g, " "), scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, innerHeight: window.innerHeight
  };
})()`;

export default async function (h) {
  const out = {};
  await toLive(h, { permission: "granted", dark: h.config.dark, width: h.config.width, height: h.config.height });
  await h.until("!entryPending && lastSuccess", 20000, "the first poll");
  await h.sleep(500);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 6000, "Page B");
  await h.sleep(900);
  out.live = await h.eval(READ);
  await h.eval(`lastSuccess.fetched_at = new Date(Date.now() - 90000).toISOString(); displayFrozen = true; syncQuality(); renderLiveTracking(); true`);
  await h.sleep(400);
  out.stale = await h.eval(READ);
  await h.eval(`lastSuccess.fetched_at = new Date().toISOString(); displayFrozen = false; syncQuality(); renderLiveTracking(); true`);
  await h.sleep(400);
  out.again = await h.eval(READ);
  // the back button goes back, as the back row did
  await h.eval("document.getElementById('live-back').click(); true");
  await h.sleep(500);
  out.afterBack = await h.eval(`({ top: screenStack[screenStack.length - 1], pageB: document.body.classList.contains("is-page-b") })`);
  return out;
}

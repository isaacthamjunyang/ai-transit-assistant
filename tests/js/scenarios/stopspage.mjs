import { openHome } from "./common.mjs";

// The destination stops page: nothing chosen at first, the Skip and Select stop pulse handoff, and the red alert when Select stop is pressed
// with nothing chosen. config: width, height, dark.
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  function box(el) { if (!el || el.getClientRects().length === 0) { return null; } var r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; }
  function parse(c) { var m = c.match(/rgba?\\(([^)]+)\\)/); if (m) { var p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2]]; }
    m = c.match(/color\\(srgb ([^)]+)\\)/); if (m) { var q = m[1].split(/[ \\/]+/).map(Number); return [q[0] * 255, q[1] * 255, q[2] * 255]; } return null; }
  function lum(c) { var f = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]; }
  function ratio(a, b) { var x = lum(a), y = lum(b); return Math.round((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) * 100) / 100; }
  var skip = document.getElementById("skip-stop"), select = document.getElementById("select-destination-stop"), error = document.getElementById("select-stop-error");
  var ss = getComputedStyle(skip), rows = Array.prototype.slice.call(document.querySelectorAll("#reachable-stops .dest-stop-row"));
  var root = getComputedStyle(document.documentElement);
  return { top: screenStack[screenStack.length - 1],
    rows: rows.map(function (row) { return { code: row.getAttribute("data-stop-code"), selected: row.classList.contains("is-selected"), pressed: row.getAttribute("aria-pressed"), pill: !!row.querySelector(".pill--best"),
      focused: document.activeElement === row }; }),
    selectedCode: selectedDestinationStop ? selectedDestinationStop.stop_code : null, markerSelected: document.querySelectorAll(".map-stop--dest.is-selected").length,
    focusInList: !!document.activeElement && !!document.activeElement.closest && !!document.activeElement.closest("#reachable-stops"),
    skip: { shown: shown("skip-stop"), text: text(skip), rect: box(skip), cls: skip.className, pulses: skip.classList.contains("pulse-button"), anims: skip.getAnimations().length,
      bg: ss.backgroundColor, color: ss.color, weight: ss.fontWeight, size: ss.fontSize, tokenFill: root.getPropertyValue("--action-yes").trim(), tokenInk: root.getPropertyValue("--action-ink").trim(), shadow: ss.textShadow,
      ratio: ratio(parse(ss.color), parse(ss.backgroundColor)), border: ss.borderTopWidth, radius: ss.borderTopLeftRadius },
    select: { text: text(select), rect: box(select), disabled: select.disabled, ariaDisabled: select.getAttribute("aria-disabled"), pulses: select.classList.contains("pulse-button"), anims: select.getAnimations().length },
    error: { shown: shown("select-stop-error"), text: shown("select-stop-error") ? text(error) : null, cls: error.className, rect: box(error), selectRect: box(select),
      bg: getComputedStyle(error).backgroundColor, color: getComputedStyle(error).color, marginTop: parseFloat(getComputedStyle(error).marginTop), marginBottom: parseFloat(getComputedStyle(error).marginBottom),
      icon: !!error.querySelector(".alert__icon svg") },
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`selectedDestination = { latitude: 1.3, longitude: 103.8, label: "Test place", label_display: "Test place" };
    pendingDestination = selectedDestination; pushScreen("results"); pushScreen("stops"); clearDestinationStops();
    renderDestinationStops({ candidates: [
      { stop_code: "S1", stop_name: "Alpha Road", lat: 1.3001, lon: 103.8, distance_m: 100, walk_minutes: 2, kind: "bus", is_reachable: true },
      { stop_code: "S2", stop_name: "Beta Road", lat: 1.3002, lon: 103.8, distance_m: 220, walk_minutes: 3, kind: "bus", is_reachable: true }
    ], reachable_stops: [], unreachable_stops: [] }); destinationStopPanel.hidden = false; true`);
  await h.sleep(400);
  out.opened = await h.eval(READ);
  // the "i" tooltip: open it and measure it (it must sit inside the viewport, wrap, and not widen the page)
  await h.eval(`document.getElementById("dest-stops-info").click(); true`);
  await h.sleep(200);
  out.tip = await h.eval(`(function () {
    var note = document.getElementById("dest-stops-note"); var r = note.getBoundingClientRect();
    return { hidden: note.hidden, text: note.textContent.trim(), left: r.left, right: r.right, top: r.top, bottom: r.bottom,
      clipped: note.scrollWidth > note.clientWidth + 1, innerWidth: window.innerWidth, innerHeight: window.innerHeight,
      scrollWidth: document.documentElement.scrollWidth };
  })()`);
  await h.eval(`document.getElementById("dest-stops-info").click(); true`);
  await h.sleep(100);
  // Select stop with nothing chosen: it stays here and says so
  await h.eval(`document.getElementById("select-destination-stop").click(); true`);
  await h.sleep(300);
  out.refused = await h.eval(READ);
  // a row is chosen: the alert goes and the pulse moves to Select stop
  await h.eval(`document.querySelector('#reachable-stops .dest-stop-row[data-stop-code="S2"]').click(); true`);
  await h.sleep(300);
  out.chosen = await h.eval(READ);
  // Select stop now goes on to Confirm
  await h.eval(`document.getElementById("select-destination-stop").click(); true`);
  await h.sleep(300);
  out.confirmed = await h.eval(`({ top: screenStack[screenStack.length - 1], stop: document.getElementById("confirm-stop-name").textContent })`);
  // Back and Skip: the pulse is Skip's again after the list is cleared
  await h.eval(`requestBack(); true`);
  await h.sleep(300);
  await h.eval(`clearDestinationStops(); renderDestinationStops({ candidates: [{ stop_code: "S1", stop_name: "Alpha Road", lat: 1.3001, lon: 103.8, distance_m: 100, walk_minutes: 2, kind: "bus", is_reachable: true }], reachable_stops: [], unreachable_stops: [] }); destinationStopPanel.hidden = false; true`);
  await h.sleep(300);
  out.reopened = await h.eval(READ);
  // the pressed state and reduced motion stop the pulse
  await h.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }, { name: "prefers-color-scheme", value: c.dark ? "dark" : "light" }] });
  await h.sleep(200);
  out.reduced = await h.eval(READ);
  return out;
}

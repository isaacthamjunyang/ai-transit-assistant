import { toLive } from "./common.mjs";

// Page B for a bus: the header (logo tile, bus number badge, "To {destination stop}", the pill; no "Arriving in" line), no
// grey rows, and the stale-data message only when the data is old. config: width, height, dark.
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  function box(el) { if (!el) { return null; } var r = el.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }; }
  var badge = document.querySelector("#live-bus-title .line-badge");
  var tile = document.getElementById("live-node");
  return {
    top: screenStack[screenStack.length - 1], pageB: document.body.classList.contains("is-page-b"),
    badgeText: badge ? text(badge) : null, badgeBus: !!(badge && badge.classList.contains("line-badge--bus")),
    to: text(document.getElementById("live-bus-to")), pill: text(document.getElementById("live-bus-pill-text")),
    tile: box(tile), badge: box(badge), toBox: box(document.getElementById("live-bus-to")), pillBox: box(document.getElementById("live-bus-pill")),
    header: text(document.getElementById("live-vehicle")), vehicleBox: box(document.getElementById("live-vehicle")),
    backBox: box(document.getElementById("live-back")), backBar: getComputedStyle(document.getElementById("back-bar")).display,
    nextTiles: document.querySelectorAll("#next-buses > li").length, map: shown("live-map-slot"),
    refresh: shown("live-refresh"), refreshDisabled: document.getElementById("live-refresh").getAttribute("aria-disabled"),
    greyRows: !!(document.getElementById("live-then") || document.getElementById("live-status") || document.querySelector("#live-tracking .status-cell")),
    staleShown: shown("quality-banner"), staleTitle: shown("quality-banner") ? text(document.getElementById("quality-banner-title")) : null,
    staleUpdated: shown("quality-banner-updated") ? text(document.getElementById("quality-banner-updated")) : null,
    body: document.body.innerText.replace(/\\s+/g, " "),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

export default async function (h) {
  const out = {};
  await toLive(h, { permission: "granted", dark: h.config.dark, width: h.config.width, height: h.config.height });
  await h.until("!entryPending && lastSuccess", 20000, "the first poll");
  await h.sleep(500);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 6000, "Page B");
  await h.sleep(800);
  out.fresh = await h.eval(READ);
  await h.eval(`lastSuccess.fetched_at = new Date(Date.now() - 90000).toISOString(); displayFrozen = true; syncQuality(); renderLiveTracking(); true`);
  await h.sleep(300);
  out.stale = await h.eval(READ);
  await h.eval(`lastSuccess.fetched_at = new Date().toISOString(); displayFrozen = false; syncQuality(); renderLiveTracking(); true`);
  await h.sleep(300);
  out.fresh2 = await h.eval(READ);
  return out;
}

import { poll, toLive } from "./common.mjs";

// Page A's probability card at a high and at a low probability: the same card (geometry and colours) apart from the ring's number,
// arc and colour, and the unlikely alert above the two bottom buttons. config: width, height, dark, metres (the distance from the
// stop that gives the state), toggle (hide and restore the alert and measure the card each time).
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  function box(id) { var el = document.getElementById(id); if (!el || el.getClientRects().length === 0) { return null; } var r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; }
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  function parse(c) { var m = c.match(/rgba?\\(([^)]+)\\)/); if (m) { var p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2]]; }
    m = c.match(/color\\(srgb ([^)]+)\\)/); if (m) { var q = m[1].split(/[ \\/]+/).map(Number); return [q[0] * 255, q[1] * 255, q[2] * 255]; } return null; }
  function bgOf(el) { while (el) { var c = getComputedStyle(el).backgroundColor; var p = parse(c); if (p && !/rgba\\([^)]*, 0\\)/.test(c) && c !== "transparent") { return p; } el = el.parentElement; } return [255, 255, 255]; }
  function lum(c) { var f = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]; }
  function ratio(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function ink(id) { var el = document.getElementById(id); return el && el.getClientRects().length ? { color: getComputedStyle(el).color, ratio: Math.round(ratio(parse(getComputedStyle(el).color), bgOf(el)) * 100) / 100 } : null; }
  var card = box("arrival-card"), rel = function (b) { return b && card ? { left: b.left - card.left, top: b.top - card.top, width: b.width, height: b.height } : null; };
  var ids = ["catch-ring", "catch-leg", "catch-node", "catch-line", "catch-to", "catch-arrives", "catch-pill", "catch-load"];
  var parts = {}; ids.forEach(function (id) { parts[id] = rel(box(id)); });
  var s = function (id, prop) { var el = document.getElementById(id); return el ? getComputedStyle(el)[prop] : null; };
  var see = document.getElementById("see-arrivals"), start = document.getElementById("start-journey");
  var cs = function (el) { var c = getComputedStyle(el); return { bg: c.backgroundColor, color: c.color, radius: c.borderTopLeftRadius, minH: c.minHeight, font: c.fontSize + "/" + c.fontWeight, cls: el.className, anim: c.animationName, dur: c.animationDuration }; };
  var other = document.getElementById("other-bus-options");
  return {
    ring: text("catch-ring-text"), ringLabel: document.getElementById("catch-ring").getAttribute("aria-label"), ringStroke: s("catch-ring-value", "stroke"), ringDash: document.getElementById("catch-ring-value").getAttribute("stroke-dasharray"),
    card: card, parts: parts, cardOrder: ["catch-node", "catch-line", "catch-to", "catch-arrives", "catch-pill", "catch-load"].map(function (id) { var b = box(id); return b ? Math.round(b.top) : null; }),
    legBg: s("catch-leg", "backgroundColor"), legRadius: s("catch-leg", "borderTopLeftRadius"), nodeRing: s("catch-node", "boxShadow"), toColor: s("catch-to", "color"), toFont: s("catch-to", "fontSize") + "/" + s("catch-to", "fontWeight"),
    timeFont: s("catch-arrives-time", "fontSize") + "/" + s("catch-arrives-time", "fontWeight"), timeColor: s("catch-arrives-time", "color"), pillBg: s("catch-pill", "backgroundColor"), loadColor: s("catch-load", "color"),
    text: text("arrival-card"), cardText: ["catch-to", "catch-arrives", "catch-pill", "catch-load"].map(text),
    alert: shown("unlikely-bar-alert") ? { rect: box("unlikely-bar-alert"), text: text("unlikely-bar-alert"), cls: document.getElementById("unlikely-bar-alert").className, ink: ink("unlikely-bar-alert") } : null,
    slotBanner: shown("unlikely-banner"), see: box("see-arrivals"), other: shown("other-bus-actions") ? box("other-bus-options") : null, bar: box("see-arrivals-bar"),
    seeStyle: cs(see), startStyle: cs(start), seeInk: ink("see-arrivals"), otherStyle: cs(other), tile: box("tile-leave"), pad: parseFloat(getComputedStyle(document.body).paddingBottom),
    anims: see.getAnimations().length, barStyle: { border: getComputedStyle(document.getElementById("see-arrivals-bar")).borderTopWidth, shadow: getComputedStyle(document.getElementById("see-arrivals-bar")).boxShadow, bg: getComputedStyle(document.getElementById("see-arrivals-bar")).backgroundColor },
    paper: getComputedStyle(document.documentElement).getPropertyValue("--color-paper").trim(), lowToken: getComputedStyle(document.documentElement).getPropertyValue("--prob-ring-low").trim(), okToken: getComputedStyle(document.documentElement).getPropertyValue("--prob-ring-ok").trim(),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, innerHeight: window.innerHeight, top: screenStack[screenStack.length - 1], pageA: document.body.classList.contains("is-page-a")
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await toLive(h, { permission: "granted", dark: c.dark, width: c.width, height: c.height });
  await h.until("!entryPending && lastSuccess", 20000, "the first poll to decide the page");
  await h.until("!explanationInFlight", 15000, "the first explanation request");
  await h.eval(`(function () { userLat = ${c.lat} + ${c.metres} / 111195; userLon = ${c.lon}; userAccuracy = 8; userLocationTimestamp = Date.now(); if (pageC) { closePageC(); } })(); true`);
  await poll(h);
  await h.sleep(500);
  out.read = await h.eval(READ);
  if (c.toggle) {
    // the alert goes away and comes back: the card and the tile above it do not move
    await h.eval(`document.getElementById("unlikely-bar-alert").style.display = "none"; true`);
    await h.sleep(200);
    out.hidden = await h.eval(READ);
    await h.eval(`document.getElementById("unlikely-bar-alert").style.display = ""; true`);
    await h.sleep(200);
    out.restored = await h.eval(READ);
  }
  return out;
}

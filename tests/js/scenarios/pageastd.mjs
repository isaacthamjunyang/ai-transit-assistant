import { poll, toLive } from "./common.mjs";

// Page A on the real page, standardised: the heading row, the pace chip, both tiles, the AI card and the sticky button in
// each probability state the server produces. config: width, height, dark, steps ([[name, metres from the stop], ...]).
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  var hero = featuredBus(lastSuccess.buses);
  var leg = document.getElementById("catch-leg");
  return {
    point: hero.probability.point, band: hero.probability.band, action: lastSuccess.chosen_action,
    atStop: hero.probability.at_stop, nearStop: lastSuccess.near_stop,
    top: screenStack[screenStack.length - 1], classes: document.body.className, pageCOpen: !!pageC, entryPending: entryPending, missed: !!missedMode, pageA: document.body.classList.contains("is-page-a"),
    ring: text("catch-ring-text"), line: text("catch-line"), to: text("catch-to"), direction: shown("catch-direction") ? text("catch-direction") : null,
    platform: text("catch-to"), arrives: text("catch-arrives"), load: shown("catch-load") ? text("catch-load") : null,
    pillShown: shown("catch-pill"), walkLine: shown("pace-walk") ? text("pace-walk") : null,
    hasLabel: !!document.querySelector("#catch-arrives .catch-card__arrives-label"),
    hasSub: shown("catch-sub"), sub: shown("catch-sub") ? text("catch-sub") : null, hasCaption: !!document.getElementById("catch-caption"),
    pill: text("catch-pill-text"), chip: shown("pace-slot") ? text("pace-slot") : null,
    tileLeave: shown("tile-leave"), tileLeaveValue: text("tile-leave-by"), tileLeaveWalk: shown("pace-walk") ? text("pace-walk") : null, tileLeaveLabelShown: shown("tile-leave-label"),
    tileLeaveName: document.getElementById("tile-leave").getAttribute("aria-label"), tileLeaveLine: Array.prototype.filter.call(document.querySelectorAll("#tile-leave-line > span"), function (el) { return !el.hidden; }).map(function (el) { return el.textContent; }).join(" "),
    tileArrival: !!document.getElementById("tile-arrival"), tileText: text("leave-tiles"),
    chipHint: !!document.querySelector("#pace-slot .field__hint"), aiNote: !!document.querySelector(".ai-card__note"),
    geo: (function () {
      function box(el) { if (!el) { return null; } var r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }
      return {
        ring: box(document.getElementById("catch-ring")), leg: box(leg), line: box(document.getElementById("catch-line")),
        to: box(document.getElementById("catch-to")), pill: box(document.getElementById("catch-pill")), paceWalk: box(document.getElementById("pace-walk")), chipBox: box(document.getElementById("pace-slot")), arrives: box(document.getElementById("catch-arrives")),
        card: box(document.getElementById("arrival-card")), tile: box(document.getElementById("tile-leave")),
        tiles: box(document.getElementById("leave-tiles")), walk: box(document.getElementById("walk-open"))
      };
    })(),
    ai: shown("ai-explanation") ? text("ai-explanation-text") : null,
    bar: shown("see-arrivals-bar") ? text("see-arrivals") : null, banner: shown("unlikely-bar-alert"),
    buttons: (function () {
      var see = document.getElementById("see-arrivals"), other = document.getElementById("other-bus-options"), bar = document.getElementById("see-arrivals-bar");
      var rs = function (el) { var r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return { w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10, top: r.top, bottom: r.bottom, left: r.left, right: r.right,
          color: s.color, background: s.backgroundColor, border: s.borderTopColor, borderWidth: s.borderTopWidth, radius: s.borderTopLeftRadius, weight: s.fontWeight }; };
      var root = getComputedStyle(document.documentElement);
      return { seeText: text("see-arrivals"), otherShown: shown("other-bus-actions"), otherText: text("other-bus-options"), see: rs(see),
        other: shown("other-bus-actions") ? rs(other) : null, bar: shown("see-arrivals-bar") ? rs(bar) : null, anims: see.getAnimations().length,
        pulse: see.classList.contains("pulse-button"), otherPulse: other.classList.contains("pulse-button"), otherAnims: other.getAnimations().length,
        seeArrow: !!see.querySelector("svg"), otherArrow: !!other.querySelector("svg"),
        successOutline: root.getPropertyValue("--color-selected-outline-success").trim(), live: root.getPropertyValue("--status-live").trim(),
        innerHeight: window.innerHeight, innerWidth: window.innerWidth,
        padding: parseFloat(getComputedStyle(document.body).paddingBottom) };
    })(),
    bannerText: shown("unlikely-bar-alert") ? text("unlikely-bar-alert") : null,
    bannerExtras: document.querySelectorAll("#unlikely-bar-alert button, #unlikely-bar-alert .alert__meta, #unlikely-bar-alert .alert__actions").length,
    bannerIsAlert: document.getElementById("unlikely-bar-alert").classList.contains("alert") && document.getElementById("unlikely-bar-alert").classList.contains("alert--warning"),
    captionAnywhere: document.body.textContent.indexOf("if you leave now and walk at a normal pace") !== -1,
    aiBadge: !!document.getElementById("ai-badge"), missRow: !!document.getElementById("if-you-miss"),
    ringColour: getComputedStyle(document.getElementById("catch-node")).boxShadow,
    badgeIsBus: !!document.querySelector("#catch-line .line-badge--bus"),
    legClass: leg.className, body: document.body.innerText.replace(/\\s+/g, " "),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await toLive(h, { permission: "granted", dark: c.dark, width: c.width, height: c.height });
  await h.until("!entryPending && lastSuccess", 20000, "the first poll to decide the page");
  await h.until("!explanationInFlight", 15000, "the first explanation request");
  for (const [name, metres] of c.steps) {
    await h.eval(`(function () {
      userLat = ${h.config.lat} + ${metres} / 111195; userLon = ${h.config.lon}; userAccuracy = 8; userLocationTimestamp = Date.now();
    })(); true`);
    // a low first poll opens Page C by design; Page A at a low band is reached by a drop after the entry was decided
    await h.eval("if (pageC) { closePageC(); } true");
    await poll(h);
    await h.sleep(400);
    out[name] = await h.eval(READ);
  }
  if (c.openOther) {
    // "Other bus options" opens Page C (the "other" entry) and keeps tracking on
    await h.eval(`document.getElementById("other-bus-options").click(); true`);
    await h.sleep(1800);
    out.other = await h.eval(`(function () {
      var page = document.getElementById("page-c");
      var notice = document.getElementById("reroute-notice");
      return { top: screenStack[screenStack.length - 1], entry: pageC ? pageC.entry : null, missed: !!missedMode, notice: notice && !notice.hidden ? notice.textContent.replace(/\\s+/g, " ").trim() : null,
        bodyMissed: document.body.classList.contains("is-bus-missed"), pageCShown: !!page && !page.hidden && page.getClientRects().length > 0,
        tracking: monitoringActive, barHidden: document.getElementById("see-arrivals-bar").hidden, barDrawn: getComputedStyle(document.getElementById("see-arrivals-bar")).display !== "none", text: page ? page.textContent.replace(/\\s+/g, " ").trim().slice(0, 300) : "" };
    })()`);
  }
  if (c.openOther) {
    await h.eval(`requestBack(); true`);
    await h.sleep(500);
    out.afterBack = await h.eval(`({ top: screenStack[screenStack.length - 1], pageC: !!pageC, pageA: document.body.classList.contains("is-page-a"), tracking: monitoringActive, dialog: !document.getElementById("leave-dialog").hidden, barDrawn: getComputedStyle(document.getElementById("see-arrivals-bar")).display !== "none" })`);
  }
  return out;
}

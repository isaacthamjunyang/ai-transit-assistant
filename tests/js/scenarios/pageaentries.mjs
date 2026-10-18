import { openHome, planOverview, tapStart } from "./common.mjs";

// Page A on every entry and at every probability: the new card and the buttons, and none of the old Page C layout. The first start,
// each probability fed through the page's own poll handler (applySuccess), and a second start after Back. config: width, height, dark,
// probs (the points to feed).
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  var visible = document.body.innerText.replace(/\\s+/g, " ");
  var see = document.getElementById("see-arrivals"), other = document.getElementById("other-bus-options");
  var pc = document.getElementById("page-c");
  return {
    top: screenStack[screenStack.length - 1], pageA: document.body.classList.contains("is-page-a"), pageCOpen: !!pageC, pageCShown: shown("page-c"), bodyClasses: document.body.className,
    ring: text("catch-ring-text"), card: shown("arrival-card"), node: shown("catch-node"), badge: shown("catch-line"), to: shown("catch-to") ? text("catch-to") : null,
    time: shown("catch-arrives") ? text("catch-arrives-time") : null, pill: shown("catch-pill") ? text("catch-pill-text") : null, load: shown("catch-load") ? text("catch-load") : null,
    train: isTrain(), seeShown: shown("see-arrivals"), seeText: text("see-arrivals"), seePulse: see.classList.contains("pulse-button"), seeArrow: !!see.querySelector("svg"),
    otherShown: shown("other-bus-options"), otherText: text("other-bus-options"), otherPulse: other.classList.contains("pulse-button"), otherArrow: !!other.querySelector("svg"),
    otherClass: other.className, alert: shown("unlikely-bar-alert") ? text("unlikely-bar-alert") : null, slotBanner: shown("unlikely-banner"),
    old: { chanceYour: visible.indexOf("Chance to catch your Bus") !== -1, arrivingIn: /Arriving in \\d+ min/.test(visible), busArrives: visible.indexOf("Bus arrives") !== -1,
      caption: visible.indexOf("if you leave now and walk at a normal pace") !== -1, oldCard: !!document.getElementById("reroute-current"), oldBtn: !!document.getElementById("pc-see-arrivals"),
      oldWarn: !!document.getElementById("pc-warn"), pageCText: pc && shown("page-c") ? text("page-c").slice(0, 120) : null },
    unlikelyNow: (function () { var hero = featuredBus(lastSuccess.buses); return isUnlikely(hero); })(),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

async function settle(h) {
  await h.until("!entryPending && lastSuccess", 20000, "the first poll");
  await h.sleep(1600);
}

export default async function (h) {
  const c = h.config;
  const out = { fed: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  await tapStart(h);
  await settle(h);
  out.first = await h.eval(READ);
  // no real poll may land between a fed value and its reading
  await h.eval("monitorGeneration += 1; clearInterval(pollTimer); if (typeof walkRescoreTimer !== \"undefined\" && walkRescoreTimer) { clearInterval(walkRescoreTimer); } true");  // no timer and no answer in flight may replace a fed value
  for (const point of c.probs) {
    await h.eval(`(function () {
      var body = JSON.parse(JSON.stringify(lastSuccess));
      var hero = featuredBus(body.buses);
      hero.probability.point = ${point};
      hero.probability.range_low = Math.max(0, ${point} - 5);
      hero.probability.range_high = ${point};
      hero.probability.band = ${point} >= 60 ? "ok" : ${point} >= 40 ? "mid" : "low";
      hero.probability.at_stop = false;
      applySuccess(body);
      return true;
    })()`);
    await h.sleep(500);
    out.fed[point] = await h.eval(READ);
  }
  // Back, then Start journey again
  await h.eval("requestBack(); true");
  await h.sleep(500);
  await h.eval("if (!document.getElementById('leave-dialog').hidden) { document.getElementById('leave-leave').click(); } true");
  await h.sleep(600);
  out.afterBack = await h.eval(`({ top: screenStack[screenStack.length - 1], monitoring: monitoringActive })`);
  await h.until("!document.getElementById('start-journey').disabled", 20000, "the overview start-journey button");
  await tapStart(h);
  await settle(h);
  out.restart = await h.eval(READ);
  return out;
}

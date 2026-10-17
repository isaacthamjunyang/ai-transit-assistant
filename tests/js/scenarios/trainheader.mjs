import { openHome, planOverview, tapStart } from "./common.mjs";

// Page B's train card: the header (the logo tile, the line badge, "To {terminus}" and the pill on one wrapping row, the refresh
// button at the top right) and the "Next trains" tiles (the time only, an aria-label with the line and the time).
// config: width, height, dark, names (termini to try in the same markup; the real one is measured first), shots (a folder).

const MEASURE = `(function () {
  function box(el) {
    if (!el) { return null; }
    var r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
  }
  var card = document.getElementById("live-vehicle");
  var badge = document.querySelector("#live-bus-title .line-badge");
  var row = document.querySelector("#live-tracking .bus-card__line");
  var pill = document.getElementById("live-bus-pill");
  var to = document.getElementById("live-bus-to");
  var refresh = document.getElementById("live-refresh");
  var hero = document.getElementById("live-node");
  var tiles = Array.prototype.map.call(document.querySelectorAll("#next-buses > li"), function (li) {
    var s = getComputedStyle(li);
    return { text: li.textContent, aria: li.getAttribute("aria-label"), height: li.getBoundingClientRect().height,
      width: li.getBoundingClientRect().width, shadow: s.boxShadow, kids: li.children.length, selected: li.classList.contains("is-selected") };
  });
  return {
    card: box(card), badge: box(badge), badgeText: badge ? badge.textContent : null, row: box(row), pill: box(pill), to: box(to),
    toText: to.textContent, refresh: box(refresh), hero: box(hero), tiles: tiles,
    lineName: !!document.querySelector("#live-tracking .bus-card__line-name"),
    arriving: !!document.querySelector("#live-tracking .journey-step__arriving"),
    statusRows: !!document.getElementById("live-status"), thenLine: !!document.getElementById("live-then"),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = { sizes: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  await tapStart(h);
  await h.until("lastSuccess && lastSuccess.leg_kind === 'rail' && !entryPending", 15000, "the first poll");
  await h.sleep(400);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 5000, "Page B");
  await h.sleep(400);
  out.real = await h.eval(MEASURE);
  if (c.shots) {
    await h.screenshot(`${c.shots}/trainheader-${c.name || "a"}-real.png`);
  }
  // other termini in the same markup: a long one and a short one (the layout, not the data)
  for (const name of c.names) {
    await h.eval(`document.getElementById("live-bus-to").textContent = "To " + ${JSON.stringify(name)}; true`);
    await h.eval("document.fonts.ready.then(function () { return true; })");
    await h.sleep(300);
    out.sizes[name] = await h.eval(MEASURE);
    if (c.shots) {
      await h.screenshot(`${c.shots}/trainheader-${c.name || "a"}-${name.split(" ")[0]}.png`);
    }
  }
  return out;
}

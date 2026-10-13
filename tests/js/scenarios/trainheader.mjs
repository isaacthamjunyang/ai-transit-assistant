import { openHome, planOverview, tapStart } from "./common.mjs";

// Page B's train card: the header (badge and name on one row, the pill and the direction under the name, the refresh button
// at the top right) and the "Next trains" tiles (the time only, an aria-label with the line and the time).
// config: width, height, dark, names (the line names to try; the real one is measured first), shots (a folder).

const MEASURE = `(function () {
  function box(el) {
    if (!el) { return null; }
    var r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
  }
  var card = document.getElementById("live-tracking");
  var badge = document.querySelector("#live-bus-title .bus-card__badge .line-badge");
  var name = document.querySelector("#live-bus-title .bus-card__line-name");
  var line = document.getElementById("live-bus-title");
  var pill = document.getElementById("live-bus-pill");
  var to = document.getElementById("live-bus-to");
  var refresh = document.getElementById("live-refresh");
  var hero = document.querySelector("#live-tracking .bus-tile--hero");
  var range = document.createRange();
  range.selectNodeContents(name);
  var rects = Array.prototype.map.call(range.getClientRects(), function (r) { return { left: r.left, top: r.top, bottom: r.bottom }; });
  var lineHeight = parseFloat(getComputedStyle(name).lineHeight);
  var tiles = Array.prototype.map.call(document.querySelectorAll("#next-buses > li"), function (li) {
    var s = getComputedStyle(li);
    return { text: li.textContent, aria: li.getAttribute("aria-label"), height: li.getBoundingClientRect().height,
      width: li.getBoundingClientRect().width, shadow: s.boxShadow, kids: li.children.length, selected: li.classList.contains("is-selected") };
  });
  return {
    card: box(card), badge: box(badge), name: box(name), line: box(line), pill: box(pill), to: box(to), refresh: box(refresh),
    hero: box(hero), nameLines: Math.round(box(name).height / lineHeight), lineHeight: lineHeight,
    nameRects: rects.length, titleText: name.textContent, tiles: tiles,
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
  // other names in the same markup: a long one and a short one (the layout, not the data)
  for (const name of c.names) {
    await h.eval(`document.querySelector("#live-bus-title .bus-card__line-name").textContent = ${JSON.stringify(name)}; true`);
    await h.eval("document.fonts.ready.then(function () { return true; })");
    await h.sleep(300);
    out.sizes[name] = await h.eval(MEASURE);
    if (c.shots) {
      await h.screenshot(`${c.shots}/trainheader-${c.name || "a"}-${name.split(" ")[0]}.png`);
    }
  }
  return out;
}

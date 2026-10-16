import { openHome, planOverview, tapStart } from "./common.mjs";

// Bus crowding (LTA Load) on the real page: the label under Page A's heading and on the Next 3 buses tiles.
// The server's Load values are scripted by the test. config: width, height, dark.
const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  var chip = document.getElementById("catch-load");
  var tiles = Array.prototype.map.call(document.querySelectorAll("#next-buses .bus-tile-card"), function (t) {
    var c = t.querySelector(".crowd-chip");
    var tr = t.getBoundingClientRect(), cr = c ? c.getBoundingClientRect() : null;
    var svg = c ? c.querySelector("svg") : null;
    return { text: c ? text(c) : null, icon: !!(c && c.querySelector("svg")), code: c ? c.getAttribute("data-load") : null,
      right: tr.right, height: tr.height, color: c ? getComputedStyle(c).color : null, svg: svg ? svg.innerHTML : null,
      inside: !c || (cr.left >= tr.left - 0.5 && cr.right <= tr.right + 0.5 && cr.top >= tr.top - 0.5 && cr.bottom <= tr.bottom + 0.5),
      clipped: !!c && (c.scrollWidth > c.clientWidth + 1 || c.scrollHeight > c.clientHeight + 1),
      iconPx: svg ? svg.getBoundingClientRect().width : null };
  });
  var walkLines = Array.prototype.filter.call(document.querySelectorAll("p, span, div"), function (el) {
    return el.children.length === 0 && /^\\d+\\s*min walk$/.test(el.textContent.trim()) && el.getClientRects().length > 0;
  }).length;
  return { walkLines: walkLines, catchShown: !!chip && !chip.hidden, catchCode: chip ? chip.getAttribute("data-load") : null, catchText: text(chip), catchIcon: !!(chip && chip.querySelector("svg")), catchColor: chip ? getComputedStyle(chip).color : null, catchSvg: chip && chip.querySelector("svg") ? chip.querySelector("svg").innerHTML : null,
    catchInside: !chip || chip.hidden || chip.getBoundingClientRect().right <= window.innerWidth,
    tiles: tiles, scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    probability: lastSuccess && lastSuccess.buses ? lastSuccess.buses.map(function (b) { return b.probability && b.probability.point; }) : null,
    loads: lastSuccess && lastSuccess.buses ? lastSuccess.buses.map(function (b) { return b.load; }) : null };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  await tapStart(h);
  await h.until("lastSuccess && !entryPending", 20000, "the first poll");
  await h.sleep(900);
  out.pageA = await h.eval(READ);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 6000, "Page B");
  await h.sleep(500);
  out.pageB = await h.eval(READ);
  return out;
}

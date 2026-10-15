import { openHome, planOverview, tapStart } from "./common.mjs";

// Bus crowding (LTA Load) on the real page: the label under Page A's heading and on the Next 3 buses tiles.
// The server's Load values are scripted by the test. config: width, height, dark.
const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  var chip = document.getElementById("catch-load");
  var tiles = Array.prototype.map.call(document.querySelectorAll("#next-buses .bus-tile-card"), function (t) {
    var c = t.querySelector(".crowd-chip");
    return { text: c ? text(c) : null, icon: !!(c && c.querySelector("svg")), code: c ? c.getAttribute("data-load") : null,
      right: t.getBoundingClientRect().right };
  });
  return { catchShown: !!chip && !chip.hidden, catchText: text(chip), catchIcon: !!(chip && chip.querySelector("svg")),
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

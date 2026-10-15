import { openHome, planOverview, tapStart } from "./common.mjs";

// Every screen's rendered text and accessible names, for a bus leg then a train leg (bus stop 28059, station NS17). No bus
// stop code in brackets may be on screen; the station codes stay. config: width, height, dark.
const SCAN = `(function () {
  var names = [];
  Array.prototype.forEach.call(document.querySelectorAll("[aria-label], [title]"), function (el) {
    var style = getComputedStyle(el);
    if (el.getAttribute("aria-label")) { names.push(el.getAttribute("aria-label")); }
    if (el.getAttribute("title")) { names.push(el.getAttribute("title")); }
  });
  var labels = Array.prototype.map.call(document.querySelectorAll(".map-stop__label, .map-dest-live__label, .leaflet-marker-icon"),
    function (el) { return el.textContent; });
  return {
    top: screenStack[screenStack.length - 1],
    text: document.body.innerText.replace(/\\s+/g, " "),
    names: names.join(" | "), labels: labels.join(" | ")
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  out.overview = await h.eval(SCAN);
  await tapStart(h);
  await h.until("lastSuccess && !entryPending", 20000, "the first poll");
  await h.sleep(600);
  out.pageA = await h.eval(SCAN);
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.sleep(900);
  out.pageW = await h.eval(SCAN);
  await h.eval("history.back(); true");
  await h.sleep(500);
  await h.eval("if (screenStack[screenStack.length - 1] !== 'live') { backToScreen('live'); } true");
  await h.sleep(300);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 6000, "Page B");
  await h.sleep(600);
  out.pageB = await h.eval(SCAN);
  await h.eval("document.getElementById('catch-yes').click(); true");
  await h.sleep(1200);
  out.onWay = await h.eval(SCAN);
  return out;
}

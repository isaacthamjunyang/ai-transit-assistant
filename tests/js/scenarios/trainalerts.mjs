import { openHome, planOverview, tapStart } from "./common.mjs";

// Train service alerts on the real page: the banner under the journey summary and on the live pages (Page A, Page B).
// The server's alert answer is scripted by the test. config: width, height, dark.
const READ = (hostId) => `(function () {
  var host = document.getElementById(${JSON.stringify(hostId)});
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  var boxes = host ? Array.prototype.map.call(host.querySelectorAll(".alert--clamp"), function (box) {
    var t = box.querySelector(".alert__text");
    var toggle = box.querySelector(".alert__toggle");
    var icon = box.querySelector(".alert__icon svg");
    var line = parseFloat(getComputedStyle(t).lineHeight);
    return { text: text(t), line: box.getAttribute("data-line"), status: box.getAttribute("data-status"),
      lines: Math.round(t.getBoundingClientRect().height / line), toggleShown: !!toggle && !toggle.hidden,
      toggleText: toggle ? text(toggle) : null, expanded: toggle ? toggle.getAttribute("aria-expanded") : null,
      toggleHeight: toggle && !toggle.hidden ? toggle.getBoundingClientRect().height : 0,
      cls: t.className, boxCls: box.className, display: getComputedStyle(t).display, clamp: getComputedStyle(t).webkitLineClamp, overflow: getComputedStyle(t).overflow, lineHeight: line, h: t.getBoundingClientRect().height, icon: !!icon, right: box.getBoundingClientRect().right };
  }) : [];
  var el = document.getElementById(${JSON.stringify(hostId)});
  return { shown: !!host && !host.hidden && getComputedStyle(host).display !== "none", boxes: boxes,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    requests: __requests.filter(function (u) { return u.indexOf("/api/train-alerts") === 0; }).length };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  await h.sleep(700);
  out.overview = await h.eval(READ("overview-train-alerts"));
  await tapStart(h);
  await h.until("lastSuccess && !entryPending", 20000, "the first poll");
  await h.sleep(900);
  out.pageA = await h.eval(READ("live-train-alerts"));
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 6000, "Page B");
  await h.sleep(500);
  out.pageB = await h.eval(READ("live-train-alerts"));
  if (out.pageB.boxes.length && out.pageB.boxes[0].toggleShown) {
    // the expand control opens the whole text and closes it again; the state stays across the one-second redraw
    await h.eval(`document.querySelector("#live-train-alerts .alert__toggle").click(); true`);
    await h.sleep(1300);
    out.pageAExpanded = await h.eval(READ("live-train-alerts"));
  }
  return out;
}

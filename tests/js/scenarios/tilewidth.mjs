import { poll, toLive } from "./common.mjs";

// The REAL page (live view, a real poll): at each width, the Leave by tile in its states. The clock time and "Leave now"
// must be one line and not clipped. With config.shots a screenshot per state is written for the widths in config.shotWidths.
const MEASURE = `(function () {
  function lines(el) {
    var span = el.querySelector(".leave-tile__nowrap") || el;
    var rects = span.getClientRects();
    var tops = {};
    for (var i = 0; i < rects.length; i++) { tops[Math.round(rects[i].top)] = true; }
    return Object.keys(tops).length;
  }
  var value = document.getElementById("tile-leave-by");
  var tile = document.getElementById("tile-leave");
  var span = value.querySelector(".leave-tile__nowrap");
  return {
    text: value.textContent,
    valueScroll: value.scrollWidth, valueClient: value.clientWidth,
    spanWidth: Math.round(span.getBoundingClientRect().width), valueBox: Math.round(value.getBoundingClientRect().width),
    valueLines: lines(value), fontPx: parseFloat(getComputedStyle(value).fontSize),
    tileScroll: tile.scrollWidth, tileClient: tile.clientWidth,
    tileRight: Math.round(tile.getBoundingClientRect().right), viewport: document.documentElement.clientWidth,
    labelHidden: document.getElementById("tile-leave-label").hidden, tileName: tile.getAttribute("aria-label"),
    arrivalGone: document.getElementById("tile-arrival") === null,
    walkLine: (document.getElementById("pace-walk") || {}).textContent || "",
    tileFull: Math.abs(tile.getBoundingClientRect().width - document.getElementById("leave-tiles").getBoundingClientRect().width) < 1.5,
    pageScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    clipped: span.getBoundingClientRect().right > value.getBoundingClientRect().right + 0.5
  };
})()`;

export default async function (h) {
  const out = { widths: {} };
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  const states = {
    by: "lastSuccess.leave_by = new Date(Date.now() + 300000).toISOString(); lastExplanationPack.leave_by = lastSuccess.leave_by; true",
    now: "lastSuccess.leave_by = new Date(Date.now() + 20000).toISOString(); lastExplanationPack.leave_by = lastSuccess.leave_by; true",
    tomorrow: "lastSuccess.leave_by = new Date(Date.now() + 30 * 3600 * 1000).toISOString(); lastExplanationPack.leave_by = lastSuccess.leave_by; true"
  };
  for (const width of h.config.widths) {
    await h.send("Emulation.setDeviceMetricsOverride", { width, height: 1000, deviceScaleFactor: 1, mobile: true });
    await h.sleep(250);
    out.widths[width] = {};
    for (const [name, code] of Object.entries(states)) {
      await h.eval(code + "; refreshDisplay(monitorGeneration); true");
      out.widths[width][name] = await h.eval(MEASURE);
      if (h.config.shots && (h.config.shotWidths || []).includes(width) && name !== "tomorrow") {
        await h.eval("document.getElementById('arrival-card').scrollIntoView(); true");
        await h.sleep(200);
        await h.screenshot(`${h.config.shots}/tile-${name}-${width}-${h.config.dark ? "dark" : "light"}.png`);
      }
    }
  }
  return out;
}

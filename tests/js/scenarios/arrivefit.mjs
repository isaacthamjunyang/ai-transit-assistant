import { openHome } from "./common.mjs";

// The Custom arrive-by control must fit inside its card at phone widths: the time input, the Today / Tomorrow row and
// the preset chips end inside the card's inner edge, the page has no sideways scroll, and the value is left-aligned.
const MEASURE = `(function () {
  var panel = document.getElementById("arrive-by-panel");
  var cs = getComputedStyle(panel);
  var inner = panel.getBoundingClientRect().right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
  var innerLeft = panel.getBoundingClientRect().left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth);
  function box(el) { var r = el.getBoundingClientRect(); return { left: r.left, right: r.right, height: r.height }; }
  var time = document.getElementById("arrive-by-time");
  var tcs = getComputedStyle(time);
  var parts = [time].concat(Array.prototype.slice.call(document.querySelectorAll("#arrive-day button, .arrive-chips button")).filter(function (el) { return el.getBoundingClientRect().width > 0; }));
  return {
    viewport: document.documentElement.clientWidth,
    pageScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    innerLeft: innerLeft, innerRight: inner, panelRight: panel.getBoundingClientRect().right,
    time: box(time), parts: parts.map(function (el) { var b = box(el); return { id: el.id || el.className, left: b.left, right: b.right }; }),
    textAlign: tcs.textAlign, appearance: tcs.webkitAppearance || tcs.appearance, minWidth: tcs.minWidth, maxWidth: tcs.maxWidth,
    timeScroll: time.scrollWidth > time.clientWidth + 1,
    panelScroll: panel.scrollWidth > panel.clientWidth
  };
})()`;

export default async function (h) {
  const out = { widths: {} };
  await openHome(h);
  await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-custom').click(); true");
  for (const width of h.config.widths || [320, 360, 390]) {
    await h.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: true });
    await h.sleep(250);
    await h.eval("arriveTimeInput.value = '23:59'; arriveTimeInput.dispatchEvent(new Event('input', { bubbles: true })); true");
    out.widths[width] = await h.eval(MEASURE);
    if (h.config.shots) {
      await h.eval("document.getElementById('arrive-by-panel').scrollIntoView(); true");
      await h.sleep(150);
      await h.screenshot(`${h.config.shots}/arrivefit-${width}.png`);
    }
  }
  return out;
}

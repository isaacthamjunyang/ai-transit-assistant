import { openHome } from "./common.mjs";

// The Home heading is one line at every width and every text size. For the root font size at 100%, 125% and 150%: the
// number of line boxes the text takes, the heading's height, whether its text fits (scrollWidth against clientWidth),
// how much of the form's width the text spans, and any sideways scroll on the page. config: width, dark.
const MEASURE = `(function () {
  var h = document.getElementById("destination-heading");
  var form = document.getElementById("destination-form");
  var cs = getComputedStyle(h);
  var range = document.createRange();
  range.selectNodeContents(h);
  var lines = range.getClientRects().length;
  var text = range.getBoundingClientRect();
  var box = h.getBoundingClientRect();
  var oneLine = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.15;
  return { lines: lines, height: box.height, padding: parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom),
    lineHeight: oneLine, fontSize: parseFloat(cs.fontSize), whiteSpace: cs.whiteSpace,
    scrollWidth: h.scrollWidth, clientWidth: h.clientWidth, textWidth: text.width, formWidth: form.getBoundingClientRect().width,
    share: text.width / form.getBoundingClientRect().width,
    textMid: (text.left + text.right) / 2, formMid: (form.getBoundingClientRect().left + form.getBoundingClientRect().right) / 2,
    boxMid: (box.left + box.right) / 2, textAlign: cs.textAlign,
    pageScroll: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    gradient: cs.backgroundImage.indexOf("linear-gradient") === 0, clip: cs.backgroundClip || cs.webkitBackgroundClip,
    top: box.top + window.scrollY };
})()`;

export default async function (h) {
  const c = h.config;
  const out = { sizes: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: 800, permission: "granted" });
  for (const pct of [100, 125, 150]) {
    await h.eval(`document.documentElement.style.fontSize = "${pct}%"; true`);
    await h.sleep(200);
    out.sizes[pct] = await h.eval(MEASURE);
  }
  return out;
}

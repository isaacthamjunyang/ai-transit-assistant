import { writeFileSync } from "node:fs";

// Opens static/styleguide.html (config.guide, a file:// URL) at config.width and screenshots the Leave by tile states and
// every sentence variant, light and dark, into config.shots. Also reports overflow, clipped text and low contrast.
const GROUPS = [
  ["tiles", "Page A, action wait", "AI Explanation: loading", "catch"],
  ["sentences", "Sentence 1:", "Sentence 3:", "catch"],
  ["sentence3", "Sentence 3:", null, "catch"],
  ["walk-row", "Page A: the button row", "Page W, waiting", "pages"],
  ["walk-states", "Page W, waiting", "Page W, Sensor details open (measured", "pages"],
  ["walk-sensors", "Page W, Sensor details open (measured", null, "pages"]
];

const PAGE_CODE = `(function (theme, groups) {
  var root = null;
  var heads = [];
  function headStarting(text) {
    for (var i = 0; i < heads.length; i++) { if (heads[i].textContent.indexOf(text) === 0) { return heads[i]; } }
    return null;
  }
  function lum(rgb) {
    var c = rgb.map(function (v) { v = v / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function parse(color) {
    var m = /rgba?\\(([^)]+)\\)/.exec(color);
    if (!m) { return null; }
    var p = m[1].split(",").map(function (s) { return parseFloat(s); });
    return { rgb: [p[0], p[1], p[2]], a: p.length > 3 ? p[3] : 1 };
  }
  function backdrop(el) {
    var layers = [];
    for (var n = el; n; n = n.parentElement) {
      var b = parse(getComputedStyle(n).backgroundColor);
      if (b && b.a > 0) { layers.push(b); if (b.a >= 1) { break; } }
    }
    var base = [255, 255, 255];
    if (!layers.length || layers[layers.length - 1].a < 1) { base = parse(getComputedStyle(document.body).backgroundColor).rgb; }
    for (var i = layers.length - 1; i >= 0; i--) {
      base = base.map(function (v, k) { return layers[i].rgb[k] * layers[i].a + v * (1 - layers[i].a); });
    }
    return base;
  }
  var out = { clips: {}, overflow: [], clipped: [], contrast: {} };
  groups.forEach(function (g) {
    root = document.getElementById(g[3] + "-sample-" + theme);
    heads = Array.prototype.slice.call(root.querySelectorAll("h4"));
    var start = headStarting(g[1]);
    var stop = g[2] ? headStarting(g[2]) : null;
    if (!start) { out.clips[g[0]] = null; return; }
    var nodes = [];
    for (var n = start; n && n !== stop; n = n.nextElementSibling) { nodes.push(n); }
    var first = nodes[0].getBoundingClientRect();
    var last = nodes[nodes.length - 1].getBoundingClientRect();
    out.clips[g[0]] = { x: 0, y: first.top + window.scrollY - 6, width: document.documentElement.clientWidth, height: last.bottom - first.top + 12 };
    nodes.forEach(function (node) {
      var box = node.getBoundingClientRect();
      Array.prototype.slice.call(node.querySelectorAll("*")).concat([node]).forEach(function (el) {
        var rect = el.getBoundingClientRect();
        var style = getComputedStyle(el);
        var label = el.tagName.toLowerCase() + "." + String(el.className).split(" ")[0] + " \\"" + (el.textContent || "").slice(0, 40) + "\\"";
        if (rect.right > document.documentElement.clientWidth + 1 || rect.left < -1) { out.overflow.push(["outside viewport", label]); }
        if (el.scrollWidth > el.clientWidth + 1 && style.overflowX !== "visible" && el.clientWidth > 0) { out.overflow.push(["scrolls sideways", label]); }
        if ((style.overflow === "hidden" || style.overflowY === "hidden") && el.scrollHeight > el.clientHeight + 1 && el.clientHeight > 0) { out.clipped.push(["text clipped", label]); }
        if (style.textOverflow === "ellipsis" && el.scrollWidth > el.clientWidth + 1) { out.clipped.push(["ellipsis cut", label]); }
      });
      ["leave-tile__value", "leave-tile__meta", "leave-tile__warn", "leave-tile__label", "ai-card__text", "walk-chance__trend", "walk-sensors__why", "walk-open-row__sub", "walk-status__state", "walk-status__distance", "sample-walk-map__chip"].forEach(function (cls) {
        Array.prototype.slice.call(node.getElementsByClassName(cls)).forEach(function (el) {
          var fg = parse(getComputedStyle(el).color);
          if (!fg) { return; }
          var bg = backdrop(el);
          var a = lum(fg.rgb), b = lum(bg);
          var ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
          if (out.contrast[cls] === undefined || ratio < out.contrast[cls]) { out.contrast[cls] = Math.round(ratio * 100) / 100; }
        });
      });
    });
  });
  return out;
})`;

export default async function (h) {
  const out = { files: [], reports: {} };
  const width = h.config.width;
  await h.open(h.config.guide, { width, height: 900, dark: false, settle: 900 });
  await h.eval("document.body.scrollWidth");
  for (const theme of ["light", "dark"]) {
    const report = await h.eval(`${PAGE_CODE}("${theme}", ${JSON.stringify(GROUPS)})`);
    const clips = report.clips;
    for (const [name] of GROUPS) {
      const clip = clips[name];
      if (!clip) continue;
      const shot = await h.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { ...clip, scale: 1 } });
      const path = `${h.config.shots}/guide-${name}-${theme}-${width}.png`;
      writeFileSync(path, Buffer.from(shot.data, "base64"));
      out.files.push(path);
    }
    const sideways = await h.eval("document.documentElement.scrollWidth > document.documentElement.clientWidth");
    out.wide = await h.eval(`(function () {
      var w = document.documentElement.clientWidth, list = [];
      Array.prototype.slice.call(document.querySelectorAll("body *")).forEach(function (el) {
        var r = el.getBoundingClientRect();
        if (r.right > w + 1 && r.width > 0) { list.push([Math.round(r.right), el.tagName.toLowerCase() + "." + String(el.className).split(" ")[0], (el.closest("section") || {}).id || ""]); }
      });
      return { scrollWidth: document.documentElement.scrollWidth, clientWidth: w, count: list.length, sample: list.slice(0, 6) };
    })()`);
    out.reports[theme] = { overflow: report.overflow, clipped: report.clipped, contrast: report.contrast, pageScrollsSideways: sideways };
  }
  return out;
}

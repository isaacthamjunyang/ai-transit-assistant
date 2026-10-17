import { openHome } from "./common.mjs";

// The hamburger menu on Home: exactly two rows, no data-status lines and no /api/data-status call from the page;
// then its attribution at the bottom of the panel and the bare "How it works" card. config: width, height, dark.
const MENU = `(function () {
  var sheet = document.getElementById("menu-sheet");
  var rows = Array.prototype.filter.call(sheet.querySelectorAll(".menu-row"), function (el) {
    return el.getClientRects().length > 0;
  }).map(function (el) { return el.textContent.replace(/\\s+/g, " ").trim(); });
  return { sheetHidden: sheet.hidden, rows: rows, text: sheet.textContent.replace(/\\s+/g, " ").trim(),
    dataBox: !!document.getElementById("menu-data"),
    demoShown: document.getElementById("demo-controls").getClientRects().length > 0 };
})()`;
const ATTRIBUTION = `(function () {
  var sheet = document.getElementById("menu-sheet");
  var line = document.getElementById("menu-attribution");
  var cs = getComputedStyle(line), r = line.getBoundingClientRect(), c = sheet.getBoundingClientRect();
  var rows = Array.prototype.filter.call(sheet.querySelectorAll(".menu-row"), function (el) { return el.getClientRects().length > 0; });
  var lastRow = rows[rows.length - 1].getBoundingClientRect();
  return { text: line.textContent.trim(), isLast: sheet.lastElementChild === line, color: cs.color, fontSize: cs.fontSize,
    visible: r.width > 0 && r.height > 0 && cs.visibility === "visible",
    inside: r.left >= c.left && r.right <= c.right + 0.5 && r.bottom <= c.bottom + 0.5,
    belowRows: r.top >= lastRow.bottom - 1, background: getComputedStyle(sheet).backgroundColor,
    bodyColor: getComputedStyle(document.querySelector(".menu-row")).color,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;
const CARD = `(function () {
  var card = document.querySelector(".first-run__card");
  var kids = Array.prototype.map.call(card.children, function (el) { return el.id || el.className; });
  return { children: kids, text: card.textContent.replace(/\\s+/g, " ").trim(),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height });
  await h.eval("window.__statusCalls = 0; var f = window.fetch; window.fetch = function (u, o) { if (String(u).indexOf('/api/data-status') !== -1) { window.__statusCalls++; } return f.call(window, u, o); }; true");
  await h.eval("document.getElementById('menu-open').click(); true");
  await h.sleep(900);
  out.menu = await h.eval(MENU);
  out.attribution = await h.eval(ATTRIBUTION);
  out.calls = await h.eval("window.__statusCalls");
  await h.eval("document.getElementById('how-it-works').click(); true");
  await h.sleep(600);
  out.card = await h.eval(CARD);
  return out;
}

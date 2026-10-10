import { openHome } from "./common.mjs";

// The hamburger menu on Home: the two status lines after the menu opens, and the failure case.
// config.fail is "404" (a non-200), "network" (the request rejects) or "" (normal).
const READ = `(function () {
  function one(id) {
    var el = document.getElementById(id);
    var cs = getComputedStyle(el), r = el.getBoundingClientRect();
    return { text: el.textContent, hidden: el.hidden, display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
      color: cs.color, height: r.height, width: r.width, fontSize: cs.fontSize,
      clipped: el.scrollHeight > el.clientHeight + 1 };
  }
  var sheet = document.getElementById("menu-sheet");
  var box = document.getElementById("menu-data");
  return { sheetHidden: sheet.hidden, sheetDisplay: getComputedStyle(sheet).display,
    boxDisplay: getComputedStyle(box).display, boxHeight: box.getBoundingClientRect().height,
    sheetBottom: sheet.getBoundingClientRect().bottom, boxBottom: box.getBoundingClientRect().bottom,
    holidays: one("menu-data-holidays"), bus: one("menu-data-bus"),
    rail: one("menu-data-rail"), attribution: one("menu-data-attribution"),
    surface: getComputedStyle(sheet).backgroundColor, bodyClass: document.body.className };
})()`;

export default async function (h) {
  const out = { fail: h.config.fail || "" };
  await openHome(h);
  if (h.config.fail === "404") {
    await h.eval("window.__realFetch = window.fetch; window.fetch = function (u, o) { return String(u).indexOf('/api/data-status') !== -1 ? Promise.resolve(new Response('{}', { status: 404 })) : window.__realFetch(u, o); }; true");
  } else if (h.config.fail === "network") {
    await h.eval("window.__realFetch = window.fetch; window.fetch = function (u, o) { return String(u).indexOf('/api/data-status') !== -1 ? Promise.reject(new TypeError('Failed to fetch')) : window.__realFetch(u, o); }; true");
  }
  await h.eval("window.__statusCalls = 0; var f = window.fetch; window.fetch = function (u, o) { if (String(u).indexOf('/api/data-status') !== -1) { window.__statusCalls++; } return f.call(window, u, o); }; true");
  await h.eval("document.getElementById('menu-open').click(); true");
  await h.sleep(1200);
  out.afterOpen = await h.eval(READ);
  out.calls = await h.eval("window.__statusCalls");
  await h.eval("document.getElementById('menu-open').click(); document.getElementById('menu-open').click(); true");
  await h.sleep(800);
  out.afterReopen = await h.eval(READ);
  out.callsAfterReopen = await h.eval("window.__statusCalls");
  if (h.config.shots) { await h.screenshot(`${h.config.shots}/menudata-${out.fail || "ok"}.png`); }
  return out;
}

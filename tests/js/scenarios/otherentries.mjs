import { openHome, planOverview, tapStart } from "./common.mjs";
export default async function (h) {
  const c = h.config;
  await openHome(h, { permission: "granted", width: 360, height: 800, dark: false });
  await planOverview(h);
  await tapStart(h);
  await h.until("!entryPending && lastSuccess", 20000, "first poll");
  await h.sleep(1200);
  await h.eval(c.entry === "other" ? "document.getElementById('other-bus-options').click(); true" : "document.getElementById('catch-no').click(); true");
  await h.sleep(300);
  await h.until("pageC && !pageC.loading", 20000, "page C options");
  await h.sleep(500);
  return await h.eval(`(function () {
    function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
    var o = pageC.options;
    return { entry: pageC.entry, failed: pageC.failed, mode: o && o.mode, cards: o && o.cards ? o.cards.length : null, rows: o && o.rows ? o.rows.length : null,
      notice: text("reroute-notice"), none: text("page-c-none"), requests: __requests.filter(function (u) { return u.indexOf("/api/reroute-options") === 0; }) };
  })()`);
}

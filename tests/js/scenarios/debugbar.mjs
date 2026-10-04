import { openHome, planOverview, tapStart } from "./common.mjs";

// The ?pace=debug bar on the real page: on top of every sticky bar, one line, and kept through navigation.
const RECT = `(function () {
  var bar = document.querySelector("#pace-debug .pace-debug__bar");
  var r = bar.getBoundingClientRect();
  var hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {top: r.top, height: r.height, width: r.width, vw: window.innerWidth,
    onTop: !!(hit && hit.closest("#pace-debug")), text: bar.textContent, search: location.search};
})()`;

export default async function (h) {
  const out = {};
  await openHome(h, { query: "?pace=debug", permission: "granted" });
  out.beforeStart = await h.eval(RECT);
  await planOverview(h);
  out.onOverview = await h.eval(RECT);
  await tapStart(h);
  await h.eval("pushScreen('arrivals'); true");
  await h.until("!document.getElementById('catch-bar').hidden", 10000, "the question bar");
  out.onLive = await h.eval(RECT);
  await h.eval("document.querySelector('#pace-debug .pace-debug__bar').click(); true");
  out.open = await h.eval(`(function () {
    var panel = document.querySelector("#pace-debug .pace-debug__panel");
    var r = panel.getBoundingClientRect();
    var hit = document.elementFromPoint(r.left + r.width / 2, r.top + 10);
    return {hidden: panel.hidden, onTop: !!(hit && hit.closest("#pace-debug")), bottom: r.bottom, vh: window.innerHeight,
      buttons: document.querySelectorAll("#pace-debug .pace-debug__button").length};
  })()`);
  await h.eval("document.querySelector('#pace-debug .pace-debug__bar').click(); true");
  await h.eval("goHome(); true");
  out.afterHome = await h.eval(RECT);
  out.boxes = await h.eval("document.querySelectorAll('#pace-debug').length");
  return out;
}

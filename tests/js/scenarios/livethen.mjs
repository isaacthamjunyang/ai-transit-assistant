import { openHome, planOverview, tapStart } from "./common.mjs";

// The live page's "Then ..." line with the next leg's data type under it. config: width, height, dark, mode ("hold" runs the
// 90 s hold checks), shots (a folder). The test server records every BusArrival query (lta_log).
const THEN = `(function () {
  var el = document.getElementById("live-then");
  var when = el.querySelector(".live-then__when");
  var box = el.getBoundingClientRect();
  return {
    shown: !el.hidden && getComputedStyle(el).display !== "none", text: el.textContent.replace(/\\s+/g, " ").trim(),
    when: when ? when.textContent : null, right: box.right, width: box.width, color: getComputedStyle(el).color,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, top: screenStack[screenStack.length - 1]
  };
})()`;

const LATER = `__requests.filter(function (u) { return u.indexOf("/api/arrivals/later?") === 0; })`;

async function settle(h) {
  await h.sleep(1300);  // the one-second display tick redraws the line
  return h.eval(THEN);
}

export default async function (h) {
  const out = {};
  await openHome(h, { dark: h.config.dark, width: h.config.width, height: h.config.height });
  await planOverview(h);
  await tapStart(h);
  await h.eval("document.getElementById('see-arrivals').click(); true");  // the line is on the bus card (Page B)
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 8000, "the bus arrivals page");
  out.start = await h.eval(THEN);
  if (h.config.mode === "rail") {
    await h.sleep(1500);
    out.requests = await h.eval(LATER);
    out.rail = await settle(h);
    return out;
  }
  if (h.config.mode === "single") {
    await h.sleep(1500);
    out.single = await settle(h);
    out.requests = await h.eval(LATER);
    return out;
  }
  await h.until(`${LATER}.length >= 1 && Object.keys(laterCache).length >= 1`, 15000, "the later-leg lookup");
  out.live = await settle(h);
  if (h.config.shots) {
    await h.screenshot(`${h.config.shots}/livethen-${h.config.name || "x"}.png`);
  }
  // 80 s after the last answer: still live. Then a failing lookup: still live. 95 s: the scheduled line, no error text.
  const stop = await h.eval("Object.keys(laterCache)[0]");
  await h.eval(`laterCache[${JSON.stringify(stop)}].fetched_at = new Date(Date.now() - 80000).toISOString(); true`);
  out.at80 = await settle(h);
  await h.eval(`window.fetch = function () { return Promise.reject(new Error("down")); }; laterAt = {}; maybeLookupLater(); true`);
  await h.sleep(500);
  out.afterFailure = await settle(h);
  await h.eval(`laterCache[${JSON.stringify(stop)}].fetched_at = new Date(Date.now() - 95000).toISOString(); true`);
  out.at95 = await settle(h);
  out.bodyText = await h.eval("document.body.innerText");
  return out;
}

import { openHome, planOverview, tapStart } from "./common.mjs";

// Page B has no "Then ..." line. The later leg's lookup still runs and its answer is still kept (laterCache, 90 s), so the
// scenario reads that data and the page text. config: width, height, dark, mode ("rail" or "single"), shots (a folder).
// The test server records every BusArrival query (lta_log).
const STATE = `(function () {
  var stop = Object.keys(laterCache)[0];
  var kept = stop ? laterLiveFor({ boarding_stop_code: stop, service_no: "36" }) : null;
  var box = document.getElementById("live-tracking").getBoundingClientRect();
  return {
    thenElement: !!document.getElementById("live-then"), kept: !!kept, stops: Object.keys(laterCache).length,
    text: document.body.innerText.replace(/\\s+/g, " "), top: screenStack[screenStack.length - 1],
    right: box.right, width: box.width, scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

const LATER = `__requests.filter(function (u) { return u.indexOf("/api/arrivals/later?") === 0; })`;

async function settle(h) {
  await h.sleep(1300);  // the one-second display tick
  return h.eval(STATE);
}

export default async function (h) {
  const out = {};
  await openHome(h, { dark: h.config.dark, width: h.config.width, height: h.config.height });
  await planOverview(h);
  await tapStart(h);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 8000, "the bus arrivals page");
  out.start = await h.eval(STATE);
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
  // 80 s after the last answer: still kept. Then a failing lookup: still kept. 95 s: dropped, nothing drawn either way.
  const stop = await h.eval("Object.keys(laterCache)[0]");
  await h.eval(`laterCache[${JSON.stringify(stop)}].fetched_at = new Date(Date.now() - 80000).toISOString(); true`);
  out.at80 = await settle(h);
  await h.eval(`window.fetch = function () { return Promise.reject(new Error("down")); }; laterAt = {}; maybeLookupLater(); true`);
  await h.sleep(500);
  out.afterFailure = await settle(h);
  await h.eval(`laterCache[${JSON.stringify(stop)}].fetched_at = new Date(Date.now() - 95000).toISOString(); true`);
  out.at95 = await settle(h);
  return out;
}

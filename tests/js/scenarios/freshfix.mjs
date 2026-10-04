import { openHome, planOverview } from "./common.mjs";

// Start journey after a long planner session: the last fix is old, so a fresh one is asked for first (maximumAge 0,
// 4 s), and the first poll goes out whatever the result, never later than about 4 s.
const FIRST = "__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; })";

export default async function (h) {
  const which = h.config.which;  // "old", "hang", "fail" or "recent"
  const out = { which };
  await openHome(h, { permission: "granted" });
  await planOverview(h);
  await h.eval(`__geo.setMode(${JSON.stringify(which === "hang" || which === "fail" ? which : "ok")}); true`);
  const age = which === "recent" ? 2000 : 120000;
  await h.eval(`userLocationTimestamp = Date.now() - ${age}; true`);
  out.callsBefore = await h.eval("__geo.state.getCalls");
  out.optionsBefore = await h.eval("__geo.state.options.length");
  const startedAt = Date.now();
  await h.eval("document.getElementById('start-journey').click(); true");
  await h.until(`${FIRST}.length > 0`, 15000, "the first poll");
  out.elapsedMs = Date.now() - startedAt;
  out.url = await h.eval(`${FIRST}[0]`);
  out.pageNow = await h.eval("Date.now()");
  out.newCalls = await h.eval(`__geo.state.options.slice(${out.optionsBefore})`);
  const match = /[?&]location_timestamp=([0-9.]+)/.exec(out.url);
  out.sentTimestamp = match ? Number(match[1]) : null;
  out.hasLocation = /[?&]lat=/.test(out.url);
  out.pollMs = await h.eval("POLL_MS");
  return out;
}

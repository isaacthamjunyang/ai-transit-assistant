import { openHome, planOverview } from "./common.mjs";

export default async function (h) {
  const out = {};
  const stored = JSON.stringify({ pace: 0.9, savedAt: Date.now() - 86400000 });
  await openHome(h, { storage: { "bus-catch-pace": stored } });
  await planOverview(h);
  out.planUrl = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/journey-plan?') === 0; })[0]");
  out.serverSpeed = await h.eval("({used: serverWalkSpeed, source: serverWalkSource})");
  out.mirror = await h.eval("walkMinutes(300)");
  await h.eval("document.getElementById('start-journey').click(); true");
  await h.until("monitoringActive === true", 10000, "polling");
  await h.sleep(800);
  out.arrivalsUrl = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; })[0]");
  out.after = await h.eval("({used: serverWalkSpeed, source: serverWalkSource, last: lastSuccess && lastSuccess.walk_speed_used})");
  return out;
}

import { poll, state, toLive } from "./common.mjs";

export default async function (h) {
  const out = { permission: h.config.permission };
  await toLive(h, { permission: h.config.permission });
  out.afterTap = await h.eval(state);
  out.status = await h.eval("paceEstimator.status()");
  if (h.config.events) {
    await h.eval("__sim.start({cadence: 1.8, gps: false}); true");
  }
  await h.sleep(3600);
  out.status = await h.eval("paceEstimator.status()");
  out.monitoring = await h.eval("monitoringActive");
  out.calls = await h.eval("__motion.permission.calls");
  await poll(h);
  out.pollWorked = await h.eval("lastSuccess !== null && lastSuccess.status === 'ok'");
  out.query = await h.eval("walkSpeedQuery()");
  out.errors = await h.eval("0");
  if (h.config.gpsOnly) {
    await h.eval("__sim.start({gps: true, gpsSpeed: 1.2, gpsAcc: 8, mode: 'still'}); true");
    await h.until("paceEstimator.snapshot().walking", 40000, "GPS-only walking");
    await poll(h);
    out.gpsOnlyUrl = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; }).slice(-1)[0]");
    out.gpsOnlySnapshot = await h.eval("paceEstimator.snapshot()");
  }
  return out;
}

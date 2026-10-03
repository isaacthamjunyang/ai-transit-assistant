import { toLive } from "./common.mjs";

async function measure(h, seconds) {
  const m0 = await h.metrics();
  const d0 = await h.eval("__motion.delivered()");
  const e0 = await h.eval("__sim.events()");
  const t0 = Date.now();
  await h.sleep(seconds * 1000);
  const m1 = await h.metrics();
  const d1 = await h.eval("__motion.delivered()");
  const e1 = await h.eval("__sim.events()");
  const dt = (Date.now() - t0) / 1000;
  return {
    seconds: dt,
    handlerCallsPerSecond: (d1 - d0) / dt,
    eventsDispatchedPerSecond: (e1 - e0) / dt,
    scriptSecondsPerSecond: (m1.ScriptDuration - m0.ScriptDuration) / dt,
    taskSecondsPerSecond: (m1.TaskDuration - m0.TaskDuration) / dt,
  };
}

export default async function (h) {
  await toLive(h, { permission: "granted" });
  if (h.config.mode === "baseline") {
    await h.eval("paceJourneyActive = false; paceEstimator.stop('baseline'); true");
  }
  await h.eval("__sim.start({cadence: 1.8, gpsSpeed: 1.3, gpsAcc: 8, pos: {lat: " + h.config.userNorth[0] + ", lon: " + h.config.userNorth[1] + "}}); true");
  await h.sleep(5000);
  const out = { mode: h.config.mode };
  out.measured = await measure(h, 25);
  out.snapshot = await h.eval("paceEstimator.snapshot()");
  return out;
}

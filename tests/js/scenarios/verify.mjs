import { poll, toLive, openHome, planOverview } from "./common.mjs";

const SNAP = `(function () { var s = paceEstimator.snapshot(); return {mode: s.mode, walking: s.walking, why: s.walkingReason,
  cadence: s.cadence && +s.cadence.toFixed(3), gps: s.gpsSpeed, stepLength: +s.stepLength.toFixed(3), steps: s.stepCount,
  smoothed: s.smoothed && +s.smoothed.toFixed(3), sent: s.sent, source: s.sentSource, motion: s.motion}; })()`;
const POS = (c) => "pos: {lat: " + c.userNorth[0] + ", lon: " + c.userNorth[1] + "}";

async function pollInfo(h) {
  await poll(h);
  return h.eval(`({url: __requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; }).slice(-1)[0].replace(/.*(walk_speed[^&]*&?walk_speed_source=[a-z]+).*/, '$1'),
    server: {used: lastSuccess.walk_speed_used, source: lastSuccess.walk_speed_source}, point: lastSuccess.buses[0].probability.point})`);
}

export default async function (h) {
  const c = h.config;
  const out = { case: c.case };
  if (c.case === "1") {
    await toLive(h, { permission: "granted" });
    await h.eval("__sim.start({cadence: 1.8, gpsSpeed: 1.3, gpsAcc: 8, " + POS(c) + "}); true");
    await h.sleep(135000);
    out.learned = await h.eval(SNAP);
    out.pollWithGps = await pollInfo(h);
    await h.eval("__sim.set({gps: false}); true");
    await h.sleep(32000);
    out.gpsLost = await h.eval(SNAP);
    out.pollCadence = await pollInfo(h);
    out.trueSpeed = 1.3;
  } else if (c.case === "2") {
    await toLive(h, { permission: "granted" });
    await h.eval("__sim.start({mode: 'still', cadence: 1.8, gpsSpeed: 0.05, gpsAcc: 8, " + POS(c) + "}); true");
    await h.sleep(20000);
    out.standing = await h.eval(SNAP);
    out.standingPoll = await pollInfo(h);
    await h.eval("__sim.set({mode: 'walk', gpsSpeed: 1.3}); true");
    await h.sleep(22000);
    out.walking = await h.eval(SNAP);
    out.walkingPoll = await pollInfo(h);
    await h.eval("__sim.set({mode: 'still', gpsSpeed: 0.05}); true");
    await h.sleep(20000);
    out.after20sStop = await h.eval(SNAP);
    out.stopPoll = await pollInfo(h);
  } else if (c.case === "3") {
    await toLive(h, { permission: "granted" });
    await h.eval("__sim.start({mode: 'shake', gpsSpeed: 0.05, gpsAcc: 8, " + POS(c) + "}); true");
    await h.sleep(40000);
    out.shakeWithGpsStill = await h.eval(SNAP);
    await h.eval("__sim.set({gps: false, mode: 'shake'}); true");
    await h.sleep(20000);
    out.shakeNoGps = await h.eval(SNAP);
    out.shakePoll = await pollInfo(h);
  } else if (c.case === "4") {
    await toLive(h, { permission: "granted" });
    await h.eval("__sim.start({mode: 'walk', cadence: 1.8, gpsSpeed: 8, gpsAcc: 8, " + POS(c) + "}); true");
    await h.sleep(45000);
    out.vehicle = await h.eval(SNAP);
    out.vehiclePoll = await pollInfo(h);
  } else if (c.case === "5") {
    await toLive(h, { permission: "denied" });
    await h.eval("__sim.start({mode: 'walk', cadence: 1.8, gpsSpeed: 1.2, gpsAcc: 8, " + POS(c) + "}); true");
    await h.sleep(30000);
    out.denied = await h.eval(SNAP);
    out.motionEventsDelivered = await h.eval("__motion.delivered()");
    out.listeners = await h.eval("__motion.listeners()");
    out.deniedPoll = await pollInfo(h);
    out.journeyWorks = await h.eval("monitoringActive && lastSuccess.status === 'ok'");
  } else if (c.case === "6") {
    await openHome(h, { permission: "granted" });
    await planOverview(h);
    await h.eval("showDemoChrome(true); true");
    await h.eval("document.getElementById('start-journey').click(); true");
    await h.until("monitoringActive === true", 10000, "polling");
    await h.eval("__sim.start({cadence: 1.8, gpsSpeed: 1.3, gpsAcc: 8, " + POS(c) + "}); true");
    await h.sleep(20000);
    out.demo = { wanted: await h.eval("paceEstimator.isWanted()"), listeners: await h.eval("__motion.listeners()"), watching: await h.eval("__geo.watching()"),
      permissionCalls: await h.eval("__motion.permission.calls"), query: await h.eval("walkSpeedQuery()") };
    out.demoPoll = await pollInfo(h);
  }
  return out;
}

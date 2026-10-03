import { poll, state, toLive } from "./common.mjs";

const SPEED_URL = "__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; }).slice(-1)[0] || ''";

export default async function (h) {
  const which = h.config.which;
  const c = h.config;
  const out = { which };
  await toLive(h, { permission: "granted" });
  out.started = await h.eval(state);

  if (which === "near") {
    __sim_start: {
      await h.eval("__sim.start({cadence: 1.8, gpsSpeed: 1.3, gpsAcc: 8, pos: {lat: " + c.userNorth[0] + ", lon: " + c.userNorth[1] + "}}); true");
    }
    await h.until("paceEstimator.snapshot().walking", 45000, "walking detected");
    await poll(h);
    out.firstPollUrl = await h.eval(SPEED_URL);
    out.firstPollSpeed = await h.eval("({used: serverWalkSpeed, source: serverWalkSource})");
    // Move to within 20 m of the stop; the estimator's watch delivers the newer fix to the page.
    const nearLat = c.lat + (20 / 6371000) * 180 / Math.PI;
    await h.eval("__sim.set({pos: {lat: " + nearLat + ", lon: " + c.lon + "}}); true");
    await h.until("Math.abs(userLat - " + nearLat + ") < 1e-7", 8000, "the page to take the watch fix");
    out.usedWatchFix = true;
    await poll(h);
    out.afterFirstNear = await h.eval(state);
    out.nearFlag1 = await h.eval("lastSuccess && lastSuccess.near_stop");
    await poll(h);
    out.afterSecondNear = await h.eval(state);
    const delivered = await h.eval("__motion.delivered()");
    await h.sleep(1500);
    out.deliveredAfterStop = (await h.eval("__motion.delivered()")) - delivered;
    out.frozenUrls = [];
    await poll(h);
    out.frozenUrls.push(await h.eval(SPEED_URL));
    await h.sleep(2200);
    await poll(h);
    out.frozenUrls.push(await h.eval(SPEED_URL));
    out.frozenSpeed = await h.eval("({used: serverWalkSpeed, source: serverWalkSource})");
    // a new Start journey tap restarts it for the next leg
    await h.eval("pushScreen('live'); beginPaceEstimator(); true");
    await h.sleep(400);
    out.restarted = await h.eval(state);
    return out;
  }

  if (which === "yes" || which === "no") {
    await h.eval("pushScreen('arrivals'); true");
    await h.until("!document.getElementById('catch-bar').hidden", 10000, "the catch question");
    out.beforeAnswer = await h.eval(state);
    await h.eval("document.getElementById('catch-" + which + "').click(); true");
    await h.sleep(500);
  } else if (which === "end") {
    await h.eval("endTracking('max'); true");
    out.endCardShown = await h.eval("!document.getElementById('end-card').hidden");
  } else if (which === "leave") {
    await h.eval("requestHome(); true");
    await h.eval("document.getElementById('leave-leave').click(); true");
  } else if (which === "back") {
    await h.eval("pushScreen('arrivals'); true");
    await h.eval("requestBack ? 0 : 0; true").catch(() => 0);
    await h.eval("pendingLeaveAction = 'back'; openLeaveDialog(); document.getElementById('leave-leave').click(); true");
  } else if (which === "hidden") {
    await h.eval("__setHidden(true); true");
    out.whileHidden = await h.eval(state);
    await h.eval("__setHidden(false); true");
    out.afterShown = await h.eval(state);
    return out;
  } else if (which === "leg2") {
    await h.eval("activeRoutePlan.route_type = 'one_transfer'; activeRoutePlan.leg_index = 2; syncPaceEstimator(); true");
  } else if (which === "onway") {
    await h.eval("pushScreen('onway'); true");
  } else if (which === "newjourney") {
    await h.eval("pushScreen('newjourney'); true");
    out.whileOverview = await h.eval(state);
    await h.eval("pushScreen('live'); true");
    out.backOnLive = await h.eval(state);
    return out;
  } else if (which === "demo") {
    await h.eval("showDemoChrome(true); true");
  } else if (which === "ended-by-unanswered") {
    await h.eval("endTracking('unanswered'); true");
  }
  out.after = await h.eval(state);
  out.afterRequests = await h.eval("__requests.length");
  return out;
}

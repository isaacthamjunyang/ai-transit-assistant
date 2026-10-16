import { openHome, planOverview, poll, tapStart } from "./common.mjs";

// The rescore on Page A: when it runs, when it never runs, and what a good answer changes on screen.
const COUNT = "__requests.filter(function (u) { return u.indexOf('/api/rescore') === 0; }).length";
const VIEW = `({
  ring: document.getElementById('catch-ring-text').textContent,
  aria: document.getElementById('catch-ring').getAttribute('aria-label'),
  tile: document.getElementById('tile-leave-by').textContent,
  detail: ((document.getElementById('pace-walk') || {}).textContent || ''),
  card: document.getElementById('ai-explanation-text').textContent,
  chip: document.getElementById('pace-slot').textContent.trim(),
  pack: lastExplanationPack ? lastExplanationPack.text : null
})`;

export default async function (h) {
  const out = { never: {} };
  const asked = async (code) => {
    const before = await h.eval(COUNT);
    await h.eval(`(function () { ${code}; walkLastRescoreAt = 0; walkRescoreTick(true); })(); true`);
    await h.sleep(500);
    return (await h.eval(COUNT)) - before;
  };

  // before Start journey: the overview is not Page A, polling has not started
  await openHome(h, { permission: "granted" });
  await planOverview(h);
  out.never.beforeStart = {
    allowed: await h.eval("rescoreAllowed()"), timer: await h.eval("walkRescoreTimer != null"),
    asked: await asked("true"),
  };

  await tapStart(h);
  await h.until("!explanationInFlight", 15000, "the first explanation request");
  await poll(h);
  out.onPageA = { top: await h.eval("screenStack[screenStack.length - 1]"), allowed: await h.eval("rescoreAllowed()"),
    timer: await h.eval("walkRescoreTimer != null") };
  // the first request on Page A
  out.firstAsked = await asked("true");
  out.url = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/rescore') === 0; }).pop()");
  await h.until("!walkRescoreBusy", 8000, "the rescore to finish");

  // one scoring: a real answer for a position 560 m away replaces ring, tile, card and chip together
  const body = await h.eval(`(async function () {
    var lat = ${h.config.lat} + 560 / 111195;
    var url = "/api/rescore?stop_code=" + selectedBoardingStop.stop_code + "&service_no=" + selectedService
      + "&lat=" + lat + "&lon=${h.config.lon}&accuracy=8&location_timestamp=" + Date.now()
      + "&explanation_rendered=1&explanation_in_flight=0";
    var response = await fetch(url);
    return await response.json();
  })()`);
  out.answerStatus = body.status;
  const before = await h.eval(`(function () { return ${VIEW}; })()`);
  out.before = before;
  out.beforePoint = await h.eval("featuredBus(lastSuccess.buses).probability.point");
  out.applied = await h.eval(`(function () {
    var body = ${JSON.stringify(body)};
    var was = lastSuccess;
    applyRescore(body);
    refreshDisplay(monitorGeneration);
    var hero = featuredBus(lastSuccess.buses);
    var e = explanationMinutes(hero.arrival_time);
    return {
      replaced: lastSuccess !== was,
      point: hero.probability.point, bodyPoint: body.buses.filter(function (b) { return b.arrival_time === hero.arrival_time; })[0].probability.point,
      leaveBy: lastSuccess.leave_by, bodyLeaveBy: body.leave_by,
      packIsBodys: lastExplanationPack === body.explanation || JSON.stringify(lastExplanationPack) === JSON.stringify(body.explanation),
      expectedCard: explanationCardText(lastExplanationPack, e, hero.arrival_time, Date.now()),
      expectedTile: leaveTileView(lastSuccess, lastExplanationPack, hero.arrival_time, Date.now()),
      bodyPace: hero.probability.pace, paceShown: paceShown,
      view: ${VIEW}
    };
  })()`);

  // "use_poll" changes nothing
  out.usePoll = await h.eval(`(function () {
    var was = lastSuccess;
    var view = JSON.stringify(${VIEW});
    applyRescore({ status: "use_poll", reason: "no_recent_arrivals", near_stop: false });
    return { same: lastSuccess === was, viewSame: JSON.stringify(${VIEW}) === view };
  })()`);

  // a reroute active (action switch_route): a good answer is ignored
  out.reroute = await h.eval(`(function () {
    var body = ${JSON.stringify(body)};
    lastSuccess.chosen_action = "switch_route";
    var was = lastSuccess;
    var view = JSON.stringify(${VIEW});
    applyRescore(body);
    var result = { same: lastSuccess === was, viewSame: JSON.stringify(${VIEW}) === view };
    lastSuccess.chosen_action = "wait";
    return result;
  })()`);

  // never: a hidden page, Demo Mode, leg 2, Page B, then after the end of tracking
  out.never.hidden = {
    asked: await asked("Object.defineProperty(document, 'hidden', { configurable: true, get: function () { return true; } })"),
    timerCleared: await h.eval("(function () { syncWalkTimers(); return walkRescoreTimer == null; })()"),
  };
  await h.eval("delete document.hidden; syncWalkTimers(); true");
  out.never.visibleAgain = await h.eval("rescoreAllowed() && walkRescoreTimer != null");
  out.never.demo = {
    asked: await asked("document.getElementById('demo-banner').hidden = false"),
    allowed: await h.eval("rescoreAllowed()"),
  };
  await h.eval("document.getElementById('demo-banner').hidden = true; syncWalkTimers(); true");
  out.never.leg2 = {
    asked: await asked("window.__plan = activeRoutePlan; activeRoutePlan = { route_type: 'one_transfer', leg_index: 2, legs: [{}, {}] }"),
    allowed: await h.eval("rescoreAllowed()"),
  };
  await h.eval("activeRoutePlan = window.__plan; syncWalkTimers(); true");
  out.never.leg1 = await h.eval("rescoreAllowed()");
  out.never.pageB = {
    asked: await asked("pushScreen('arrivals')"),
    allowed: await h.eval("rescoreAllowed()"), timerCleared: await h.eval("walkRescoreTimer == null"),
  };
  await h.eval("pushScreen('live'); syncWalkTimers(); true");
  out.never.backOnA = await h.eval("rescoreAllowed() && walkRescoreTimer != null");
  out.never.afterAnswer = {
    asked: await asked("endTracking('unanswered')"),
    allowed: await h.eval("rescoreAllowed()"), timerCleared: await h.eval("walkRescoreTimer == null"),
  };
  return out;
}

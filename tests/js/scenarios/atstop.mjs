import { poll, toLive } from "./common.mjs";

// At the stop in the real page: the ring, the Leave by tile, the AI card, the pace chip and the Leave now banner, with
// the user 12 m from the boarding stop and a good fix; then 60 m away (the normal formula again).
const VIEW = `({
  ring: document.getElementById('catch-ring-text').textContent,
  aria: document.getElementById('catch-ring').getAttribute('aria-label'),
  tile: document.getElementById('tile-leave-by').textContent,
  detail: ((document.getElementById('pace-walk') || {}).textContent || ''),
  detailHidden: (!document.getElementById('pace-walk') || document.getElementById('pace-walk').hidden),
  cautionHidden: document.getElementById('tile-leave-caution').hidden,
  card: document.getElementById('ai-explanation-text').textContent,
  chip: document.getElementById('pace-slot').textContent.trim(),
  chipHidden: document.getElementById('pace-slot').hidden,
  tilesShown: !document.getElementById('leave-tiles').hidden,
  action: lastSuccess.chosen_action,
  atStop: featuredBus(lastSuccess.buses).probability.at_stop,
  packAtStop: lastExplanationPack ? lastExplanationPack.at_stop : null,
  e: explanationMinutes(featuredBus(lastSuccess.buses).arrival_time)
})`;

export default async function (h) {
  const out = {};
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request");
  const moveTo = (metres, accuracy) => h.eval(`(function () {
    userLat = ${h.config.lat} + ${metres} / 111195; userLon = ${h.config.lon}; userAccuracy = ${accuracy}; userLocationTimestamp = Date.now();
  })(); true`);
  await moveTo(60, 8);
  await poll(h);
  out.far = await h.eval(VIEW);
  await moveTo(12, 8);
  await poll(h);
  await h.sleep(300);
  out.atStop = await h.eval(VIEW);
  out.atStopRescore = await h.eval("({ near: lastSuccess.near_stop })");
  // a poor fix (accuracy 31 m) at 12 m: the normal formula, not the rule
  await moveTo(12, 31);
  await poll(h);
  out.poorFix = await h.eval(VIEW);
  // back to a good fix: the rescore (no poll) brings the at-stop text back
  await moveTo(12, 8);
  await h.eval("walkLastRescoreAt = 0; walkRescoreTick(true); true");
  await h.until("featuredBus(lastSuccess.buses).probability.at_stop === true", 8000, "the rescore to say at the stop");
  await h.sleep(300);
  out.rescored = await h.eval(VIEW);
  // and a rescore that says "not at the stop" brings the caption back
  await moveTo(60, 8);
  await h.eval("walkLastRescoreAt = 0; walkRescoreTick(true); true");
  await h.until("featuredBus(lastSuccess.buses).probability.at_stop === false", 8000, "the rescore away");
  await h.sleep(300);
  out.afterRescoreAway = await h.eval(VIEW);
  return out;
}

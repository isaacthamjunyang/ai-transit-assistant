import { toOverview, startJourney, poll, moveTo } from "./common.mjs";

// 08 Walk page: the (sample) phone starts about 665 m from the stop, where the chance to catch the bus is low (about 25%), and walks
// towards it in 15 m steps. Each step is a new position fix; the page's own code scores the bus again (the rescore the page runs every
// few seconds is asked for at once), so the chance, the distance and the movement state are the app's, not edited.
export default async function (h) {
  await toOverview(h);
  await startJourney(h);
  await moveTo(h, 420);
  await poll(h);
  await h.tap("#walk-open");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 6000, "Page W");
  // the phone is really 665 m out: a fix, then the page's own rescore
  await h.eval(`__geo.push({ lat: ${h.config.lat} + 665 / 111195, lon: ${h.config.lon}, acc: 8, speed: 1.3, heading: 180 }); true`);
  await h.sleep(300);
  await h.eval("walkLastRescoreAt = 0; walkRescoreTick(true); true");
  await h.until("!walkRescoreBusy", 5000, "the rescore");
  // the jump from 420 m to 665 m was only setting the scene: the movement state starts from here
  await h.eval("walkSamples = []; walkLastFixT = null; walkTrend = { anchor: null, text: null, calm: 0 }; renderWalkPage(); true");
  await h.mapsReady();
  await h.sleep(500);
  const read = () => h.eval(`(function () {
    var t = function (id) { var e = document.getElementById(id); return e ? e.textContent.split(String.fromCharCode(10)).join(" ").trim() : null; };
    return t("walk-ring-text") + " | " + t("walk-distance-value") + " | " + t("walk-state");
  })()`);
  const out = { sequence: [await read()] };
  out.clip = await h.record("08-walk", async () => {
    await h.sleep(1200);
    for (let metres = 650; metres >= 530; metres -= 15) {
      await h.eval(`__geo.push({ lat: ${h.config.lat} + ${metres} / 111195, lon: ${h.config.lon}, acc: 8, speed: 1.3, heading: 180 }); true`);
      await h.sleep(250);
      await h.eval("walkLastRescoreAt = 0; walkRescoreTick(true); true");
      await h.until("!walkRescoreBusy", 5000, "the rescore");
      await h.sleep(700);
      out.sequence.push(await read());
    }
    await h.sleep(900);
    await h.eval("window.scrollTo({ top: 460, behavior: 'smooth' }); true");
    await h.sleep(1500);
  }, { tail: 0.6 });
  return out;
}

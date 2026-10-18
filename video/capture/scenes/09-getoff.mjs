import { toOverview, startJourney } from "./common.mjs";

// 09 Get off: Yes, I caught it -> On your way; the phone nears the stop to get off at and the get-off banner appears (page open).
export default async function (h) {
  await toOverview(h);
  await h.eval(`window.__notes = []; var Fake = function (title) { window.__notes.push(String(title)); }; Fake.permission = "granted";
    Fake.requestPermission = function () { return Promise.resolve("granted"); }; window.Notification = Fake; true`);
  await startJourney(h);
  await h.tap("#see-arrivals");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals' && !document.getElementById('catch-bar').hidden", 12000, "the catch question");
  await h.sleep(500);
  const out = {};
  out.clip = await h.record("09-getoff", async () => {
    await h.sleep(700);
    await h.tap("#catch-yes");
    await h.until("screenStack[screenStack.length - 1] === 'onway'", 8000, "On your way");
    await h.sleep(2200);
    // the (sample) phone rides towards the last stop of the leg: 1500 m, 900 m, then inside 400 m
    const target = await h.eval(`(function () {
      var step = onWayState.steps.filter(function (s) { return s.type === "transit"; })[0];
      var stops = legLatLngs(step.leg);
      return stops[stops.length - 1];
    })()`);
    for (const metres of [1500, 900, 380]) {
      await h.eval(`(function () { var t = ${JSON.stringify(target)}; __geo.set({ lat: t[0] - ${metres} / 111195, lon: t[1] + 0.00007, acc: 8 }); onWayReadAt = 0; onWayTick(); })(); true`);
      await h.sleep(metres === 380 ? 300 : 900);
    }
    await h.until("!document.getElementById('on-way-alert').hidden", 8000, "the get-off banner");
    out.banner = await h.eval("document.getElementById('on-way-alert-text').textContent.trim()");
    await h.sleep(3000);
  });
  return out;
}

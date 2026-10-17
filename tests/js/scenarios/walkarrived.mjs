import { poll, toLive } from "./common.mjs";

// "Arrived" on Page W: decided by the server's near_stop (the 30 m rule, the poll's own function), asked
// by the rescore and used together with the poll's. How long after the fix does the state line change?
export default async function (h) {
  const out = { steps: {} };
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  const stopLat = h.config.lat, stopLon = h.config.lon;
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  const stateNow = () => h.eval("document.getElementById('walk-state').textContent");
  const moveTo = (metres) => h.eval(`(function () {
    var lat = ${stopLat} + ${metres} / 111195, lon = ${stopLon};
    __geo.set({ lat: lat, lon: lon, acc: 8 });
    window.__moveAt = Date.now();
    walkOnFix({ t: Date.now(), lat: lat, lon: lon, accuracy: 8, heading: null, speed: null });
  })(); true`);
  const waitFor = async (predicate, limitMs) => {
    const start = Date.now();
    while (Date.now() - start < limitMs) {
      const text = await stateNow();
      if (predicate(text)) {
        return { ms: Date.now() - start, text };
      }
      await h.sleep(200);
    }
    return { ms: null, text: await stateNow() };
  };
  const ARRIVED = "Arrived";
  const record = async (name, metres, predicate) => {
    await moveTo(metres);
    const found = await waitFor(predicate, 8000);
    out.steps[name] = Object.assign({ metres }, found, {
      nearStop: await h.eval("walkChanceSource.nearStop"), samples: await h.eval("walkSamples.length"),
      span: await h.eval("walkSamples.length ? walkSamples[walkSamples.length - 1].t - walkSamples[0].t : 0")
    });
  };
  // 31 m: not arrived (the answer comes back false); 29 m: arrived within one rescore interval; 31 m again: not arrived
  await record("at31", 31, (t) => t !== ARRIVED && t !== "Waiting for your location…");
  await h.sleep(5600);
  out.at31After = { state: await stateNow(), nearStop: await h.eval("walkChanceSource.nearStop") };
  await record("to29", 29, (t) => t === ARRIVED);
  await record("back31", 31, (t) => t !== ARRIVED);
  out.back31After = { state: await stateNow(), nearStop: await h.eval("walkChanceSource.nearStop") };
  await record("to12", 12, (t) => t === ARRIVED);
  // Arrived wins over the movement states even with under 10 s of history
  out.priority = await h.eval("({ state: document.getElementById('walk-state').textContent, span: walkSamples.length ? walkSamples[walkSamples.length - 1].t - walkSamples[0].t : 0 })");
  // a fresh opening 12 m from the stop: the immediate rescore says near_stop, and Arrived beats "Checking your movement"
  await h.eval("requestBack(); true");
  await h.until("screenStack[screenStack.length - 1] === 'live'", 5000, "Page A");
  await h.eval(`userLat = ${stopLat} + 12 / 111195; userLon = ${stopLon}; userAccuracy = 8; userLocationTimestamp = Date.now(); __geo.set({ lat: userLat, lon: userLon, acc: 8 }); window.__openAt = Date.now(); true`);
  await h.eval("document.getElementById('walk-open').click(); true");
  const opened = await waitFor((t) => t === ARRIVED, 8000);
  out.freshOpen = Object.assign({}, opened, { span: await h.eval("walkSamples.length ? walkSamples[walkSamples.length - 1].t - walkSamples[0].t : 0"), samples: await h.eval("walkSamples.length") });
  // the request count: a new fix asks at once, and never more than once every 5 s
  out.rescoreRequests = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/rescore') === 0; }).length");
  out.interval = await h.eval("WALK_RESCORE_MS");
  return out;
}

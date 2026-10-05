import { poll, toLive } from "./common.mjs";

// Screenshots of the REAL Page A and Page W in their states (config.shots is the folder, config.dark the theme).
export default async function (h) {
  const out = { files: [] };
  const dir = h.config.shots;
  const theme = h.config.dark ? "dark" : "light";
  const width = h.config.width || 390;
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  await h.send("Emulation.setDeviceMetricsOverride", { width, height: 1500, deviceScaleFactor: 1, mobile: true });
  const shot = async (name) => {
    await h.sleep(350);
    const path = `${dir}/${name}-${theme}-${width}.png`;
    await h.screenshot(path);
    out.files.push(path);
  };
  const stopLat = h.config.lat, stopLon = h.config.lon;
  const fix = (ago, metres, accuracy = 8, speed = 1.3, heading = 180) =>
    h.eval(`walkOnFix({ t: Date.now() - ${ago}, lat: ${stopLat} + ${metres} / 111195, lon: ${stopLon}, accuracy: ${accuracy}, heading: ${heading}, speed: ${speed} }); true`);
  const reset = () => h.eval("walkSamples = []; walkLastFixT = null; userLocationTimestamp = null; walkChanceSource.nearStop = false; true");

  await h.eval("window.scrollTo(0, 0); true");
  await shot("pageA");
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");

  await h.eval("userLat = null; userLon = null; renderWalkPage(); true");
  await shot("pageW-waiting");

  await reset();
  await fix(12000, 300); await fix(6000, 285); await fix(0, 270);
  await h.eval("walkTrend = { anchor: 70, text: 'rising', calm: 0 }; renderWalkPage(); true");
  await shot("pageW-onway");

  await reset();
  await fix(12000, 220, 8, 0, null); await fix(6000, 220, 8, 0, null); await fix(0, 219, 8, 0, null);
  await h.eval("walkTrend = { anchor: 70, text: 'falling', calm: 0 }; renderWalkPage(); true");
  await shot("pageW-notmoving");

  await reset();
  await fix(0, 12);
  await h.eval("walkChanceSource.nearStop = true; walkTrend = { anchor: 70, text: 'steady', calm: 2 }; renderWalkPage(); true");
  await shot("pageW-arrived");

  await reset();
  await fix(12000, 330, 150, 0, null); await fix(0, 330, 150, 0, null);
  await poll(h);
  await h.eval("walkFitState = { done: false, distance: null }; renderWalkPage(); true");
  await shot("pageW-poor-accuracy");

  await reset();
  await fix(12000, 300); await fix(0, 270);
  await h.eval("paceEstimator.snapshot = function () { return { gpsSpeed: 1.3, gpsAccuracy: 8, cadence: 1.9, stepLength: 0.72, stepCount: 4 }; }; renderWalkPage(); true");
  await shot("pageW-sensors-closed");
  await h.eval("document.getElementById('walk-sensors-toggle').click(); document.getElementById('walk-sensors').scrollIntoView(); true");
  await shot("pageW-sensors-open");
  return out;
}

import { poll, toLive } from "./common.mjs";

// Page W at 20 m, 59 m and 300 m from the stop (config.shots is the folder, config.dark the theme), 390 px wide.
export default async function (h) {
  const out = { files: [] };
  const theme = h.config.dark ? "dark" : "light";
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  for (const metres of [12, 20, 59, 300]) {
    await h.eval(`userLat = ${h.config.lat} + ${metres} / 111195; userLon = ${h.config.lon}; userAccuracy = 20; userLocationTimestamp = Date.now(); true`);
    await h.eval("document.getElementById('walk-open').click(); true");
    await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
    await h.sleep(1800);
    const path = `${h.config.shots}/pageW-fit-${metres}m-${theme}-390.png`;
    await h.screenshot(path);
    out.files.push(path);
    await h.eval("requestBack(); true");
    await h.until("screenStack[screenStack.length - 1] === 'live'", 5000, "Page A");
    await h.sleep(300);
  }
  return out;
}

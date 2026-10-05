import { poll, toLive } from "./common.mjs";

// The Leave by tile and the AI card in their states: leave by, leave now, each with and without an uncertain location.
// With config.shots (a folder) a screenshot of each state is written there. Without it only the text is returned.
const READ = `({
  tile: document.getElementById('tile-leave-by').textContent,
  detail: document.getElementById('tile-leave-detail').textContent,
  detailHidden: document.getElementById('tile-leave-detail').hidden,
  caution: document.getElementById('tile-leave-caution-text').textContent,
  cautionHidden: document.getElementById('tile-leave-caution').hidden,
  card: document.getElementById('ai-explanation-text').textContent
})`;

export default async function (h) {
  const out = { states: {} };
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  await h.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 1400, deviceScaleFactor: 1, mobile: true });
  const states = {
    by: "true",
    byUncertain: "lastExplanationPack.uncertain = true; true",
    now: "lastExplanationPack.uncertain = false; lastSuccess.leave_by = new Date(Date.now() + 30000).toISOString(); lastExplanationPack.leave_by = lastSuccess.leave_by; true",
    nowUncertain: "lastExplanationPack.uncertain = true; true",
    nowRemembered: "lastExplanationPack.uncertain = false; lastExplanationPack.walk_speed_source = 'remembered'; lastExplanationPack.walk_speed_used = 1.1; true",
    nowMeasured: "lastExplanationPack.walk_speed_source = 'gps'; lastExplanationPack.walk_speed_used = 1.31; true",
    unlikely: "lastExplanationPack.band = 'low'; true"
  };
  for (const [name, code] of Object.entries(states)) {
    await h.eval(code + "; refreshDisplay(monitorGeneration); true");
    out.states[name] = await h.eval(READ);
    if (h.config.shots) {
      await h.eval("document.getElementById('arrival-card').scrollIntoView(); true");
      await h.sleep(250);
      await h.screenshot(h.config.shots + "/pageA-" + name + "-" + (h.config.dark ? "dark" : "light") + ".png");
    }
  }
  return out;
}

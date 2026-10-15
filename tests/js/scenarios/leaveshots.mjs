import { poll, toLive } from "./common.mjs";

// The Leave by tile and the AI card in their states: leave by, leave now, each with and without an uncertain location.
// With config.shots (a folder) a screenshot of each state is written there. Without it only the text is returned.
const READ = `({
  tile: document.getElementById('tile-leave-by').textContent,
  detail: document.getElementById('pace-walk').textContent,
  detailHidden: document.getElementById('pace-walk').hidden,
  caution: document.getElementById('tile-leave-caution-text').textContent,
  cautionHidden: document.getElementById('tile-leave-caution').hidden,
  card: document.getElementById('ai-explanation-text').textContent,
  expectedClock: leaveClockText(lastSuccess.leave_by, Date.now())
})`;

export default async function (h) {
  const out = { states: {} };
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  await h.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 1400, deviceScaleFactor: 1, mobile: true });
  const states = {
    by: "true",
    // a leave-by on the next Singapore day, at 02:00, whatever time it is now: the tile and the card say "(tomorrow)"
    byTomorrow: "lastSuccess.leave_by = new Date(Date.parse(singaporeParts(new Date()).key + 'T02:00:00+08:00') + 86400000).toISOString(); lastExplanationPack.leave_by = lastSuccess.leave_by; lastExplanationPack.uncertain = false; lastExplanationPack.walk_speed_source = 'default'; lastExplanationPack.walk_speed_used = 1.25; true",
    byUncertain: "lastSuccess.leave_by = new Date(Date.now() + 300000).toISOString(); lastExplanationPack.leave_by = lastSuccess.leave_by; lastExplanationPack.uncertain = true; true",
    now: "lastExplanationPack.uncertain = false; lastSuccess.leave_by = new Date(Date.now() + 30000).toISOString(); lastExplanationPack.leave_by = lastSuccess.leave_by; true",
    nowUncertain: "lastExplanationPack.uncertain = true; true",
    nowRemembered: "lastExplanationPack.uncertain = false; lastExplanationPack.walk_speed_source = 'remembered'; lastExplanationPack.walk_speed_used = 1.1; true",
    nowMeasured: "lastExplanationPack.walk_speed_source = 'gps'; lastExplanationPack.walk_speed_used = 1.31; true",
    unlikely: "lastExplanationPack.band = 'low'; true"
  };
  for (const [name, code] of Object.entries(states)) {
    // one synchronous page task: change the state, redraw, read. A poll answer or the one-second tick cannot slip in between.
    out.states[name] = await h.eval("(function () { " + code + "; refreshDisplay(monitorGeneration); return " + READ + "; })()");
    if (h.config.shots) {
      await h.eval("document.getElementById('arrival-card').scrollIntoView(); true");
      await h.sleep(250);
      await h.screenshot(h.config.shots + "/pageA-" + name + "-" + (h.config.dark ? "dark" : "light") + ".png");
    }
  }
  return out;
}

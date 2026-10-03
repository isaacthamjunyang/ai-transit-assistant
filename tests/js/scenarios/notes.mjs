import { openHome, planOverview, tapStart } from "./common.mjs";

const NOTES = `({overview: document.getElementById("overview-motion-note").textContent,
  newJourney: document.getElementById("new-journey-motion-note").textContent})`;

export default async function (h) {
  const out = {};
  await openHome(h, { permission: h.config.permission });
  await planOverview(h);
  out.onOverview = await h.eval(NOTES);
  if (h.config.shots) {
    await h.eval("document.getElementById('overview-motion-note').scrollIntoView(); true");
    await h.sleep(250);
    await h.screenshot(h.config.shots + "/overview-note-" + h.config.permission + "-" + (h.config.dark ? "dark" : "light") + ".png");
  }
  if (h.config.permission === "denied") {
    await tapStart(h);
    await h.sleep(300);
    await h.eval("pushScreen('newjourney'); true");
    out.afterDenied = await h.eval(NOTES);
    if (h.config.shots) {
      await h.eval("document.getElementById('new-journey-motion-note').scrollIntoView(); true");
      await h.sleep(250);
      await h.screenshot(h.config.shots + "/overview-note-after-denied-" + (h.config.dark ? "dark" : "light") + ".png");
    }
  }
  if (h.config.demo) {
    await h.eval("showDemoChrome(true); pushScreen('journey'); true");
    out.inDemo = await h.eval(NOTES);
  }
  return out;
}

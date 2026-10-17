import { openHome, planOverview, tapStart } from "./common.mjs";

// The overview and new-journey motion notes were removed: neither element exists and no text on the page starts with the
// old sentence ("How it works" holds the one privacy line, in a card that is hidden here).
const NOTES = `({overview: !!document.getElementById("overview-motion-note"),
  newJourney: !!document.getElementById("new-journey-motion-note"),
  text: Array.prototype.some.call(document.querySelectorAll("body *"), function (el) {
    return el.getClientRects().length > 0 && el.children.length === 0 && /^Motion data stays on your phone\. Only/.test(el.textContent.trim());
  })})`;

export default async function (h) {
  const out = {};
  await openHome(h, { permission: h.config.permission });
  await planOverview(h);
  out.onOverview = await h.eval(NOTES);
  if (h.config.permission === "denied") {
    await tapStart(h);
    await h.sleep(300);
    await h.eval("pushScreen('newjourney'); true");
    out.afterDenied = await h.eval(NOTES);
  }
  if (h.config.demo) {
    await h.eval("showDemoChrome(true); pushScreen('journey'); true");
    out.inDemo = await h.eval(NOTES);
  }
  return out;
}

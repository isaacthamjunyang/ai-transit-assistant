import { toOverview, startJourney, poll, moveTo } from "./common.mjs";

// 07 Page A (bus), on a frozen clock: the server's and the page's clock stand at 9:00:00 PM and the sample bus is 8.0 minutes away,
// so the bus is due at 9:08 PM. The app's own rules then give the Leave by time from the phone's distance to the stop
// (leave by = bus time - walk - 135 s). The scene starts at 83% with "Leave by 9:01 PM" and moves the phone away from the stop in steps;
// each step is a new position fix and a poll, and the page draws what the app decides: the ring, the alerts, the pace message and the
// Leave by tile (which becomes "Leave now" when the app's rule says so).
const STEPS = [
  { metres: 352, label: "83% with a Leave by time" },
  { metres: 359, label: "81%" },
  { metres: 411, label: "60%" },
  { metres: 437, label: "47%" },
  { metres: 492, label: "23%" },
  { metres: 579, label: "5%" },
];

export default async function (h) {
  await toOverview(h);
  await h.freezeClock(); // the page's clock joins the server's: 9:00:00 PM
  await startJourney(h);
  const read = () => h.eval(`(function () {
    var t = function (id) { var e = document.getElementById(id); return e && !e.hidden && e.getClientRects().length ? e.textContent.split(String.fromCharCode(10)).join(" ").replace(/ +/g, " ").trim() : null; };
    var alerts = Array.prototype.filter.call(document.querySelectorAll(".live-only .alert, #unlikely-bar-alert"), function (e) { return !e.hidden && e.getClientRects().length > 0; })
      .map(function (e) { return e.textContent.split(String.fromCharCode(10)).join(" ").replace(/ +/g, " ").trim(); });
    return { ring: t("catch-ring-text"), tile: t("tile-leave"), pace: t("pace-slot"), bus: t("catch-arrives"), alerts: alerts };
  })()`);
  const out = { sequence: [] };
  await moveTo(h, STEPS[0].metres);
  await poll(h);
  await h.sleep(400);
  out.clip = await h.record("07-pagea", async () => {
    for (const [index, step] of STEPS.entries()) {
      if (index > 0) {
        await moveTo(h, step.metres);
        await poll(h);
      }
      await h.sleep(1500); // hold the state
      out.sequence.push({ metres: step.metres, ...(await read()) });
    }
    await h.sleep(600);
  });
  return out;
}

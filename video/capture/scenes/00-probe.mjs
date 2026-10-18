import { toOverview, startJourney, poll, moveTo } from "./common.mjs";

// Not a scene: a probe (run: run_capture.py 00) for scene 07. On the frozen clock (21:00:00, bus 8.0 min away) it moves the phone to a
// list of distances from the stop and prints what Page A shows: ring, Leave by tile, pace chip, the card's bus time and the alerts.
export default async function (h) {
  const out = {};
  await toOverview(h);
  await h.freezeClock();
  await startJourney(h);
  const distances = (h.config.distances || [330, 345, 352, 359, 380, 411, 437, 470, 492, 540, 579, 620]);
  for (const m of distances) {
    await moveTo(h, m);
    await poll(h);
    await h.sleep(350);
    out[m] = await h.eval(`(function () {
      var t = function (id) { var e = document.getElementById(id); return e && !e.hidden && e.getClientRects().length ? e.textContent.split(String.fromCharCode(10)).join(" ").replace(/ +/g, " ").trim() : null; };
      return [t("catch-ring-text"), "tile=" + t("tile-leave"), "pace=" + t("pace-slot"), "bus=" + t("catch-arrives"), "banner=" + t("unlikely-bar-alert"),
        "alerts=" + Array.prototype.filter.call(document.querySelectorAll("#live .alert, .live-only .alert"), function (e) { return !e.hidden && e.getClientRects().length > 0; })
          .map(function (e) { return e.textContent.split(String.fromCharCode(10)).join(" ").replace(/ +/g, " ").trim(); }).join(" / ")].join(" | ");
    })()`);
  }
  return out;
}

import { toOverview, startJourney } from "./common.mjs";

// 06 MRT: pick MRT only, start, the train page (Page A for a train) and Page B with scheduled times.
export default async function (h) {
  await toOverview(h);
  await h.choose("#priority-select", "mrt_only");
  await h.until(`planPriority === "mrt_only" && overviewState === "ready"`, 20000, "the MRT plan");
  await h.sleep(500);
  await h.tap("#start-journey");
  await h.until("monitoringActive === true", 10000, "polling to start");
  await h.until("lastSuccess && lastSuccess.leg_kind === 'rail' && !entryPending", 20000, "the first train poll");
  await h.sleep(500);
  const out = {};
  out.clip = await h.record("06-mrt", async () => {
    await h.sleep(1500);
    await h.tap("#see-arrivals");
    await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 8000, "the train page");
    await h.mapsReady();
    await h.sleep(1800);
    await h.eval("window.scrollTo({ top: 420, behavior: 'smooth' }); true");
    await h.sleep(1400);
  });
  out.text = await h.eval("document.body.innerText.split(String.fromCharCode(10)).join(' | ').slice(0, 600)");
  return out;
}

import { toOverview, startJourney } from "./common.mjs";

// 05 Arrivals: Page A, then Page B with the next three buses and their crowding labels (scripted LTA Load values).
export default async function (h) {
  await toOverview(h);
  await startJourney(h);
  const out = {};
  out.clip = await h.record("05-arrivals", async () => {
    await h.sleep(1300);
    await h.tap("#see-arrivals");
    await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 8000, "Page B");
    await h.mapsReady();
    await h.sleep(1800);
    await h.eval("window.scrollTo({ top: 420, behavior: 'smooth' }); true");
    await h.sleep(1400);
    out.tiles = await h.eval("Array.prototype.map.call(document.querySelectorAll('#next-buses .bus-tile-card'), function (t) { return t.textContent.split(String.fromCharCode(10)).join(' '); })");
    await h.sleep(600);
  });
  return out;
}

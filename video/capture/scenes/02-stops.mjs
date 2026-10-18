import { openHome, screen } from "./common.mjs";

// 02 Plan around a stop: the stops page (green Skip), choose a station, Confirm, and the journey that ends there with the final walk.
export default async function (h) {
  await openHome(h);
  await h.tapText("#quick-picks button", "School");
  await h.tap("#arrive-by-field");
  await h.tap("#arrive-60");
  await h.sleep(300);
  const out = {};
  out.clip = await h.record("02-stops", async () => {
    await h.tap("#find-route");
    await h.until(`${screen} === "stops" && document.querySelectorAll(".dest-stop-row").length >= 2`, 15000, "the stops page");
    await h.mapsReady();
    await h.sleep(1500); // the green Skip button, the real map and the list
    await h.tapText(".dest-stop-row", "MRT station");
    await h.sleep(500);
    await h.tap("#select-destination-stop");
    await h.until(`${screen} === "confirm"`, 8000, "confirm");
    await h.sleep(1000);
    await h.tap("#confirm-destination-stop");
    await h.until(`${screen} === "journey" && !document.getElementById("start-journey").disabled`, 25000, "the overview");
    await h.sleep(900);
    await h.eval("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }); true");
    await h.sleep(1600);
  });
  out.rowsAfter = await h.eval(`Array.prototype.map.call(document.querySelectorAll("#overview-timeline .journey-step"), function (r) { return r.textContent.replace(/\\s+/g, " ").trim(); })`);
  return out;
}

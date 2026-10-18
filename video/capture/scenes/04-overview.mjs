import { openHome, screen } from "./common.mjs";

// 04 Journey overview: the priority select (Fastest, Bus only, MRT only) and the summary card with bus and MRT legs.
export default async function (h) {
  await openHome(h);
  await h.tapText("#quick-picks button", "School");
  await h.tap("#arrive-by-field");
  await h.tap("#arrive-60");
  await h.tap("#find-route");
  await h.until(`${screen} === "stops" && document.querySelectorAll(".dest-stop-row").length >= 2`, 15000, "the stops page");
  await h.sleep(500);
  await h.tap("#skip-stop");
  await h.until(`${screen} === "confirm"`, 8000, "confirm");
  await h.sleep(500);
  await h.tap("#confirm-destination-stop");
  await h.until(`${screen} === "journey" && !document.getElementById("start-journey").disabled`, 25000, "the overview");
  await h.sleep(800);
  const out = {};
  const ready = (p) => h.until(`planPriority === "${p}" && overviewState === "ready" && !document.getElementById("overview-timeline").hidden`, 20000, "the plan for " + p);
  const summary = () => h.eval(`document.getElementById("overview-summary").getAttribute("aria-label")`);
  out.clip = await h.record("04-overview", async () => {
    await h.sleep(1700);
    out.fastest = await summary();
    await h.choose("#priority-select", "bus_only");
    await ready("bus_only");
    await h.sleep(1700);
    out.bus = await summary();
    await h.choose("#priority-select", "mrt_only");
    await ready("mrt_only");
    await h.sleep(1700);
    out.mrt = await summary();
    await h.choose("#priority-select", "fastest");
    await ready("fastest");
    await h.sleep(1500);
  });
  return out;
}

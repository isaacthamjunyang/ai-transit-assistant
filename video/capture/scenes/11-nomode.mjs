import { openHome, screen } from "./common.mjs";

// 11 Late night: OneMap finds no transit (a walk only), so the overview shows the no-transit ride-app card.
export default async function (h) {
  await openHome(h);
  await h.tapText("#quick-picks button", "School");
  await h.tap("#arrive-by-field", { after: 250 });
  await h.tap("#arrive-60", { after: 250 });
  await h.sleep(200);
  const out = {};
  out.clip = await h.record("11-nomode", async () => {
    await h.tap("#find-route");
    await h.until(`${screen} === "stops"`, 15000, "the stops page");
    await h.mapsReady();
    await h.sleep(700);
    await h.tap("#skip-stop");
    await h.until(`${screen} === "confirm"`, 8000, "confirm");
    await h.sleep(500);
    await h.tap("#confirm-destination-stop");
    await h.until(`${screen} === "journey" && !document.getElementById("ride-apps").hidden`, 25000, "the ride-app card");
    await h.sleep(1800);
    await h.eval("document.getElementById('ride-apps').scrollIntoView({ behavior: 'smooth', block: 'center' }); true");
    await h.sleep(2000);
  });
  out.text = await h.eval("document.getElementById('journey-overview').innerText.split(String.fromCharCode(10)).join(' | ').slice(0, 400)");
  return out;
}

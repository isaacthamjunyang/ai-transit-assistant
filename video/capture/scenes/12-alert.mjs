import { toOverview } from "./common.mjs";

// 12 Train service alert: the banner for a disruption on the line the journey uses (LTA's alert answer is scripted).
export default async function (h) {
  await toOverview(h);
  await h.sleep(300);
  const out = {};
  out.clip = await h.record("12-alert", async () => {
    await h.sleep(900);
    await h.eval("var b = document.querySelector('#overview-train-alerts'); if (b) { b.scrollIntoView({ behavior: 'smooth', block: 'center' }); } true");
    await h.sleep(2600);
    out.banner = await h.eval("(function () { var b = document.querySelector('#overview-train-alerts'); return b ? b.innerText.split(String.fromCharCode(10)).join(' | ').slice(0, 300) : null; })()");
    await h.eval("window.scrollTo({ top: 0, behavior: 'smooth' }); true");
    await h.sleep(900);
    await h.tap("#start-journey");
    await h.until("monitoringActive === true && lastSuccess && !entryPending", 20000, "the first poll");
    await h.sleep(2200);
  });
  return out;
}

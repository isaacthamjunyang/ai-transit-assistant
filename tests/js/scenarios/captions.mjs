import { poll, toLive } from "./common.mjs";

const CARD = `({
  caption: document.getElementById("catch-caption").textContent,
  line: document.getElementById("catch-pace-line").textContent,
  live: document.getElementById("catch-pace-line").getAttribute("aria-live"),
  visible: !!document.getElementById("catch-pace-line").offsetParent
})`;

export default async function (h) {
  const out = { sources: {} };
  await toLive(h, { permission: "granted", storage: h.config.storage });
  await poll(h);
  out.real = { server: await h.eval("({used: lastSuccess.walk_speed_used, source: lastSuccess.walk_speed_source})"), card: await h.eval(CARD) };
  for (const [source, used] of [["gps", 1.31], ["cadence", 1.2], ["remembered", 0.9], ["default", 1.25]]) {
    await h.eval(`lastSuccess.walk_speed_used = ${used}; lastSuccess.walk_speed_source = "${source}";
      renderCatchCard(featuredBus(lastSuccess.buses)); true`);
    out.sources[source] = await h.eval(CARD);
    if (h.config.shots) {
      await h.eval("document.getElementById('arrival-card').scrollIntoView(); true");
      await h.sleep(250);
      await h.screenshot(h.config.shots + "/card-" + source + "-" + (h.config.dark ? "dark" : "light") + ".png");
    }
  }
  await h.eval("lastSuccess.walk_speed_source = 'bogus'; lastSuccess.walk_speed_used = 9; renderCatchCard(featuredBus(lastSuccess.buses)); true");
  out.bogus = await h.eval(CARD);
  await h.eval("lastSuccess.walk_speed_used = 1.25; lastSuccess.walk_speed_source = 'gps'; true");
  await h.eval("activeRoutePlan.route_type = 'one_transfer'; activeRoutePlan.leg_index = 2; renderCatchCard(featuredBus(lastSuccess.buses)); true");
  out.leg2 = await h.eval(CARD);
  return out;
}

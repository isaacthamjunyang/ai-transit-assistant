import { toLive, poll } from "./common.mjs";

// Real poll payloads (normal, uncertain location, low band, a reroute that fires, a Missed arrival, no tracked bus):
// the sentences the page draws from the tile's minutes equal the pack's own text at the same instant.
const MODS = {
  normal: "true",
  uncertain: "userAccuracy = 150; true",
  low: "userLat = userLat + 0.03; true",
  reroute: "true",
  missed: "true",
  none: "true"
};

export default async function (h) {
  const which = h.config.which;
  const out = { which };
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await h.eval(MODS[which]);
  await poll(h);
  out.card = await h.eval("document.getElementById('ai-explanation-text').textContent");
  out.pack = await h.eval("lastExplanationPack ? JSON.parse(JSON.stringify(lastExplanationPack)) : null");
  out.heroEta = await h.eval("(function () { var hero = featuredBus(lastSuccess.buses); return hero ? hero.arrival_time : null; })()");
  out.tileSub = await h.eval("document.getElementById('catch-sub-eta').textContent");
  if (out.pack) {
    out.redrawn = await h.eval(`(function () {
      var pack = lastExplanationPack;
      var parts = pack.snapshot.split("|");
      var m = /^(.*T\\d\\d:\\d\\d:\\d\\d)(?:\\.(\\d+))?(.*)$/.exec(parts.slice(3).join("|"));
      var pollMs = Date.parse(m[1] + m[3]) + (m[2] ? Number("0." + m[2]) * 1000 : 0);
      var real = Date.now;
      Date.now = function () { return pollMs; };
      try {
        var e = explanationMinutes(featuredBus(lastSuccess.buses).arrival_time);
        var lead = explanationLead(pack, e);
        renderExplanationNow();
        return { e: e, lead: lead, text: document.getElementById('ai-explanation-text').textContent };
      } finally {
        Date.now = real;
      }
    })()`);
  }
  return out;
}

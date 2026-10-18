import { toOverview, startJourney } from "./common.mjs";

// 10 Page C: "No, I missed it" -> two recommended cards (fastest, highest chance) and the other options. The server's answer is
// scripted in the page (a fetch stub for /api/reroute-options); the page draws it with its own code.
function row(id, service, wait, destMinutes, point, tags, extra) {
  const at = new Date(Date.now() + wait * 60000).toISOString();
  const dest = new Date(Date.now() + destMinutes * 60000).toISOString();
  return Object.assign({ id, service_no: service, stop_code: "28389", stop_name: "Opp Blk 515", point, band: point >= 50 ? "ok" : "low",
    range_low: point - 5, range_high: point + 5, arrival_time: at, estimated_arrival: dest, destination_arrival: dest,
    distance_m: 0, walk_m: 0, at_current_stop: true, next_of_same_service: false, monitored: true, group: 2,
    tags: tags, unlikely: false, after_target: false, recommended: tags.length > 0, leave_by: at }, extra || {});
}

export default async function (h) {
  await toOverview(h);
  await startJourney(h);
  await h.tap("#see-arrivals");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals' && !document.getElementById('catch-bar').hidden", 12000, "the catch question");
  const cards = [row("a", "187", 3, 22, 71, ["fastest"]), row("b", "98", 9, 31, 93, ["highest_chance"])];
  const rows = [row("p", "49", 11, 40, 52, []), row("l", "335", 22, 70, 90, [], { after_target: true })];
  const answer = { status: "ok", options: { mode: "winner", entry: "recommended", recommended: cards[0], cards, rows } };
  await h.eval(`(function () {
    var real = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : input.url;
      if (url.indexOf("/api/reroute-options") === 0) {
        return new Promise(function (resolve) { setTimeout(function () {
          resolve(new Response(JSON.stringify(${JSON.stringify(answer)}), { status: 200, headers: { "Content-Type": "application/json" } }));
        }, 700); });
      }
      return real.call(window, input, init);
    };
  })(); true`);
  const out = {};
  out.clip = await h.record("10-pagec", async () => {
    await h.sleep(900);
    await h.tap("#catch-no");
    await h.until("pageC && !pageC.loading && pageC.options", 10000, "Page C options");
    await h.mapsReady(4000);
    await h.sleep(2600);
    await h.eval("window.scrollTo({ top: 520, behavior: 'smooth' }); true");
    await h.sleep(1800);
  });
  out.text = await h.eval("document.getElementById('page-c').innerText.split(String.fromCharCode(10)).join(' | ').slice(0, 500)");
  return out;
}

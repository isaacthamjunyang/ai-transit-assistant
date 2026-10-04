import { toLive, poll } from "./common.mjs";

// A model reply counts only when its snapshot key is the one of the poll on screen. A late reply for an older
// poll is dropped and cannot overwrite the newer text.
const CALLS = "window.__explainCalls";

function reply(snapshot, advice) {
  return `new Response(JSON.stringify({status: "ok", source: "model", snapshot: ${JSON.stringify(snapshot)}, action: lastExplanationPack.action,
    reason_code: lastExplanationPack.reason_code, advice: ${JSON.stringify(advice)},
    clause: "It is advisable to " + ${JSON.stringify(advice)} + ".", queued: false}), {status: 200, headers: {"Content-Type": "application/json"}})`;
}

export default async function (h) {
  const out = {};
  await toLive(h, { permission: "granted" });
  await poll(h);
  out.firstPack = await h.eval("lastExplanationPack ? {snapshot: lastExplanationPack.snapshot, keys: Object.keys(lastExplanationPack.fact_sheet).sort(), clause: lastExplanationPack.clause} : null");
  // let the page's own first explanation request (made on the first poll) finish before taking over fetch
  await h.until("!explanationInFlight", 15000, "the first real explanation request to finish");
  await h.eval(`${CALLS} = [];
    var realFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : input.url;
      if (url === "/api/explain") {
        return new Promise(function (resolve) { ${CALLS}.push({body: JSON.parse(init.body), resolve: resolve}); });
      }
      return realFetch.apply(window, arguments);
    };
    explainedAction = null; explainedAdvice = null; explanationInFlight = false; pendingExplanation = null; true`);
  out.s1 = await h.eval("lastExplanationPack.snapshot");
  await h.eval("beginExplanation(lastExplanationPack); true");
  out.firstRequest = await h.eval(`${CALLS}[0].body`);
  // a newer poll arrives while the first reply is still out
  await h.sleep(1100);
  await poll(h);
  out.s2 = await h.eval("lastExplanationPack.snapshot");
  out.pendingAfterPoll = await h.eval("pendingExplanation !== null");
  out.textBefore = await h.eval("document.getElementById('ai-explanation-text').textContent");
  // the late reply for the OLD poll: dropped
  await h.eval(`${CALLS}[0].resolve(${reply(out.s1, "wait for your alert before leaving")}); true`);
  await h.until(`${CALLS}.length === 2`, 5000, "the pending request for the newer poll");
  out.afterLate = await h.eval(`({text: document.getElementById('ai-explanation-text').textContent, advice: explainedAdvice,
    clause: explanationClause, secondBody: ${CALLS}[1].body})`);
  // the reply for the poll on screen: used
  await h.eval(`${CALLS}[1].resolve(${reply(out.s2, "wait for your leave-by alert and keep walking steadily")}); true`);
  await h.until("explainedAdvice !== null", 5000, "the matching reply");
  out.afterMatch = await h.eval(`({text: document.getElementById('ai-explanation-text').textContent, advice: explainedAdvice})`);
  // the text follows the tile: set the tile's bus to 7 minutes and redraw
  out.tile = await h.eval(`(function () {
    var hero = featuredBus(lastSuccess.buses);
    hero.arrival_time = new Date(Date.now() + 7 * 60000 + 100).toISOString();
    renderCatchCard(hero);
    renderExplanationNow();
    return {sub: document.getElementById('catch-sub-eta').textContent, text: document.getElementById('ai-explanation-text').textContent};
  })()`);
  // a poll with no explanation clears the card (nothing from an older poll stays)
  out.cleared = await h.eval(`(function () {
    syncExplanation({status: "ok", buses: []});
    return document.getElementById('ai-explanation-text').textContent;
  })()`);
  return out;
}

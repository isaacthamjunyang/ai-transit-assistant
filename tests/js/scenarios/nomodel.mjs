import { toLive, poll } from "./common.mjs";

// With the model path off the pack says model_enabled false and the page makes no call to /api/explain or
// /api/explain-option, however the page functions are driven.
export default async function (h) {
  const out = {};
  await toLive(h, { permission: "granted" });
  await h.eval(`window.__calls = [];
    var realFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : input.url;
      if (url.indexOf("/api/explain") === 0) { window.__calls.push(url); }
      return realFetch.apply(window, arguments);
    };
    true`);
  await poll(h);
  await h.sleep(300);
  out.modelEnabled = await h.eval("lastExplanationPack.model_enabled");
  out.pageFlag = await h.eval("AI_EXPLANATION_ENABLED");
  await h.eval("beginExplanation(lastExplanationPack); true");
  await h.eval(`(function () {
    try { requestOptionExplanation({ service_no: "11", stop_code: "01011", reason_code: "HIGHEST_CHANCE", explanation: { reason_code: "HIGHEST_CHANCE", action: "switch_route", text: "x" } }); } catch (e) { }
    return true;
  })()`);
  await poll(h);
  await h.sleep(300);
  out.calls = await h.eval("window.__calls");
  out.text = await h.eval("document.getElementById('ai-explanation-text').textContent");
  return out;
}

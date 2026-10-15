import { openHome, planOverview } from "./common.mjs";

// The muted traffic line under the summary card: shown when the planned route has a bus leg, hidden on a rail-only
// route and while there is no summary. Reads the note, the summary and the leg rows. config: width, height, dark.

const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function shown(el) { return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  var note = document.getElementById("overview-traffic-note");
  var summary = document.getElementById("overview-summary");
  var legs = pendingItinerary && pendingItinerary.legs ? pendingItinerary.legs : [];
  return {
    note: shown(note) ? text(note) : null, noteHidden: note.hidden, summaryShown: shown(summary),
    summaryTime: text(document.getElementById("summary-time")),
    legKinds: legs.map(function (l) { return l.kind; }),
    noteIsAfterSummary: (function () { var n = summary.nextElementSibling; if (n && n.id === "overview-train-alerts") { n = n.nextElementSibling; } return n === note; })(),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    inlineStyles: note.hasAttribute("style")
  };
})()`;

export default async function (h) {
  const c = h.config;
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  const before = await h.eval(`(function () {
    var note = document.getElementById("overview-traffic-note");
    return { hidden: note.hidden, text: note.textContent };
  })()`);
  await planOverview(h);
  await h.sleep(300);
  return { before: before, ready: await h.eval(READ) };
}

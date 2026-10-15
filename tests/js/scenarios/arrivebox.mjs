import { openHome, planOverview } from "./common.mjs";

// The Arrive by card in the overview with a route, then the same card when the answer is empty, and the guard that
// keeps the on-your-way and new-journey cards from ever being drawn blank.
const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.trim() : null; }
  var box = document.getElementById("overview-arrive-box");
  return {
    shown: shown("overview-arrive-box"), value: shown("overview-arrive-value") ? text("overview-arrive-value") : null,
    edit: !!box.querySelector("#overview-arrive-edit") && shown("overview-arrive-edit"),
    start: document.getElementById("start-journey").disabled, state: overviewState,
    startTop: Math.round(document.getElementById("start-journey").getBoundingClientRect().top + window.scrollY),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  await h.sleep(400);
  out.route = await h.eval(READ);
  // an empty answer hides the card at once, a route shows it again
  await h.eval(`setOverviewState("no-route"); true`);
  out.noRoute = await h.eval(READ);
  await h.eval(`setOverviewState("no-service"); true`);
  out.noService = await h.eval(READ);
  await h.eval(`setOverviewState("loading"); true`);
  out.loading = await h.eval(READ);
  await h.eval(`setOverviewState("ready"); syncOverviewArrive(); true`);
  out.back = await h.eval(READ);
  // no estimate: the card is not drawn, in the overview and on the other two screens
  await h.eval(`renderArriveCard("overview", null); renderArriveCard("on-way", null); renderArriveCard("new-journey", null); true`);
  out.noEstimate = await h.eval(`({
    overview: !document.getElementById("overview-arrive-box").hidden,
    onWay: !document.getElementById("on-way-arrive-box").hidden,
    newJourney: !document.getElementById("new-journey-arrive-box").hidden })`);
  const iso = new Date(Date.UTC(2026, 9, 14, 10, 30)).toISOString();
  await h.eval(`renderArriveCard("on-way", ${JSON.stringify(iso)}); renderArriveCard("new-journey", ${JSON.stringify(iso)}); true`);
  out.withEstimate = await h.eval(`({
    onWay: !document.getElementById("on-way-arrive-box").hidden && document.getElementById("on-way-arrive-value").textContent.trim() !== "",
    newJourney: !document.getElementById("new-journey-arrive-box").hidden && document.getElementById("new-journey-arrive-value").textContent.trim() !== "" })`);
  return out;
}

import { openHome, planOverview } from "./common.mjs";

// The journey overview's gap between the "Your journey" heading and the priority select, in every overview state, plus the gap under
// the select and the card's overflow. States: ready (the planner's route, here the static fallback), loading, no-location, no-route,
// no-service, unavailable. config: width, height, dark.
const READ = `(function () {
  var title = document.getElementById("overview-title").getBoundingClientRect();
  var priority = document.getElementById("overview-priority");
  var select = document.getElementById("priority-select").getBoundingClientRect();
  var wrap = priority.getBoundingClientRect();
  var next = null;
  for (var el = priority.nextElementSibling; el; el = el.nextElementSibling) {
    if (el.getClientRects().length > 0 && !el.hidden) { next = el; break; }
  }
  var card = document.getElementById("overview-card").getBoundingClientRect();
  return { gap: select.top - title.bottom, wrapGap: wrap.top - title.bottom, below: next ? next.getBoundingClientRect().top - wrap.bottom : null, nextId: next ? next.id || next.className : null,
           titleH: title.height, selectH: select.height, cardLeft: card.left, cardRight: card.right, state: overviewState,
           scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, selectRight: select.right };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  await h.sleep(300);
  out.ready = await h.eval(READ);
  out.after = {};
  for (const state of ["loading", "no-location", "no-route", "no-service", "unavailable", "ready"]) {
    await h.eval(`setOverviewState(${JSON.stringify(state)}); true`);
    await h.sleep(100);
    out[state] = await h.eval(READ);
  }
  // the static planner's own empty sentences (the fallback planner) in the same two empty containers
  await h.eval(`document.getElementById("overview-no-route-text").textContent = noRouteText({ planner: "static", route_status: "no_feasible_route" }); setOverviewState("no-route"); true`);
  await h.sleep(100);
  out.fallbackNoRoute = await h.eval(READ);
  await h.eval(`document.getElementById("overview-no-service-text").textContent = noServiceText({ planner: "static", route_status: "no_service" }); setOverviewState("no-service"); true`);
  await h.sleep(100);
  out.fallbackNoService = await h.eval(READ);
  await h.eval(`document.getElementById("ride-apps").hidden = false; true`);
  await h.sleep(100);
  out.rideApps = await h.eval(READ);
  return out;
}

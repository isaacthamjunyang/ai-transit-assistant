import { openHome } from "./common.mjs";

// The overview's empty states by priority: a walk-only answer (no_service) or a 404 (no_feasible_route) from the real
// app, for each of the five priorities; then the page's own word choice for the closed cases and the static planner,
// fed bodies directly (the test app's clock cannot be moved).
// config: width, height, dark, priorities.

const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  return {
    noService: shown("overview-no-service") ? text(document.getElementById("overview-no-service-text")) : null,
    noRoute: shown("overview-no-route") ? text(document.getElementById("overview-no-route-text")) : null,
    ready: shown("overview-timeline"), loading: shown("overview-skeleton"), priority: planPriority,
    select: document.getElementById("priority-select").value,
    buttons: Array.prototype.map.call(document.querySelectorAll(shown("overview-no-service") ? "#overview-no-service button" : "#overview-no-route button"), text),
    arriveBox: shown("overview-arrive-box"),
    arriveBoxHeight: document.getElementById("overview-arrive-box").getBoundingClientRect().height,
    rideApps: shown("ride-apps"), startDisabled: document.getElementById("start-journey").disabled,
    startTop: Math.round(document.getElementById("start-journey").getBoundingClientRect().top + window.scrollY),
    cardGap: Math.round(document.getElementById("start-journey").getBoundingClientRect().top
      - document.getElementById("overview-card").getBoundingClientRect().bottom),
    privacy: !!document.getElementById("overview-motion-note"),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = { byPriority: {}, words: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  // like planOverview, but an empty answer never enables Start journey, so it waits for the skeleton to go instead
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination"};
    pushScreen("journey"); true`);
  await h.sleep(300);
  await h.until("document.getElementById('overview-skeleton').hidden", 20000, "the first plan");
  for (const priority of c.priorities) {
    await h.eval(`(function () {
      var select = document.getElementById("priority-select");
      select.value = ${JSON.stringify(priority)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    await h.sleep(200);
    await h.until(`document.getElementById("overview-skeleton").hidden && planPriority === ${JSON.stringify(priority)}`, 20000, "the plan for " + priority);
    await h.sleep(150);
    out.byPriority[priority] = await h.eval(READ);
  }
  const body = (priority, extra) => JSON.stringify(Object.assign({ planner: "onemap", priority: priority, route_status: "no_service", stopped: false }, extra || {}));
  const words = async (key, expression) => { out.words[key] = await h.eval(expression); };
  for (const priority of ["fastest", "fewest_transfers", "least_walking", "bus_only", "mrt_only"]) {
    await words(`${priority}|service|open`, `noServiceText(${body(priority)})`);
    await words(`${priority}|service|stopped`, `noServiceText(${body(priority, { stopped: true })})`);
    await words(`${priority}|route|open`, `noRouteText(${body(priority, { route_status: "no_feasible_route" })})`);
    await words(`${priority}|route|stopped`, `noRouteText(${body(priority, { route_status: "no_feasible_route", stopped: true })})`);
  }
  await words("static|service", `noServiceText(${body("fastest", { planner: "static" })})`);
  await words("static|service|bus_only", `noServiceText(${body("bus_only", { planner: "static", stopped: true })})`);
  await words("static|route", `noRouteText(${body("fastest", { planner: "static", route_status: "no_feasible_route" })})`);
  return out;
}

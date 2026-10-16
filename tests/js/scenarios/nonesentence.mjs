import { openHome } from "./common.mjs";

// The "No other buses or routes are available right now." sentence and the unlikely banner, in every Page C state.
// The page is fed states directly: no request is made. config: width, height, dark.
const SHOW = (entry, state, options) => `(function () {
  screenStack.push("live");
  document.getElementById("page-c").hidden = false;
  rerouteNotice = ${entry === "missed" ? 'BUS_LEFT_NOTICE.replace("{service}", "174")' : '""'};
  pageC = { entry: ${JSON.stringify(entry)}, loading: ${state === "loading"}, failed: ${state === "failed"}, noBuses: false,
    options: ${JSON.stringify(state === "done" ? options : null)}, missedEpoch: null, fetchedAt: Date.now() };
  syncPageCClasses();
  renderPageC();
  return true;
})()`;

const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  var page = document.getElementById("page-c").textContent.replace(/\\s+/g, " ");
  var needle = "No other buses or routes are available right now.";
  return { warn: text("pc-warn-text"), notice: shown("reroute-notice") ? text("reroute-notice") : null,
    none: text("page-c-none"), ride: shown("pc-ride-apps"), cards: document.querySelectorAll("#reroute-cards > *").length,
    rows: document.querySelectorAll("#reroute-alternatives .alt-row").length,
    occurrences: page.split(needle).length - 1, refresh: shown("reroute-refresh"),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;

function row(id, service, minutes) {
  const at = new Date(Date.now() + minutes * 60000).toISOString();
  return { id, service_no: service, stop_code: "90041", stop_name: "Here", point: 60, band: "mid", range_low: 55,
    range_high: 65, arrival_time: at, estimated_arrival: at, destination_arrival: at, distance_m: 0, walk_m: 0,
    at_current_stop: true, next_of_same_service: false, monitored: true, group: 2, tags: [],
    unlikely: false, after_target: false, recommended: false, leave_by: at };
}

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  const empty = { mode: "none", entry: "x", recommended: null, cards: [], rows: [] };
  const found = { mode: "none", entry: "x", recommended: null, cards: [], rows: [row("a", "36", 9)] };
  for (const entry of ["unlikely", "missed"]) {
    for (const [name, state, options] of [["empty", "done", empty], ["found", "done", found],
      ["loading", "loading", null], ["failed", "failed", null]]) {
      await h.eval(SHOW(entry, state, options));
      out[entry + "_" + name] = await h.eval(READ);
    }
  }
  return out;
}

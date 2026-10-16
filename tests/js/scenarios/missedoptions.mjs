import { openHome } from "./common.mjs";

// Page C after "No, I missed it": with options (the left text, the rows in the order the server sent), with the recommended
// card, with none (the plain no-options text and the ride-app card), and the unlikely entry (no ride-app card, no left text).
// The page is fed option bodies directly: no request is made.
// config: width, height, dark.

const SHOW = (missed, options, point) => `(function () {
  screenStack.push("live");
  document.getElementById("page-c").hidden = false;
  rerouteNotice = ${missed ? 'BUS_LEFT_NOTICE.replace("{service}", "174")' : '""'};
  lastKnownPoint = ${point};
  pageC = { entry: ${JSON.stringify(missed ? "missed" : "unlikely")}, loading: false, failed: false, noBuses: false,
    options: ${JSON.stringify(options)}, missedEpoch: null, fetchedAt: Date.now() };
  syncPageCClasses();
  renderPageC();
  return true;
})()`;

const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  function text(id) { var el = document.getElementById(id); return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#reroute-alternatives .alt-row"), function (row) {
    var badge = row.querySelector(".alt-row__service .line-badge");
    var to = row.querySelector(".alt-row__to");
    var when = row.querySelector(".alt-row__arrives");
    var icon = row.querySelector(".alt-row__icon");
    return { service: badge ? badge.textContent.replace(/^Bus /, "").trim() : null,
      badgeBus: !!(badge && badge.classList.contains("line-badge--bus")),
      to: to ? to.textContent.trim() : null, when: when ? when.textContent.trim() : null,
      ring: icon ? getComputedStyle(icon).boxShadow : null,
      text: row.textContent.replace(/\\s+/g, " ").trim(), hidden: row.hidden };
  });
  var cards = Array.prototype.map.call(document.querySelectorAll("#reroute-cards .option-merged"), function (card) {
    var badge = card.querySelector(".option-heading .line-badge");
    var node = card.querySelector(".option-heading .step-node");
    var when = card.querySelector(".option-heading .catch-card__when");
    var line = card.querySelector(".option-heading .journey-step__line");
    return { badge: badge ? badge.textContent.replace(/^Bus /, "").trim() : null,
      badgeBus: !!(badge && badge.classList.contains("line-badge--bus")),
      line: line ? line.textContent.replace(/\\s+/g, " ").trim() : null, when: when ? when.textContent.trim() : null,
      ring: node ? getComputedStyle(node).boxShadow : null,
      leave: (card.querySelector(".option-card__leave") || {}).textContent || null,
      destination: card.querySelector(".option-card__destination") ? card.querySelector(".option-card__destination").textContent : null,
      tags: Array.prototype.map.call(card.querySelectorAll(".option-chip"), function (el) { return el.textContent.trim(); }),
      sentences: card.querySelectorAll(".option-reason").length,
      button: (card.parentNode.querySelector(".primary") || {}).textContent || null,
      oldBlocks: !!card.parentNode.querySelector(".option-explain, .ai-card, .option-badges, .pill--best"),
      ringEl: !!card.querySelector(".prob-ring"),
      oldTitle: !!card.querySelector(".option-card__title, .option-card__meta, .option-card__live"),
      right: card.getBoundingClientRect().right };
  });
  var ride = document.getElementById("pc-ride-apps");
  return {
    notice: shown("reroute-notice") ? text("reroute-notice") : null,
    none: text("page-c-none"),
    rows: rows,
    cardRows: cards,
    cards: document.querySelectorAll("#reroute-cards > *").length,
    ride: shown("pc-ride-apps"),
    rideLinks: ride ? ride.querySelectorAll("a").length : 0,
    page: document.getElementById("page-c").textContent.replace(/\\s+/g, " "),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

function row(id, service, minutes, point, group) {
  const at = new Date(Date.now() + minutes * 60000).toISOString();
  return { id, service_no: service, stop_code: "90041", stop_name: "Here", point, band: "high", range_low: point - 5,
    range_high: point + 5, arrival_time: at, estimated_arrival: at,
    destination_arrival: new Date(Date.now() + (minutes + 25) * 60000).toISOString(), distance_m: 0, walk_m: 0,
    at_current_stop: true, next_of_same_service: group === 1, monitored: true, group, tags: [],
    unlikely: false, after_target: false, recommended: false, leave_by: at };
}

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  const listed = [row("a", "174", 12, 70, 1), row("b", "174", 26, 60, 1), row("c", "36", 9, 55, 2),
    row("d", "61", 7, 40, 3), row("e", "190", 15, 50, 3)];
  await h.eval(SHOW(true, { mode: "none", entry: "recommended", recommended: null, rows: listed }, 76));
  out.withOptions = await h.eval(READ);
  // the recommended card and the alternatives, with the destination stop's code in its name (it must not show)
  await h.eval(`confirmedDestinationStop = { stop_code: "90021", stop_name: "Pebble Bay (90021)", lat: 1.3, lon: 103.8 }; true`);
  const best = row("r", "36", 6, 72, 2);
  best.recommended = true;
  best.tags = ["highest_chance"];
  best.leave_by = new Date(Date.now() + 120000).toISOString();
  await h.eval(SHOW(true, { mode: "winner", entry: "recommended", recommended: best, cards: [best], rows: listed }, 76));
  out.withCard = await h.eval(READ);
  await h.eval(SHOW(true, { mode: "none", entry: "recommended", recommended: null, rows: [] }, 76));
  out.empty = await h.eval(READ);
  await h.eval(SHOW(false, { mode: "none", entry: "better", recommended: null, rows: [] }, 76));
  out.unlikely = await h.eval(READ);
  return out;
}

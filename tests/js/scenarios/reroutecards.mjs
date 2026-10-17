import { openHome } from "./common.mjs";

// Page C's recommended cards, fed option bodies directly (no request is made): two cards with different tags, one card
// with both tags and the Next best, one option only, no destination estimate, and a next-day destination.
// config: width, height, dark.

const SHOW = (options) => `(function () {
  screenStack.push("live");
  document.getElementById("page-c").hidden = false;
  rerouteNotice = BUS_LEFT_NOTICE.replace("{service}", "174");
  lastKnownPoint = 76;
  pageC = { entry: "missed", loading: false, failed: false, noBuses: false,
    options: ${JSON.stringify(options)}, missedEpoch: null, fetchedAt: Date.now() };
  syncPageCClasses();
  renderPageC();
  return true;
})()`;

const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; }
  function raw(el) { return el ? el.textContent : null; }
  var cards = Array.prototype.map.call(document.querySelectorAll("#reroute-cards .reroute-option"), function (wrap) {
    var card = wrap.querySelector(".option-merged");
    var destination = card.querySelector(".option-card__destination");
    var when = card.querySelector(".option-heading .catch-card__when");
    return {
      tags: Array.prototype.map.call(card.querySelectorAll(".option-chip"), text),
      sentences: card.querySelectorAll(".option-reason").length,
      order: Array.prototype.filter.call(card.querySelectorAll(".option-heading .catch-card__when, .option-card__destination, .option-card__leave"),
        function (el) { return !el.hidden && el.textContent.trim() !== ""; }).map(function (el) {
          return el.classList.contains("option-card__destination") ? "option-card__destination" : el.classList.contains("option-card__leave") ? "option-card__leave" : el.className.split(" ")[0];
        }),
      when: raw(when), destination: destination && !destination.hidden ? raw(destination) : null,
      leave: text(card.querySelector(".option-card__leave")),
      ring: !!card.querySelector(".prob-ring"),
      button: text(wrap.querySelector("button.primary")),
      right: wrap.getBoundingClientRect().right
    };
  });
  var rows = document.querySelectorAll("#reroute-alternatives .alt-row");
  var heading = document.getElementById("reroute-alternatives-heading");
  return {
    cards: cards, rows: rows.length, heading: text(heading),
    rowDestinations: Array.prototype.map.call(rows, function (row) {
      var reach = row.querySelector(".alt-row__reach");
      return reach && reach.textContent ? reach.textContent : null;
    }),
    aiBlocks: document.querySelectorAll("#page-c .ai-card, #page-c .option-explain").length,
    pills: document.querySelectorAll("#page-c .pill--best, #page-c .option-badges").length,
    text: document.getElementById("page-c").textContent.replace(/\\s+/g, " "),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

function row(id, service, wait, destMinutes, point, tags, extra) {
  const at = new Date(Date.now() + wait * 60000).toISOString();
  const dest = destMinutes === null ? null : new Date(Date.now() + destMinutes * 60000).toISOString();
  return Object.assign({ id, service_no: service, stop_code: "90041", stop_name: "Here", point, band: "high",
    range_low: point - 5, range_high: point + 5, arrival_time: at, estimated_arrival: dest, destination_arrival: dest,
    distance_m: 0, walk_m: 0, at_current_stop: true, next_of_same_service: false, monitored: true, group: 2,
    tags: tags, unlikely: false, after_target: false, recommended: tags.length > 0,
    leave_by: at }, extra || {});
}


function body(cards, rows) {
  return { mode: cards.length ? "winner" : "none", entry: "recommended", recommended: cards[0] || null, cards: cards, rows: rows };
}

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`confirmedDestinationStop = { stop_code: "90021", stop_name: "Pebble Bay", lat: 1.3, lon: 103.8 }; true`);
  const alt = row("c", "36", 9, 40, 50, []);
  out.two = await (async () => {
    const fastest = row("a", "16", 3, 20, 60, ["fastest"]);
    const highest = row("b", "7", 8, 30, 80, ["highest_chance"]);
    await h.eval(SHOW(body([fastest, highest], [alt])));
    return h.eval(READ);
  })();
  out.both = await (async () => {
    const first = row("a", "7", 3, 20, 80, ["fastest", "highest_chance"]);
    const second = row("b", "16", 8, 30, 60, ["next_best"]);
    await h.eval(SHOW(body([first, second], [alt])));
    return h.eval(READ);
  })();
  out.single = await (async () => {
    const only = row("a", "7", 3, 20, 80, ["fastest", "highest_chance"]);
    await h.eval(SHOW(body([only], [])));
    return h.eval(READ);
  })();
  out.noEstimate = await (async () => {
    const only = row("a", "7", 3, null, 80, ["highest_chance"]);
    const listed = row("c", "36", 9, null, 50, []);
    await h.eval(SHOW(body([only], [listed])));
    return h.eval(READ);
  })();
  out.tomorrow = await (async () => {
    const late = row("a", "7", 3, 26 * 60, 80, ["fastest", "highest_chance"]);
    await h.eval(SHOW(body([late], [])));
    return h.eval(READ);
  })();
  return out;
}

import { openHome } from "./common.mjs";

// The approved Page C design (pagec-v2) on the real page, fed option bodies directly (no request is made): the current-bus
// card, two recommended cards, alternative rows with their alerts, and the empty answer. config: width, height, dark.
function row(id, service, wait, destMinutes, point, tags, extra) {
  const at = new Date(Date.now() + wait * 60000).toISOString();
  const dest = destMinutes === null ? null : new Date(Date.now() + destMinutes * 60000).toISOString();
  return Object.assign({ id, service_no: service, stop_code: "90041", stop_name: "Here", point, band: point >= 50 ? "ok" : "low",
    range_low: point - 5, range_high: point + 5, arrival_time: at, estimated_arrival: dest, destination_arrival: dest,
    distance_m: 0, walk_m: 0, at_current_stop: true, next_of_same_service: false, monitored: true, group: 2,
    tags: tags, unlikely: false, after_target: false, recommended: tags.length > 0, leave_by: at }, extra || {});
}

const SHOW = (options, entry) => `(function () {
  screenStack.push("live");
  document.getElementById("page-c").hidden = false;
  lastKnownPoint = 76;
  pageC = { entry: ${JSON.stringify(entry)}, loading: false, failed: false, noBuses: false,
    options: ${JSON.stringify(options)}, missedEpoch: null, fetchedAt: Date.now() };
  syncPageCClasses();
  renderPageC();
  return true;
})()`;

const READ = `(function () {
  function box(el) { if (!el) { return null; } var r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }
  function css(el, prop) { return el ? getComputedStyle(el)[prop] : null; }
  var current = document.getElementById("reroute-current");
  var cards = Array.prototype.map.call(document.querySelectorAll("#reroute-cards .option-merged"), function (card) {
    var ring = card.querySelector(".prob-ring"), copy = card.querySelector(".option-card__copy");
    var leave = card.querySelector(".leave-tile--option:not(.leave-tile--reach)"), reach = card.querySelector(".leave-tile--reach");
    var button = card.querySelector("button.primary");
    return {
      card: box(card), ring: box(ring), ringClass: ring ? ring.className : "", copy: box(copy),
      leave: box(leave), leaveBg: css(leave, "backgroundColor"), leaveColor: css(leave, "color"),
      leaveValue: leave ? parseFloat(css(leave.querySelector(".leave-tile__value"), "fontSize")) : 0,
      leaveLabelAbove: leave ? leave.querySelector(".leave-tile__label").getBoundingClientRect().bottom <= leave.querySelector(".leave-tile__value").getBoundingClientRect().top + 2 : null,
      reach: box(reach), reachBg: css(reach, "backgroundColor"), reachColor: css(reach, "color"),
      reachValue: reach ? parseFloat(css(reach.querySelector(".leave-tile__value"), "fontSize")) : 0,
      button: box(button), buttonInside: !!button && card.contains(button),
      tags: Array.prototype.map.call(card.querySelectorAll(".option-chip"), function (t) { return t.textContent.trim(); }),
      tagIsAlert: !!card.querySelector(".option-chip.alert"),
      leaveTop: leave ? leave.getBoundingClientRect().top : null, reachTop: reach ? reach.getBoundingClientRect().top : null,
      buttonTop: button ? button.getBoundingClientRect().top : null, mainTop: card.querySelector(".option-card").getBoundingClientRect().top
    };
  });
  var rows = Array.prototype.map.call(document.querySelectorAll("#reroute-alternatives .alt-row"), function (item) {
    var hit = item.querySelector(".alt-row__hit"), ring = item.querySelector(".prob-ring");
    var alerts = Array.prototype.map.call(item.querySelectorAll(":scope > .alert"), function (a) {
      return { text: a.textContent.trim(), box: box(a), kind: a.className };
    });
    var reach = item.querySelector(".alt-row__reach");
    return { item: box(item), hit: box(hit), ring: box(ring), body: box(item.querySelector(".alt-row__body")), alerts: alerts,
      reach: reach ? reach.textContent : null, reachBold: reach && reach.querySelector("b") ? css(reach.querySelector("b"), "fontWeight") : null,
      chance: item.querySelector(".alt-row__chance") ? item.querySelector(".alt-row__chance").textContent : null };
  });
  var head = document.getElementById("reroute-alternatives-head");
  var warn = document.getElementById("pc-warn");
  var none = document.getElementById("page-c-none"), notice = document.getElementById("reroute-notice");
  var ride = document.getElementById("pc-ride-apps");
  var links = ride ? Array.prototype.map.call(ride.querySelectorAll("a"), box) : [];
  return {
    cards: cards, rows: rows,
    headRow: head && !head.hidden ? { heading: box(head.querySelector(".reroute-alternatives__heading")), updated: box(head.querySelector(".reroute-updated")),
      refresh: box(head.querySelector(".refresh-button")), headingSize: css(head.querySelector(".reroute-alternatives__heading"), "fontSize") } : null,
    current: current && !current.hidden ? {
      arrivesTime: parseFloat(css(current.querySelector(".catch-card__arrives-time"), "fontSize")),
      labelAbove: current.querySelector(".catch-card__arrives-label").getBoundingClientRect().bottom <= current.querySelector(".catch-card__arrives-time").getBoundingClientRect().top + 2,
      captionInCopy: !!current.querySelector(".catch-card__copy .catch-card__caption"),
      warn: warn && !warn.hidden ? { cls: warn.className, text: warn.textContent.trim(), box: box(warn), radius: css(warn, "borderTopLeftRadius") } : null,
      button: box(current.querySelector("#pc-see-arrivals")), card: box(current) } : null,
    none: none && !none.hidden ? { text: none.textContent.trim(), cls: none.className } : null,
    notice: notice && !notice.hidden ? { text: notice.textContent.trim(), cls: notice.className } : null,
    ride: ride && !ride.hidden ? { box: box(ride), links: links, bg: css(ride, "backgroundColor"), border: css(ride, "borderTopWidth") } : null,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

function body(cards, rows) {
  return { mode: cards.length ? "winner" : "none", entry: "recommended", recommended: cards[0] || null, cards: cards, rows: rows };
}

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`confirmedDestinationStop = { stop_code: "90021", stop_name: "Pebble Bay", lat: 1.3, lon: 103.8 }; true`);
  const fastest = row("a", "16", 3, 20, 69, ["fastest"]);
  const highest = row("b", "7", 8, 30, 92, ["highest_chance"]);
  const warnRow = row("w", "158", 3, 25, 5, [], { unlikely: true });
  const plain = row("p", "36", 9, 40, 50, []);
  const late = row("l", "14", 22, 70, 92, [], { after_target: true });
  await h.eval(SHOW(body([fastest, highest], [warnRow, plain, late]), "unlikely"));
  // the current-bus card of the unlikely entry, filled with sample values (the warning shows as the page shows it)
  await h.eval(`(function () {
    document.getElementById("reroute-current").hidden = false;
    document.getElementById("pc-title").textContent = "Chance to catch your Bus 158";
    document.getElementById("pc-arrives").hidden = false;
    document.getElementById("pc-arrives-time").textContent = "12:37 PM";
    document.getElementById("pc-ring-text").textContent = "5%";
    document.getElementById("pc-warn").hidden = false;
    return true;
  })()`);
  await h.sleep(300);
  out.route = await h.eval(READ);
  // the empty answer after a miss: the info alert and the ride-app card
  await h.eval(SHOW(body([], []), "missed"));
  await h.eval(`document.getElementById("reroute-current").hidden = true; true`);
  await h.sleep(300);
  out.empty = await h.eval(READ);
  return out;
}

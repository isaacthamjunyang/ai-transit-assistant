import { openHome } from "./common.mjs";

// The approved overview design (overview-v2): the groups, the summary, the Arrive by card and the empty answer, in the real
// page against a stubbed OneMap. config: width, height, dark, empty (the plan answer is empty: the ride-app card shows).
const READ = `(function () {
  function box(el) { var r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right }; }
  function visible(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  var groups = Array.prototype.map.call(document.querySelectorAll("#overview-timeline > li.journey-step--leg"), function (li) {
    var cs = getComputedStyle(li);
    return { border: cs.borderTopWidth, style: cs.borderTopStyle, color: cs.borderTopColor, radius: cs.borderTopLeftRadius, bg: cs.backgroundColor, box: box(li) };
  });
  var rows = document.querySelectorAll("#overview-timeline > li");
  var afters = Array.prototype.map.call(rows, function (li) { return getComputedStyle(li, "::after").content; });
  var card = getComputedStyle(document.getElementById("overview-card"));
  var sum = document.getElementById("overview-summary");
  var cells = sum ? Array.prototype.map.call(sum.querySelectorAll(".overview-summary__cell"), box) : [];
  var hero = sum && visible("overview-summary") ? sum.querySelector(".overview-summary__cell:first-child .overview-summary__value") : null;
  var arrive = document.getElementById("overview-arrive-value");
  var time = arrive ? arrive.querySelector(".arrive-box__time") : null;
  var lead = arrive ? arrive.querySelector(".arrive-box__lead") : null;
  var taps = Array.prototype.map.call(document.querySelectorAll("#journey-overview button:not([hidden]), #journey-overview .ride-apps__link, #journey-overview select"), function (el) {
    return { id: el.id || el.textContent.trim(), shown: el.getClientRects().length > 0, h: el.getBoundingClientRect().height, w: el.getBoundingClientRect().width };
  }).filter(function (t) { return t.shown; });
  var sel = document.getElementById("priority-select");
  var scs = getComputedStyle(sel);
  var titleEl = document.querySelector("#overview-timeline .journey-step__title");
  var title = getComputedStyle(titleEl || document.body);
  var chev = document.querySelector(".priority-select-wrap__chevron");
  var select = { box: box(sel), border: scs.borderTopWidth, borderColor: scs.borderTopColor, color: scs.color, bg: scs.backgroundColor,
    size: scs.fontSize, weight: scs.fontWeight, family: scs.fontFamily, titleSize: title.fontSize, titleWeight: title.fontWeight,
    titleFamily: title.fontFamily, appearance: scs.appearance, chevron: chev ? box(chev) : null,
    wrap: box(sel.parentElement), padRight: scs.paddingRight, aria: sel.getAttribute("aria-label") };
  var ride = Array.prototype.map.call(document.querySelectorAll("#ride-apps .ride-apps__link"), box);
  return {
    cardBg: card.backgroundColor, cardBorder: card.borderTopWidth, cardPad: card.paddingLeft,
    titleSize: getComputedStyle(document.getElementById("overview-title")).fontSize,
    groups: groups, afters: afters, cells: cells, sumBg: sum ? getComputedStyle(sum).backgroundColor : null,
    sumBar: sum ? getComputedStyle(sum).borderLeftWidth : null,
    heroSize: hero ? getComputedStyle(hero).fontSize : null,
    arriveText: arrive && !arrive.hidden ? arrive.textContent.replace(/\s+/g, " ").trim() : null,
    arriveNext: arrive && arrive.querySelector(".arrive-box__next") ? arrive.querySelector(".arrive-box__next").textContent : null,
    arriveLead: lead ? lead.textContent : null, arriveTime: time ? time.textContent : null,
    arriveTimeLines: time ? Math.round(time.getBoundingClientRect().height / parseFloat(getComputedStyle(time).lineHeight)) : null,
    arriveTimeFont: time ? getComputedStyle(time).fontSize : null,
    taps: taps, ride: ride, select: select,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    rideShown: visible("ride-apps")
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination", walk_minutes: 3};
    pushScreen("journey"); true`);
  await h.until("document.getElementById('overview-skeleton').hidden && document.getElementById('overview-card').getAttribute('aria-busy') === 'false'", 20000, "the plan");
  await h.sleep(500);
  out.first = await h.eval(READ);
  // a change of priority must not move the select (the same box before and after)
  out.shift = await h.eval(`(function () {
    var sel = document.getElementById("priority-select");
    var before = sel.getBoundingClientRect();
    sel.value = "least_walking";
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    var after = sel.getBoundingClientRect();
    return { before: [before.x, before.y, before.width, before.height], after: [after.x, after.y, after.width, after.height] };
  })()`);
  if (!c.empty) {
    // very long stop names, one unbroken word: the page must not scroll sideways
    out.longNames = await h.eval(`(function () {
      var titles = document.querySelectorAll("#overview-timeline .journey-step__title, #overview-timeline .journey-step__detail");
      Array.prototype.forEach.call(titles, function (el) { el.textContent = "Extraordinarilylongstopnamewithoutanybreaks Interchange Terminal (NS17)"; });
      return { scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
    })()`);
  }
  return out;
}

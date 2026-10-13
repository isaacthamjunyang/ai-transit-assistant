import { openHome } from "./common.mjs";

// The journey overview with a OneMap answer: one row per leg, the line badges and the priority chips.
// config: width, dark, choose (a priority value to pick in the select).
const READ = `(function () {
  function text(el) { return el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim(); }
  function box(el) { var r = el.getBoundingClientRect(); return { w: r.width, h: r.height, x: r.x, y: r.y, right: r.right }; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#overview-timeline > li"), function (li) {
    var badge = li.querySelector(".line-badge");
    var cs = badge ? getComputedStyle(badge) : null;
    var edit = li.querySelector(".journey-step__edit");
    return {
      cls: li.className, node: li.querySelector(".step-node").className, text: text(li),
      icon: { color: getComputedStyle(li.querySelector(".step-node")).color, bg: getComputedStyle(li.querySelector(".step-node")).backgroundColor,
        svg: li.querySelector(".step-node svg") ? li.querySelector(".step-node svg").innerHTML.length : 0 },
      title: li.querySelector(".journey-step__title") ? text(li.querySelector(".journey-step__title")) : "",
      lines: Array.prototype.map.call(li.querySelectorAll(".journey-step__body > p"), text),
      badge: badge ? { text: badge.textContent, cls: badge.className, bg: cs.backgroundColor, color: cs.color,
        box: box(badge), name: badge.nextElementSibling ? text(badge.nextElementSibling) : "" } : null,
      edit: edit ? { label: edit.getAttribute("aria-label"), box: box(edit) } : null,
      markers: Array.prototype.map.call(li.querySelectorAll(".step-node"), function (n) { return n.className; })
        .filter(function (c) { return c.indexOf("--rail") !== -1 || c.indexOf("--bus") !== -1; }),
      bar: !!li.querySelector(".journey-step__bar"),
      leg: li.querySelector(".journey-step__bar") ? (function () {
        var nodes = li.querySelectorAll(".step-node");
        var bar = li.querySelector(".journey-step__bar");
        return {
          barBg: getComputedStyle(bar).backgroundColor, bar: box(bar),
          start: box(nodes[0]), end: box(nodes[1]),
          startIcon: nodes[0].innerHTML, endIcon: nodes[1].innerHTML,
          startRing: getComputedStyle(nodes[0]).boxShadow, endRing: getComputedStyle(nodes[1]).boxShadow,
          startBg: getComputedStyle(nodes[0]).backgroundColor, endBg: getComputedStyle(nodes[1]).backgroundColor,
          startColor: getComputedStyle(nodes[0]).color, endColor: getComputedStyle(nodes[1]).color,
          endText: text(li.querySelector(".journey-step__body--end")), li: box(li)
        };
      })() : null,
      right: box(li).right
    };
  });
  var sel = document.getElementById("priority-select");
  var label = document.querySelector("label[for=priority-select]");
  var select = {
    tag: sel.tagName, value: sel.value, aria: sel.getAttribute("aria-label"), label: label ? text(label) : null, box: box(sel),
    tabIndex: sel.tabIndex, disabled: sel.disabled, text: sel.options[sel.selectedIndex].text,
    options: Array.prototype.map.call(sel.options, function (o) { return { value: o.value, text: o.text, disabled: o.disabled }; }),
    focused: document.activeElement === sel
  };
  function top(id) { var el = document.getElementById(id); return el ? el.getBoundingClientRect().top : null; }
  var order = { title: top("overview-title"), select: top("priority-select"), summary: top("overview-summary"),
    timeline: top("overview-timeline"), skeleton: top("overview-skeleton") };
  var sumEl = document.getElementById("overview-summary");
  var summary = sumEl && visible("overview-summary") ? {
    cls: sumEl.className, aria: sumEl.getAttribute("aria-label"), role: sumEl.getAttribute("role"),
    labels: Array.prototype.map.call(sumEl.querySelectorAll(".overview-summary__label"), text),
    values: Array.prototype.map.call(sumEl.querySelectorAll(".overview-summary__value"), text),
    bar: getComputedStyle(sumEl).borderLeftColor, barWidth: getComputedStyle(sumEl).borderLeftWidth,
    bg: getComputedStyle(sumEl).backgroundColor, box: box(sumEl)
  } : null;
  function visible(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  function say(id) { var el = document.getElementById(id); return el && visible(id) ? text(el) : null; }
  return {
    rows: rows, select: select, order: order, summary: summary, visibleLabels: document.querySelectorAll("#overview-card label").length,
    titleText: text(document.getElementById("overview-title")), reasonLeft: !!document.getElementById("overview-reason"),
    fallbackNote: say("overview-fallback-note"), priorityNote: say("overview-priority-note"),
    noRoute: visible("overview-no-route") ? text(document.getElementById("overview-no-route-text")) : null,
    noService: visible("overview-no-service"),
    startDisabled: document.getElementById("start-journey").disabled,
    timelineVisible: visible("overview-timeline"),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    planRequests: __requests.filter(function (u) { return u.indexOf("/api/journey-plan?") === 0; }),
    arrivalRequests: __requests.filter(function (u) { return u.indexOf("/api/arrivals") === 0; }).length,
    chipsLeft: document.querySelectorAll("#overview-priority [role=radio], #overview-priority .arrive-chip").length
  };
})()`;

async function waitForPlan(h, count) {
  await h.until(`__requests.filter(function (u) { return u.indexOf('/api/journey-plan?') === 0; }).length >= ${count}
    && document.getElementById('overview-card').getAttribute('aria-busy') === 'false'`, 20000, "the plan to load");
  await h.sleep(400);
}

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height });
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination", walk_minutes: 3};
    pushScreen("journey"); true`);
  await waitForPlan(h, 1);
  out.first = await h.eval(READ);
  if (c.shots) { await h.screenshot(`${c.shots}/overviewlegs-${c.name || "first"}.png`); }
  if (c.estimate) {
    // the arrival sentence with a range in the data: the screen shows the point time only
    out.estimate = await h.eval(`(function () {
      var at = Date.now() + 25 * 60000;
      function iso(ms) { return new Date(ms).toISOString(); }
      var data = { estimated_arrival: iso(at), arrival_low: iso(at - 8 * 60000), arrival_high: iso(at + 8 * 60000) };
      var seen = {};
      [["", "without"], ["2099-01-01T00:00", "with"]].forEach(function (pair) {
        arriveByInput.value = pair[0];
        renderArrivalViews(data);
        seen[pair[1]] = { overview: document.getElementById("journey-arrival-estimate").textContent,
          box: document.getElementById("overview-arrive-estimate").textContent, live: document.getElementById("live-arrival-estimate").textContent };
      });
      arriveByInput.value = "";
      return seen;
    })()`);
  }
  if (c.durations) {
    out.durations = await h.eval(`[0, 1, 59, 60, 65, 119, 120, 185].map(function (n) { return formatDuration(n); })`);
    out.tones = await h.eval(`(function () {
      var seen = {};
      [0, 1, 2, 3, 4].forEach(function (t) {
        renderOverviewSummary({ minutes: 70, transfers: t, walking: 61 });
        var box = document.getElementById("overview-summary");
        var cs = getComputedStyle(box);
        seen[t] = { cls: box.className, aria: box.getAttribute("aria-label"), bar: cs.borderLeftColor, bg: cs.backgroundColor,
          values: Array.prototype.map.call(box.querySelectorAll(".overview-summary__value"), function (v) { return v.textContent; }),
          labels: Array.prototype.map.call(box.querySelectorAll(".overview-summary__label"), function (v) { return v.textContent; }) };
      });
      return seen;
    })()`);
  }
  if (c.choose) {
    await h.eval(`var s = document.getElementById("priority-select"); s.focus(); s.value = "${c.choose}";
      s.dispatchEvent(new Event("change", {bubbles: true})); true`);
    await waitForPlan(h, 2);
    out.afterChoose = await h.eval(READ);
  }
  return out;
}

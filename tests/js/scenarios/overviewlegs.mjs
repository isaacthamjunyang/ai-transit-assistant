import { openHome } from "./common.mjs";

// The journey overview with a OneMap answer: one row per leg, the line badges and the priority chips.
// config: width, dark, click (a priority id to tap), keys (a key to press on the selected chip).
const READ = `(function () {
  function text(el) { return el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim(); }
  function box(el) { var r = el.getBoundingClientRect(); return { w: r.width, h: r.height, x: r.x, y: r.y, right: r.right }; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#overview-timeline > li"), function (li) {
    var badge = li.querySelector(".line-badge");
    var cs = badge ? getComputedStyle(badge) : null;
    var edit = li.querySelector(".journey-step__edit");
    return {
      cls: li.className, node: li.querySelector(".step-node").className, text: text(li),
      title: li.querySelector(".journey-step__title") ? text(li.querySelector(".journey-step__title")) : "",
      lines: Array.prototype.map.call(li.querySelectorAll(".journey-step__body > p"), text),
      badge: badge ? { text: badge.textContent, cls: badge.className, bg: cs.backgroundColor, color: cs.color,
        box: box(badge), name: badge.nextElementSibling ? text(badge.nextElementSibling) : "" } : null,
      edit: edit ? { label: edit.getAttribute("aria-label"), box: box(edit) } : null,
      right: box(li).right
    };
  });
  var chips = Array.prototype.map.call(document.querySelectorAll("#overview-priority [role=radio]"), function (chip) {
    return { id: chip.id, text: text(chip), checked: chip.getAttribute("aria-checked"), tab: chip.tabIndex,
      disabled: chip.getAttribute("aria-disabled"), selected: chip.classList.contains("is-selected"),
      box: box(chip), focused: document.activeElement === chip };
  });
  function visible(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  function say(id) { var el = document.getElementById(id); return el && visible(id) ? text(el) : null; }
  return {
    rows: rows, chips: chips, totals: say("overview-totals"), trainNote: say("overview-train-note"),
    fallbackNote: say("overview-fallback-note"), priorityNote: say("overview-priority-note"),
    noRoute: visible("overview-no-route") ? text(document.getElementById("overview-no-route-text")) : null,
    noService: visible("overview-no-service"), reason: say("overview-reason-text"),
    startDisabled: document.getElementById("start-journey").disabled,
    timelineVisible: visible("overview-timeline"),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    planRequests: __requests.filter(function (u) { return u.indexOf("/api/journey-plan?") === 0; }),
    arrivalRequests: __requests.filter(function (u) { return u.indexOf("/api/arrivals") === 0; }).length,
    groupLabel: document.querySelector("#overview-priority [role=radiogroup]").getAttribute("aria-label")
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
  if (c.click) {
    await h.eval(`document.getElementById("priority-${c.click}").click(); true`);
    await waitForPlan(h, 2);
    out.afterClick = await h.eval(READ);
  }
  if (c.keys) {
    await h.eval(`document.querySelector("#overview-priority [aria-checked=true]").focus(); true`);
    const before = await h.eval(`__requests.filter(function (u) { return u.indexOf('/api/journey-plan?') === 0; }).length`);
    await h.eval(`document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "${c.keys}", bubbles: true})); true`);
    await waitForPlan(h, before + 1);
    out.afterKey = await h.eval(READ);
  }
  return out;
}

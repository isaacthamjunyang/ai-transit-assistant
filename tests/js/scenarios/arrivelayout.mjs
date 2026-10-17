import { openHome } from "./common.mjs";

// The Arrive by chips and the Custom panel, on Home and on the Confirm destination screen (one component): the two rows, the single
// lines, the new "In 1 hr 30 min" preset (Singapore time, whatever the phone's zone), the time field's outline and the clock button.
// config: width, height, dark, zone (the browser time zone).
const CLOCK = (iso) => `(function () {
  var Real = window.__RealDate || Date; window.__RealDate = Real;
  var offset = Real.parse(${JSON.stringify(iso)}) - Real.now();
  function Fake() { var a = Array.prototype.slice.call(arguments); return a.length ? new (Function.prototype.bind.apply(Real, [null].concat(a)))() : new Real(Real.now() + offset); }
  Fake.now = function () { return Real.now() + offset; }; Fake.parse = Real.parse; Fake.UTC = Real.UTC; Fake.prototype = Real.prototype;
  window.Date = Fake; return true;
})()`;

const LAYOUT = `(function () {
  function box(el) { var r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; }
  function lines(el) {
    var range = document.createRange(); range.selectNodeContents(el);
    var tops = {}; Array.prototype.forEach.call(range.getClientRects(), function (r) { tops[Math.round(r.top)] = true; });
    return Object.keys(tops).length;
  }
  var panel = document.getElementById("arrive-by-panel");
  var rows = Array.prototype.map.call(panel.querySelectorAll(".arrive-chips__row"), function (row) {
    return { chips: Array.prototype.map.call(row.children, function (chip) {
      var s = getComputedStyle(chip), r = chip.getBoundingClientRect();
      return { id: chip.id, text: chip.textContent.trim(), role: chip.getAttribute("role"), checked: chip.getAttribute("aria-checked"), lines: lines(chip),
               left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height, fontSize: s.fontSize, paddingLeft: s.paddingLeft,
               shadow: s.boxShadow, border: s.borderTopColor, borderWidth: s.borderTopWidth, scrollW: chip.scrollWidth, clientW: chip.clientWidth };
    }), rect: box(row), scrollW: row.scrollWidth, clientW: row.clientWidth };
  });
  var focusable = Array.prototype.filter.call(panel.querySelectorAll("button, input"), function (el) { return el.getClientRects().length > 0 && el.tabIndex >= 0; }).map(function (el) { return el.id; });
  return { rows: rows, panel: box(panel), panelScrollW: panel.scrollWidth, panelClientW: panel.clientWidth,
           group: panel.querySelector(".arrive-chips").getAttribute("role") + "|" + panel.querySelector(".arrive-chips").getAttribute("aria-label"),
           focusable: focusable, scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
           inConfirm: !!document.getElementById("confirm-arrive-slot").querySelector("#arrive-by-panel"), screen: screenStack[screenStack.length - 1] };
})()`;

const TIMEFIELD = `(function () {
  function box(el) { var r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; }
  var input = document.getElementById("arrive-by-time"), button = document.getElementById("arrive-time-picker"), chip = document.getElementById("arrive-custom");
  var si = getComputedStyle(input), sb = getComputedStyle(button), sc = getComputedStyle(chip), root = getComputedStyle(document.documentElement);
  function bgOf(el) { while (el) { var c = getComputedStyle(el).backgroundColor; if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") { return c; } el = el.parentElement; } return "rgb(255, 255, 255)"; }
  var label = document.querySelector("#arrive-by-custom label");
  return { input: box(input), button: box(button), field: box(input.parentElement), inputShadow: si.boxShadow, chipShadow: sc.boxShadow, inputRadius: si.borderTopLeftRadius,
           chipRadius: sc.borderTopLeftRadius, inputBorderWidth: si.borderTopWidth, chipBorderWidth: sc.borderTopWidth, inputBorder: si.borderTopColor, chipBorder: sc.borderTopColor,
           inputBg: bgOf(input), buttonColor: sb.color, buttonLabel: button.getAttribute("aria-label"), buttonType: button.tagName + "|" + button.getAttribute("type"),
           inputLabel: input.getAttribute("aria-label"), labelPresent: !!label, labelTexts: Array.prototype.map.call(document.querySelectorAll("#arrive-by-custom label"), function (l) { return l.textContent; }),
           bodyHasTime: Array.prototype.some.call(document.querySelectorAll("#arrive-by-custom *"), function (el) { return el.children.length === 0 && el.textContent.trim() === "Time"; }),
           tokens: { outline: root.getPropertyValue("--color-selected-outline").trim(), link: root.getPropertyValue("--color-link").trim(), card: root.getPropertyValue("--color-card").trim() },
           nativeIcon: getComputedStyle(input, "::-webkit-calendar-picker-indicator").display, dayTop: document.getElementById("arrive-day").getBoundingClientRect().top,
           scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;

const READ = `({ value: arriveByInput.value, choice: arriveByChoice, picked: arriveByPicked,
  display: document.getElementById("arrive-by-display").textContent.replace(/\\s+/g, " ").trim(),
  chosen: document.getElementById("arrive-by-chosen-text").textContent.replace(/\\s+/g, " ").trim(),
  checked: ["arrive-30", "arrive-60", "arrive-90", "arrive-none", "arrive-custom"].map(function (id) { return id + ":" + document.getElementById(id).getAttribute("aria-checked"); }),
  panelHidden: document.getElementById("arrive-by-panel").hidden, customVisible: !document.getElementById("arrive-by-custom").hidden,
  today: document.getElementById("arrive-day-today").getAttribute("aria-checked"), tomorrow: document.getElementById("arrive-day-tomorrow").getAttribute("aria-checked"), day: arriveDay })`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await h.send("Emulation.setTimezoneOverride", { timezoneId: c.zone || "America/Los_Angeles" });
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  out.browserZone = await h.eval("Intl.DateTimeFormat().resolvedOptions().timeZone");
  const open = () => h.eval("if (document.getElementById('arrive-by-panel').hidden) { document.getElementById('arrive-by-field').click(); } true");
  await open();
  await h.sleep(150);
  out.home = await h.eval(LAYOUT);
  // Custom open: the time field and its button
  await h.eval("document.getElementById('arrive-custom').click(); true");
  await h.sleep(150);
  out.homeCustom = await h.eval(LAYOUT);
  out.field = await h.eval(TIMEFIELD);
  out.fieldAfterFocus = await h.eval(`(function () { document.getElementById("arrive-by-time").focus(); return ${TIMEFIELD}; })()`);
  // the clock button and the field open the picker; with no showPicker the input is focused; a refusal falls back to the focus
  out.picker = await h.eval(`(function () {
    var input = document.getElementById("arrive-by-time"), button = document.getElementById("arrive-time-picker"), result = {};
    window.__picked = 0;
    input.showPicker = function () { window.__picked += 1; };
    input.blur(); button.click(); result.buttonCalls = window.__picked;
    input.blur(); input.click(); result.fieldCalls = window.__picked - result.buttonCalls;
    input.showPicker = function () { throw new Error("NotAllowedError"); };
    input.blur(); button.click(); result.refusedFocus = document.activeElement === input;
    Object.defineProperty(input, "showPicker", { value: undefined, configurable: true, writable: true });
    input.blur(); button.click(); result.missingFocus = document.activeElement === input;
    input.blur(); input.click(); result.fieldMissingFocus = document.activeElement === input;
    delete input.showPicker;
    return result;
  })()`);
  // the new preset: Singapore time, whatever the phone's zone
  const cases = {};
  const preset = async (key, iso) => {
    await h.eval(CLOCK(iso));
    await open();
    await h.eval("document.getElementById('arrive-90').click(); true");
    await h.sleep(150);
    cases[key] = await h.eval(READ);
  };
  await preset("noon", "2026-01-15T04:00:00Z");  // 12:00 PM in Singapore: 1:30 PM
  await preset("midnight", "2026-01-15T15:07:00Z");  // 11:07 PM in Singapore: 12:40 AM the next day
  // the other presets, for the same clock
  await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-60').click(); true");
  cases.hour = await h.eval(READ);
  await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-30').click(); true");
  cases.half = await h.eval(READ);
  // selecting it clears a Custom day choice: Custom, Tomorrow, then the preset, then Custom again
  await h.eval(CLOCK("2026-01-15T04:00:00Z"));
  await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-custom').click(); true");
  await h.eval("arriveTimeInput.value = '18:30'; arriveTimeInput.dispatchEvent(new Event('input', { bubbles: true })); document.getElementById('arrive-day-tomorrow').click(); true");
  cases.customTomorrow = await h.eval(READ);
  await open();
  await h.eval("document.getElementById('arrive-90').click(); true");
  cases.afterPreset = await h.eval(READ);
  await open();
  await h.eval("document.getElementById('arrive-custom').click(); true");
  cases.customAgain = await h.eval(READ);
  await h.eval("document.getElementById('arrive-none').click(); true");
  cases.none = await h.eval(READ);
  out.cases = cases;
  // the Confirm destination screen: the same component, the same rows
  await h.eval("resetScreens(); true");
  await h.eval(`selectedDestination = {latitude: 1.3, longitude: 103.8, label: "Destination", label_display: "Destination"}; pushScreen("stops"); pushScreen("confirm"); true`);
  await h.sleep(300);
  await open();
  await h.sleep(150);
  out.confirm = await h.eval(LAYOUT);
  return out;
}

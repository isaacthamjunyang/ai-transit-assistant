import { openHome } from "./common.mjs";

// The Custom arrive-by control: a time input and a Today / Tomorrow toggle, in Singapore time whatever the phone's zone.
// config.zone is the browser time zone (default America/Los_Angeles). The page's clock is moved with a fake Date.
const CLOCK = (iso) => `(function () {
  var Real = window.__RealDate || Date; window.__RealDate = Real;
  var offset = Real.parse(${JSON.stringify(iso)}) - Real.now();
  function Fake() { var a = Array.prototype.slice.call(arguments); return a.length ? new (Function.prototype.bind.apply(Real, [null].concat(a)))() : new Real(Real.now() + offset); }
  Fake.now = function () { return Real.now() + offset; }; Fake.parse = Real.parse; Fake.UTC = Real.UTC; Fake.prototype = Real.prototype;
  window.Date = Fake; return true;
})()`;

const READ = `({
  value: arriveByInput.value, time: arriveTimeInput.value, day: arriveDay,
  errorHidden: document.getElementById('arrive-by-error').hidden, error: document.getElementById('arrive-by-error').textContent,
  confirmDisabled: document.getElementById('confirm-destination-stop').disabled,
  display: document.getElementById('arrive-by-display').textContent.replace(/\\s+/g, ' ').trim(),
  chosen: document.getElementById('arrive-by-chosen-text').textContent.trim(),
  describedBy: arriveTimeInput.getAttribute('aria-describedby'),
  underField: Array.prototype.filter.call(arriveTimeInput.parentNode.children, function (el) { return el !== arriveTimeInput && el.id !== 'arrive-day' && !el.matches('label') && !el.hidden && el.textContent.trim() !== ''; }).map(function (el) { return el.id || el.className; }),
  fromNowAnywhere: document.body.textContent.indexOf('from now') !== -1,
  resolvedGone: document.getElementById('arrive-by-resolved') === null,
  picked: arriveByPicked, findRoute: document.getElementById('find-route').getAttribute('aria-disabled'),
  today: document.getElementById('arrive-day-today').getAttribute('aria-checked'),
  tomorrow: document.getElementById('arrive-day-tomorrow').getAttribute('aria-checked'),
  customVisible: !document.getElementById('arrive-by-custom').hidden
})`;

export default async function (h) {
  const out = { cases: {} };
  await h.send("Emulation.setTimezoneOverride", { timezoneId: h.config.zone || "America/Los_Angeles" });
  await openHome(h);
  out.browserZone = await h.eval("Intl.DateTimeFormat().resolvedOptions().timeZone");
  const setTime = (value) => h.eval(`(function () { arriveTimeInput.value = ${JSON.stringify(value)}; arriveTimeInput.dispatchEvent(new Event('input', { bubbles: true })); })(); true`);
  const clickDay = (day) => h.eval(`document.getElementById('arrive-day-${day}').click(); true`);
  const custom = async () => {
    await h.eval("if (document.getElementById('arrive-by-panel').hidden) { document.getElementById('arrive-by-field').click(); } document.getElementById('arrive-custom').click(); true");
  };
  const reset = () => h.eval("applyArriveValue('', 'arrive-none'); arriveByPicked = false; true");
  // a valid Custom time closes the panel, like a preset; the dropdown reopens it
  const reopen = () => h.eval("if (document.getElementById('arrive-by-panel').hidden) { document.getElementById('arrive-by-field').click(); } true");

  // the controls
  await custom();
  out.controls = await h.eval(`({
    dateInputs: document.querySelectorAll('input[type=datetime-local], input[type=date], input[type=month], input[type=week]').length,
    timeInputs: document.querySelectorAll('input[type=time]').length,
    timeType: arriveTimeInput.type,
    options: Array.prototype.map.call(document.querySelectorAll('#arrive-day [role=radio]'), function (b) { return b.textContent.trim(); }),
    group: document.getElementById('arrive-day').getAttribute('role') + '|' + document.getElementById('arrive-day').getAttribute('aria-label'),
    labels: Array.prototype.map.call(document.querySelectorAll('#arrive-day [role=radio]'), function (b) { return b.getAttribute('aria-label'); }),
    heights: Array.prototype.map.call(document.querySelectorAll('#arrive-day [role=radio], #arrive-by-time'), function (b) { return b.getBoundingClientRect().height; }),
    marker: getComputedStyle(document.getElementById('arrive-day-today'), '::before').content,
    state: ${READ}
  })`);
  // keyboard: an arrow key moves the selection
  await h.eval("document.getElementById('arrive-day-today').focus(); true");
  await h.send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  await h.send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  out.afterArrow = await h.eval(`({ day: arriveDay, focus: document.activeElement.id })`);
  await clickDay("today");

  // 11:50 PM in Singapore (the phone is in Los Angeles): Tomorrow 12:10 AM works and reads "(tomorrow)"
  await h.eval(CLOCK("2026-10-08T23:50:00+08:00"));
  await reset(); await custom();
  await setTime("00:10"); await clickDay("tomorrow");
  out.cases.midnight = await h.eval(READ);
  out.cases.midnightClock = await h.eval("formatArriveByClock(arriveByInput.value)");
  await clickDay("today");
  out.cases.midnightToday = await h.eval(READ);           // Today 12:10 AM has passed
  await setTime("23:55"); await clickDay("today");
  out.cases.midnightTodayLate = await h.eval(READ);       // Today 11:55 PM is fine
  await setTime("23:55"); await clickDay("tomorrow");
  out.cases.midnightTooFar = await h.eval(READ);          // Tomorrow 11:55 PM is 24 h 5 min away
  await setTime(""); out.cases.empty = await h.eval(READ);

  // presets set the time and the toggle; a preset after midnight selects Tomorrow; Custom then shows them
  await reset(); await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-30').click(); true");
  out.cases.preset30 = await h.eval(READ);
  await custom();
  out.cases.preset30InCustom = await h.eval(READ);
  await h.eval("document.getElementById('arrive-60').click(); true");
  out.cases.preset60 = await h.eval(READ);
  await h.eval(CLOCK("2026-10-08T15:00:00+08:00"));
  await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-30').click(); true");
  out.cases.preset30Afternoon = await h.eval(READ);

  // Today with a time that has passed: the message, no silent switch, Confirm and Find route disabled
  await h.eval(CLOCK("2026-10-08T18:00:00+08:00"));
  await reset(); await custom();
  await setTime("17:00"); await clickDay("today");
  out.cases.pastToday = await h.eval(READ);
  await clickDay("tomorrow");
  out.cases.pastThenTomorrow = await h.eval(READ);        // Tomorrow 5:00 PM is 23 h ahead
  await setTime("19:00");
  out.cases.tooFarTomorrow = await h.eval(READ);          // Tomorrow 7:00 PM is 25 h ahead

  // the Singapore date is used, not the phone's: 7:30 AM on Oct 9 in Singapore is still Oct 8 in Los Angeles
  await h.eval(CLOCK("2026-10-09T07:30:00+08:00"));
  await reset(); await custom();
  await setTime("08:00"); await clickDay("today");
  out.cases.singaporeToday = await h.eval(READ);
  await clickDay("tomorrow");
  out.cases.singaporeTomorrow = await h.eval(READ);
  out.localDate = await h.eval("new Date().toLocaleDateString('en-CA')");  // the phone's date (Los Angeles)
  out.singaporeDay = await h.eval("singaporeDay(0)");

  // the selected option: aria-checked, bold, a ring and no tick; and nothing moves when the selection changes
  const boxes = () => h.eval("Array.prototype.map.call(document.querySelectorAll('#arrive-day [role=radio]'), function (b) { var r = b.getBoundingClientRect(); var g = document.getElementById('arrive-day').getBoundingClientRect(); return [r.x - g.x, r.y - g.y, r.width, r.height]; })");
  const styleOf = (id) => h.eval("(function () { var b = document.getElementById('" + id + "'); var cs = getComputedStyle(b); return { checked: b.getAttribute('aria-checked'), weight: cs.fontWeight, ring: cs.boxShadow !== 'none' && cs.boxShadow.indexOf('0px 0px 0px 2px') !== -1, content: getComputedStyle(b, '::before').content }; })()");
  const panelWidth = () => h.eval("document.getElementById('arrive-by-panel').getBoundingClientRect().width");
  await h.eval(CLOCK("2026-10-08T12:00:00+08:00"));
  await reset(); await custom();
  out.toggle = { fresh: { today: await styleOf("arrive-day-today"), tomorrow: await styleOf("arrive-day-tomorrow") } };
  await clickDay("today"); await reopen();
  out.toggle.today = await styleOf("arrive-day-today"); out.toggle.tomorrow = await styleOf("arrive-day-tomorrow");
  out.toggle.boxesToday = await boxes(); out.toggle.panelWidthToday = await panelWidth();
  await clickDay("tomorrow"); await reopen();
  out.toggle.afterTomorrow = { today: await styleOf("arrive-day-today"), tomorrow: await styleOf("arrive-day-tomorrow") };
  out.toggle.boxesTomorrow = await boxes();
  out.toggle.panelWidthTomorrow = await panelWidth();
  await clickDay("today");

  // the prefill: Singapore time + 5 min, rounded up to the whole minute, only when the time is empty
  const prefill = async (iso) => {
    await h.eval(CLOCK(iso));
    await reset();
    await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-custom').click(); true");
    return await h.eval(READ);
  };
  out.prefill = {
    mid: await prefill("2026-10-08T18:00:10+08:00"),          // 6:05:10 PM rounds up to 6:06 PM
    lateInMinute: await prefill("2026-10-08T18:00:45+08:00"), // 6:05:45 PM rounds up to 6:06 PM
    singapore: await prefill("2026-10-09T07:30:10+08:00"),    // Los Angeles is still on Oct 8
    midnight: await prefill("2026-10-08T23:58:10+08:00"),     // 12:03:10 AM rounds up to 12:04 AM, next Singapore day
  };

  await h.eval(CLOCK("2026-10-08T18:00:10+08:00"));
  await reset(); await custom();
  await setTime("18:05"); await clickDay("today"); await reopen();
  out.nothingUnder = await h.eval(READ);
  // it follows the time and the toggle
  await setTime("17:30");                                       // Today 5:30 PM has passed: message, caption hidden
  out.whenPast = await h.eval(READ);
  await clickDay("tomorrow");                                   // Tomorrow 5:30 PM is 23 h 30 min away
  out.whenTomorrow = await h.eval(READ);
  await clickDay("today"); await setTime("18:30");
  await reopen();
  out.whenBefore = await h.eval(READ);
  await h.eval(CLOCK("2026-10-08T18:10:10+08:00"));
  await h.eval("arriveRecheckTick(); true");                     // the minute tick
  out.whenTick = await h.eval(READ);
  await h.eval(CLOCK("2026-10-08T18:31:10+08:00"));
  await h.eval("arriveRecheckTick(); true");                     // the time has passed while the page sat open
  out.whenPassed = await h.eval(READ);

  // presets: not overwritten by the prefill
  await h.eval(CLOCK("2026-10-08T15:00:20+08:00"));
  await reset();
  await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-30').click(); true");
  const preset = await h.eval(READ);
  await custom();
  const presetKept = await h.eval(READ);
  await setTime("16:45"); await clickDay("today"); await reopen();
  await h.eval("document.getElementById('arrive-custom').click(); true");
  const userKept = await h.eval(READ);
  await h.eval("document.getElementById('arrive-none').click(); document.getElementById('arrive-by-field').click(); true");
  const none = await h.eval(READ);
  await custom();
  const afterNone = await h.eval(READ);
  await setTime("");
  await h.eval("document.getElementById('arrive-custom').click(); true");
  const afterClear = await h.eval(READ);
  out.prefill.preset = preset; out.prefill.presetKept = presetKept; out.prefill.userKept = userKept;
  out.prefill.none = none; out.prefill.afterNone = afterNone; out.prefill.afterClear = afterClear;

  // the clock passes the chosen time while the page sits open
  await h.eval(CLOCK("2026-10-08T15:00:00+08:00"));
  await reset(); await custom();
  await setTime("15:05"); await clickDay("today");
  await reopen();
  await h.eval(CLOCK("2026-10-08T15:07:00+08:00"));
  await h.eval("document.getElementById('confirm-destination-stop').disabled = false; true");
  await h.eval("onArriveCustomEdit(); true");
  out.prefill.clockPassed = await h.eval(READ);

  // the panel: Custom opens it; a valid Today or Tomorrow closes it and the dropdown names the choice; a problem keeps it
  // open with its message at least 12 px under the day buttons
  const PANEL = `(function () {
    var panel = document.getElementById('arrive-by-panel');
    var box = function (id) { var r = document.getElementById(id).getBoundingClientRect(); return { top: r.top, bottom: r.bottom, height: r.height, width: r.width }; };
    var ring = function (id) { return getComputedStyle(document.getElementById(id)).boxShadow; };
    var errorEl = document.getElementById('arrive-by-error');
    return { hidden: panel.hidden, expanded: document.getElementById('arrive-by-field').getAttribute('aria-expanded'),
      timeBox: box('arrive-by-time'), todayBox: box('arrive-day-today'), tomorrowBox: box('arrive-day-tomorrow'),
      errorBox: errorEl.hidden ? null : box('arrive-by-error'), errorShown: !errorEl.hidden,
      errorClass: errorEl.className, errorText: errorEl.textContent.trim(),
      customRing: ring('arrive-custom'), todayRing: ring('arrive-day-today'), tomorrowRing: ring('arrive-day-tomorrow'),
      customSelected: document.getElementById('arrive-custom').classList.contains('is-selected'),
      todayChecked: document.getElementById('arrive-day-today').getAttribute('aria-checked'),
      tomorrowChecked: document.getElementById('arrive-day-tomorrow').getAttribute('aria-checked'),
      findRoute: document.getElementById('find-route').getAttribute('aria-disabled'), time: arriveTimeInput.value,
      token: getComputedStyle(document.documentElement).getPropertyValue('--color-selected-outline').trim(),
      display: document.getElementById('arrive-by-display').textContent.replace(/\\s+/g, ' ').trim(),
      confirmDisabled: document.getElementById('confirm-destination-stop').disabled,
      todayWeight: getComputedStyle(document.getElementById('arrive-day-today')).fontWeight };
  })()`;
  out.panel = {};
  await h.eval(CLOCK("2026-10-08T18:00:10+08:00"));
  await reset();
  await h.eval("document.getElementById('arrive-by-field').click(); document.getElementById('arrive-custom').click(); true");
  out.panel.customOpened = await h.eval(PANEL);                 // Custom opens the panel: time field, both days, none chosen
  await setTime("19:00");
  out.panel.timeTyped = await h.eval(PANEL);                    // typing a time with no day: still open, still disabled
  await clickDay("today");
  out.panel.todayValid = await h.eval(PANEL);                   // a tap on Today: valid, the panel closes, "Custom · 7:00 PM"
  await reopen();
  out.panel.reopened = await h.eval(PANEL);                     // reopened: Today is still outlined
  await setTime("17:00");
  out.panel.todayPast = await h.eval(PANEL);                    // retyped into the past: the message, the panel stays open
  await setTime("19:30");
  out.panel.retyped = await h.eval(PANEL);                      // a valid retype re-validates but does not close
  await setTime("17:30"); await clickDay("tomorrow");
  out.panel.tomorrowValid = await h.eval(PANEL);                // 23 h 30 min ahead: closes, "(Tomorrow)"
  await reopen();
  await setTime("19:00");
  out.panel.tomorrowFar = await h.eval(PANEL);                  // 25 h ahead: its own message, the panel stays open
  await clickDay("tomorrow");
  out.panel.tomorrowFarTap = await h.eval(PANEL);               // tapping Tomorrow again changes nothing
  await clickDay("today");
  out.panel.backToToday = await h.eval(PANEL);

  // presets and No target clear the chosen day: the next Custom starts unselected again
  await reopen();
  await h.eval("document.getElementById('arrive-30').click(); true");
  await reopen();
  await h.eval("document.getElementById('arrive-custom').click(); true");
  out.panel.afterPreset = await h.eval(PANEL);
  await clickDay("today");
  await reopen();
  await h.eval("document.getElementById('arrive-none').click(); true");
  await reopen();
  await h.eval("document.getElementById('arrive-custom').click(); true");
  out.panel.afterNone = await h.eval(PANEL);

  // the keyboard: no option is checked at first; the arrow keys only move the focus; Enter selects and closes
  const press = async (key, code, vk, text) => {
    await h.send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: vk, text });
    await h.send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: vk });
  };
  await h.eval(CLOCK("2026-10-08T18:00:10+08:00"));
  await reset(); await custom();
  await h.eval("document.getElementById('arrive-day-today').focus(); true");
  await press("ArrowRight", "ArrowRight", 39);
  out.panel.keyArrow = { focus: await h.eval("document.activeElement.id"), state: await h.eval(PANEL),
    checked: await h.eval("Array.prototype.map.call(document.querySelectorAll('#arrive-day [role=radio]'), function (b) { return b.getAttribute('aria-checked'); })") };
  await h.eval("document.getElementById('arrive-day-today').focus(); true");
  await press("Enter", "Enter", 13, "\r");
  out.panel.keyEnter = await h.eval(PANEL);
  await reset(); await custom();
  await setTime("12:00");
  await h.eval("document.getElementById('arrive-day-tomorrow').focus(); true");
  await press(" ", "Space", 32, " ");
  out.panel.keySpace = await h.eval(PANEL);

  // midnight: the suggested time is 12:04 AM; Today has passed, Tomorrow works
  await h.eval(CLOCK("2026-10-08T23:58:10+08:00"));
  await reset(); await custom();
  out.panel.midnightOpen = await h.eval(PANEL);
  await clickDay("today");
  out.panel.midnightToday = await h.eval(PANEL);
  await clickDay("tomorrow");
  out.panel.midnightTomorrow = await h.eval(PANEL);

  // the same element on the Confirm page
  out.confirm = await h.eval(`(function () {
    placeArriveBy(true);
    var slot = document.getElementById('confirm-arrive-slot');
    return { inSlot: slot.contains(document.getElementById('arrive-by-time')), timeInputs: document.querySelectorAll('input[type=time]').length,
      dateInputs: document.querySelectorAll('input[type=datetime-local], input[type=date]').length };
  })()`);
  return out;
}

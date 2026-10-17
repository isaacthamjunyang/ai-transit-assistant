import { openHome } from "./common.mjs";

// The header and back row as rounded blocks on every page, the back button in the menu button's colours, the one-time
// pulse of the four action buttons (and its reduced-motion switch-off), and the green flag on the destination rows.
// config: width, dark. The destination search is answered in the page (no OneMap call).
const PAGES = ["home", "results", "stops", "confirm", "journey", "live", "arrivals", "newjourney", "onway", "walk"];

const BLOCKS = `(function (name) {
  applyScreen(name);
  document.getElementById("back-bar").hidden = name === "home";
  var box = function (el) {
    var r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height, radius: s.borderTopLeftRadius,
      background: s.backgroundColor, borderWidth: s.borderTopWidth, borderColor: s.borderTopColor, shadow: s.boxShadow, position: s.position,
      cssTop: s.top, zIndex: s.zIndex };
  };
  var header = document.querySelector(".app-header"), back = document.getElementById("back-bar");
  var shown = back.getClientRects().length > 0;
  var menu = document.getElementById("menu-open"), backButton = document.getElementById("back-home");
  return { page: name, header: box(header), back: shown ? box(back) : null,
    gap: shown ? back.getBoundingClientRect().top - header.getBoundingClientRect().bottom : null,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})`;

const STYLE = `(function (el) {
  var s = getComputedStyle(el), r = el.getBoundingClientRect();
  return { background: s.backgroundColor, color: s.color, border: s.borderTopColor, borderWidth: s.borderTopWidth,
    borderStyle: s.borderTopStyle, radius: s.borderTopLeftRadius, w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
    iconColor: getComputedStyle(el.querySelector(".icon")).color, label: el.getAttribute("aria-label") || el.textContent.trim() };
})`;

const ANIM = `(function (id) {
  var b = document.getElementById(id), a = b.getAnimations(), t = a[0] ? a[0].effect.getTiming() : null;
  return { count: a.length, state: a[0] ? a[0].playState : null, name: a[0] ? a[0].animationName : null,
    duration: t ? t.duration : null, iterations: t ? String(t.iterations) : null,
    keyframes: a[0] ? a[0].effect.getKeyframes().map(function (k) { return [Math.round(k.offset * 100), k.transform]; }) : null,
    offset: [b.offsetTop, b.offsetHeight, b.offsetWidth], scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth, focusVisible: b.matches(":focus-visible") };
})`;

export default async function (h) {
  const c = h.config;
  const out = { pages: [] };
  await openHome(h, { dark: c.dark, width: c.width || 360, height: 800, permission: "granted" });
  for (const name of PAGES) {
    out.pages.push(await h.eval(`${BLOCKS}(${JSON.stringify(name)})`));
  }
  await h.eval(`applyScreen("home"); document.getElementById("back-bar").hidden = true; true`);

  // the back row is not sticky: after 600 px of scrolling it is out of view, and scrolling back up shows it again
  await h.eval(`(function () { var s = document.createElement("div"); s.id = "test-spacer";
    s.style.height = "3000px"; s.style.flex = "none"; document.body.appendChild(s); })(); true`);
  out.scroll = [];
  for (const name of PAGES.filter((p) => p !== "home" && p !== "walk" && p !== "arrivals")) {  // Pages W and B have their own back button beside the title
    await h.eval(`applyScreen(${JSON.stringify(name)}); document.getElementById("back-bar").hidden = false; window.scrollTo(0, 0); true`);
    await h.sleep(60);
    const READ = `(function () {
      var back = document.getElementById("back-bar").getBoundingClientRect(), header = document.querySelector(".app-header").getBoundingClientRect();
      var main = document.querySelector("main.wrap").getBoundingClientRect();
      return { y: window.scrollY, backTop: back.top, backBottom: back.bottom, headerBottom: header.bottom, mainTop: main.top,
        height: document.documentElement.scrollHeight, position: getComputedStyle(document.getElementById("back-bar")).position,
        scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
    })()`;
    const top = await h.eval(READ);
    await h.eval(`window.scrollTo(0, 600); true`); await h.sleep(80);
    const down = await h.eval(READ);
    await h.eval(`window.scrollTo(0, 300); true`); await h.sleep(60);
    const part = await h.eval(READ);
    await h.eval(`window.scrollTo(0, 0); true`); await h.sleep(80);
    const up = await h.eval(READ);
    out.scroll.push({ page: name, top, down, part, up });
  }
  await h.eval(`document.getElementById("test-spacer").remove(); window.scrollTo(0, 0); applyScreen("home"); document.getElementById("back-bar").hidden = true; true`);

  // the back button and the menu button
  await h.eval(`applyScreen("results"); document.getElementById("back-bar").hidden = false; true`);
  out.menuButton = await h.eval(`${STYLE}(document.getElementById("menu-open"))`);
  out.backButton = await h.eval(`${STYLE}(document.getElementById("back-home"))`);
  await h.eval(`applyScreen("home"); document.getElementById("back-bar").hidden = true; true`);

  // the pulse: every 2 s while visible and enabled; none while disabled, hidden, pressed, keyboard-focused or reduced motion
  const wait = (ms) => h.sleep(ms);
  const key = async (name, code, vk) => {
    await h.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: name, code, windowsVirtualKeyCode: vk });
    await h.send("Input.dispatchKeyEvent", { type: "keyUp", key: name, code, windowsVirtualKeyCode: vk });
  };
  out.pulse = {};
  await h.eval(`applyScreen("stops"); document.getElementById("select-destination-stop").disabled = true; true`); await wait(80);
  out.pulse.selectDisabled = await h.eval(`${ANIM}("select-destination-stop")`);
  await h.eval(`document.getElementById("select-destination-stop").disabled = false; true`); await wait(80);
  out.pulse.selectEnabled = await h.eval(`${ANIM}("select-destination-stop")`);
  out.pulse.samples = [];
  for (let i = 0; i < 6; i++) {
    out.pulse.samples.push(await h.eval(`${ANIM}("select-destination-stop")`));
    await wait(350);
  }
  // pressed: the button is held down with the mouse
  await h.eval(`document.getElementById("select-destination-stop").scrollIntoView({ block: "center" }); true`);
  const rect = await h.eval(`(function () { var r = document.getElementById("select-destination-stop").getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
  await h.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: rect[0], y: rect[1] });
  await h.send("Input.dispatchMouseEvent", { type: "mousePressed", x: rect[0], y: rect[1], button: "left", clickCount: 1 });
  await wait(80);
  out.pulse.pressed = await h.eval(`${ANIM}("select-destination-stop")`);
  await h.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 2, y: 2 });  // let go away from the button: no click
  await h.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: 2, y: 2, button: "left", clickCount: 1 });
  await h.eval(`document.activeElement && document.activeElement.blur(); true`); await wait(80);
  out.pulse.afterRelease = await h.eval(`${ANIM}("select-destination-stop")`);
  // keyboard focus: Tab until the button has the focus
  await h.eval(`document.body.focus(); true`);
  for (let i = 0; i < 80; i++) {
    await key("Tab", "Tab", 9);
    if (await h.eval(`!!document.activeElement && document.activeElement.id === "select-destination-stop"`)) break;
  }
  await wait(80);
  out.pulse.keyboardFocus = await h.eval(`${ANIM}("select-destination-stop")`);
  await h.eval(`document.activeElement.blur(); true`); await wait(80);
  out.pulse.afterBlur = await h.eval(`${ANIM}("select-destination-stop")`);

  await h.eval(`applyScreen("confirm"); true`); await wait(80);
  out.pulse.confirm = await h.eval(`${ANIM}("confirm-destination-stop")`);
  await h.eval(`document.getElementById("confirm-destination-stop").disabled = true; true`); await wait(80);
  out.pulse.confirmDisabled = await h.eval(`${ANIM}("confirm-destination-stop")`);
  await h.eval(`document.getElementById("confirm-destination-stop").disabled = false; true`);
  await h.eval(`applyScreen("journey"); document.getElementById("start-journey").disabled = true; true`); await wait(80);
  out.pulse.startDisabled = await h.eval(`${ANIM}("start-journey")`);
  await h.eval(`document.getElementById("start-journey").disabled = false; true`); await wait(80);
  out.pulse.start = await h.eval(`${ANIM}("start-journey")`);
  // Find my route on Home: the same shared class, the same animation, none while disabled
  await h.eval(`applyScreen("home"); destinationInput.value = ""; applyArriveValue("", "arrive-none"); arriveByPicked = false; syncSearchReadiness(); true`); await wait(80);
  out.pulse.findDisabled = await h.eval(`${ANIM}("find-route")`);
  await h.eval(`destinationInput.value = "x"; arriveByPicked = true; syncSearchReadiness(); true`); await wait(80);
  out.pulse.find = await h.eval(`${ANIM}("find-route")`);
  out.pulse.classes = await h.eval(`["find-route", "select-destination-stop", "confirm-destination-stop", "start-journey", "see-arrivals"].map(function (id) { return [id, document.getElementById(id).classList.contains("pulse-button")]; })`);
  await h.eval(`destinationInput.value = ""; arriveByPicked = false; syncSearchReadiness(); true`);
  await h.eval(`applyScreen("live"); document.getElementById("see-arrivals-bar").hidden = true; true`); await wait(80);
  out.pulse.seeHidden = await h.eval(`${ANIM}("see-arrivals")`);
  await h.eval(`document.getElementById("see-arrivals-bar").hidden = false; true`); await wait(80);
  out.pulse.see = await h.eval(`${ANIM}("see-arrivals")`);

  // reduced motion: no animation at all
  await h.send("Emulation.setEmulatedMedia", { features: [
    { name: "prefers-reduced-motion", value: "reduce" },
    { name: "prefers-color-scheme", value: c.dark ? "dark" : "light" }
  ] });
  await wait(200);
  out.pulse.reduced = await h.eval(`${ANIM}("see-arrivals")`);
  await h.eval(`applyScreen("home"); destinationInput.value = "x"; arriveByPicked = true; syncSearchReadiness(); true`); await wait(80);
  out.pulse.reducedFind = await h.eval(`${ANIM}("find-route")`);
  await h.eval(`destinationInput.value = ""; arriveByPicked = false; syncSearchReadiness(); true`);
  await h.send("Emulation.setEmulatedMedia", { features: [
    { name: "prefers-reduced-motion", value: "no-preference" },
    { name: "prefers-color-scheme", value: c.dark ? "dark" : "light" }
  ] });

  // the leave dialog: Stay is Save's look, Leave is Cancel's look, Stay has the focus
  const BTN = `(function (el) {
    var s = getComputedStyle(el), r = el.getBoundingClientRect();
    return { text: el.textContent.trim(), color: s.color, background: s.backgroundColor, border: s.borderTopColor, borderWidth: s.borderTopWidth,
      borderStyle: s.borderTopStyle, radius: s.borderTopLeftRadius, fontSize: s.fontSize, fontWeight: s.fontWeight,
      paddingLeft: s.paddingLeft, paddingTop: s.paddingTop, h: Math.round(r.height * 10) / 10, w: Math.round(r.width * 10) / 10 };
  })`;
  await h.eval(`applyScreen("home"); true`);
  await h.eval(`document.querySelector('[data-saved-action="add"]').click(); true`);
  out.panelButtons = await h.eval(`Array.prototype.map.call(document.querySelectorAll("#saved-panel .saved-panel__actions button"), ${BTN})`);
  out.panelCard = await h.eval(`getComputedStyle(document.getElementById("saved-panel")).backgroundColor`);
  await h.eval(`Array.prototype.filter.call(document.querySelectorAll("#saved-panel button"), function (b) { return b.textContent.trim() === "Cancel"; })[0].click(); true`);
  await h.eval(`openLeaveDialog(); true`); await wait(60);
  out.dialog = await h.eval(`({ hidden: document.getElementById("leave-dialog").hidden,
    buttons: [document.getElementById("leave-stay"), document.getElementById("leave-leave")].map(${BTN}),
    focus: document.activeElement && document.activeElement.id, order: Array.prototype.map.call(document.querySelectorAll("#leave-dialog button"), function (b) { return b.id; }),
    background: getComputedStyle(document.getElementById("leave-dialog")).backgroundColor,
    labels: Array.prototype.map.call(document.querySelectorAll("#leave-dialog button"), function (b) { return b.textContent.trim(); }),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })`);
  await h.eval(`closeLeaveDialog(); true`);

  // every nearby stop is listed, in order, with no note: a bus stop with no direct bus is a row like any other
  await h.eval(`applyScreen("stops"); true`);
  out.stops = await h.eval(`(function () {
    selectedDestination = { latitude: 1.3, longitude: 103.8, label: "Test place", label_display: "Test place" };
    var cands = [
      { stop_code: "S1", stop_name: "Alpha Road", lat: 1.3001, lon: 103.8, distance_m: 100, walk_minutes: 2, kind: "bus", is_reachable: true },
      { stop_code: "S2", stop_name: "Beta Road", lat: 1.3002, lon: 103.8, distance_m: 220, walk_minutes: 3, kind: "bus", is_reachable: false },
      { stop_code: "S3", stop_name: "Gamma Station", lat: 1.3003, lon: 103.8, distance_m: 330, walk_minutes: 5, kind: "station", station_mode: "MRT", lines: [{ code: "NS", name: "North-South Line" }] },
      { stop_code: "S4", stop_name: "Delta Road", lat: 1.3004, lon: 103.8, distance_m: 440, walk_minutes: 6, kind: "bus", is_reachable: false },
      { stop_code: "S5", stop_name: "Echo Road", lat: 1.3005, lon: 103.8, distance_m: 550, walk_minutes: 7, kind: "bus", is_reachable: true }
    ];
    renderDestinationStops({ candidates: cands, reachable_stops: [], unreachable_stops: [] });
    var rows = Array.prototype.map.call(document.querySelectorAll("#reachable-stops .dest-stop-row"), function (row) {
      var r = row.getBoundingClientRect();
      return { code: row.getAttribute("data-stop-code"), cls: row.className, text: row.textContent.replace(/\\s+/g, " ").trim(),
        h: Math.round(r.height * 10) / 10, note: !!row.querySelector(".dest-stop-row__note"), pill: !!row.querySelector(".pill--best"),
        metas: row.querySelectorAll(".dest-stop-row__meta").length };
    });
    return { rows: rows, order: destStopOrder.slice(), selected: selectedDestinationStop ? selectedDestinationStop.stop_code : null,
      scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
  })()`);

  // the destination rows carry the green flag
  await h.eval(`applyScreen("home"); true`);
  await h.eval(`(function () { var f = window.fetch; window.fetch = function (input, init) { var url = typeof input === "string" ? input : input.url;
    if (url.indexOf("/api/destinations?") === 0) { return Promise.resolve(new Response(JSON.stringify({ status: "ok", results: [
      { id: "a", label: "National University of Singapore", address: "21 Lower Kent Ridge Road", label_display: "National University of Singapore", address_display: "21 Lower Kent Ridge Road", latitude: 1.2966, longitude: 103.7764 },
      { id: "b", label: "Orchard Road Mall", address: "Orchard Road", label_display: "Orchard Road Mall", address_display: "Orchard Road", latitude: 1.304, longitude: 103.83 }
    ] }), { status: 200, headers: { "Content-Type": "application/json" } })); }
    return f.call(window, input, init); }; })(); true`);
  await h.eval(`applyArriveValue("", "arrive-none"); destinationInput.value = "nus"; destinationInput.dispatchEvent(new Event("input", { bubbles: true })); destinationForm.requestSubmit(); true`);
  await h.until(`document.querySelectorAll("#destination-results .place-tile").length > 1`, 8000, "the destination rows");
  out.rows = await h.eval(`Array.prototype.map.call(document.querySelectorAll("#destination-results .place-tile"), function (tile) {
    var s = getComputedStyle(tile), icon = tile.querySelector("svg");
    return { path: icon ? icon.querySelector("path").getAttribute("d") : "", color: getComputedStyle(icon).color, background: s.backgroundColor,
      hidden: tile.getAttribute("aria-hidden"), title: tile.parentNode.querySelector(".place-row__title").textContent.trim() };
  })`);
  out.markerEnd = await h.eval(`getComputedStyle(document.documentElement).getPropertyValue("--marker-end").trim()`);
  return out;
}

import { openHome } from "./common.mjs";

// The first-run explainer on the real Home page. config: width, height, dark, mode ("normal" or "blocked": storage throws).
const READ = `(function () {
  var box = document.getElementById("first-run");
  function rect(el) { var r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }
  var shown = !!box && !box.hidden && getComputedStyle(box).display !== "none";
  var active = document.activeElement;
  var buttons = Array.prototype.map.call(box.querySelectorAll("button"), function (b) {
    return { id: b.id, hidden: b.hidden, text: b.textContent.trim(), h: b.hidden ? 0 : b.getBoundingClientRect().height, w: b.hidden ? 0 : b.getBoundingClientRect().width };
  });
  var flag = null;
  try { flag = window.localStorage.getItem("bus-catch-first-run-v1"); } catch (e) { flag = "blocked"; }
  var header = document.querySelector("header");
  var main = document.querySelector("main");
  return {
    shown: shown, step: document.getElementById("first-run-step").textContent, text: document.getElementById("first-run-text").textContent,
    icon: !!document.querySelector("#first-run-icon svg"), buttons: buttons, active: active ? active.id || active.tagName : null,
    inside: !!(active && box.contains(active)), flag: flag, bodyClass: document.body.classList.contains("is-first-run"),
    card: shown ? rect(document.querySelector(".first-run__card")) : null,
    header: header ? rect(header) : null, main: main ? rect(main) : null,
    requests: __requests.length, scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    menuHidden: document.getElementById("menu-sheet").hasAttribute("hidden"),
    api: { done: window.FirstRun.isDone(), storage: window.FirstRun.storageAvailable() }
  };
})()`;

async function key(h, name, shift = false) {
  await h.send("Input.dispatchKeyEvent", { type: "keyDown", key: name, code: name, windowsVirtualKeyCode: name === "Tab" ? 9 : 27, modifiers: shift ? 8 : 0 });
  await h.send("Input.dispatchKeyEvent", { type: "keyUp", key: name, code: name, windowsVirtualKeyCode: name === "Tab" ? 9 : 27, modifiers: shift ? 8 : 0 });
  await h.sleep(120);
}

export default async function (h) {
  const c = h.config;
  const out = {};
  const blocked = c.mode === "blocked";
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "none", firstRun: true, blockStorage: blocked });
  await h.until("(function () { var b = document.getElementById('first-run'); return !!b && !b.hidden; })()", 8000, "the first-run card");
  await h.sleep(200);
  out.opened = await h.eval(READ);
  // keyboard: Tab and Shift+Tab stay inside the card
  out.tabs = [];
  for (let i = 0; i < 4; i++) { await key(h, "Tab"); out.tabs.push(await h.eval("document.activeElement.id")); }
  await key(h, "Tab", true);
  out.shiftTab = await h.eval("document.activeElement.id");
  // Next, Next, Done with the keyboard-activated buttons
  await h.eval("document.getElementById('first-run-next').click(); true");
  out.step2 = await h.eval(READ);
  await h.eval("document.getElementById('first-run-next').click(); true");
  out.step3 = await h.eval(READ);
  await h.eval("document.getElementById('first-run-next').click(); true");
  await h.sleep(150);
  out.afterDone = await h.eval(READ);
  if (!blocked) {
    // a reload on this phone: the flag is set, so the card does not come back
    await h.eval("location.reload(); true");
    await h.sleep(1800);
    out.reloaded = await h.eval(READ);
  }
  // reopen from the menu, and close with Escape
  await h.eval("document.getElementById('menu-open').click(); true");
  await h.sleep(100);
  out.menuOpen = await h.eval(READ);
  await h.eval("document.getElementById('how-it-works').click(); true");
  await h.sleep(150);
  out.reopened = await h.eval(READ);
  await key(h, "Escape");
  out.afterEscape = await h.eval(READ);
  // the menu row reopens it any number of times; Skip closes it and keeps the flag
  await h.eval("document.getElementById('menu-open').click(); document.getElementById('how-it-works').click(); true");
  await h.sleep(100);
  await h.eval("document.getElementById('first-run-skip').click(); true");
  out.afterSkip = await h.eval(READ);
  if (!blocked) {
    // Demo Mode never shows the card, whatever the flag says
    await h.eval("firstRunDecided = false; decideFirstRun(true); true");
    out.demo = await h.eval(READ);
    // a fresh phone: remove the flag and reload; the card is back, and Skip on the first step sets the flag
    await h.eval("window.localStorage.removeItem('bus-catch-first-run-v1'); location.reload(); true");
    await h.until("(function () { var b = document.getElementById('first-run'); return !!b && !b.hidden; })()", 10000, "the card after a reset");
    out.fresh = await h.eval(READ);
    await h.eval("document.getElementById('first-run-skip').click(); true");
    out.skipFlag = await h.eval(READ);
  }
  return out;
}

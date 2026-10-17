import { openHome } from "./common.mjs";

// The approved Home design (tmp/design/home-v2.html) in the real page: the four states (empty, saved, edit, add panel),
// the animated hero and its reduced-motion still frame, the tap targets and the colours. The destination search is
// answered in the page (no OneMap call). config: width, dark.

const PLACES = [
  { id: "r1", label: "Home Sweet Home", address: "1 Home Road", latitude: 1.29667, longitude: 103.77639 },
  { id: "r2", label: "National University of Singapore", address: "21 Lower Kent Ridge Road", latitude: 1.30421, longitude: 103.83197 }
];

const HELPERS = `
  window.__text = function (el) { return el ? el.textContent.replace(/\\s+/g, " ").trim() : null; };
  window.__type = function (id, value) {
    var input = document.getElementById(id); input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true })); return input.value; };
  window.__button = function (scope, text) {
    return Array.prototype.filter.call(document.querySelectorAll(scope + " button"), function (b) {
      return __text(b) === text; })[0] || null; };
  window.__stub = function (places) {
    var realFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : input.url;
      if (url.indexOf("/api/destinations?") === 0) {
        var results = places.map(function (p) { return { id: p.id, label: p.label, address: p.address,
          label_display: p.label, address_display: p.address, latitude: p.latitude, longitude: p.longitude }; });
        return Promise.resolve(new Response(JSON.stringify({ status: "ok", results: results }),
          { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return realFetch.call(window, input, init); }; };
  true;`;

const GEOMETRY = `(function () {
  var top = function (selector) {
    var el = document.querySelector(selector);
    return el ? Math.round((el.getBoundingClientRect().top + window.scrollY) * 10) / 10 : null;
  };
  return {
    hero: top(".hero"), heading: top("#destination-heading"), search: top(".search-row"), row: top("#quick-picks"),
    location: top("#location-status"), arrive: top("#arrive-by-wrap"),
    locationBox: (function () {
      var el = document.getElementById("location-status"), cs = getComputedStyle(el), r = el.getBoundingClientRect();
      var title = document.querySelector("#location-status .info-row__title").getBoundingClientRect();
      return { h: Math.round(r.height * 10) / 10, w: Math.round(r.width * 10) / 10, titleTop: Math.round((title.top - r.top) * 10) / 10,
        titleLeft: Math.round((title.left - r.left) * 10) / 10 };
    })(),
    searchGap: (function () {
      var chip = document.querySelector("#quick-picks .quick-pick");
      return Math.round((chip.getBoundingClientRect().top - document.querySelector(".search-row").getBoundingClientRect().bottom) * 10) / 10;
    })(),
    savedGap: (function () {
      var rect = function (el) { return el.getBoundingClientRect(); };
      var parts = [document.getElementById("quick-picks")].concat(Array.prototype.slice.call(document.getElementById("saved-places").children).filter(function (el) { return el.getClientRects().length > 0; }));
      var last = parts.reduce(function (a, b) { return rect(b).bottom > rect(a).bottom ? b : a; });
      return Math.round((rect(document.getElementById("location-status")).top - rect(last).bottom) * 10) / 10;
    })(),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    heroHeight: document.querySelector(".hero").getBoundingClientRect().height
  };
})()`;

const CONTROLS = `(function () {
  var size = function (el) {
    var r = el.getBoundingClientRect();
    return { text: __text(el), w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 };
  };
  var out = { chips: Array.prototype.map.call(document.querySelectorAll("#quick-picks .quick-pick"), size) };
  ["#find-route", "#arrive-by-field", "#destination"].forEach(function (s) { out[s] = size(document.querySelector(s)); });
  var panel = document.getElementById("saved-panel");
  out.panel = panel.hidden ? [] : Array.prototype.filter.call(panel.querySelectorAll("button, input"), function (el) {
    return el.getClientRects().length > 0;
  }).map(size);
  return out;
})()`;

const HERO_MOTION = `(function () {
  var name = function (selector) {
    var el = document.querySelector(selector);
    var style = getComputedStyle(el);
    return { name: style.animationName, duration: style.animationDuration, count: style.animationIterationCount };
  };
  var inside = function (selector) {
    var hero = document.querySelector(".hero__art").getBoundingClientRect();
    var r = document.querySelector(selector).getBoundingClientRect();
    return r.left >= hero.left - 0.5 && r.right <= hero.right + 0.5 && r.top >= hero.top - 0.5 && r.bottom <= hero.bottom + 0.5;
  };
  var svg = document.querySelector(".hero__art");
  return {
    bus: name(".hero-move--bus"), train: name(".hero-move--train"), tree: name(".hero-tree"), cloud: name(".hero-cloud"),
    heading: name("#destination-heading"),
    busInside: inside(".hero-move--bus .hero-bus__body"), trainInside: inside(".hero-move--train .hero-train__body"),
    ariaHidden: svg.getAttribute("aria-hidden"), focusable: svg.getAttribute("focusable"),
    interactive: svg.querySelectorAll("a, button, input, select, textarea, [tabindex], [onclick]").length,
    styleAttrs: svg.querySelectorAll("[style]").length + (svg.hasAttribute("style") ? 1 : 0),
    parentHidden: !!svg.closest("[aria-hidden='true']") || svg.getAttribute("aria-hidden") === "true"
  };
})()`;

async function addPlace(h, index, name) {
  await h.eval(`document.querySelector('[data-saved-action="add"]').click(); true`);
  await h.eval(`__type("saved-search", "x"); document.querySelector("#saved-panel form").requestSubmit(); true`);
  await h.until(`document.querySelectorAll("#saved-panel .saved-panel__choose").length > ${index}`, 5000, "add results");
  await h.eval(`document.querySelectorAll("#saved-panel .saved-panel__choose")[${index}].click(); true`);
  await h.eval(`__type("saved-name", ${JSON.stringify(name)}); __button("#saved-panel", "Save").click(); true`);
  await h.sleep(250);
}

export default async function (h) {
  const c = h.config;
  const out = { states: {} };
  await openHome(h, { dark: c.dark, width: c.width || 360, height: 800, permission: "granted" });
  await h.eval(HELPERS);
  await h.eval(`__stub(${JSON.stringify(PLACES)}); localStorage.removeItem("bus-catch-saved-places-v1"); renderSavedPlaces(); true`);
  out.states.empty = { geometry: await h.eval(GEOMETRY), controls: await h.eval(CONTROLS) };
  out.motion = await h.eval(HERO_MOTION);

  await addPlace(h, 0, "Home");
  await addPlace(h, 1, "School");
  out.states.saved = { geometry: await h.eval(GEOMETRY), controls: await h.eval(CONTROLS) };
  await h.eval(`document.querySelector('[data-saved-action="toggle-edit"]').click(); true`);
  out.states.edit = { geometry: await h.eval(GEOMETRY), controls: await h.eval(CONTROLS) };
  await h.eval(`document.querySelector('[data-saved-action="toggle-edit"]').click(); true`);
  await h.eval(`document.querySelector('[data-saved-action="add"]').click(); true`);
  out.states.add = { geometry: await h.eval(GEOMETRY), controls: await h.eval(CONTROLS) };
  await h.eval(`__button("#saved-panel", "Cancel").click(); true`);

  // Find my route keeps its bar and pulses once when it becomes ready (a class, never a script style)
  out.find = await h.eval(`(function () {
    var button = document.getElementById("find-route");
    var r = document.querySelector(".home-footer").getBoundingClientRect();
    return { disabled: button.getAttribute("aria-disabled"), ready: button.classList.contains("is-ready"),
             footerHeight: Math.round(r.height), opacity: getComputedStyle(button).opacity };
  })()`);

  // colours: the tokens as the page resolves them in this theme
  out.tokens = await h.eval(`(function () {
    var root = getComputedStyle(document.documentElement);
    var get = function (name) { return root.getPropertyValue(name).trim(); };
    var pick = function (selector, prop) { return getComputedStyle(document.querySelector(selector))[prop]; };
    return {
      g: [get("--heading-g1"), get("--heading-g2"), get("--heading-g3"), get("--heading-g4")],
      card: get("--color-card"), ink: get("--color-ink"),
      tint: get("--tint-neutral"), secondary: get("--color-secondary"), link: get("--color-link"),
      locationMeta: pick("#location-state", "color"), locationBg: pick("#location-status", "backgroundColor"),
      arriveTitle: pick("#arrive-by-wrap .info-row__title", "color"), arriveBg: pick("#arrive-by-wrap", "backgroundColor"),
      selectColor: pick("#arrive-by-field", "color"), selectBg: pick("#arrive-by-field", "backgroundColor"),
      selectBorder: pick("#arrive-by-field", "borderTopColor"), selectBorderWidth: pick("#arrive-by-field", "borderTopWidth"),
      searchBorder: pick(".search-row .field__shell", "borderTopColor"), searchBorderWidth: pick(".search-row .field__shell", "borderTopWidth"),
      searchBg: pick(".search-row .field__shell", "backgroundColor"),
      requiredColor: pick("#arrive-required-tag", "color"), requiredBorder: pick("#arrive-required-tag", "borderTopColor"),
      headingFill: pick("#destination-heading", "webkitTextFillColor"),
      headerBg: pick(".app-header", "backgroundColor"),
      brandBg: pick("#home-button", "backgroundColor"), brandColor: pick("#home-button", "color"),
      menuBg: pick("#menu-open", "backgroundColor"), menuColor: pick("#menu-open", "color"),
      menuBorder: pick("#menu-open", "borderTopColor"), menuBorderWidth: pick("#menu-open", "borderTopWidth"),
      menuIcon: pick("#menu-open .icon", "color"),
      paper: getComputedStyle(document.body).backgroundColor, pageCard: pick("#search-card", "backgroundColor"),
      locationBorderWidth: pick("#location-status", "borderTopWidth"), locationBorderStyle: pick("#location-status", "borderTopStyle"),
      locationRadius: pick("#location-status", "borderTopLeftRadius"),
      locationPadding: ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"].map(function (k) { return pick("#location-status", k); }),
      locationFill: pick("#location-status", "backgroundColor"),
      arriveBorderWidth: pick("#arrive-by-wrap", "borderTopWidth"), arriveBorderStyle: pick("#arrive-by-wrap", "borderTopStyle"),
      arriveRadius: pick("#arrive-by-wrap", "borderTopLeftRadius"),
      arrivePadding: ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"].map(function (k) { return pick("#arrive-by-wrap", k); }),
      pinColor: pick("#location-status .icon-tile--start", "color"), pinTile: pick("#location-status .icon-tile--start", "backgroundColor"),
      dot: pick("#location-status .status-dot--ok", "backgroundColor"), dotShown: pick("#location-status .status-dot--ok", "display"),
      locationTitle: pick("#location-status .info-row__title", "color")
    };
  })()`);

  out.header = await h.eval(`(function () {
    var box = function (selector) {
      var r = document.querySelector(selector).getBoundingClientRect();
      return { w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 };
    };
    var menu = document.getElementById("menu-open");
    return { title: document.title, brand: __text(document.getElementById("home-button")),
             brandLabel: document.getElementById("home-button").getAttribute("aria-label"),
             menu: box("#menu-open"), brandBox: box("#home-button"), menuName: __text(menu),
             menuExpanded: menu.getAttribute("aria-expanded") };
  })()`);

  // the delete question and the add panel's buttons, side by side
  const BUTTON = `function (el) {
    var s = getComputedStyle(el), r = el.getBoundingClientRect();
    return { text: __text(el), color: s.color, background: s.backgroundColor, border: s.borderTopColor,
             borderWidth: s.borderTopWidth, borderStyle: s.borderTopStyle, radius: s.borderTopLeftRadius,
             fontSize: s.fontSize, fontWeight: s.fontWeight, paddingLeft: s.paddingLeft, h: Math.round(r.height * 10) / 10 };
  }`;
  await h.eval(`document.querySelector('[data-saved-action="toggle-edit"]').click(); true`);
  await h.eval(`document.querySelector('.saved-chip__badge').click(); true`);
  out.deleteQuestion = await h.eval(`(function () {
    var read = ${BUTTON};
    var buttons = Array.prototype.slice.call(document.querySelectorAll("#saved-panel .saved-panel__actions button"));
    return { order: buttons.map(__text), buttons: buttons.map(read), focus: __text(document.activeElement),
             title: __text(document.querySelector("#saved-panel .saved-panel__title")) };
  })()`);
  await h.eval(`__button("#saved-panel", "Cancel").click(); true`);
  await h.eval(`document.querySelector('[data-saved-action="toggle-edit"]').click(); true`);
  await h.eval(`document.querySelector('[data-saved-action="add"]').click(); true`);
  out.addPanel = await h.eval(`(function () {
    var read = ${BUTTON};
    var buttons = Array.prototype.slice.call(document.querySelectorAll("#saved-panel .saved-panel__actions button"));
    return { buttons: buttons.map(read),
             pick: document.getElementById("saved-panel").textContent.indexOf("Pick a place from the results") };
  })()`);
  await h.eval(`__button("#saved-panel", "Cancel").click(); true`);

  // reduced motion: every animation is none and the bus and the train are still in view
  await h.send("Emulation.setEmulatedMedia", { features: [
    { name: "prefers-reduced-motion", value: "reduce" },
    { name: "prefers-color-scheme", value: c.dark ? "dark" : "light" }
  ] });
  await h.sleep(300);
  out.reduced = await h.eval(HERO_MOTION);
  out.reducedFind = await h.eval(`getComputedStyle(document.getElementById("find-route")).animationName`);
  return out;
}

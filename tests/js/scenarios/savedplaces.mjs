import { openHome } from "./common.mjs";

// Saved places on Home, driven in the real page. The destination search is answered in the page (no OneMap call); every
// other request goes to the real test app. config: width, height, dark, mode ("flow" | "layout" | "storage").
// The page's own network log (__sent, from the test prelude) is read at the end: nothing there may carry a saved name or
// coordinate except the destination-stops request a tap makes (the same one a picked search result makes).

const PLACES = [
  { id: "r1", label: "National University of Singapore", address: "21 Lower Kent Ridge Road", latitude: 1.29667, longitude: 103.77639 },
  { id: "r2", label: "Orchard Road", address: "Orchard Road, Singapore", latitude: 1.30421, longitude: 103.83197 },
  { id: "r3", label: "Changi Airport", address: "Airport Boulevard", latitude: 1.35711, longitude: 103.98905 },
  { id: "r4", label: "Marina Bay Sands", address: "10 Bayfront Avenue", latitude: 1.28349, longitude: 103.86026 },
  { id: "r5", label: "Botanic Gardens", address: "1 Cluny Road", latitude: 1.31386, longitude: 103.81589 },
  { id: "r6", label: "Sentosa", address: "Sentosa Island", latitude: 1.24940, longitude: 103.83030 }
];

const HELPERS = `
  window.__spText = function (el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; };
  window.__spShown = function (el) { return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; };
  window.__spRow = function () {
    return Array.prototype.map.call(document.querySelectorAll("#quick-picks > *"), function (node) {
      var main = node.classList.contains("saved-chip") ? node.querySelector(".saved-chip__main") : node;
      return { text: __spText(node.classList.contains("saved-chip") ? node.querySelector(".saved-chip__name") : node),
               label: main.getAttribute("aria-label"), saved: node.classList.contains("saved-chip") };
    });
  };
  window.__spType = function (id, value) {
    var input = document.getElementById(id);
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return input.value;
  };
  window.__spButton = function (scope, text) {
    return Array.prototype.filter.call(document.querySelectorAll(scope + " button"), function (b) {
      return __spText(b) === text;
    })[0] || null;
  };
  window.__spStub = function (places) {
    var realFetch = window.fetch;
    window.__spSearches = [];
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : input.url;
      if (url.indexOf("/api/destinations?") === 0) {
        window.__spSearches.push(url);
        var results = places.map(function (p) {
          return { id: p.id, label: p.label, address: p.address, label_display: p.label, address_display: p.address,
                   latitude: p.latitude, longitude: p.longitude };
        });
        return Promise.resolve(new Response(JSON.stringify({ status: "ok", results: results }),
          { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return realFetch.call(window, input, init);
    };
  };
  true;
`;

async function addPlace(h, query, index, name) {
  await h.eval(`__spButton("#quick-picks", "+").click(); true`);
  await h.eval(`__spType("saved-search", ${JSON.stringify(query)});
    document.querySelector("#saved-panel form").requestSubmit(); true`);
  await h.until(`document.querySelectorAll("#saved-panel .saved-panel__choose").length > ${index}`, 5000, "the add results");
  await h.eval(`document.querySelectorAll("#saved-panel .saved-panel__choose")[${index}].click(); true`);
  const typed = await h.eval(`__spType("saved-name", ${JSON.stringify(name)})`);
  await h.eval(`__spButton("#saved-panel", "Save").click(); true`);
  return typed;
}

const SNAP = `(function () {
  var panel = document.getElementById("saved-panel");
  return {
    row: __spRow(),
    count: __spShown(document.getElementById("saved-places-count")) ? __spText(document.getElementById("saved-places-count")) : null,
    note: __spText(document.getElementById("saved-places-note")),
    noteShown: getComputedStyle(document.getElementById("saved-places-note")).visibility !== "hidden",
    toggle: __spText(document.querySelector('#quick-picks [data-saved-action="toggle-edit"]')),
    layout: (function () {
      var rect = function (el) { var r = el.getBoundingClientRect(); return { top: r.top, height: r.height }; };
      var hair = document.querySelector("#saved-places + hr");
      return { row: rect(document.getElementById("quick-picks")), note: rect(document.getElementById("saved-places-note")),
               places: rect(document.getElementById("saved-places")), below: hair ? rect(hair) : null };
    })(),
    storage: __spShown(document.getElementById("saved-places-storage")) ? __spText(document.getElementById("saved-places-storage")) : null,
    panel: __spShown(panel) ? __spText(panel) : null,
    error: __spShown(panel.querySelector(".saved-panel__error")) ? __spText(panel.querySelector(".saved-panel__error")) : null,
    stored: localStorageSafe(),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

const STORAGE_READ = `
  window.localStorageSafe = function () {
    try { return localStorage.getItem("bus-catch-saved-places-v1"); } catch (error) { return "unavailable"; }
  };
  true;
`;

export default async function (h) {
  const c = h.config;
  const out = { steps: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(HELPERS);
  await h.eval(STORAGE_READ);
  await h.eval(`__spStub(${JSON.stringify(PLACES)}); localStorage.removeItem("bus-catch-saved-places-v1"); renderSavedPlaces(); true`);

  if (c.mode === "storage") {
    // private mode: reading storage throws, so the feature works for the session and says so once
    await h.eval(`Object.defineProperty(window, "localStorage", { get: function () { throw new Error("denied"); }, configurable: true }); renderSavedPlaces(); true`);
    out.steps.empty = await h.eval(SNAP);
    await addPlace(h, "NUS", 0, "School");
    out.steps.firstSave = await h.eval(SNAP);
    await addPlace(h, "Orchard", 1, "Shops");
    out.steps.secondSave = await h.eval(SNAP);
    return out;
  }

  out.steps.empty = await h.eval(SNAP);

  // add: the name is typed by the user, trimmed and capped at 24, and the picked place shows under the field
  await h.eval(`__spButton("#quick-picks", "+").click(); true`);
  out.steps.addOpen = await h.eval(SNAP);
  await h.eval(`__spType("saved-search", "NUS"); document.querySelector("#saved-panel form").requestSubmit(); true`);
  await h.until(`document.querySelectorAll("#saved-panel .saved-panel__choose").length > 0`, 5000, "the add results");
  out.steps.noPickSave = await h.eval(`(function () { __spButton("#saved-panel", "Save").click(); return ${SNAP}; })()`);
  await h.eval(`document.querySelectorAll("#saved-panel .saved-panel__choose")[0].click(); true`);
  out.steps.picked = await h.eval(`({ picked: __spText(document.querySelector(".saved-panel__picked")),
    nameShown: __spShown(document.getElementById("saved-name")), focus: document.activeElement.id,
    maxLength: document.getElementById("saved-name").maxLength })`);
  out.steps.emptyName = await h.eval(`(function () { __spType("saved-name", "   "); __spButton("#saved-panel", "Save").click(); return ${SNAP}; })()`);
  out.steps.longTyped = await h.eval(`__spType("saved-name", "  A very long name for a place that is far too long  ")`);
  out.steps.longRefused = await h.eval(`(function () { __spButton("#saved-panel", "Save").click(); return ${SNAP}; })()`);
  await h.eval(`__spType("saved-name", "  Uni  "); __spButton("#saved-panel", "Save").click(); true`);
  out.steps.afterFirst = await h.eval(SNAP);

  // the same place again is refused with a short message
  await h.eval(`__spButton("#quick-picks", "+").click();
    __spType("saved-search", "NUS"); document.querySelector("#saved-panel form").requestSubmit(); true`);
  await h.until(`document.querySelectorAll("#saved-panel .saved-panel__choose").length > 0`, 5000, "the add results");
  await h.eval(`document.querySelectorAll("#saved-panel .saved-panel__choose")[0].click();
    __spType("saved-name", "Again"); __spButton("#saved-panel", "Save").click(); true`);
  out.steps.duplicate = await h.eval(SNAP);
  await h.eval(`__spButton("#saved-panel", "Cancel").click(); true`);

  // four more, to the limit: order of adding, no "+", the count note
  await addPlace(h, "Orchard", 1, "Shops");
  await addPlace(h, "Changi", 2, "Grandmother's flat Bedok");
  await addPlace(h, "Marina", 3, "Work");
  out.steps.four = await h.eval(SNAP);
  const CONTROLS = `(function () {
    function look(el) {
      if (!el) { return null; }
      var c = getComputedStyle(el), r = el.getBoundingClientRect();
      return { text: __spText(el), label: el.getAttribute("aria-label"), borderStyle: c.borderTopStyle,
               borderColor: c.borderTopColor, borderWidth: c.borderTopWidth, color: c.color,
               background: c.backgroundColor, height: r.height, width: r.width, visible: __spShown(el),
               pressed: el.getAttribute("aria-pressed") };
    }
    return { add: look(document.querySelector('#quick-picks [data-saved-action="add"]')),
             toggle: look(document.querySelector('#quick-picks [data-saved-action="toggle-edit"]')),
             saved: look(document.querySelector("#quick-picks .saved-chip__main")) };
  })()`;
  out.steps.controlsNormal = await h.eval(CONTROLS);
  await h.eval(`__spButton("#quick-picks", "Edit").click(); true`);
  out.steps.controlsEditing = await h.eval(CONTROLS);
  await h.eval(`__spButton("#quick-picks", "Done").click(); true`);
  out.steps.controlsBack = await h.eval(CONTROLS);
  await addPlace(h, "Botanic", 4, "Park");
  out.steps.five = await h.eval(SNAP);
  out.steps.fiveLayout = await h.eval(`(function () {
    var chips = Array.prototype.slice.call(document.querySelectorAll("#quick-picks button"));
    var names = Array.prototype.slice.call(document.querySelectorAll(".saved-chip__name"));
    return { minHeight: Math.min.apply(null, chips.map(function (b) { return b.getBoundingClientRect().height; })),
             maxRight: Math.max.apply(null, chips.map(function (b) { return b.getBoundingClientRect().right; })),
             truncated: names.map(function (n) { return n.scrollWidth > n.clientWidth; }),
             ellipsis: names.map(function (n) { return getComputedStyle(n).textOverflow; }),
             innerWidth: window.innerWidth };
  })()`);

  // the look in normal mode: saved chips with a green outline only, neutral add chip, chips side by side, no "..." button
  const VARS = `(function () {
    var root = getComputedStyle(document.documentElement);
    function token(name) { return root.getPropertyValue(name).trim(); }
    return { card: token("--color-card"), tint: token("--tint-success"), ink: token("--color-ink"),
             stale: token("--status-stale"), line: token("--color-line"),
             outlineSuccess: token("--color-selected-outline-success"), outlineSelected: token("--color-selected-outline"),
             live: token("--status-live") };
  })()`;
  out.steps.tokens = await h.eval(VARS);
  out.steps.look = await h.eval(`(function () {
    function css(el, prop) { return getComputedStyle(el)[prop]; }
    var saved = document.querySelector("#quick-picks .saved-chip__main");
    var add = document.querySelector('#quick-picks [data-saved-action="toggle-edit"]');  // a neutral chip (no "+" at five)
    var chips = Array.prototype.slice.call(document.querySelectorAll("#quick-picks .saved-chip"));
    var rects = chips.map(function (c) { return c.getBoundingClientRect(); });
    var gaps = [];
    for (var i = 1; i < rects.length; i += 1) {
      if (Math.abs(rects[i].top - rects[i - 1].top) < 2) { gaps.push(Math.round((rects[i].left - rects[i - 1].right) * 10) / 10); }
    }
    return { border: css(saved, "borderTopColor"), borderWidth: css(saved, "borderTopWidth"),
             background: css(saved, "backgroundColor"), color: css(saved, "color"),
             icons: saved.querySelectorAll("svg, img").length, tickNodes: document.querySelectorAll(".saved-chip__tick").length,
             name: __spText(saved.querySelector(".saved-chip__name")), nameColor: css(saved.querySelector(".saved-chip__name"), "color"),
             addColor: css(add, "color"),
             addBackground: css(add, "backgroundColor"), addBorder: css(add, "borderTopColor"),
             gaps: gaps, chipCount: chips.length, menus: document.querySelectorAll("#quick-picks .saved-chip__menu").length,
             menuButtons: Array.prototype.filter.call(document.querySelectorAll("#quick-picks button"), function (b) {
               return __spText(b) === "…" || /Rename/.test(b.getAttribute("aria-label") || ""); }).length };
  })()`);

  // a chosen saved place keeps the blue 2 px outline as an outer ring with a gap, apart from the green outline
  await h.eval(`__spButton("#quick-picks", "Work").click(); true`);
  out.steps.selected = await h.eval(`(function () {
    var chip = Array.prototype.filter.call(document.querySelectorAll("#quick-picks .saved-chip__main"), function (b) {
      return __spText(b) === "Work"; })[0];
    var style = getComputedStyle(chip);
    return { cls: chip.className, shadow: style.boxShadow, border: style.borderTopColor, pressed: chip.getAttribute("aria-pressed"),
             others: Array.prototype.filter.call(document.querySelectorAll("#quick-picks .saved-chip__main.is-selected"), function () { return true; }).length,
             width: chip.getBoundingClientRect().width };
  })()`);
  await h.eval(`__spType("destination", ""); true`);  // typing clears the chosen saved place
  out.steps.unselected = await h.eval(`(function () {
    var chip = Array.prototype.filter.call(document.querySelectorAll("#quick-picks .saved-chip__main"), function (b) {
      return __spText(b) === "Work"; })[0];
    return { cls: chip.className, pressed: chip.getAttribute("aria-pressed"), width: chip.getBoundingClientRect().width };
  })()`);

  // edit mode: a badge on each chip's upper right corner, the chip itself renames, and nothing moves
  const GEOMETRY = `Array.prototype.map.call(document.querySelectorAll("#quick-picks .saved-chip, #quick-picks > button"), function (node) {
    var r = node.getBoundingClientRect();
    return [Math.round(r.left * 10) / 10, Math.round(r.top * 10) / 10, Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10];
  })`;
  const EDIT_READ = `(function () {
    var toggle = document.querySelector('#quick-picks [data-saved-action="toggle-edit"]');
    var chips = Array.prototype.slice.call(document.querySelectorAll("#quick-picks .saved-chip"));
    var rects = chips.map(function (c) { return c.getBoundingClientRect(); });
    function hit(a, b) { return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom; }
    var badges = chips.map(function (chip, i) {
      var badge = chip.querySelector(".saved-chip__badge");
      if (!badge) { return null; }
      var box = badge.getBoundingClientRect();
      var mark = badge.querySelector(".saved-chip__badge-mark").getBoundingClientRect();
      var c = rects[i];
      return { label: badge.getAttribute("aria-label"), text: __spText(badge), tag: badge.tagName, tabindex: badge.tabIndex,
               hitWidth: box.width, hitHeight: box.height, markWidth: mark.width, markHeight: mark.height,
               dx: Math.round(((mark.left + mark.width / 2) - c.right) * 10) / 10,
               dy: Math.round(((mark.top + mark.height / 2) - c.top) * 10) / 10,
               overlapsNeighbour: rects.some(function (r, j) { return j !== i && hit(box, r); }),
               overlapsOwnChip: hit(box, c) };
    }).filter(Boolean);
    return {
      toggle: toggle ? __spText(toggle) : null, pressed: toggle ? toggle.getAttribute("aria-pressed") : null,
      badges: badges, badgeCount: document.querySelectorAll("#quick-picks .saved-chip__badge").length,
      menus: document.querySelectorAll("#quick-picks .saved-chip__menu").length,
      mains: Array.prototype.map.call(document.querySelectorAll("#quick-picks .saved-chip__main"), function (b) {
        return { label: b.getAttribute("aria-label"), action: b.getAttribute("data-saved-action"),
                 disabled: b.getAttribute("aria-disabled") }; }),
      starters: document.querySelectorAll("#quick-picks > button:not([data-saved-action])").length,
      scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
    };
  })()`;
  out.steps.normalGeometry = await h.eval(GEOMETRY);
  out.steps.normalRead = await h.eval(EDIT_READ);
  await h.eval(`__spButton("#quick-picks", "Edit").click(); true`);
  out.steps.editGeometry = await h.eval(GEOMETRY);
  out.steps.editRead = await h.eval(EDIT_READ);
  out.steps.editSnap = await h.eval(SNAP);
  out.steps.badgeFocus = await h.eval(`(function () {
    var badge = document.querySelector("#quick-picks .saved-chip__badge");
    badge.focus();
    return { focused: document.activeElement === badge, tag: document.activeElement.tagName };
  })()`);

  // in edit mode the chip name opens the rename panel (it does not select)
  await h.eval(`document.querySelectorAll("#quick-picks .saved-chip__main")[1].click(); true`);
  out.steps.edit = await h.eval(`({ panel: __spText(document.getElementById("saved-panel")),
    value: document.getElementById("saved-edit-name").value, screen: screenStack[screenStack.length - 1],
    saved: savedSelection })`);
  await h.eval(`__spType("saved-edit-name", "   "); __spButton("#saved-panel", "Save").click(); true`);
  out.steps.editEmpty = await h.eval(SNAP);
  await h.eval(`__spType("saved-edit-name", "Mall"); __spButton("#saved-panel", "Save").click(); true`);
  out.steps.renamed = await h.eval(`(function () { var s = ${SNAP}; s.edit = ${EDIT_READ}; return s; })()`);

  // delete: the badge asks first, Cancel keeps it, Delete removes it with no request and ends edit mode
  out.steps.sentBeforeDelete = await h.eval(`__sent.length`);
  await h.eval(`document.querySelectorAll("#quick-picks .saved-chip__badge")[1].click(); true`);
  out.steps.confirm = await h.eval(SNAP);
  await h.eval(`__spButton("#saved-panel", "Cancel").click(); true`);
  out.steps.cancelled = await h.eval(`(function () { var s = ${SNAP}; s.edit = ${EDIT_READ}; return s; })()`);
  await h.eval(`document.querySelectorAll("#quick-picks .saved-chip__badge")[1].click();
    __spButton("#saved-panel", "Delete").click(); true`);
  out.steps.deleted = await h.eval(`(function () { var s = ${SNAP}; s.edit = ${EDIT_READ}; return s; })()`);
  out.steps.sentAfterDelete = await h.eval(`__sent.slice(${out.steps.sentBeforeDelete}).map(function (e) { return e.via + " " + e.url + " " + e.body; })`);

  // keyboard: Escape leaves edit mode; Done leaves it too; every control is a button in the tab order
  await h.eval(`__spButton("#quick-picks", "Edit").click(); true`);
  out.steps.escapeBefore = await h.eval(`__spText(document.querySelector('#quick-picks [data-saved-action="toggle-edit"]'))`);
  out.steps.keyboardEdit = await h.eval(`Array.prototype.map.call(document.querySelectorAll("#quick-picks button"), function (b) {
    return { tag: b.tagName, tabindex: b.tabIndex, type: b.type, label: !!(b.getAttribute("aria-label") || b.textContent.trim()) };
  })`);
  await h.eval(`document.querySelector("#quick-picks .saved-chip__main").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); true`);
  out.steps.escapeAfter = await h.eval(`__spText(document.querySelector('#quick-picks [data-saved-action="toggle-edit"]'))`);
  await h.eval(`__spButton("#quick-picks", "Edit").click(); true`);
  await h.eval(`document.querySelectorAll("#quick-picks .saved-chip__badge")[0].click();
    document.getElementById("saved-panel").querySelector("button").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); true`);
  out.steps.escapeFromConfirm = await h.eval(`(function () { var s = ${SNAP}; s.edit = ${EDIT_READ}; return s; })()`);
  await h.eval(`__spButton("#quick-picks", "Edit").click(); __spButton("#quick-picks", "Done").click(); true`);
  out.steps.done = await h.eval(EDIT_READ);
  out.steps.keyboard = await h.eval(`Array.prototype.map.call(document.querySelectorAll("#quick-picks button"), function (b) {
    return { tag: b.tagName, tabindex: b.tabIndex, type: b.type, label: !!(b.getAttribute("aria-label") || b.textContent.trim()) };
  })`);

  // malformed storage is dropped on read and the list is cut to five
  await h.eval(`localStorage.setItem("bus-catch-saved-places-v1", JSON.stringify({ v: 1, places: [
      { id: "a", name: "Good", address: "x", latitude: 1.3, longitude: 103.8 },
      { id: "b", name: "", address: "x", latitude: 1.3, longitude: 103.8 },
      { id: "c", name: "No point", address: "x" },
      { id: "d", name: "Far", address: "x", latitude: 999, longitude: 103.8 },
      "junk", null,
      { id: "e", name: "Two", address: "y", latitude: 1.31, longitude: 103.81 },
      { id: "f", name: "Three", address: "y", latitude: 1.32, longitude: 103.82 },
      { id: "g", name: "Four", address: "y", latitude: 1.33, longitude: 103.83 },
      { id: "h", name: "Five", address: "y", latitude: 1.34, longitude: 103.84 },
      { id: "i", name: "Six", address: "y", latitude: 1.35, longitude: 103.85 }] }));
    renderSavedPlaces(); true`);
  out.steps.malformed = await h.eval(SNAP);
  await h.eval(`localStorage.setItem("bus-catch-saved-places-v1", "{not json"); renderSavedPlaces(); true`);
  out.steps.garbage = await h.eval(SNAP);

  // taps: with no arrive-by chosen the same prompt as Find my route; with one chosen, the stops step with the stored point
  await h.eval(`localStorage.setItem("bus-catch-saved-places-v1", JSON.stringify({ v: 1, places: [
      { id: "t1", name: "Uni", address: "21 Lower Kent Ridge Road", latitude: 1.29667, longitude: 103.77639 }] }));
    renderSavedPlaces(); true`);
  await h.eval(`__spButton("#quick-picks", "Uni").click(); true`);
  out.steps.tapNoArrive = await h.eval(`({ screen: screenStack[screenStack.length - 1], value: destinationInput.value,
    prompt: __spText(document.getElementById("arrive-required")),
    prompted: document.getElementById("arrive-required").classList.contains("is-shown"),
    selected: selectedDestination ? selectedDestination.label_display : null })`);
  await h.eval(`document.getElementById("arrive-none").click(); true`);
  await h.until("arriveByPicked === true", 5000, "an arrive-by choice");
  await h.eval(`window.__spBefore = __sent.length; __spButton("#quick-picks", "Uni").click(); true`);
  await h.until("screenStack[screenStack.length - 1] === 'stops'", 8000, "the destination stops step");
  out.steps.tap = await h.eval(`({ screen: screenStack[screenStack.length - 1],
    name: selectedDestination.label_display, address: selectedDestination.address_display,
    latitude: selectedDestination.latitude, longitude: selectedDestination.longitude,
    heading: __spText(document.getElementById("dest-place-name")),
    requests: __sent.slice(window.__spBefore).map(function (e) { return e.via + " " + e.url + " " + e.body; }),
    searches: window.__spSearches.length })`);

  // typing in the search box clears a chosen saved place
  await h.eval(`resetScreens(); __spButton("#quick-picks", "Uni").click(); true`);
  out.steps.typedBefore = await h.eval(`({ saved: savedSelection ? savedSelection.name : null })`);
  await h.eval(`__spType("destination", "Marina"); true`);
  out.steps.typedAfter = await h.eval(`({ saved: savedSelection, value: destinationInput.value })`);
  // nothing saved: "+" alone, no Edit toggle, no badges, the note concealed; then one saved place and back to none
  await h.eval(`resetScreens(); localStorage.removeItem("bus-catch-saved-places-v1"); renderSavedPlaces(); true`);
  out.steps.none = await h.eval(`(function () { var s = ${SNAP}; s.edit = ${EDIT_READ}; return s; })()`);
  await h.eval(`localStorage.setItem("bus-catch-saved-places-v1", JSON.stringify({ v: 1, places: [
      { id: "s1", name: "Solo", address: "1 Solo Road", latitude: 1.3, longitude: 103.8 }] }));
    renderSavedPlaces(); true`);
  out.steps.solo = await h.eval(SNAP);
  await h.eval(`__spButton("#quick-picks", "Edit").click(); true`);
  out.steps.soloEdit = await h.eval(`(function () { var s = ${SNAP}; s.edit = ${EDIT_READ}; return s; })()`);
  await h.eval(`document.querySelector("#quick-picks .saved-chip__badge").click();
    __spButton("#saved-panel", "Delete").click(); true`);
  out.steps.lastDeleted = await h.eval(`(function () { var s = ${SNAP}; s.edit = ${EDIT_READ}; return s; })()`);
  await h.eval(`__spButton("#quick-picks", "+").click(); true`);
  out.steps.noneAddOpen = await h.eval(SNAP);
  await h.eval(`__spButton("#saved-panel", "Cancel").click(); true`);
  out.steps.noneAfterCancel = await h.eval(SNAP);
  out.steps.noCustom = await h.eval(`document.body.innerHTML.indexOf('data-saved-action="custom"') === -1
    && Array.prototype.every.call(document.querySelectorAll("#quick-picks button, #saved-places button"), function (b) {
      return __spText(b) !== "Custom"; })`);

  // the page's whole network log: no saved name and no coordinate outside the tap's own request
  out.steps.network = await h.eval(`__sent.map(function (e) { return e.via + " " + e.url + " " + e.body; })`);
  out.steps.text = await h.eval(`(function () {
    var parts = [document.getElementById("quick-picks").innerHTML, document.getElementById("saved-places").innerHTML];
    return parts.join(" ");
  })()`);
  return out;
}

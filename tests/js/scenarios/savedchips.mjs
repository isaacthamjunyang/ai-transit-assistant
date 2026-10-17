import { openHome } from "./common.mjs";

// Saved-place chips against the Arrive by chips on Home: unselected and selected looks side by side, the Add place chip and
// the Edit / Done button (unchanged), the edit-mode delete badges and the geometry before and after a selection.
// config: width, height, dark.

const PLACES = [
  { id: "s1", name: "Home", address: "1 Home Road", latitude: 1.3, longitude: 103.8 },
  { id: "s2", name: "Work", address: "2 Work Road", latitude: 1.31, longitude: 103.81 },
  { id: "s3", name: "Grandmother's flat Bedok", address: "3 Bedok Road", latitude: 1.32, longitude: 103.9 }
];

const HELPERS = `
  window.__text = function (el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; };
  window.__look = function (el) {
    if (!el) { return null; }
    var c = getComputedStyle(el), r = el.getBoundingClientRect();
    return { text: __text(el), borderWidth: c.borderTopWidth, borderStyle: c.borderTopStyle, border: c.borderTopColor, background: c.backgroundColor,
             color: c.color, radius: c.borderTopLeftRadius, shadow: c.boxShadow, weight: c.fontWeight, w: r.width, h: r.height, left: r.left, top: r.top,
             pressed: el.getAttribute("aria-pressed"), checked: el.getAttribute("aria-checked"), cls: el.className };
  };
  window.__chip = function (name) {
    return Array.prototype.filter.call(document.querySelectorAll("#quick-picks .saved-chip__main"), function (b) {
      return __text(b.querySelector(".saved-chip__name")) === name; })[0];
  };
  window.__geometry = function () {
    return Array.prototype.map.call(document.querySelectorAll("#quick-picks > *"), function (n) {
      var r = n.getBoundingClientRect(); return [Math.round(r.left * 10) / 10, Math.round(r.top * 10) / 10, Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10]; });
  };
  true;
`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(HELPERS);
  await h.eval(`localStorage.setItem("bus-catch-saved-places-v1", JSON.stringify({ v: 1, places: ${JSON.stringify(PLACES)} })); renderSavedPlaces(); true`);
  await h.sleep(200);
  out.tokens = await h.eval(`(function () {
    var root = getComputedStyle(document.documentElement);
    function token(name) { return root.getPropertyValue(name).trim(); }
    return { card: token("--color-card"), line: token("--color-line"), ink: token("--color-ink"), outlineSelected: token("--color-selected-outline"),
             outlineSuccess: token("--color-selected-outline-success") };
  })()`);
  // the Arrive by chips: an unselected one now; a selected one at the end (choosing one may open the next page)
  out.arriveUnselected = await h.eval(`__look(document.getElementById("arrive-30"))`);
  // the saved chips before any selection
  out.geometryBefore = await h.eval(`__geometry()`);
  out.unselected = await h.eval(`__look(__chip("Work"))`);
  out.unselectedLong = await h.eval(`__look(__chip("Grandmother's flat Bedok"))`);
  out.add = await h.eval(`__look(document.querySelector('#quick-picks [data-saved-action="add"]'))`);
  out.edit = await h.eval(`__look(document.querySelector('#quick-picks [data-saved-action="toggle-edit"]'))`);
  // select one
  await h.eval(`__chip("Work").click(); true`);
  await h.sleep(400);
  out.selected = await h.eval(`__look(__chip("Work"))`);
  out.selectedCount = await h.eval(`document.querySelectorAll("#quick-picks .saved-chip__main.is-selected").length`);
  out.others = await h.eval(`Array.prototype.filter.call(document.querySelectorAll("#quick-picks .saved-chip__main"), function (b) { return __text(b.querySelector(".saved-chip__name")) !== "Work"; }).map(__look)`);
  out.geometryAfter = await h.eval(`__geometry()`);
  out.addAfter = await h.eval(`__look(document.querySelector('#quick-picks [data-saved-action="add"]'))`);
  out.editAfter = await h.eval(`__look(document.querySelector('#quick-picks [data-saved-action="toggle-edit"]'))`);
  out.scroll = await h.eval(`({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })`);
  // edit mode: the delete badges, and the chips keep their size
  await h.eval(`document.querySelector('#quick-picks [data-saved-action="toggle-edit"]').click(); true`);
  await h.sleep(300);
  out.editMode = await h.eval(`(function () {
    var badges = Array.prototype.map.call(document.querySelectorAll("#quick-picks .saved-chip__badge"), function (b) { var r = b.getBoundingClientRect(); return [r.width, r.height]; });
    return { badges: badges, geometry: __geometry(), done: __look(document.querySelector('#quick-picks [data-saved-action="toggle-edit"]')),
             chip: __look(document.querySelector("#quick-picks .saved-chip__main")) };
  })()`);
  await h.eval(`document.querySelector('#quick-picks [data-saved-action="toggle-edit"]').click(); true`);
  await h.eval(`document.getElementById("arrive-60").click(); true`);
  out.arriveSelected = await h.eval(`__look(document.getElementById("arrive-60"))`);
  out.arriveSelectedState = await h.eval(`document.getElementById("arrive-60").getAttribute("aria-checked") + "|" + document.getElementById("arrive-60").classList.contains("is-selected")`);
  return out;
}

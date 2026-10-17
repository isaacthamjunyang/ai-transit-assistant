import { openHome } from "./common.mjs";

// The destination stop page with bus stops and stations in one list. config: width, height, dark, shots (a folder),
// click (a stop code to tap), confirm (true to press Select stop and then Confirm).
const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function box(el) { var r = el.getBoundingClientRect(); return { w: r.width, h: r.height, x: r.x, y: r.y, right: r.right }; }
  var rows = Array.prototype.map.call(document.querySelectorAll("#reachable-stops .dest-stop-row"), function (row) {
    var tile = row.querySelector(".dest-tile");
    var cs = getComputedStyle(tile);
    return {
      code: row.getAttribute("data-stop-code"), kind: row.getAttribute("data-kind"), cls: row.className, tileCls: tile.className,
      name: text(row.querySelector(".dest-stop-row__name")), label: text(row.querySelector(".dest-stop-row__kind")),
      lines: Array.prototype.map.call(row.querySelectorAll(".dest-stop-row__line"), function (line) {
        var badge = line.querySelector(".line-badge");
        return { text: text(line), badge: badge.textContent, badgeCls: badge.className };
      }),
      meta: text(row.querySelector(".dest-stop-row__meta")), note: !!row.querySelector(".dest-stop-row__note"),
      selected: row.classList.contains("is-selected"), pressed: row.getAttribute("aria-pressed"), pill: text(row.querySelector(".pill")),
      tileRing: cs.boxShadow, tileBg: cs.backgroundColor, tileColor: cs.color, tileIcon: tile.innerHTML.length, box: box(row),
      text: text(row)
    };
  });
  var markers = Array.prototype.map.call(document.querySelectorAll(".dest-map .map-stop--dest"), function (el) {
    var dot = el.querySelector(".map-stop__dot");
    var ds = getComputedStyle(dot);
    return { cls: el.className, label: text(el.querySelector(".map-stop__label")), icon: dot.innerHTML.length, border: ds.borderTopColor,
      borderWidth: ds.borderTopWidth, shadow: ds.boxShadow, bg: ds.backgroundColor, selected: el.classList.contains("is-selected") };
  });
  return {
    title: text(document.getElementById("dest-stops-title")), info: text(document.getElementById("dest-stops-note")),
    rows: rows, markers: markers, status: text(document.getElementById("destination-stop-status")),
    selectDisabled: document.getElementById("select-destination-stop").disabled,
    selectedCode: selectedDestinationStop ? selectedDestinationStop.stop_code : null,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    order: destStopOrder.slice()
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height });
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    pushScreen("stops"); loadDestinationStops(); true`);
  await h.until("document.querySelectorAll('#reachable-stops .dest-stop-row').length > 0 || !document.getElementById('destination-stop-status').hidden", 15000, "the stop list");
  await h.sleep(600);
  out.first = await h.eval(READ);
  if (c.shots) {
    await h.screenshot(`${c.shots}/deststations-${c.name || "x"}.png`);
  }
  if (c.click) {
    await h.eval(`document.querySelector('#reachable-stops .dest-stop-row[data-stop-code="${c.click}"]').click(); true`);
    await h.sleep(400);
    out.afterClick = await h.eval(READ);
    if (c.shots) {
      await h.screenshot(`${c.shots}/deststations-${c.name || "x"}-selected.png`);
    }
  }
  if (c.confirm) {
    await h.eval("document.getElementById('select-destination-stop').click(); true");
    await h.until("screenStack[screenStack.length - 1] === 'confirm'", 8000, "the confirm screen");
    out.confirmScreen = await h.eval(`({heading: document.getElementById("confirm-stop-heading").textContent,
      edit: document.getElementById("edit-destination-stop").getAttribute("aria-label"),
      name: document.getElementById("confirm-stop-name").textContent,
      info: document.getElementById("confirm-info-text").textContent.trim(),
      tileCls: document.getElementById("confirm-stop-tile").className,
      tileRing: getComputedStyle(document.getElementById("confirm-stop-tile")).boxShadow,
      tileSvg: document.getElementById("confirm-stop-tile").innerHTML.length,
      tileIsTrain: document.getElementById("confirm-stop-tile").innerHTML.indexOf("M8 21l2-5") !== -1,
      lines: Array.prototype.map.call(document.querySelectorAll("#confirm-stop-lines .dest-stop-row__line"), function (l) {
        return { text: l.textContent.replace(/\\s+/g, " ").trim(), badge: l.querySelector(".line-badge").textContent };
      }),
      linesShown: !document.getElementById("confirm-stop-lines").hidden})`);
    await h.eval("confirmDestinationStop.click(); true");
    await h.until("__requests.some(function (u) { return u.indexOf('/api/journey-plan?') === 0; })", 15000, "the journey plan request");
    out.planRequest = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/journey-plan?') === 0; })[0]");
    out.confirmed = await h.eval("({code: confirmedDestinationStop.stop_code, kind: confirmedDestinationStop.kind, lat: confirmedDestinationStop.lat, lon: confirmedDestinationStop.lon})");
  }
  return out;
}

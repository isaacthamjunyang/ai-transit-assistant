import { poll, toLive } from "./common.mjs";

// Page W's map fit in the real page (tiles blocked, fake geolocation): both markers in view, the zoom, the Range chip,
// the user-moved flag, a real pan, open-back-open, and the same checks for Page B's map.
const MEASURE = `(function () {
  var c = map.getCenter();
  var size = map.getSize();
  var chip = document.querySelector(".walk-map .leaflet-control-scale-line");
  var youPoint = walkYou ? map.latLngToContainerPoint(walkYou.getLatLng()) : null;
  var stopPoint = walkStopMarker ? map.latLngToContainerPoint(walkStopMarker.getLatLng()) : null;
  var inside = function (p) { return !!p && p.x >= 0 && p.y >= 0 && p.x <= size.x && p.y <= size.y; };
  var label = walkStopMarker && walkStopMarker.getElement() ? walkStopMarker.getElement().querySelector(".map-stop__label") : null;
  var youEl = walkYou ? walkYou.getElement() : null;
  var overlap = false;
  if (label && youEl) {
    var a = label.getBoundingClientRect(), b = youEl.getBoundingClientRect();
    overlap = a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }
  var side = label ? ["is-right", "is-left", "is-top", "is-bottom"].filter(function (n) { return label.classList.contains(n); }) : [];
  var acc = document.querySelector(".walk-map .walk-accuracy");
  var line = document.querySelector(".walk-map .walk-line");
  return {
    top: screenStack[screenStack.length - 1], zoom: map.getZoom(), center: [c.lat, c.lng], size: [size.x, size.y],
    chip: chip ? chip.textContent : null, you: youPoint && [Math.round(youPoint.x), Math.round(youPoint.y)],
    stop: stopPoint && [Math.round(stopPoint.x), Math.round(stopPoint.y)],
    youInside: inside(youPoint), stopInside: inside(stopPoint),
    apart: youPoint && stopPoint ? Math.round(Math.hypot(youPoint.x - stopPoint.x, youPoint.y - stopPoint.y)) : null,
    moved: walkUserMoved, liveMoved: liveUserMoved, side: side, labelOverlapsYou: overlap,
    accuracyVisible: !!acc && acc.getBoundingClientRect().width > 4, accuracyWidth: acc ? Math.round(acc.getBoundingClientRect().width) : 0,
    lineVisible: !!line && line.getBoundingClientRect().height + line.getBoundingClientRect().width > 4,
    fit: walkFitState
  };
})()`;

const MEASURE_B = `(function () {
  var size = map.getSize();
  var c = map.getCenter();
  var you = userLat !== null ? map.latLngToContainerPoint([userLat, userLon]) : null;
  var stop = liveStopMarker ? map.latLngToContainerPoint(liveStopMarker.getLatLng()) : null;
  var inside = function (p) { return !!p && p.x >= 0 && p.y >= 0 && p.x <= size.x && p.y <= size.y; };
  var chip = document.querySelector("#live-map-slot .leaflet-control-scale-line");
  return { top: screenStack[screenStack.length - 1], zoom: map.getZoom(), size: [size.x, size.y], clientWidth: mapElement.clientWidth,
    inSlot: mapElement.parentNode === document.getElementById("live-map-slot"), youInside: inside(you), stopInside: inside(stop),
    chip: chip ? chip.textContent : null, center: [c.lat, c.lng], tilePane: document.querySelector(".leaflet-tile-pane") !== null };
})()`;

export default async function (h) {
  const out = { distances: {}, late: null };
  await toLive(h, { permission: "granted" });
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  const stopLat = h.config.lat, stopLon = h.config.lon;
  const toPageA = async () => {
    await h.eval("if (screenStack[screenStack.length - 1] !== 'live') { requestBack(); } true");
    await h.sleep(500);
    await h.until("screenStack[screenStack.length - 1] === 'live'", 5000, "Page A");
  };
  const setFix = (metres, accuracy) => h.eval(`userLat = ${stopLat} + ${metres} / 111195; userLon = ${stopLon}; userAccuracy = ${accuracy}; userLocationTimestamp = Date.now(); __geo.set({ lat: userLat, lon: userLon, acc: ${accuracy} }); true`);
  const openW = async () => {
    await h.eval("document.getElementById('walk-open').click(); true");
    await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
    await h.sleep(1600);  // the display tick and the layout frame have both run
  };

  for (const metres of [8, 12, 20, 24, 25, 59, 300, 1200, 5000]) {
    await setFix(metres, 20);
    await openW();
    out.distances[metres] = await h.eval(MEASURE);
    await toPageA();
  }

  // the zoom of the first view and Page B's fit never replace Page W's: 59 m, several ticks
  await setFix(59, 20);
  await openW();
  await h.sleep(2200);
  out.afterTicks = await h.eval(MEASURE);

  // the live bus is kilometres away (a real, monitored bus): Page B's fit would include it and zoom out to the island
  await h.eval("(function () { var hero = featuredBus(lastSuccess.buses); hero.latitude = " + stopLat + " + 0.06; hero.longitude = " + stopLon + " + 0.08; hero.monitored = true; liveFit = { done: false, withBus: false }; })(); true");
  await h.sleep(2300);
  out.withFarBus = await h.eval(MEASURE);

  // a programmatic fit and Leaflet's animated zooms do not set the user-moved flag
  await h.eval("walkFitState = { done: false, distance: null }; walkUserMoved = false; liveUserMoved = false; renderWalkPage(); true");
  out.afterProgrammaticFit = await h.eval(MEASURE);
  await h.eval("map.setZoom(map.getZoom() - 1); true");
  await h.sleep(700);
  await h.eval("map.flyTo(map.getCenter(), map.getZoom() + 1); true");
  await h.sleep(1500);
  out.afterAnimatedZooms = await h.eval(MEASURE);
  await h.eval("walkFitState = { done: false, distance: null }; renderWalkPage(); true");

  // a real drag (trusted pointer events) sets the flag, and later fixes do not refit
  await h.eval("mapElement.scrollIntoView({ block: 'center' }); true");  // Page W's map sits under two cards now
  await h.sleep(200);
  const rect = await h.eval("(function () { var r = mapElement.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()");
  const [cx, cy] = rect;
  await h.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: cx, y: cy });
  await h.send("Input.dispatchMouseEvent", { type: "mousePressed", x: cx, y: cy, button: "left", buttons: 1, clickCount: 1 });
  for (let i = 1; i <= 6; i++) {
    await h.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: cx + i * 15, y: cy + i * 10, button: "left", buttons: 1 });
  }
  await h.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: cx + 90, y: cy + 60, button: "left", buttons: 0, clickCount: 1 });
  await h.sleep(600);
  out.afterPan = await h.eval(MEASURE);
  await h.eval(`__geo.set({ lat: ${stopLat} + 600 / 111195, lon: ${stopLon}, acc: 20 }); walkOnFix({ t: Date.now() + 1000, lat: ${stopLat} + 600 / 111195, lon: ${stopLon}, accuracy: 20, heading: null, speed: null }); true`);
  await h.sleep(1500);
  out.afterFarFix = await h.eval(MEASURE);
  await h.eval("document.getElementById('walk-recentre').click(); true");
  await h.sleep(300);
  out.afterRecentre = await h.eval(MEASURE);

  // open, back, open again keeps the fit correct
  await toPageA();
  await setFix(59, 20);
  await openW();
  out.firstOpen = await h.eval(MEASURE);
  await toPageA();
  await openW();
  out.secondOpen = await h.eval(MEASURE);

  // late fix: Page W opened with no fix, the fix arrives afterwards
  await toPageA();
  await h.eval("userLat = null; userLon = null; userLocationTimestamp = null; true");
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  await h.sleep(600);
  out.noFix = await h.eval(MEASURE);
  await h.eval(`__geo.set({ lat: ${stopLat} + 59 / 111195, lon: ${stopLon}, acc: 20 }); walkOnFix({ t: Date.now(), lat: ${stopLat} + 59 / 111195, lon: ${stopLon}, accuracy: 20, heading: null, speed: null }); true`);
  await h.sleep(1800);
  out.late = await h.eval(MEASURE);

  // Page B's own map: the same checks (no hidden-container problem)
  out.pageB = {};
  await toPageA();
  for (const metres of [20, 59, 300, 1200, 5000]) {
    await setFix(metres, 20);
    await h.eval("document.getElementById('see-arrivals').click(); true");
    await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 5000, "Page B");
    await h.sleep(1600);
    out.pageB[metres] = await h.eval(MEASURE_B);
    await h.eval("requestBack(); true");
    await h.until("screenStack[screenStack.length - 1] === 'live'", 5000, "Page A");
    await h.sleep(300);
  }
  // Page B after Page W: the map is back in Page B's slot with a size
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  await h.sleep(800);
  await h.eval("document.getElementById('see-arrivals').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 5000, "Page B after W");
  await h.sleep(1600);
  out.pageBAfterW = await h.eval(MEASURE_B);
  return out;
}

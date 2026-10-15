import { openHome, poll, toLive } from "./common.mjs";

// The two map markers in the real page: the red pin (current location) and the green flag (destination), on the
// destination stops page, the live map (Pages A and B share it), Page W and the overlap case.
const HELPERS = `
  window.__mmPoint = function (marker) {
    var o = marker.options.icon.options;
    var el = marker.getElement();
    var box = el.getBoundingClientRect();
    var area = mapElement.getBoundingClientRect();
    var at = map.latLngToContainerPoint(marker.getLatLng());
    return { anchor: o.iconAnchor, size: o.iconSize, left: box.left - area.left, top: box.top - area.top,
             x: at.x, y: at.y, width: box.width, height: box.height };
  };
  window.__mmLook = function (marker, bodyClass) {
    var el = marker.getElement();
    var body = el.querySelector("." + bodyClass);
    var casing = el.querySelector(".map-flag__casing");
    var s = getComputedStyle(body);
    var e = getComputedStyle(el);
    var label = el.querySelector(".marker__label");
    return {
      cls: el.className, ariaLabel: el.getAttribute("aria-label"), role: el.getAttribute("role"),
      fill: s.fill, stroke: s.stroke, strokeWidth: s.strokeWidth,
      casingStroke: casing ? getComputedStyle(casing).stroke : null,
      background: e.backgroundColor, borderWidth: e.borderTopWidth, shadow: e.boxShadow, display: e.display,
      text: label ? label.textContent : null, labelVisibility: label ? getComputedStyle(label).visibility : null,
      labelLeft: label ? label.getBoundingClientRect().left : null,
      boxLeft: el.getBoundingClientRect().left, boxRight: el.getBoundingClientRect().right,
      html: marker.options.icon.options.html, point: __mmPoint(marker), lifted: !!marker.__lifted
    };
  };
  window.__mmTokens = function () {
    return { start: cssToken("--marker-start"), end: cssToken("--marker-end"), ring: cssToken("--map-marker-ring"),
             land: cssToken("--map-land-standin"), primary: cssToken("--color-primary") };
  };
  true;
`;

export default async function (h) {
  const c = h.config;
  const out = {};
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(HELPERS);
  await h.until("userMarker !== null", 5000, "the current location marker");
  out.tokens = await h.eval("__mmTokens()");

  // the destination stops page: the flag on the destination, the pin on the user
  await h.eval(`selectedDestination = { latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination" };
    pushScreen("stops"); showDestinationPin(); map.setView([userLat, userLon], 16, { animate: false }); true`);
  await h.sleep(300);
  out.stopsPin = await h.eval(`__mmLook(userMarker, "map-pin__body")`);
  out.stopsFlag = await h.eval(`__mmLook(flagMarkers.dest, "map-flag__body")`);
  out.stopsOldPins = await h.eval(`document.querySelectorAll(".dest-pin, .dest-pin__svg, .dest-pin__body").length`);
  out.stopsUserMarkers = await h.eval(`Array.prototype.map.call(document.querySelectorAll(".user-marker"), function (el) {
    var s = getComputedStyle(el); return { background: s.backgroundColor, radius: s.borderTopLeftRadius, border: s.borderTopWidth }; })`);
  out.stopsAria = await h.eval(`({ pin: userMarker.getElement().getAttribute("aria-label"), tabindex: userMarker.getElement().tabIndex,
    popup: userMarker.getPopup().getContent() })`);

  // the overlap case on that page: the destination 2 m from the user
  await h.eval(`selectedDestination = { latitude: userLat + 2 / 111195, longitude: userLon, label: "Destination", label_display: "Destination" };
    showDestinationPin(); map.setView([userLat, userLon], 18, { animate: false }); true`);
  await h.sleep(200);
  out.overlap = await h.eval(`(function () {
    var f = flagMarkers.dest, p = userMarker;
    var flag = f.getElement().querySelector(".map-flag__body").getBoundingClientRect();
    var pin = p.getElement().querySelector(".map-pin__body").getBoundingClientRect();
    return { lifted: !!f.__lifted, anchor: f.options.icon.options.iconAnchor, flagBottom: flag.bottom, pinTop: pin.top,
             flagLeft: flag.left, flagRight: flag.right, pinLeft: pin.left, pinRight: pin.right,
             flagVisible: flag.width > 0 && getComputedStyle(f.getElement()).display !== "none",
             pinVisible: pin.width > 0, flagLabel: f.getElement().getAttribute("aria-label") };
  })()`);
  // apart again: back on the coordinate
  await h.eval(`selectedDestination = { latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination" };
    showDestinationPin(); true`);
  out.apart = await h.eval(`({ lifted: !!flagMarkers.dest.__lifted, anchor: flagMarkers.dest.options.icon.options.iconAnchor })`);
  await h.eval(`pushScreen("home"); true`).catch(() => null);

  // Page A: the live flows (the map shows on Page W and Page B)
  await toLive(h, { permission: "granted", dark: c.dark, width: c.width, height: c.height });
  await h.eval(HELPERS);
  await h.until("!explanationInFlight", 15000, "the first explanation request to finish");
  await poll(h);
  // Page W: the pin with You, and the heading wedge from the pin's tip
  await h.eval("document.getElementById('walk-open').click(); true");
  await h.until("screenStack[screenStack.length - 1] === 'walk'", 5000, "Page W");
  await h.sleep(400);
  out.walk = await h.eval(`(function () {
    var m = null;
    map.eachLayer(function (layer) {
      var o = layer.options && layer.options.icon && layer.options.icon.options;
      if (o && o.className && o.className.indexOf("walk-you") !== -1) { m = layer; }
    });
    var look = __mmLook(m, "map-pin__body");
    var wedge = m.getElement().querySelector(".walk-wedge");
    look.wedgeTop = wedge ? getComputedStyle(wedge).top : null;
    look.flags = Array.prototype.filter.call(document.querySelectorAll("#walk-map-slot .map-flag__svg"), function (el) { return el.getClientRects().length > 0; }).length;
    look.accuracy = document.querySelectorAll("#walk-map-slot .walk-accuracy").length;
    return look;
  })()`);
  // Page B holds the live map: the flag with the place name beside it
  await h.eval("pushScreen('arrivals'); true");
  await h.until("screenStack[screenStack.length - 1] === 'arrivals'", 5000, "Page B");
  await h.sleep(400);
  await h.eval(`confirmedDestinationStop = { stop_code: "${c.dest}", stop_name: "Destination", lat: ${c.destPos[0]}, lon: ${c.destPos[1]} };
    syncLiveDestination(); true`);
  out.liveFlag = await h.eval(`__mmLook(liveDestMarker, "map-flag__body")`);
  out.livePin = await h.eval(`__mmLook(userMarker, "map-pin__body")`);
  out.liveLabel = await h.eval(`(function () { var l = liveDestMarker.getElement().querySelector(".map-dest-live__label");
    return l ? l.textContent : null; })()`);
  out.liveOldPins = await h.eval(`document.querySelectorAll(".dest-pin, .dest-pin__svg").length`);
  out.liveBlue = await h.eval(`Array.prototype.some.call(document.querySelectorAll(".user-marker:not(.walk-you)"), function (el) {
    return getComputedStyle(el).backgroundColor === getComputedStyle(document.documentElement).getPropertyValue("--color-primary"); })`);
  out.liveOverlap = await h.eval(`(function () {
    confirmedDestinationStop = { stop_code: "${c.dest}", stop_name: "Destination", lat: userLat + 2 / 111195, lon: userLon };
    syncLiveDestination();
    return { lifted: !!liveDestMarker.__lifted, anchor: liveDestMarker.options.icon.options.iconAnchor,
             label: liveDestMarker.getElement().getAttribute("aria-label") };
  })()`);
  await h.eval(`confirmedDestinationStop = { stop_code: "${c.dest}", stop_name: "Destination", lat: ${c.destPos[0]}, lon: ${c.destPos[1]} };
    syncLiveDestination(); true`);

  if (c.shots) { await h.screenshot(`${c.shots}/markers-${c.name || "map"}.png`); }
  return out;
}

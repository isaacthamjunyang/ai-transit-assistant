import { openHome } from "./common.mjs";

// The route preview on the map after Start journey: how each leg is drawn, and the pins.
const READ = `(function () {
  function style(layer) {
    var o = layer.options;
    return { color: o.color, weight: o.weight, dash: o.dashArray || "", cap: o.lineCap, points: layer.getLatLngs().length };
  }
  var names = ["ns", "ew", "cg", "ne", "cc", "dt", "te", "bp", "sk", "pg", "ss"];
  var tokens = { walk: cssToken("--map-walk-line"), bus: cssToken("--map-line-bus") };
  names.forEach(function (code) {
    tokens[code] = cssToken("--map-line-" + code);
    tokens[code + "_casing"] = cssToken("--map-line-" + code + "-casing");
  });
  return {
    layers: routePreviewLayers.map(style),
    pins: routeRoleMarkers.map(function (m) { return m.options.icon.options.html; }),
    tokens: tokens
  };
})()`;

export default async function (h) {
  const c = h.config;
  await openHome(h, { dark: c.dark, width: c.width, height: c.height });
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination", walk_minutes: 3};
    pushScreen("journey"); true`);
  await h.until("!document.getElementById('start-journey').disabled", 20000, "the overview start-journey button");
  await h.eval("document.getElementById('start-journey').click(); true");
  await h.until("monitoringActive === true", 10000, "polling to start");
  await h.sleep(600);
  const out = await h.eval(READ);
  if (c.shots) { await h.screenshot(`${c.shots}/routemap-${c.name || "map"}.png`); }
  return out;
}

// Shared steps: load the real page, plan the journey in its overview, and tap "Start journey".
export async function openHome(h, extra = {}) {
  const c = h.config;
  await h.open(c.base + "/" + (extra.query || ""), {
    dark: extra.dark ?? h.config.dark, prelude: {
      position: { lat: c.userNorth[0], lon: c.userNorth[1], acc: 8 },
      permission: extra.permission || "none", storage: extra.storage,
    },
    settle: 800,
  });
  await h.until("typeof userLat === 'number'", 15000, "the first location fix");
}

export async function planOverview(h) {
  const c = h.config;
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination"};
    pushScreen("journey"); true`);
  await h.until("!document.getElementById('start-journey').disabled", 20000, "the overview start-journey button");
}

export async function tapStart(h) {
  await h.eval("document.getElementById('start-journey').click(); true");
  await h.until("monitoringActive === true", 10000, "polling to start");
}

export async function toLive(h, extra = {}) {
  await openHome(h, extra);
  await planOverview(h);
  await tapStart(h);
}

export const state = `({
  wanted: paceEstimator.isWanted(), running: paceEstimator.isRunning(), latched: paceEstimator.isLatched(),
  listeners: __motion.listeners(), watching: __geo.watching(), monitoring: monitoringActive,
  screen: screenStack[screenStack.length - 1], reason: paceEstimator.status().stopReason
})`;

export async function poll(h) {
  const before = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; }).length");
  await h.eval("requestArrivals(monitorGeneration); true");
  await h.until(`__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; }).length > ${before} && !pollBusy`, 15000, "a poll");
  await h.sleep(150);
}

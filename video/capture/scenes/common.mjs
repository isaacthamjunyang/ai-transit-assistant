// Shared steps for the scenes: open the real page with sample saved places, and a few waits.
export async function openHome(h, extra = {}) {
  const c = h.config;
  const places = { v: 1, places: c.places };
  await h.open(c.base + "/" + (extra.query || ""), {
    dark: extra.dark ?? true,
    prelude: {
      position: { lat: c.userNorth[0], lon: c.userNorth[1], acc: 8 },
      permission: "granted",
      storage: { "bus-catch-saved-places-v1": JSON.stringify(places), ...(extra.storage || {}) },
    },
    settle: 900,
  });
  await h.until("typeof userLat === 'number'", 15000, "the first location fix");
  await h.sleep(300);
}

export const screen = "screenStack[screenStack.length - 1]";

// Home -> School -> arrive in 1 hour -> Find my route -> Skip -> Confirm: the journey overview, ready.
export async function toOverview(h, extra = {}) {
  await openHome(h, extra);
  await h.tapText("#quick-picks button", "School");
  await h.tap("#arrive-by-field", { after: 250 });
  await h.tap(extra.arrive || "#arrive-60", { after: 250 });
  await h.tap("#find-route");
  await h.until(`${screen} === "stops" && document.querySelectorAll(".dest-stop-row").length >= 2`, 15000, "the stops page");
  await h.sleep(400);
  await h.tap("#skip-stop");
  await h.until(`${screen} === "confirm"`, 8000, "confirm");
  await h.sleep(300);
  await h.tap("#confirm-destination-stop");
  await h.until(`${screen} === "journey" && !document.getElementById("start-journey").disabled`, 25000, "the overview");
  await h.sleep(600);
}

// ... then Start journey: Page A (or W / B) with live polling.
export async function startJourney(h) {
  await h.tap("#start-journey");
  await h.until("monitoringActive === true", 10000, "polling to start");
  await h.until("!entryPending && lastSuccess", 20000, "the first poll to decide the page");
  await h.sleep(500);
}

// The same hand-poll the tests use.
export async function poll(h) {
  const before = await h.eval("__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; }).length");
  await h.eval("requestArrivals(monitorGeneration); true");
  await h.until(`__requests.filter(function (u) { return u.indexOf('/api/arrivals?') === 0; }).length > ${before} && !pollBusy`, 15000, "a poll");
  await h.sleep(250);
}

// Move the (sample) phone `metres` north of the first stop; the next poll scores the bus again.
export async function moveTo(h, metres) {
  await h.eval(`(function () { userLat = ${h.config.lat} + ${metres} / 111195; userLon = ${h.config.lon}; userAccuracy = 8; userLocationTimestamp = Date.now(); if (typeof pageC !== "undefined" && pageC) { closePageC(); } })(); true`);
}

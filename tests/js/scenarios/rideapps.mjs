import { openHome } from "./common.mjs";

// The ride-app card under an empty plan answer, in the real page against the real app and a stubbed OneMap: for each
// priority its heading, distance line, links and boxes; then a tap on every link with navigation cancelled, counting
// everything the page sends. config: width, height, dark, priorities, tap.

const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function shown(el) { return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  var card = document.getElementById("ride-apps");
  var distance = document.getElementById("ride-apps-distance");
  var links = Array.prototype.slice.call(card.querySelectorAll("a"));
  var box = card.getBoundingClientRect();
  return {
    shown: shown(card), priority: planPriority,
    noService: shown(document.getElementById("overview-no-service")), noRoute: shown(document.getElementById("overview-no-route")),
    ready: shown(document.getElementById("overview-timeline")),
    heading: text(card.querySelector("h3")),
    distance: shown(distance) ? text(distance) : null,
    note: text(card.querySelector(".ride-apps__note")),
    links: links.map(function (a) {
      var r = a.getBoundingClientRect();
      return { text: text(a), href: a.getAttribute("href"), target: a.getAttribute("target"), rel: a.getAttribute("rel"),
               height: r.height, left: r.left, right: r.right };
    }),
    box: { top: box.top + window.scrollY, height: box.height },
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    inlineStyles: card.querySelectorAll("[style]").length
  };
})()`;

export default async function (h) {
  const c = h.config;
  const out = { byPriority: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination"};
    pushScreen("journey"); true`);
  await h.sleep(300);
  await h.until("document.getElementById('overview-skeleton').hidden", 20000, "the first plan");
  for (const priority of c.priorities) {
    await h.eval(`(function () {
      var select = document.getElementById("priority-select");
      select.value = ${JSON.stringify(priority)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    await h.sleep(200);
    await h.until(`document.getElementById("overview-skeleton").hidden && planPriority === ${JSON.stringify(priority)}`, 20000, "the plan for " + priority);
    await h.sleep(150);
    const first = await h.eval(READ);
    await h.sleep(500);
    const later = await h.eval(READ);
    out.byPriority[priority] = { ...first, settledTop: later.box.top, settledHeight: later.box.height };
  }
  if (c.tap) {
    // navigation is cancelled before it starts, so nothing leaves the page; only what the page itself sends is counted
    await h.eval(`document.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("a")) { e.preventDefault(); } }, true); true`);
    const before = await h.eval("({ sent: __sent.length, requests: __requests.length, href: location.href })");
    out.tapped = await h.eval(`(function () {
      var links = document.querySelectorAll("#ride-apps a");
      Array.prototype.forEach.call(links, function (a) { a.click(); });
      return links.length;
    })()`);
    await h.sleep(500);
    out.after = await h.eval(`({ sent: __sent.slice(${before.sent}).map(function (e) { return e.url + " " + e.body; }),
      requests: __requests.slice(${before.requests}), href: location.href })`);
    out.before = before;
    // the whole of what the page has sent since it opened: no coordinate of the user or the place is in a ride-app link
    out.hrefs = await h.eval(`Array.prototype.map.call(document.querySelectorAll("#ride-apps a"), function (a) { return a.href; })`);
    out.coords = await h.eval("({ lat: userLat, lon: userLon, dlat: selectedDestination.latitude, dlon: selectedDestination.longitude })");
  }
  return out;
}

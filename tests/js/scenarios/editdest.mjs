import { openHome } from "./common.mjs";

// "Edit destination" on the journey overview, in every state, for each priority and for both ways in: through the search
// results (home > results > stops > confirm > journey) and through a saved place (home > stops > confirm > journey, which never
// visits the results page). It taps the real button and reports where the page ends up, what the history stack is and whether
// the button was the element under its own centre. config: width, height, dark, flow ("search" | "saved"), priorities,
// state ("route" | "empty"), destPos, dest.

const READ = `(function () {
  function shown(id) { var el = document.getElementById(id); return !!el && !el.hidden && getComputedStyle(el).display !== "none"; }
  function which() {
    var ids = ["overview-no-service", "overview-no-route"];
    for (var i = 0; i < ids.length; i++) { if (shown(ids[i])) { return ids[i]; } }
    return shown("overview-timeline") ? "route" : "none";
  }
  return { stack: screenStack.slice(), top: screenStack[screenStack.length - 1], state: which(), priority: planPriority,
    destination: selectedDestination ? selectedDestination.label : null, stop: confirmedDestinationStop ? confirmedDestinationStop.stop_code : null,
    pending: pendingDestination ? pendingDestination.label : null,
    visible: ["screen-results", "screen-stops"].map(function (id) { return id; }), historyLength: history.length };
})()`;

async function enter(h, c) {
  await h.eval(`selectedDestination = {latitude: ${c.destPos[0]}, longitude: ${c.destPos[1]}, label: "Destination", label_display: "Destination"};
    pendingDestination = selectedDestination;
    confirmedDestinationStop = {stop_code: "${c.dest}", stop_name: "Destination"};
    if (${c.flow === "search" ? "true" : "false"}) { pushScreen("results"); }
    pushScreen("stops"); pushScreen("confirm"); pushScreen("journey"); true`);
  await h.sleep(300);
  await h.until("document.getElementById('overview-skeleton').hidden", 20000, "the first plan");
}

export default async function (h) {
  const c = h.config;
  const out = { byPriority: {} };
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  for (const priority of c.priorities) {
    await h.eval("resetScreens(); true");
    await h.sleep(200);
    await enter(h, c);
    await h.eval(`(function () {
      var select = document.getElementById("priority-select");
      select.value = ${JSON.stringify(priority)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    await h.sleep(200);
    await h.until(`document.getElementById("overview-skeleton").hidden && planPriority === ${JSON.stringify(priority)}`, 20000, "the plan for " + priority);
    await h.sleep(200);
    const before = await h.eval(READ);
    // the button that is on screen: the empty state's own, or the Destination row's Edit link in the route state
    const target = await h.eval(`(function () {
      var button = null;
      ["overview-edit-destination", "overview-edit-destination-service"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el && el.getClientRects().length > 0 && !el.closest("[hidden]")) { button = el; }
      });
      if (!button) {
        Array.prototype.forEach.call(document.querySelectorAll('.journey-step__edit[aria-label="Edit destination"]'), function (el) {
          if (el.getClientRects().length > 0) { button = el; }
        });
      }
      if (!button) { return null; }
      button.scrollIntoView({ block: "center" });
      var r = button.getBoundingClientRect();
      var under = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { id: button.id || null, text: button.getAttribute("aria-label") || button.textContent.trim(), disabled: !!button.disabled, covered: !(under === button || button.contains(under)),
        w: r.width, h: r.height };
    })()`);
    let after = null;
    if (target) {
      await h.eval(`(function () {
        var button = null;
        ["overview-edit-destination", "overview-edit-destination-service"].forEach(function (id) {
          var el = document.getElementById(id);
          if (el && el.getClientRects().length > 0 && !el.closest("[hidden]")) { button = el; }
        });
        if (!button) {
          Array.prototype.forEach.call(document.querySelectorAll('.journey-step__edit[aria-label="Edit destination"]'), function (el) {
            if (el.getClientRects().length > 0) { button = el; }
          });
        }
        button.click();
        return true;
      })()`);
      await h.sleep(700);
      after = await h.eval(READ);
      after.pageShown = await h.eval(`(function () {
        function vis(sel) { var el = document.querySelector(sel); return !!el && !el.hidden && el.getClientRects().length > 0; }
        return { overview: vis("#overview-card"), stops: vis("#dest-stops-note") || vis("#destination-stops") || vis("#dest-stop-list"), results: vis("#destination-results") };
      })()`);
    }
    out.byPriority[priority] = { before, target, after };
  }
  return out;
}

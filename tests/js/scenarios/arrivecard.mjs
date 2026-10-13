import { openHome, planOverview } from "./common.mjs";

// The Arrive by card in the overview, the on-your-way overview and the new-journey overview, driven in the real page with
// a target and an estimate set directly. The times are built from the page's own Singapore date (today or tomorrow plus
// a clock reading), so no test reads the time of day and no clock is moved. config: width, height, dark.

const CASES = {
  before: { target: ["today", "18:30"], est: ["today", "18:18"] },
  beforeOne: { target: ["today", "18:30"], est: ["today", "18:29"] },
  after: { target: ["today", "18:30"], est: ["today", "18:35"], pill: "Arrive-by check: Risk of delay" },
  afterOne: { target: ["today", "18:30"], est: ["today", "18:31"], pill: "Arrive-by check: Risk of delay" },
  notAvailable: { target: ["today", "18:30"], est: ["today", "18:20"], pill: "Arrive-by check: N/A" },
  onTarget: { target: ["today", "18:30"], est: ["today", "18:30"] },
  hours: { target: ["today", "18:30"], est: ["today", "17:25"] },
  hoursWhole: { target: ["today", "18:30"], est: ["today", "16:30"] },
  hoursOneMin: { target: ["today", "18:30"], est: ["today", "17:29"] },
  hoursAfter: { target: ["today", "18:30"], est: ["today", "19:45"] },
  acrossMidnight: { target: ["tomorrow", "00:05"], est: ["today", "23:55"] },
  acrossMidnightAfter: { target: ["today", "23:55"], est: ["tomorrow", "00:10"] },
  nextDay: { target: ["tomorrow", "18:30"], est: ["tomorrow", "18:18"] },
  noTarget: { target: null, est: ["today", "18:18"] },
  noEstimate: { target: ["today", "18:30"], est: null },
  neither: { target: null, est: null }
};

const READ = `(function () {
  function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
  function shown(el) { return !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0; }
  var box = document.querySelector("#journey-overview .arrive-box");
  var main = document.getElementById("overview-arrive-value");
  var gap = document.getElementById("overview-arrive-estimate");
  var status = document.getElementById("overview-arrive-status");
  var lines = Array.prototype.filter.call(box.querySelectorAll(".arrive-box__copy > p"), shown);
  return {
    label: box.querySelector(".arrive-box__label") ? text(box.querySelector(".arrive-box__label")) : null,
    visibleText: text(box.querySelector(".arrive-box__copy")),
    role: box.getAttribute("role"), name: box.getAttribute("aria-label"),
    iconShown: shown(box.querySelector(".arrive-box__icon")),
    boxBackground: getComputedStyle(box).backgroundColor,
    pillColour: shown(status) ? getComputedStyle(status).color : null,
    gapClass: gap.className,
    main: shown(main) ? text(main) : null,
    gap: shown(gap) ? text(gap) : null,
    status: shown(status) ? text(status) : null,
    order: lines.map(function (p) { return p.id || p.className; }),
    mainSize: shown(main) ? parseFloat(getComputedStyle(main).fontSize) : null,
    gapSize: shown(gap) ? parseFloat(getComputedStyle(gap).fontSize) : null,
    gapColour: shown(gap) ? getComputedStyle(gap).color : null,
    mainColour: shown(main) ? getComputedStyle(main).color : null,
    editVisible: shown(document.getElementById("overview-arrive-edit")),
    inlineStyles: box.querySelectorAll("[style]").length,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth
  };
})()`;

export default async function (h) {
  const c = h.config;
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await planOverview(h);
  await h.sleep(300);
  const out = { cases: {} };
  const keys = await h.eval(`(function () {
    return { today: singaporeStamp(new Date()).split("T")[0],
             tomorrow: singaporeStamp(new Date(Date.now() + 86400000)).split("T")[0] };
  })()`);
  out.keys = keys;
  for (const [name, spec] of Object.entries(CASES)) {
    out.cases[name] = await h.eval(`(function () {
      var keys = ${JSON.stringify(keys)};
      var spec = ${JSON.stringify(spec)};
      var value = spec.target ? keys[spec.target[0]] + "T" + spec.target[1] : "";
      plannedArriveBy = value;  // the overview already planned for this value: no new plan
      arriveByInput.value = value;
      journeyComparison.textContent = value ? (spec.pill || "Arrive-by check: On track") : "";
      var data = null;
      if (spec.est) {
        var at = new Date(keys[spec.est[0]] + "T" + spec.est[1] + ":00+08:00").getTime();
        data = { estimated_arrival: new Date(at).toISOString(), arrival_low: new Date(at - 60000).toISOString(),
                 arrival_high: new Date(at + 60000).toISOString() };
      }
      renderArrivalViews(data);
      syncArriveBySummary();
      syncOverviewArrive();
      return ${READ};
    })()`);
  }
  // the other two cards take the same lines from their own render functions (with the minimum state they need)
  out.other = await h.eval(`(function () {
    function text(el) { return el ? el.textContent.replace(/[ \\t\\r\\n]+/g, " ").trim() : null; }
    function line(id) { var el = document.getElementById(id); return el && !el.hidden ? text(el) : null; }
    var keys = ${JSON.stringify(keys)};
    var result = {};
    function render(target) {
      var value = target ? keys.tomorrow + "T" + target : "";
      plannedArriveBy = value;
      arriveByInput.value = value;
      var at = new Date(keys.tomorrow + "T18:18:00+08:00").getTime();
      var iso = new Date(at).toISOString();
      renderArrivalViews({ estimated_arrival: iso, arrival_low: iso, arrival_high: iso });
      onWayState = { train: false, service: "18", stop: selectedBoardingStop, estimateIso: iso,
                     boardedAt: Date.now(), steps: [], alerted: {}, over: false, key: "" };
      renderOnWay();
      newJourneyRow = { stop_name: "Stop", stop_code: "99999", service_no: "18", distance_m: 100, reroute: { stop: {} },
                        estimated_arrival: iso };
      renderNewJourney();
      return { onWay: { main: line("on-way-arrive-value"), gap: line("on-way-arrive-estimate") },
               newJourney: { main: line("new-journey-arrive-value"), gap: line("new-journey-arrive-estimate") } };
    }
    result.withTarget = render("18:30");
    result.noTarget = render("");
    arriveByInput.value = "";
    plannedArriveBy = "";
    return result;
  })()`);
  return out;
}

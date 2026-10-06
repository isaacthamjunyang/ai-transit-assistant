// Opens static/styleguide.html (config.guide, a file:// URL) at 390 px and returns the texts the samples show:
// every probability range, every AI card text, every Leave by tile, so a test can check they are values the app can produce.
export default async function (h) {
  await h.open(h.config.guide, { width: 390, height: 900, dark: false, settle: 900 });
  return await h.eval(`(function () {
    var out = { ranges: [], cards: [], tiles: [] };
    var text = document.body.textContent;
    var found = text.match(/[Rr]ange:?\\s*\\d+\\s*[\\u2013-]\\s*\\d+\\s*%/g) || [];
    found.forEach(function (s) { var n = s.match(/\\d+/g); out.ranges.push([Number(n[0]), Number(n[1]), s]); });
    Array.prototype.slice.call(document.querySelectorAll("[aria-label]")).forEach(function (el) {
      var m = /range (\\d+) to (\\d+) percent/.exec(el.getAttribute("aria-label"));
      if (m) { out.ranges.push([Number(m[1]), Number(m[2]), el.getAttribute("aria-label")]); }
    });
    Array.prototype.slice.call(document.querySelectorAll(".ai-card__text")).forEach(function (el) { out.cards.push(el.textContent); });
    Array.prototype.slice.call(document.querySelectorAll(".leave-tiles > .leave-tile:first-child")).forEach(function (el) {
      var value = el.querySelector(".leave-tile__value");
      var meta = el.querySelector(".leave-tile__meta");
      if (value) { out.tiles.push([value.textContent, meta ? meta.textContent : ""]); }
    });
    out.sensorSamples = Array.prototype.slice.call(document.querySelectorAll(".walk-sensors.is-open")).map(function (el) {
      var rows = {};
      Array.prototype.slice.call(el.querySelectorAll(".walk-sensors__list > div")).forEach(function (row) { rows[row.querySelector("dt").textContent] = row.querySelector("dd").textContent; });
      var why = el.querySelector(".walk-sensors__why");
      var panel = el.querySelector(".walk-sensors__panel");
      var page = el.closest(".walk-page-sample");
      var distance = page ? page.querySelector(".walk-status__distance") : null;
      var state = page ? page.querySelector(".walk-status__state") : null;
      var progress = page ? page.querySelector(".walk-progress") : null;
      var chip = page ? page.querySelector(".sample-walk-map__chip") : null;
      return { rows: rows, why: why ? why.textContent : "", whyFirst: !!why && panel.firstElementChild === why, icon: !!why && !!why.querySelector("svg"),
        distance: distance ? distance.textContent : "", state: state ? state.textContent : "", progress: progress ? progress.value : null, chip: chip ? chip.textContent : "" };
    });
    out.walkSamples = Array.prototype.slice.call(document.querySelectorAll(".walk-page-sample")).map(function (el) {
      var trend = el.querySelector(".walk-chance__trend");
      return [el.querySelector(".walk-status__state").textContent, trend ? trend.textContent : ""];
    });
    return out;
  })()`);
}

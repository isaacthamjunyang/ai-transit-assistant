import { openHome } from "./common.mjs";

// Every alert of the real page rendered the same way: each static .alert in the markup (all pages), the script-built ones
// (the six severities, a pace alert, a train alert, the notification alerts) and the style-guide-free pieces are cloned into one
// visible host with the page's own styles, then measured. config: width, height, dark.
const MEASURE = `(function () {
  var host = document.createElement("div");
  host.id = "alert-host";
  host.className = "alert-stack";
  document.body.appendChild(host);
  var rows = [];
  function add(source, page, el) {
    var copy = el.cloneNode(true);
    copy.removeAttribute("hidden");
    copy.classList.remove("is-suppressed");
    copy.removeAttribute("id");
    Array.prototype.forEach.call(copy.querySelectorAll("[hidden]"), function (n) { if (n.classList.contains("alert__text") || n.classList.contains("alert__meta")) { n.removeAttribute("hidden"); } });
    var text = copy.querySelector(".alert__text");
    if (text && !text.textContent.trim()) { text.textContent = "Sample message text"; }
    host.appendChild(copy);
    rows.push({ source: source, page: page, el: copy });
  }
  var pageOf = function (el) {
    var holder = el.closest("section[id], main, header, #alert-slot, #first-run, #menu-sheet, form");
    return holder ? (holder.id || holder.tagName.toLowerCase()) : "page";
  };
  Array.prototype.forEach.call(document.querySelectorAll(".alert"), function (el) {
    if (el.closest("#alert-host")) { return; }
    add(el.id || "static", pageOf(el), el);
  });
  ALERT_KINDS.forEach(function (kind) {
    add("built-" + kind, "built", buildAlert(kind, "A " + kind + " message that is long enough to wrap onto a second line in a narrow column"));
  });
  add("pace-slower", "pace", paceChip("slower"));
  add("pace-unlikely", "pace", paceChip("unlikely"));
  add("train", "train", buildTrainAlert({ line: "NSL", status: "disrupted", message: "No train service between Bishan and Woodlands." }, 0, "t"));
  var out = rows.map(function (row) {
    var el = row.el;
    var cs = getComputedStyle(el);
    var icon = el.querySelector(":scope > .alert__icon");
    var svg = icon ? icon.querySelector("svg") : null;
    var ir = icon ? icon.getBoundingClientRect() : null;
    var er = el.getBoundingClientRect();
    var hr = host.getBoundingClientRect();
    var kind = (el.className.match(/alert--(\\w+)/) || [])[1] || null;
    return {
      source: row.source, page: row.page, kind: kind,
      radius: cs.borderTopLeftRadius, padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].join(" "),
      border: cs.borderTopWidth + " " + cs.borderTopStyle, borderColor: cs.borderTopColor, color: cs.color, background: cs.backgroundColor,
      fontWeight: cs.fontWeight, fontSize: cs.fontSize,
      hasIcon: !!svg, iconW: ir ? Math.round(ir.width) : 0, iconLeft: ir ? Math.round(ir.left - er.left) : null,
      iconFirst: !!icon && el.firstElementChild === icon,
      width: Math.round(er.width), hostWidth: Math.round(hr.width), right: er.right, viewport: window.innerWidth,
      text: (el.querySelector(".alert__text") || {}).textContent ? el.querySelector(".alert__text").textContent.trim().length > 0 : false,
      inlineStyle: el.querySelectorAll("[style]").length + (el.hasAttribute("style") ? 1 : 0),
      buttons: Array.prototype.filter.call(el.querySelectorAll("button"), function (b) { return b.getClientRects().length > 0; }).map(function (b) { return Math.round(b.getBoundingClientRect().height); })
    };
  });
  return { alerts: out, hostBg: getComputedStyle(document.body).backgroundColor,
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
})()`;

export default async function (h) {
  const c = h.config;
  await openHome(h, { dark: c.dark, width: c.width, height: c.height, permission: "granted" });
  await h.sleep(300);
  return { measured: await h.eval(MEASURE) };
}

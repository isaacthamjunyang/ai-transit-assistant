/* The script half of the one alert component (see .alert in components.css). Every warning, error, info, success,
   neutral and simulated message in the app is an .alert: a rounded rectangle with a left icon and bold text. The icon is
   drawn here, from the severity class, so the markup stays short and every alert gets the same icon in the same place.
   Classic script: the page and the style guide both load it. No styles are set from here, only classes. */
var ALERT_KINDS = ["warning", "error", "info", "success", "neutral", "simulated"];
var ALERT_ICON_BODIES = {
  warning: "<path d=\"M12 4 3 20h18L12 4z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"></path>"
    + "<path d=\"M12 10v4M12 17h.01\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path>",
  error: "<circle cx=\"12\" cy=\"12\" r=\"9\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></circle>"
    + "<path d=\"M9 9l6 6M15 9l-6 6\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path>",
  info: "<circle cx=\"12\" cy=\"12\" r=\"9\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></circle>"
    + "<path d=\"M12 11v6M12 7.5h.01\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path>",
  success: "<circle cx=\"12\" cy=\"12\" r=\"9\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></circle>"
    + "<path d=\"M8 12.5l3 3 5-6\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"></path>"
};

// The icon for a severity: neutral and simulated messages use the info mark.
function alertIcon(kind) {
  var key = ALERT_ICON_BODIES[kind] ? kind : "info";
  return "<svg class=\"icon\" viewBox=\"0 0 24 24\" aria-hidden=\"true\" focusable=\"false\">" + ALERT_ICON_BODIES[key] + "</svg>";
}

function alertKindOf(el) {
  for (var i = 0; i < ALERT_KINDS.length; i++) {
    if (el.classList.contains("alert--" + ALERT_KINDS[i])) {
      return ALERT_KINDS[i];
    }
  }
  return "info";
}

// Fills the icon of one alert from its severity class.
function paintAlert(el) {
  var icon = null;
  for (var i = 0; i < el.children.length; i++) {
    if (el.children[i].classList.contains("alert__icon")) {
      icon = el.children[i];
    }
  }
  if (icon) {
    icon.innerHTML = alertIcon(alertKindOf(el));
  }
}

function paintAlerts(root) {
  Array.prototype.forEach.call((root || document).querySelectorAll(".alert"), paintAlert);
}

// A change of severity swaps the class and the icon together.
function setAlertKind(el, kind) {
  ALERT_KINDS.forEach(function (name) {
    el.classList.remove("alert--" + name);
  });
  el.classList.add("alert--" + (ALERT_KINDS.indexOf(kind) === -1 ? "info" : kind));
  paintAlert(el);
}

// Sets the message of an alert (the first .alert__text inside it) and shows or hides the alert with it.
function setAlertText(el, text) {
  if (!el) {
    return;
  }
  var target = el.querySelector(".alert__text");
  if (target) {
    target.textContent = text;
  }
  el.hidden = text === "";
}

// A new alert for script-built messages: kind, the message and optional {id, role, className, textId, body}.
function buildAlert(kind, text, options) {
  var opts = options || {};
  var box = document.createElement("div");
  box.className = "alert alert--" + (ALERT_KINDS.indexOf(kind) === -1 ? "info" : kind) + (opts.className ? " " + opts.className : "");
  if (opts.id) {
    box.id = opts.id;
  }
  if (opts.role) {
    box.setAttribute("role", opts.role);
  }
  var icon = document.createElement("span");
  icon.className = "alert__icon";
  icon.setAttribute("aria-hidden", "true");
  box.appendChild(icon);
  var copy = document.createElement("p");
  copy.className = "alert__text";
  if (opts.textId) {
    copy.id = opts.textId;
  }
  copy.textContent = text;
  if (opts.body) {
    // an alert with more than one line: the text sits in a body column that the caller can add lines to
    var column = document.createElement("div");
    column.className = "alert__body";
    column.appendChild(copy);
    box.appendChild(column);
  } else {
    box.appendChild(copy);
  }
  paintAlert(box);
  return box;
}

paintAlerts(document);

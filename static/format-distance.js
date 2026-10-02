function formatDistance(meters) {
  var value = Number(meters);
  if (!isFinite(value)) {
    return "";
  }
  var rounded = Math.round(value);
  var space = "\u00a0";
  if (Math.abs(rounded) < 1000) {
    return String(rounded) + space + "m";
  }
  var kilometres = Math.round(rounded / 100) / 10;
  var text = kilometres.toFixed(1);
  if (text.slice(-2) === ".0") {
    text = text.slice(0, -2);
  }
  return text + space + "km";
}

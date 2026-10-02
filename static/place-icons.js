/* Category tiles for search results. Cosmetic only: matched on the display name. */

var PLACE_ICONS = [
  { id: "train", words: ["mrt", "station"] },
  { id: "bag", words: ["mall", "shoppes", "plaza", "square"] },
  { id: "museum", words: ["museum", "gallery"] },
  { id: "plane", words: ["airport", "terminal"] },
  { id: "building", words: ["hotel", "resort", "sands"] },
  { id: "cap", words: ["university", "college", "school", "nus", "ntu"] },
  { id: "cross", words: ["hospital"] },
  { id: "tree", words: ["park", "garden"] }
];

var PLACE_ICON_SVG = {
  train: "<rect x=\"5\" y=\"4\" width=\"14\" height=\"11\" rx=\"3\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></rect><path d=\"M5 11h14M8 15v3M16 15v3M7 19l-2 2M17 19l2 2\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path>",
  bag: "<path d=\"M6 8h12l-1 12H7L6 8z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"></path><path d=\"M9 8V6a3 3 0 0 1 6 0v2\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></path>",
  museum: "<path d=\"M3 10l9-6 9 6M6 10v8M10 10v8M14 10v8M18 10v8M4 18h16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"></path>",
  plane: "<path d=\"M3 13l18-6-5 5 2 7-3-3-4 3 1-5-9-1z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"></path>",
  building: "<rect x=\"5\" y=\"3\" width=\"14\" height=\"18\" rx=\"1\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></rect><path d=\"M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path>",
  cap: "<path d=\"M2 10l10-5 10 5-10 5L2 10z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"></path><path d=\"M6 12v4c2 2 10 2 12 0v-4M22 10v6\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path>",
  cross: "<path d=\"M12 5v14M5 12h14\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path>",
  tree: "<path d=\"M12 21v-5\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"></path><path d=\"M12 16c-4 0-7-3-7-6 3 0 4-1 7-5 3 4 4 5 7 5 0 3-3 6-7 6z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"></path>",
  pin: "<path d=\"M12 21s6-5.2 6-10a6 6 0 1 0-12 0c0 4.8 6 10 6 10z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></path><circle cx=\"12\" cy=\"11\" r=\"2\" fill=\"currentColor\"></circle>"
};

function placeIconId(name) {
  var text = String(name || "").toLowerCase();
  var i;
  var j;
  for (i = 0; i < PLACE_ICONS.length; i += 1) {
    for (j = 0; j < PLACE_ICONS[i].words.length; j += 1) {
      if (text.indexOf(PLACE_ICONS[i].words[j]) !== -1) {
        return PLACE_ICONS[i].id;
      }
    }
  }
  return "pin";
}

function placeIconSvg(id) {
  var body = PLACE_ICON_SVG[id] || PLACE_ICON_SVG.pin;
  return "<svg class=\"icon\" viewBox=\"0 0 24 24\" focusable=\"false\" aria-hidden=\"true\">" + body + "</svg>";
}

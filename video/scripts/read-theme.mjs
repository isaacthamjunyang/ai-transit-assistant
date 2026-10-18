// Reads the colours and the font of the app from static/theme.css (the one source) into src/generated/theme.json, so the video never
// carries a palette of its own. Runs before preview and render (npm scripts do it); safe to run any time.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(resolve(here, "..", "..", "static", "theme.css"), "utf8");

// The body of the first rule whose selector list contains `selector` (ignoring the @media copy).
function block(selector, last = false) {
  const start = last ? css.lastIndexOf(selector) : css.indexOf(selector);
  if (start === -1) throw new Error("theme.css has no " + selector);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
}

function tokens(body) {
  const out = {};
  for (const match of body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) out[match[1]] = match[2].replace(/\/\*.*?\*\//g, "").trim();
  return out;
}

const root = tokens(block(":root {"));
const dark = { ...root, ...tokens(block(".theme-sample-dark {", true)) };
const wanted = ["color-paper", "color-card", "color-ink", "color-muted", "color-line", "color-primary", "color-primary-ink", "color-secondary",
  "color-secondary-ink", "color-link", "status-live", "status-uncertain", "status-unavailable", "fill-success", "fill-warning", "fill-danger",
  "prob-point", "radius-card", "radius-control", "font-stack", "shadow-card"];
const pick = (from) => Object.fromEntries(wanted.filter((k) => from[k] !== undefined).map((k) => [k, from[k]]));
mkdirSync(join(here, "..", "src", "generated"), { recursive: true });
writeFileSync(join(here, "..", "src", "generated", "theme.json"), JSON.stringify({ source: "static/theme.css", dark: pick(dark), light: pick(root) }, null, 2) + "\n");
console.log("theme.json written from static/theme.css");

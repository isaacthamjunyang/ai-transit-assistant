// Drives the real page in headless Edge over the DevTools protocol and records it (CDP screencast) at 390x844 CSS px, device scale 3.
// usage: node driver.mjs <edge.exe> <scene.mjs> <json config>
// The scene module's default export gets a helper `h` and returns a small object that is printed as JSON.
// Recording: h.record(name, async () => { ...taps... }) writes assets/<name>.webm (VP9, 30 fps) using the ffmpeg that ships with Remotion.
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { makeNetwork, stats as networkStats } from "./network.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const videoRoot = resolve(here, "..");
const repoRoot = resolve(videoRoot, "..");
const [, , edgePath, scenePath, configJson] = process.argv;
const config = JSON.parse(configJson || "{}");
const profile = mkdtempSync(join(tmpdir(), "edge-video-"));
const FPS = 30;
const WIDTH = 390;
const HEIGHT = 844;
const SCALE = 3;

const edge = spawn(edgePath, [
  "--headless=new", "--disable-gpu", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
  "--disable-background-timer-throttling", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--force-device-scale-factor=3", "--window-size=390,844",
  `--remote-debugging-port=0`, `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForTarget() {
  let port = 0;
  for (let i = 0; i < 150 && !port; i++) {
    try {
      port = Number(readFileSync(join(profile, "DevToolsActivePort"), "utf8").split(String.fromCharCode(10))[0]);
    } catch (e) { /* not written yet */ }
    if (!port) await sleep(100);
  }
  if (!port) throw new Error("Edge wrote no DevToolsActivePort");
  for (let i = 0; i < 100; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page;
    } catch (e) { /* not up yet */ }
    await sleep(100);
  }
  throw new Error("Edge did not start");
}

// A subtle tap marker, drawn on top of the page only while recording (it is not part of the app): a ring that fades.
// The page's clock: real until a scene calls h.freezeClock(), then fixed at config.clockMs (the same instant the server's clock is frozen at).
const CLOCK_SCRIPT = `(function () {
  var RD = Date, fixed = null;
  function FD() {
    var args = Array.prototype.slice.call(arguments);
    if (!(this instanceof FD)) { return fixed === null ? RD() : new RD(fixed).toString(); }
    if (args.length === 0) { return new RD(fixed === null ? RD.now() : fixed); }
    return new (Function.prototype.bind.apply(RD, [null].concat(args)))();
  }
  FD.prototype = RD.prototype; FD.now = function () { return fixed === null ? RD.now() : fixed; }; FD.UTC = RD.UTC; FD.parse = RD.parse;
  window.Date = FD;
  window.__freezeClock = function (ms) { fixed = ms; };
})();`;

const TAP_MARKER = `(function () {
  if (window.__tapMarker) { return true; }
  var style = document.createElement("style");
  style.textContent = "@keyframes __tap { from { transform: translate(-50%,-50%) scale(.4); opacity: .55; } to { transform: translate(-50%,-50%) scale(1.5); opacity: 0; } }" +
    ".__tap { position: fixed; z-index: 2147483647; width: 44px; height: 44px; border-radius: 50%; border: 3px solid #ffffff; background: rgba(255,255,255,.28); pointer-events: none; animation: __tap .55s ease-out forwards; }";
  document.head.appendChild(style);
  window.__tapMarker = function (x, y) {
    var dot = document.createElement("div");
    dot.className = "__tap"; dot.style.left = x + "px"; dot.style.top = y + "px";
    document.body.appendChild(dot);
    setTimeout(function () { dot.remove(); }, 700);
  };
  return true;
})()`;

async function main() {
  const target = await waitForTarget();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0;
  const waiting = new Map();
  const errors = [];
  let net = null;
  const handle = (data) => {
    if (data.id && waiting.has(data.id)) {
      const { resolve: ok, reject } = waiting.get(data.id);
      waiting.delete(data.id);
      data.error ? reject(new Error(JSON.stringify(data.error))) : ok(data.result);
    } else if (data.method === "Runtime.exceptionThrown") {
      errors.push(data.params.exceptionDetails.exception?.description || data.params.exceptionDetails.text);
    } else if (data.method === "Fetch.requestPaused") {
      if (net) net.onPaused(data.params);
    }
  };
  ws.onmessage = (message) => {
    try { handle(JSON.parse(message.data)); } catch (error) { errors.push("driver: " + error); }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const mine = ++id;
    waiting.set(mine, { resolve, reject });
    ws.send(JSON.stringify({ id: mine, method, params }));
  });

  const prelude = readFileSync(join(repoRoot, "tests", "js", "page_prelude.js"), "utf8");
  const stills = join(videoRoot, "assets", "stills");
  mkdirSync(stills, { recursive: true });

  const h = {
    config, errors, sleep, send,
    async open(url, options = {}) {
      await send("Page.enable");
      await send("Emulation.setFocusEmulationEnabled", { enabled: true }).catch(() => {});
      await send("Page.bringToFront").catch(() => {});
      await send("Runtime.enable");
      net = makeNetwork({ videoRoot, localBase: new URL(config.base).origin + "/", send });
      await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }, { urlPattern: "*tile.openstreetmap.org*", requestStage: "Response" }] });
      // a normal browser User-Agent (the headless one says HeadlessChrome)
      const agent = (await this.eval("navigator.userAgent")).replace("HeadlessChrome", "Chrome");
      await send("Emulation.setUserAgentOverride", { userAgent: agent });
      await send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: 0, mobile: true });
      await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 });
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: options.dark === false ? "light" : "dark" }] });
      await send("Page.addScriptToEvaluateOnNewDocument", { source: CLOCK_SCRIPT });
      const source = prelude.replace("__CONFIG__", JSON.stringify(options.prelude || {}));
      await send("Page.addScriptToEvaluateOnNewDocument", { source });
      await send("Page.navigate", { url });
      for (let i = 0; i < 200; i++) {
        if ((await this.eval("document.readyState")) === "complete") break;
        await sleep(100);
      }
      await this.eval(TAP_MARKER);
      await sleep(options.settle ?? 600);
    },
    async freezeClock() {
      if (!config.clockMs) throw new Error("this scene has no frozen clock");
      await this.eval(`window.__freezeClock(${config.clockMs}); true`);
    },
    async theme(dark) {
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: dark ? "dark" : "light" }] });
    },
    async eval(expression) {
      const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) {
        throw new Error("page error: " + (result.exceptionDetails.exception?.description || result.exceptionDetails.text));
      }
      return result.result.value;
    },
    async until(expression, timeoutMs = 15000, label = expression) {
      const end = Date.now() + timeoutMs;
      while (Date.now() < end) {
        if (await this.eval(expression)) return true;
        await sleep(120);
      }
      throw new Error("timed out waiting for: " + label);
    },
    // A real touch on the centre of an element (found by a CSS selector or a JS expression returning an element).
    async tap(target, options = {}) {
      const expression = typeof target === "string" && !target.startsWith("(") && !target.startsWith("document") && !target.startsWith("window")
        ? `document.querySelector(${JSON.stringify(target)})` : target;
      const rect = await this.eval(`(function () {
        var el = ${expression};
        if (!el) { return null; }
        el.scrollIntoView({ block: "nearest" });
        var r = el.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`);
      if (!rect) throw new Error("nothing to tap: " + target);
      await this.eval(`window.__tapMarker(${rect.x}, ${rect.y}); true`);
      await sleep(options.lead ?? 180);
      await send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: rect.x, y: rect.y }] });
      await sleep(70);
      await send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await sleep(options.after ?? 450);
    },
    // A native select: tap it (so its focus ring shows), then pick the value (headless capture cannot draw the native pop-up list).
    async choose(selector, value) {
      await this.tap(selector, { after: 350 });
      await this.eval(`(function () { var s = document.querySelector(${JSON.stringify(selector)}); s.value = ${JSON.stringify(value)}; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
    },
    // A tap on the first element matching `selector` whose text contains `text`.
    async tapText(selector, text, options = {}) {
      return this.tap(`(Array.prototype.filter.call(document.querySelectorAll(${JSON.stringify(selector)}), function (el) { return el.textContent.indexOf(${JSON.stringify(text)}) !== -1 && el.getClientRects().length > 0; })[0])`, options);
    },
    // Real typing: one key event per character.
    async type(text, delay = 90) {
      for (const char of text) {
        await send("Input.dispatchKeyEvent", { type: "keyDown", text: char, key: char });
        await send("Input.dispatchKeyEvent", { type: "keyUp", key: char });
        await sleep(delay);
      }
    },
    // Wait (up to `timeoutMs`) until the map tiles that are on screen have loaded; never fails a scene.
    async mapsReady(timeoutMs = 9000) {
      const end = Date.now() + timeoutMs;
      while (Date.now() < end) {
        const state = await this.eval(`(function () { var maps = document.querySelectorAll(".leaflet-container"); var tiles = document.querySelectorAll(".leaflet-tile");
          var visible = Array.prototype.filter.call(maps, function (m) { return m.getClientRects().length > 0; });
          var loading = Array.prototype.filter.call(document.querySelectorAll(".leaflet-tile"), function (t) { return !t.complete || t.classList.contains("leaflet-tile-loading"); }).length;
          return { maps: visible.length, tiles: tiles.length, loading: loading }; })()`);
        if (state.maps === 0 || (state.tiles > 0 && state.loading === 0)) { await sleep(250); return state; }
        await sleep(200);
      }
      return null;
    },
    async scrollTo(selector, top = 0) {
      await this.eval(`(function () { var el = document.querySelector(${JSON.stringify(selector)}); if (el) { el.scrollTo({ top: ${top}, behavior: "smooth" }); } return true; })()`);
    },
    async still(name) {
      const shot = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(join(stills, name + ".png"), Buffer.from(shot.data, "base64"));
    },
    // Record what the page does while `action` runs: a loop of full-resolution screenshots (the CDP screencast changes its frame size
    // on some state changes in headless Edge, so it is not used), each stamped with its time and resampled to 30 fps afterwards.
    async record(name, action, options = {}) {
      const lead = options.lead ?? 0.6;
      const tail = options.tail ?? 1.2;
      const got = [];
      let running = true;
      const begun = Date.now();
      const worker = async () => {
        while (running) {
          const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 90, optimizeForSpeed: true });
          got.push({ t: Date.now() / 1000, data: shot.data }); // stamped when it arrives (it shows the page just before that)
        }
      };
      const loop = Promise.all([0, 18, 36].map(async (wait) => { await sleep(wait); await worker(); }));
      await sleep(lead * 1000);
      const started = Date.now();
      try {
        await action();
      } finally {
        await sleep(tail * 1000);
        running = false;
        await loop;
      }
      if (!got.length) throw new Error("no frames for " + name);
      return encode(name, got, (Date.now() - started) / 1000, (Date.now() - begun) / 1000);
    },
  };

  // The ffmpeg that ships with Remotion (node_modules/@remotion/compositor-<platform>/ffmpeg), so nothing is installed globally.
function ffmpegPath() {
  const base = join(videoRoot, "node_modules", "@remotion");
  const dir = readdirSync(base).find((d) => d.startsWith("compositor-"));
  if (!dir) throw new Error("Remotion's compositor package is missing: run npm install in video/");
  return join(base, dir, process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg");
}

// width x height of a JPEG from its SOF marker.
function jpegSize(buffer) {
  let i = 2;
  while (i + 9 < buffer.length) {
    if (buffer[i] !== 0xff) { i++; continue; }
    const marker = buffer[i + 1];
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return [buffer.readUInt16BE(i + 7), buffer.readUInt16BE(i + 5)];
    }
    i += 2 + buffer.readUInt16BE(i + 2);
  }
  return [0, 0];
}

function encode(name, got, seconds, wallSeconds) {
  const sizes = {};
  for (const frame of got) {
    const key = jpegSize(Buffer.from(frame.data, "base64")).join("x");
    sizes[key] = (sizes[key] || 0) + 1;
  }


    got.sort((a, b) => a.t - b.t);
    const t0 = got[0].t;
    const duration = Math.max(got[got.length - 1].t - t0 + 1 / FPS, wallSeconds - 0.15); // a still page sends no frames: hold the last one to the end
    const count = Math.max(2, Math.round(duration * FPS));
    const dir = mkdtempSync(join(tmpdir(), "frames-"));
    let cursor = 0;
    for (let n = 0; n < count; n++) {
      const time = t0 + n / FPS;
      while (cursor + 1 < got.length && got[cursor + 1].t <= time) cursor++;
      writeFileSync(join(dir, `f${String(n).padStart(5, "0")}.jpg`), Buffer.from(got[cursor].data, "base64"));
    }
    const out = join(videoRoot, "assets", `${name}.webm`);
    mkdirSync(dirname(out), { recursive: true });
    const run = spawnSync(ffmpegPath(), [
      "-y", "-framerate", String(FPS), "-i", join(dir, "f%05d.jpg"),
      "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "26", "-pix_fmt", "yuv420p", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", out,
    ], { encoding: "utf8" });
    rmSync(dir, { recursive: true, force: true });
    if (run.status !== 0) throw new Error("ffmpeg failed: " + (run.stderr || "").slice(-600));
    return { name, sizes, file: `assets/${name}.webm`, screencastFrames: got.length, outputFrames: count, seconds: Math.round(count / FPS * 100) / 100,
      realFps: Math.round(got.length / duration * 10) / 10, bytes: statSync(out).size, actionSeconds: Math.round(seconds * 10) / 10 };
  }

  let result;
  try {
    const module = await import(pathToFileURL(scenePath).href);
    result = { ok: true, result: await module.default(h), errors, network: { ...networkStats, blocked: networkStats.blocked.slice(0, 8) } };
  } catch (error) {
    result = { ok: false, error: String(error && error.stack || error), errors };
  }
  console.log("@@RESULT@@" + JSON.stringify(result));
  ws.close();
}

main().catch((error) => {
  console.log("@@RESULT@@" + JSON.stringify({ ok: false, error: String(error && error.stack || error) }));
}).finally(() => {
  if (process.platform === "win32" && edge.pid) {
    try { spawnSync("taskkill", ["/PID", String(edge.pid), "/T", "/F"], { stdio: "ignore" }); } catch (e) { /* already gone */ }
  }
  edge.kill();
  setTimeout(() => {
    try { rmSync(profile, { recursive: true, force: true }); } catch (e) { /* locked profile: leave it to the OS */ }
    process.exit(0);
  }, 500);
});

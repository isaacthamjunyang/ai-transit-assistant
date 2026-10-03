// Drives the real page in headless Edge over the DevTools protocol (no dependencies: Node 22+ has WebSocket).
// usage: node page_driver.mjs <edge.exe> <scenario.mjs> <json config>
// The scenario module's default export gets a helper and returns an object that is printed as JSON.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const [, , edgePath, scenarioPath, configJson] = process.argv;
const config = JSON.parse(configJson || "{}");
const profile = mkdtempSync(join(tmpdir(), "edge-driver-"));

const edge = spawn(edgePath, [
  "--headless=new", "--disable-gpu", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-background-timer-throttling", "--no-first-run", "--no-default-browser-check",
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

async function main() {
  const target = await waitForTarget();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0;
  const waiting = new Map();
  const errors = [];
  const consoleLines = [];
  ws.onmessage = (message) => {
    try { handle(JSON.parse(message.data)); } catch (error) { errors.push("driver: " + error); }
  };
  const handle = (data) => {
    if (data.id && waiting.has(data.id)) {
      const { resolve, reject } = waiting.get(data.id);
      waiting.delete(data.id);
      data.error ? reject(new Error(JSON.stringify(data.error))) : resolve(data.result);
    } else if (data.method === "Runtime.exceptionThrown") {
      errors.push(data.params.exceptionDetails.exception?.description || data.params.exceptionDetails.text);
    } else if (data.method === "Runtime.consoleAPICalled") {
      consoleLines.push(data.params.type + ": " + data.params.args.map((a) => a.value ?? a.description).join(" "));
    } else if (data.method === "Fetch.requestPaused") {
      const url = data.params.request.url;
      const blocked = /tile\.openstreetmap\.org/.test(url) || /fonts\.g/.test(url);
      send(blocked ? "Fetch.fulfillRequest" : "Fetch.continueRequest",
        blocked ? { requestId: data.params.requestId, responseCode: 204, body: "" } : { requestId: data.params.requestId }).catch(() => {});
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const mine = ++id;
    waiting.set(mine, { resolve, reject });
    ws.send(JSON.stringify({ id: mine, method, params }));
  });

  const prelude = readFileSync(join(here, "page_prelude.js"), "utf8");
  const helper = {
    config, errors, consoleLines, sleep, send,
    async open(url, options = {}) {
      await send("Page.enable");
      await send("Emulation.setFocusEmulationEnabled", { enabled: true }).catch(() => {});
      await send("Page.bringToFront").catch(() => {});
      await send("Runtime.enable");
      await send("Performance.enable");
      await send("Fetch.enable", { patterns: [{ urlPattern: "*tile.openstreetmap.org*" }] });
      await send("Emulation.setDeviceMetricsOverride", {
        width: options.width || 390, height: options.height || 844, deviceScaleFactor: 1, mobile: true,
      });
      await send("Emulation.setEmulatedMedia", {
        features: [{ name: "prefers-color-scheme", value: options.dark ? "dark" : "light" }],
      });
      const source = prelude.replace("__CONFIG__", JSON.stringify(options.prelude || {}));
      await send("Page.addScriptToEvaluateOnNewDocument", { source });
      await send("Page.navigate", { url });
      for (let i = 0; i < 200; i++) {
        const state = await this.eval("document.readyState");
        if (state === "complete") break;
        await sleep(100);
      }
      await sleep(options.settle ?? 500);
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
        await sleep(150);
      }
      throw new Error("timed out waiting for: " + label);
    },
    async screenshot(path) {
      const shot = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(path, Buffer.from(shot.data, "base64"));
    },
    async metrics() {
      const out = await send("Performance.getMetrics");
      return Object.fromEntries(out.metrics.map((m) => [m.name, m.value]));
    },
  };

  let result;
  try {
    const module = await import(pathToFileURL(scenarioPath).href);
    result = await module.default(helper);
    result = { ok: true, result, errors, consoleLines: consoleLines.slice(-30) };
  } catch (error) {
    result = { ok: false, error: String(error && error.stack || error), errors, consoleLines: consoleLines.slice(-30) };
  }
  console.log("@@RESULT@@" + JSON.stringify(result));
  ws.close();
}

main().catch((error) => {
  console.log("@@RESULT@@" + JSON.stringify({ ok: false, error: String(error && error.stack || error) }));
}).finally(() => {
  edge.kill();
  setTimeout(() => {
    try { rmSync(profile, { recursive: true, force: true }); } catch (e) { /* locked profile: leave it to the OS */ }
    process.exit(0);
  }, 500);
});

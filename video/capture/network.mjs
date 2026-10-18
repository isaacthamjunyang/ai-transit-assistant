// What the captured page may fetch. Everything is blocked except:
//   - the app itself on its local port (and data: / blob: URLs);
//   - Leaflet 1.9.4, served from the npm copy in video/node_modules (the app asks unpkg for it; nothing leaves the machine);
//   - OpenStreetMap map tiles (tile.openstreetmap.org), fixed zoom levels, only the tiles a scene shows, fetched once by the
//     browser itself with a normal browser User-Agent and kept in video/assets/tiles-cache/<z>/<x>/<y>.png (git-ignored), so a
//     second capture needs no tile request at all. The attribution Leaflet draws on the map stays visible in the clips.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const TILE = /^https:\/\/(?:[abc]\.)?tile\.openstreetmap\.org\/(\d+)\/(\d+)\/(\d+)\.png(?:\?.*)?$/;
const LEAFLET = /^https:\/\/unpkg\.com\/leaflet@1\.9\.4\/dist\/(.+?)(?:\?.*)?$/;
const MIME = { css: "text/css", js: "application/javascript", png: "image/png", map: "application/json" };

export const stats = { tilesFromCache: 0, tilesFetched: 0, tilesFailed: 0, blocked: [] };

export function makeNetwork({ videoRoot, localBase, send }) {
  const tilesDir = join(videoRoot, "assets", "tiles-cache");
  const leafletDir = join(videoRoot, "node_modules", "leaflet", "dist");
  const pendingTiles = new Map(); // requestId -> cache path, for the response stage

  const fulfill = (params, file, type) => send("Fetch.fulfillRequest", {
    requestId: params.requestId, responseCode: 200,
    responseHeaders: [{ name: "Content-Type", value: type }, { name: "Access-Control-Allow-Origin", value: "*" }, { name: "Cache-Control", value: "no-store" }],
    body: readFileSync(file).toString("base64"),
  });

  async function onPaused(params) {
    const url = params.request.url;
    const stage = params.responseStatusCode !== undefined || params.responseErrorReason !== undefined ? "response" : "request";
    if (stage === "response") {
      const file = pendingTiles.get(params.requestId);
      pendingTiles.delete(params.requestId);
      if (file && params.responseStatusCode === 200) {
        const body = await send("Fetch.getResponseBody", { requestId: params.requestId });
        mkdirSync(dirname(file), { recursive: true });
        writeFileSync(file, Buffer.from(body.body, body.base64Encoded ? "base64" : "utf8"));
        stats.tilesFetched += 1;
      } else if (file) {
        stats.tilesFailed += 1;
      }
      return send("Fetch.continueResponse", { requestId: params.requestId });
    }
    if (url.startsWith(localBase) || url.startsWith("data:") || url.startsWith("blob:")) {
      return send("Fetch.continueRequest", { requestId: params.requestId });
    }
    const leaflet = LEAFLET.exec(url);
    if (leaflet) {
      const file = join(leafletDir, leaflet[1]);
      if (existsSync(file)) return fulfill(params, file, MIME[file.split(".").pop()] || "application/octet-stream");
    }
    const tile = TILE.exec(url);
    if (tile) {
      const file = join(tilesDir, tile[1], tile[2], tile[3] + ".png");
      if (existsSync(file)) {
        stats.tilesFromCache += 1;
        return fulfill(params, file, "image/png");
      }
      pendingTiles.set(params.requestId, file);
      // the browser fetches it (its own User-Agent, one request per tile); the response stage stores it
      return send("Fetch.continueRequest", { requestId: params.requestId });
    }
    stats.blocked.push(url.slice(0, 80));
    return send("Fetch.failRequest", { requestId: params.requestId, errorReason: "BlockedByClient" });
  }

  return { onPaused: (params) => onPaused(params).catch(() => {}) };
}

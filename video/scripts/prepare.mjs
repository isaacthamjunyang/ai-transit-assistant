// Runs before preview and render: the app's colours into src/generated/theme.json, and whether assets/music.mp3 exists (and how long
// it is) into src/generated/audio.json (the browser bundle cannot look at the disk itself).
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const run = spawnSync(process.execPath, [join(here, "read-theme.mjs")], { stdio: "inherit" });
if (run.status !== 0) process.exit(run.status ?? 1);

const musicPath = join(root, "assets", "music.mp3");
const music = existsSync(musicPath);
let seconds = 0;
if (music) {
  // the length of the track, read with the ffmpeg that ships with Remotion (it prints "Duration: hh:mm:ss.xx" and exits non-zero)
  const base = join(root, "node_modules", "@remotion");
  const dir = readdirSync(base).find((d) => d.startsWith("compositor-"));
  const exe = join(base, dir, process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg");
  const probe = spawnSync(exe, ["-hide_banner", "-i", musicPath], { encoding: "utf8" });
  const match = /Duration: (\d+):(\d+):(\d+(?:\.\d+)?)/.exec((probe.stderr || "") + (probe.stdout || ""));
  if (!match) throw new Error("could not read the length of assets/music.mp3");
  seconds = Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}
mkdirSync(join(root, "src", "generated"), { recursive: true });
writeFileSync(join(root, "src", "generated", "audio.json"), JSON.stringify({ file: music ? "music.mp3" : null, seconds }) + "\n");
console.log(music ? `music: assets/music.mp3 found (${seconds.toFixed(1)} s)` : "music: assets/music.mp3 not found");

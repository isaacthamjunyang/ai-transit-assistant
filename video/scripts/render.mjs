// npm run render / render:music -> out/<name>.mp4 (H.264). With assets/music.mp3 the track is mixed in (1 s fade in, 2 s fade out,
// looped or trimmed to the video; see src/JustInTime.tsx). Without it the render is muted and this says so.
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const out = process.argv[2] || "out/just-in-time.mp4";

const prepared = spawnSync(process.execPath, [join(here, "prepare.mjs")], { stdio: "inherit" });
if (prepared.status !== 0) process.exit(prepared.status ?? 1);

const music = existsSync(join(root, "assets", "music.mp3"));
if (!music) console.log("\n>>> video/assets/music.mp3 is missing: rendering MUTED (no audio track). Add the file and render again for music.\n");

const cli = join(root, "node_modules", "@remotion", "cli", "remotion-cli.js");
const args = [cli, "render", "src/index.ts", "JustInTime", out, "--public-dir=assets", "--codec=h264", ...(music ? [] : ["--muted"]), ...process.argv.slice(3)];
const done = spawnSync(process.execPath, args, { cwd: root, stdio: "inherit" });
if (done.status === 0) console.log(music ? "Rendered with music: " + out : "Rendered muted: " + out);
process.exit(done.status ?? 1);

// npm run capture [-- 01 05 ...]: runs capture/run_capture.py with the repo's virtual environment (no global install needed).
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const python = [join(repo, ".venv", "Scripts", "python.exe"), join(repo, ".venv", "bin", "python")].find(existsSync);
if (!python) {
  console.error("No .venv found in the repo root. Create it and install requirements.txt first.");
  process.exit(2);
}
const run = spawnSync(python, [join(here, "run_capture.py"), ...process.argv.slice(2)], { stdio: "inherit", cwd: repo });
process.exit(run.status ?? 1);

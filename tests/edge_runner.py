"""Find headless Edge and run a page in it. Browser tests skip (with a reason) when Edge is not installed."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_edge() -> str | None:
    found = shutil.which("msedge")
    if found:
        return found
    for path in CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def dump_dom(url: str, timeout: float = 90.0, budget_ms: int | None = None) -> str:
    """The page's DOM after it loaded, from headless Edge with a throwaway profile."""
    edge = find_edge()
    if edge is None:
        raise RuntimeError("Edge is not installed")
    with tempfile.TemporaryDirectory(prefix="edge-profile-") as profile:
        command = [
            edge,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--allow-file-access-from-files",
            f"--user-data-dir={profile}",
        ]
        if budget_ms:
            command.append(f"--virtual-time-budget={budget_ms}")
        command += ["--dump-dom", url]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    return completed.stdout


def file_url(path: Path) -> str:
    return path.resolve().as_uri()

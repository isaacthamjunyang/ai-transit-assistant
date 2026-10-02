"""The shared distance formatter is a static script the page loads."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static" / "format-distance.js"
PAGE = ROOT / "static" / "index.html"

CASES = [
    (0, "0\u00a0m"),
    (5, "5\u00a0m"),
    (320, "320\u00a0m"),
    (999, "999\u00a0m"),
    (999.6, "1\u00a0km"),
    (1000, "1\u00a0km"),
    (1234, "1.2\u00a0km"),
    (10686, "10.7\u00a0km"),
    (23780, "23.8\u00a0km"),
]


def test_page_loads_the_formatter_module():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "function formatDistance" in source
    assert 'src="format-distance.js"' in PAGE.read_text(encoding="utf-8")


def test_formatter_cases_when_node_is_available():
    node = shutil.which("node")
    if node is None:
        return
    rows = ", ".join(
        "["
        + str(meters)
        + ", ["
        + ", ".join(str(ord(char)) for char in expected)
        + "]]"
        for meters, expected in CASES
    )
    program = (
        SCRIPT.read_text(encoding="utf-8")
        + "\nvar cases = ["
        + rows
        + "];\nfunction codes(text) {\n"
        + "  return Array.prototype.map.call(text, function (ch) { return ch.charCodeAt(0); }).join(',');\n"
        + "}\ncases.forEach(function (row) {\n"
        + "  var got = formatDistance(row[0]);\n"
        + "  var want = row[1].join(',');\n"
        + "  if (codes(got) !== want) throw new Error(String(row[0]) + ' -> ' + codes(got));\n"
        + "});\n"
    )
    completed = subprocess.run(
        [node, "-e", program],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

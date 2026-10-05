"""The style guide builds every sample with one script. A syntax error in it leaves the guide empty, so check it."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[1] / "static" / "styleguide.html"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_style_guide_script_has_no_syntax_error(tmp_path):
    scripts = re.findall(r"<script>(.*?)</script>", GUIDE.read_text(encoding="utf-8"), re.S)
    assert scripts
    for index, source in enumerate(scripts):
        path = tmp_path / f"guide_{index}.js"
        path.write_text(source, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, encoding="utf-8")
        assert done.returncode == 0, done.stderr[-600:]

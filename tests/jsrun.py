"""Running the browser code of examples/webserial: in Node, and in headless Chrome. Each skips the test when missing."""

import html
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WEB = ROOT / "examples" / "webserial"
CHROMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
# Windows installs Chrome off PATH
WIN_CHROMES = [
    Path(p) / "Google" / "Chrome" / "Application" / "chrome.exe"
    for p in filter(None, map(os.environ.get, ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")))
]
NODE_MAJOR = 20  # the browser code uses String.prototype.isWellFormed and the global crypto


def node(script: str, *args: str) -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not installed")
    version = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if int(version.lstrip("v").split(".")[0]) < NODE_MAJOR:
        pytest.skip(f"node {version} is older than {NODE_MAJOR}")
    return subprocess.run(
        [exe, "-e", script, *args], capture_output=True, text=True, encoding="utf-8", check=True, cwd=ROOT
    ).stdout


def chrome() -> str:
    """The installed Chrome, or skip the test."""
    exe = next((p for p in map(shutil.which, CHROMES) if p), None) or next(
        (str(p) for p in WIN_CHROMES if p.is_file()), None
    )
    if exe is None:
        pytest.skip("Chrome is not installed")
    return exe


def chrome_dump(page: Path, profile: Path) -> str:
    """The DOM of `page` (a file) after headless Chrome has run its scripts, timers and promises."""
    exe = chrome()
    # --no-sandbox: CI runners may not allow Chrome's sandbox; the pages are this repository's own files.
    # --virtual-time-budget: the dump waits for timers and promises (crypto.subtle) instead of the load event only.
    cmd = [
        exe,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=60000",
        "--dump-dom",
        page.as_uri(),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True, timeout=120).stdout


def pre(dom: str, element_id: str) -> str:
    """The text of <pre id=element_id> in a dumped DOM."""
    m = re.search(rf'<pre id="{element_id}">(.*?)</pre>', dom, re.S)
    assert m, f"no <pre id={element_id}> in the page: {dom[:2000]}"
    return html.unescape(m[1])

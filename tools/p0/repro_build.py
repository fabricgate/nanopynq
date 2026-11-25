"""P0: build the same base design N times in separate folders and compare .fs hashes.

Usage: uv run python tools/p0/repro_build.py --board tangnano9k [--runs N]
(The Tang Nano 4K base uses GW_JTAG, which the YoWASP tools cannot build; tools/build_base.py builds it.)
Needs `uv sync --extra build`. Prints Markdown tables to stdout.
"""

import argparse
import hashlib
import importlib.metadata as md
import platform
import subprocess
import tempfile
import time
from pathlib import Path

from nanopynq.boards import get_board
from nanopynq.build.gowin import build_gowin

ROOT = Path(__file__).resolve().parents[2]
GATEWARE = ROOT / "gateware"
STAGES = {"yowasp-yosys": "synth", "yowasp-nextpnr-himbaechel-gowin": "pnr", "gowin_pack": "pack"}


def build_once(board: str, out_dir: Path) -> tuple[str, dict[str, float]]:
    times: dict[str, float] = {}

    def timed_run(cmd, **kw):  # build_gowin's `run` hook: time each tool invocation
        t = time.perf_counter()
        r = subprocess.run(cmd, **kw)
        times[STAGES[cmd[0]]] = time.perf_counter() - t
        return r

    sources = sorted((ROOT / "src" / "nanopynq" / "rtl").glob("*.v")) + [GATEWARE / "boards" / board / "top.v"]
    fs = build_gowin(sources, GATEWARE / "boards" / board / f"{board}.cst", get_board(board),
                     out_dir, run=timed_run)
    return hashlib.sha256(fs.read_bytes()).hexdigest(), times


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, choices=["tangnano9k"])
    ap.add_argument("--runs", type=int, default=2)
    a = ap.parse_args()

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(1, a.runs + 1):
            sha, times = build_once(a.board, Path(tmp) / f"run{i}")
            results.append((i, sha, times))

    print(f"## repro_build: {a.board}\n")
    print(f"- OS: {platform.platform()}")
    print(f"- Python: {platform.python_version()}")
    for pkg in ("yowasp-yosys", "yowasp-nextpnr-himbaechel-gowin", "Apycula"):
        print(f"- {pkg}: {md.version(pkg)}")
    print("\n| run | sha256 | synth [s] | pnr [s] | pack [s] | total [s] |")
    print("|---|---|---|---|---|---|")
    for i, sha, t in results:
        print(f"| {i} | `{sha}` | {t['synth']:.1f} | {t['pnr']:.1f} | {t['pack']:.1f} | {sum(t.values()):.1f} |")
    same = len({sha for _, sha, _ in results}) == 1
    print(f"\nResult: {'REPRODUCIBLE (all sha256 identical)' if same else 'NOT REPRODUCIBLE (sha256 differ)'}")
    raise SystemExit(0 if same else 1)


if __name__ == "__main__":
    main()

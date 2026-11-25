"""Program / open / close cycles on the 20K, alternating the base and sdram designs, failures counted by type.

Usage: uv run python tools/p0/linux20k/cycles.py --rounds 300 [--loader nanopynq|openfpgaloader|gowin_sram]

A round: Overlay(design) programs it (nanopynq's own sequence, program_sram; openFPGALoader, which leaves
ftdi_sio on Interface 0; or tools/p0/webusb/gowin_sram.py over nanopynq's Mpsse), reads sys.id / sys.design_id / scratch, closes; then
Overlay(design, download=False) reads sys.design_id and closes. Exit code 1 on any failure.
"""

import argparse
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from nanopynq import Overlay
from nanopynq.program import program_sram, program_sram_openfpgaloader

GOWIN_SRAM = Path(__file__).resolve().parents[1] / "webusb" / "gowin_sram.py"


def gowin_sram(board, bitstream):
    r = subprocess.run([sys.executable, str(GOWIN_SRAM), str(bitstream)], capture_output=True, text=True)
    if r.returncode or "DONE" not in r.stdout:
        raise RuntimeError(f"gowin_sram.py exit {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, required=True)
    ap.add_argument("--loader", choices=["nanopynq", "openfpgaloader", "gowin_sram"], default="nanopynq")
    a = ap.parse_args()
    programmer = {"nanopynq": program_sram, "openfpgaloader": program_sram_openfpgaloader,
                  "gowin_sram": gowin_sram}[a.loader]
    fails, t0 = Counter(), time.monotonic()
    for i in range(a.rounds):
        design = ("base", "sdram")[i % 2]
        for download in (True, False):
            try:
                with Overlay(design, board="tangnano20k", download=download, programmer=programmer) as ol:
                    t = ol._transport
                    got = (t.read(0x0), t.read(0xC))
                    if got != (0x4E505131, ol.manifest.design_id):
                        raise ValueError(f"sys.id / design_id 0x{got[0]:08X} / 0x{got[1]:08X}")
                    t.write(0x8, i)
                    if t.read(0x8) != i:
                        raise ValueError("scratch")
            except Exception as e:
                fails[type(e).__name__] += 1
                print(f"round {i} {design} download={download}: {type(e).__name__}: {e}", flush=True)
        if (i + 1) % 50 == 0:
            print(f"{i + 1} rounds, {time.monotonic() - t0:.0f} s, failures {dict(fails)}", flush=True)
    print(f"done: {a.rounds} rounds ({2 * a.rounds} opens) in {time.monotonic() - t0:.0f} s, "
          f"loader {a.loader}, failures {dict(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

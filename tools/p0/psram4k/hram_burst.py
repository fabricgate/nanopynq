"""Hardware check of src/nanopynq/rtl/hyperram_ctrl.v through hram_burst (one burst at a time): builds
hram_burst_top.v with the patched toolchain, refuses to program unless the placement is the one of
hram_probe (check_placement), then writes random 8-word bursts and reads them back: bursts that cross a
512-word boundary first, then random addresses over the 8 MB. Throwaway; not part of the package.
--mult N (2, 3 or 4) builds hram_fast_top.v instead: everything on a PLL clock of N x 27 MHz, so the
HyperRAM CK is N x 6.75 MHz. Each burst's CYCLES register gives its CS# low time and the bus rate;
RESULT: PASS needs 0 mismatches and every burst's CS# low time under tCSM (4 us).

Usage (Git Bash; OSS/OVL/CHIPDB as for tools/build_base.py, openFPGALoader as for Overlay):
    uv run python tools/p0/psram4k/hram_burst.py [--no-build] [--n 300] [--mult N]
"""

import argparse
import dataclasses
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))

from build_base import build_jtag_local  # noqa: E402
from hram_probe import RENAME, check_placement  # noqa: E402
from nanopynq.boards import get_board  # noqa: E402
from nanopynq.program import program_sram  # noqa: E402
from nanopynq.transport.jtagbridge import JTAGBridge  # noqa: E402

BASE = 0x5000
ADDR, CTRL, STATUS, CYCLES, WBUF, RBUF = (BASE + o for o in (0x0, 0x4, 0x8, 0xC, 0x20, 0x40))
TCSM_US = 4.0


def burst(jb, addr: int, words: list[int] | None = None, n: int = 8) -> list[int]:
    jb.write(ADDR, addr)
    if words is not None:
        jb.write(WBUF, words)
    jb.write(CTRL, 1 | int(words is not None) << 1 | (len(words) if words else n) << 4)
    st = jb.read(STATUS)
    if st & 1:
        raise RuntimeError("still busy")
    if words is not None:
        return []
    if (st >> 8) & 0xF != n:
        raise RuntimeError(f"read got {(st >> 8) & 0xF} of {n} words")
    return jb.read(RBUF, n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--mult", type=int, choices=(2, 3, 4), help="run on a PLL clock of MULT x 27 MHz")
    a = ap.parse_args()
    board = get_board("tangnano4k")
    # No -c: with fewer than 3 byte values unused in the bitstream, Apicula's compressor writes 0x00 as the
    # spare keys, and openFPGALoader then expands every 0x00 data byte ("checksum data is truncated").
    # Seen with the 54 MHz build (reports/report_4k_peripherals.md 3.5).
    board = dataclasses.replace(board, pack_args=[x for x in board.pack_args if x != "-c"])
    f_clk = 27e6 * (a.mult or 1)
    out = HERE / "build" / (f"burst_x{a.mult}" if a.mult else "burst")
    if not a.no_build:
        out.mkdir(parents=True, exist_ok=True)
        top = [HERE / "hram_burst_top.v"]
        if a.mult:
            (out / "mult.v").write_text(f"`define HRAM_MULT {a.mult}\n")
            top = [out / "mult.v", HERE / "hram_fast_top.v"]
        sources = top[:-1] + sorted((ROOT / "src" / "nanopynq" / "rtl").glob("*.v")) + [HERE / "hram_burst.v", top[-1]]
        build_jtag_local(sources, HERE / "hram_probe.cst", board, out, seed=1, synth_extra=RENAME)
    check_placement(out / "pnr.json")
    program_sram(board, out / "top.fs")
    rnd = random.Random(1)
    crossing = [512 * k - d for k in (1, 2, 4096, 8191) for d in (1, 4, 7)]
    addrs = crossing + [rnd.randrange((1 << 22) - 8) for _ in range(a.n - len(crossing))]
    jb = JTAGBridge.open(board.host_link)
    bad, wcyc, rcyc = [], [], []
    try:
        print(f"sysinfo id 0x{jb.read(0x0):08X}")
        t0 = time.monotonic()
        for addr in addrs:
            words = [rnd.randrange(1 << 16) for _ in range(8)]
            burst(jb, addr, words)
            wcyc.append(jb.read(CYCLES))
            got = burst(jb, addr)
            rcyc.append(jb.read(CYCLES))
            if got != words:
                bad.append((addr, words, got))
        dt = time.monotonic() - t0
    finally:
        jb.close()
    for addr, w, g in bad[:3]:
        print(f"mismatch at 0x{addr:06X}: wrote {[hex(x) for x in w]} read {[hex(x) for x in g]}")
    print(f"{len(addrs)} bursts of 8 words ({len(crossing)} crossing a 512-word boundary first): "
          f"{len(bad)} mismatches, {len(addrs) / dt:.0f} write+read pairs/s over JTAG")
    us = lambda c: c / f_clk * 1e6  # noqa: E731
    for name, c in (("write", wcyc), ("read", rcyc)):
        print(f"  {name}: {min(c)}..{max(c)} clocks at {f_clk / 1e6:.0f} MHz = CS# low up to {us(max(c)):.2f} us, "
              f"{16 / us(max(c)):.1f} MB/s per 8-word burst (CK {f_clk / 4e6:.2f} MHz)")
    worst = us(max(wcyc + rcyc))
    ok = not bad and worst < TCSM_US
    print(f"RESULT: {'PASS' if ok else 'FAIL'} ({len(bad)} mismatches, longest CS# low {worst:.2f} us < {TCSM_US} us)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

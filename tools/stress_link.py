"""Hardware stress test of the host link (UART or JTAG) through Overlay: random register round trips.

Usage: uv run python tools/stress_link.py --board tangnano4k [--design DIR] [--n 500] [--no-download]

Mixes, with random.Random(1): a random 32-bit value written to SCRATCH (+0x8) and read back, an ID
read, a random LED bit written and read back, and a read of a random unmapped address (0xDEADBEEF).
Prints the mismatches (first 3), the count and the word round trips per second; exit code 1 on any.
"""

import argparse
import random
import sys
import time

from nanopynq import Overlay

ID, SCRATCH, LEDS = 0x4E505131, 0x8, 0x1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--design", default="base")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args()

    rnd = random.Random(1)
    bad, words = [], 0
    with Overlay(a.design, board=a.board, download=not a.no_download) as ol:
        t = ol._transport
        t0 = time.perf_counter()
        for i in range(a.n):
            kind = rnd.randrange(4)
            if kind == 0:
                v = rnd.getrandbits(32)
                t.write(SCRATCH, v)
                checks = [("scratch", v, t.read(SCRATCH))]
                words += 2
            elif kind == 1:
                checks = [("id", ID, t.read(0x0))]
                words += 1
            elif kind == 2:
                v = rnd.getrandbits(1)
                t.write(LEDS, v)
                checks = [("led", v, t.read(LEDS))]
                words += 2
            else:
                addr = rnd.randrange(0x3000, 1 << 32, 4)
                checks = [(f"unmapped 0x{addr:08X}", 0xDEADBEEF, t.read(addr))]
                words += 1
            bad += [(i, *c) for c in checks if c[1] != c[2]]
        dt = time.perf_counter() - t0
        t.write(LEDS, 0)
    for i, what, want, got in bad[:3]:
        print(f"mismatch #{i} {what}: wanted 0x{want:08X} got 0x{got:08X}")
    print(f"{a.n} operations ({words} words) in {dt:.2f} s -> {words / dt:.0f} words/s, {len(bad)} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

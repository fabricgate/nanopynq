"""P0 spike: how fast can N register reads go when the N+1 DR scans are sent in one USB transfer?
Needs a design with the JTAG bridge on the board (the bundled base, or sccb_probe). Reads the sysinfo
ID (0x0) N times per flush and checks every response. Stops at the first error. Throwaway.

Usage: uv run python tools/p0/cam4k/batch_speed.py [N ...]
"""

import sys
import time

from nanopynq.boards import get_board
from nanopynq.transport.jtagbridge import JTAGBridge, _command

ID = 0x4E505131


def batch_read(jb, addr: int, n: int) -> list[int]:
    for _ in range(n):
        jb._dr(_command(addr))
    jb._dr(0)
    resp = jb.jtag.flush()[1:]
    bad = [r for r in resp if r >> 32 != 1 << 31]
    if bad:
        raise RuntimeError(f"{len(bad)} bad responses, first 0x{bad[0]:016X}")
    return [r & 0xFFFF_FFFF for r in resp]


def main(sizes: list[int]) -> int:
    jb = JTAGBridge.open(get_board("tangnano4k").host_link)
    try:
        for n in sizes:
            reps = max(1, 2048 // n)
            t0 = time.perf_counter()
            for _ in range(reps):
                words = batch_read(jb, 0x0, n)
                if any(w != ID for w in words):
                    print(f"N={n}: wrong data {words[:4]}")
                    return 1
            dt = time.perf_counter() - t0
            print(f"N={n:4d}: {reps * n} words in {dt:.2f} s -> {reps * n / dt:7.0f} words/s "
                  f"({4 * reps * n / dt / 1000:.1f} kB/s)")
    finally:
        jb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main([int(a) for a in sys.argv[1:]] or [1, 4, 16, 32, 64, 128]))

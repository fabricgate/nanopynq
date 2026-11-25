"""P0: UARTBone throughput at each baud rate (needs a board whose bridge runs at that baud).

Usage: uv run python tools/p0/bench_uart.py --port COM5 --baud 115200 1000000 3000000

The bridge baud is a parameter of gateware/boards/<board>/top.v (`.BAUD(...)`); build_gowin has no
define/parameter override, so edit it, rebuild (tools/build_base.py) and load the bitstream for
each baud before measuring it. A baud that does not match the loaded bitstream is reported as
"no response". Run one baud per invocation if you reload the bitstream in between.
"""

import argparse
import time

from nanopynq.errors import TransportTimeout
from nanopynq.transport.uartbone import UARTBone

SYSINFO_ID_ADDR, SYSINFO_ID = 0x0, 0x4E505131


def measure(ub, words: int, duration: float, clock=time.perf_counter) -> tuple[int, float]:
    """Repeat a `words`-word read for `duration` s of `clock`; return (reads, elapsed)."""
    n, t0 = 0, clock()
    while clock() - t0 < duration:
        ub.read(SYSINFO_ID_ADDR, None if words == 1 else words, burst="fixed")
        n += 1
    return n, clock() - t0


def bench(ub, baud: int, duration: float = 2.0, clock=time.perf_counter) -> list[str]:
    """One Markdown table row for `baud`; 'no response' if the device does not answer."""
    try:
        n1, t1 = measure(ub, 1, duration, clock)
        n255, t255 = measure(ub, 255, duration, clock)
    except TransportTimeout:
        return [f"| {baud} | no response | no response |"]
    return [f"| {baud} | {n1 / t1:.0f} | {n255 * 255 * 4 / 1000 / t255:.1f} |"]


def main() -> None:
    import serial

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, nargs="+", default=[115200, 1000000, 3000000])
    ap.add_argument("--duration", type=float, default=2.0)
    a = ap.parse_args()

    print("| baud | 1-word reads [/s] | 255-word burst [kB/s] |")
    print("|---|---|---|")
    for baud in a.baud:
        with serial.Serial(a.port, baud, timeout=0.5) as port:
            ub = UARTBone(port, baud)
            try:
                ident = ub.read(SYSINFO_ID_ADDR)
            except TransportTimeout:
                print(f"| {baud} | no response | no response |")
                continue
            if ident != SYSINFO_ID:
                print(f"| {baud} | bad ID 0x{ident:08x} | - |")
                continue
            print("\n".join(bench(ub, baud, a.duration)), flush=True)


if __name__ == "__main__":
    main()

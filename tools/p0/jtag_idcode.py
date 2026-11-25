"""P0: read the FPGA's JTAG IDCODE from Python through the board's FT2232-compatible
interface A (WinUSB after Zadig on Windows). Feasibility check for the JTAG bridge
candidate (design doc 4.11); it is not part of the nanopynq package.

Run (Git Bash, libusb-1.0.dll from oss-cad-suite on PATH):
    PATH="$OSS/lib:$PATH" \
        uv run --with pyftdi python tools/p0/jtag_idcode.py --expect 0x100981b
"""

import argparse
import sys
import time

from pyftdi.jtag import JtagEngine


def read_idcode(url: str, frequency: float) -> int:
    jtag = JtagEngine(trst=False, frequency=frequency)
    jtag.configure(url)
    try:
        jtag.reset()  # Test-Logic-Reset loads the IDCODE instruction
        return int(jtag.read_dr(32))
    finally:
        jtag.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="ftdi://0x0403:0x6010/1")
    ap.add_argument("--frequency", type=float, default=1e6)
    ap.add_argument("--repeat", type=int, default=100)
    ap.add_argument("--expect", type=lambda s: int(s, 0))
    args = ap.parse_args(argv)

    idcode = read_idcode(args.url, args.frequency)
    print(f"idcode 0x{idcode:08x}")
    if args.expect is not None and idcode != args.expect:
        print(f"expected 0x{args.expect:08x}")
        return 1

    # rough round-trip cost of one JTAG access (open/close excluded)
    jtag = JtagEngine(trst=False, frequency=args.frequency)
    jtag.configure(args.url)
    try:
        t0 = time.perf_counter()
        for _ in range(args.repeat):
            jtag.reset()
            jtag.read_dr(32)
        dt = time.perf_counter() - t0
    finally:
        jtag.close()
    print(f"{args.repeat} reset+read_dr(32) in {dt:.3f} s -> {args.repeat / dt:.0f} accesses/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Program the PLL check design and read its clock meter (reports/report_4k_peripherals.md, step 1).

Build:  tools/build_base.py --board tangnano4k --design pllcheck --out DIR
Run (Git Bash, openFPGALoader and libusb on PATH):
    PATH="$OSS/bin:$OSS/lib:$PATH" uv run python tools/p0/pll4k/pll_check.py DIR
Passes when LOCK is high and every count is within +-1 of the expected edges per 100 ms gate.
"""

import sys
import time

from nanopynq import Overlay

EXPECTED = {"CLKOUT 126 MHz": 12_600_000, "CLKDIV/5 25.2 MHz": 2_520_000, "CLKOUTD 31.5 MHz": 3_150_000}
READS = 5

ol = Overlay(sys.argv[1], board="tangnano4k")
try:
    meter = ol.pll_meter
    time.sleep(0.35)  # the first gate after configuration is partial; wait for two whole ones
    fails = 0
    for k in range(READS):
        status = meter.read(0x0)
        lock, valid = status & 1, (status >> 8) & 0b111
        line = [f"lock={lock} valid={valid:03b}"]
        ok = lock == 1 and valid == 0b111
        for i, (name, want) in enumerate(EXPECTED.items()):
            got = meter.read(0x4 + 4 * i)
            ok &= abs(got - want) <= 1
            line.append(f"{name}: {got} ({got * 10 / 1e6:.4f} MHz, {got - want:+d})")
        fails += not ok
        print(f"#{k} " + " | ".join(line))
        time.sleep(0.1)
finally:
    ol.close()
print("RESULT:", "PASS" if fails == 0 else f"FAIL ({fails}/{READS} reads off)")
sys.exit(1 if fails else 0)

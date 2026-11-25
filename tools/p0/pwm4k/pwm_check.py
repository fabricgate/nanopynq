"""Program the PWM / timer design and measure it (reports/report_4k_peripherals.md, step 5).

Build:  tools/build_base.py --board tangnano4k --design pwm --out DIR
Run (Git Bash, openFPGALoader and libusb on PATH):
    PATH="$OSS/bin:$OSS/lib:$PATH" uv run python tools/p0/pwm4k/pwm_check.py DIR [--keep]
For each setting the clock meter counts the PWM edges in a 100 ms gate (expected 2 700 000 / PERIOD,
+-1), and WRAPS over about a second of host time must match 27 MHz / PERIOD within 2 %. The last
setting is left running: the LED glows dimly (1 kHz, 5 % duty). --keep reuses the design on the board.
"""

import argparse
import sys
import time

from nanopynq import Overlay

F_CLK, GATE = 27_000_000, 2_700_000
SETTINGS = ((27, 9), (270, 135), (2700, 2000), (27000, 1350))  # (PERIOD, DUTY): 1 MHz .. 1 kHz

ap = argparse.ArgumentParser()
ap.add_argument("design")
ap.add_argument("--keep", action="store_true")
args = ap.parse_args()

ol = Overlay(args.design, board="tangnano4k", download=not args.keep)
ok = True
try:
    pwm, meter = ol.pwm, ol.pwm_meter
    for period, duty in SETTINGS:
        pwm.write(0x0, 0)
        pwm.write(0x4, period)
        pwm.write(0x8, duty)
        pwm.write(0x0, 1)
        time.sleep(0.35)  # past the first, partial gate
        counts = [meter.read(0x4) for _ in range(3)]
        want = GATE // period
        w0, t0 = pwm.read(0x10), time.perf_counter()
        time.sleep(1.0)
        w1, t1 = pwm.read(0x10), time.perf_counter()
        rate, want_rate = (w1 - w0) / (t1 - t0), F_CLK / period
        good = all(abs(c - want) <= 1 for c in counts) and abs(rate / want_rate - 1) < 0.02
        ok &= good
        print(f"PERIOD {period:6d} DUTY {duty:5d}: edges/100 ms {counts} (want {want}), "
              f"WRAPS {rate:,.0f}/s (want {want_rate:,.0f}) {'ok' if good else 'NG'}")
finally:
    ol.close()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

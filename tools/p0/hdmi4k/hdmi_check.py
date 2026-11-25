"""Program the HDMI test design and drive it (reports/report_4k_peripherals.md, step 2).

Build:  tools/build_base.py --board tangnano4k --design hdmi --out DIR
Run (Git Bash, openFPGALoader and libusb on PATH):
    PATH="$OSS/bin:$OSS/lib:$PATH" uv run python tools/p0/hdmi4k/hdmi_check.py DIR [--solid RRGGBB] [--keep]
Prints the frame rate from the FRAMES register (expected 60.0: 25.2 MHz / (800 * 525)). With --solid the
screen turns that colour, otherwise it shows the colour bars. --keep skips programming (reuses the design
already on the board).
"""

import argparse
import sys
import time

from nanopynq import Overlay

ap = argparse.ArgumentParser()
ap.add_argument("design")
ap.add_argument("--solid", type=lambda s: int(s, 16))
ap.add_argument("--keep", action="store_true")
args = ap.parse_args()

ol = Overlay(args.design, board="tangnano4k", download=not args.keep)
try:
    video = ol.video
    if args.solid is None:
        video.write(0x0, 0)
    else:
        video.write(0x4, args.solid)
        video.write(0x0, 1)
    f0, t0 = video.read(0x8), time.perf_counter()
    time.sleep(2.0)
    f1, t1 = video.read(0x8), time.perf_counter()
finally:
    ol.close()
fps = (f1 - f0) / (t1 - t0)
mode = "colour bars" if args.solid is None else f"solid #{args.solid:06X}"
print(f"{mode}: {f1 - f0} frames in {t1 - t0:.2f} s = {fps:.1f} fps")
ok = 59.0 <= fps <= 61.0
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

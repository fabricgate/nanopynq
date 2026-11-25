"""20K: Overlay base (programs over openFPGALoader), sys, scratch, LEDs, buttons, round trip.

Usage: uv run python tools/p0/linux20k/check_20k.py [--no-download]
"""
import sys
import time

from nanopynq import Overlay

download = "--no-download" not in sys.argv
t0 = time.perf_counter()
with Overlay("base", board="tangnano20k", download=download) as ol:
    t_open = time.perf_counter() - t0
    t = ol._transport
    print(f"open {t_open:.2f} s (download={download})")
    print(f"id 0x{t.read(0x0):08X} version 0x{t.read(0x4):08X} design_id 0x{t.read(0xC):08X}")
    t.write(0x8, 0x2FFAE1A8)
    print(f"scratch 0x{t.read(0x8):08X}")
    for i, led in enumerate(ol.leds):
        led.on()
        print(f"led{i} on -> reg 0x{t.read(0x1000):08X}")
    for led in ol.leds:
        led.off()
    print(f"leds off -> reg 0x{t.read(0x1000):08X}")
    print("buttons", [b.read() for b in ol.buttons])
    n = 200
    t1 = time.perf_counter()
    for _ in range(n):
        t.read(0x0)
    print(f"round trip {(time.perf_counter() - t1) / n * 1e3:.2f} ms")

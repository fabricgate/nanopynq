"""SDRAM design: random burst writes/reads of 1..1000 words at random word offsets, 200 rounds.

Usage: uv run python tools/p0/linux20k/burst_20k.py
"""
import random
import time

from nanopynq import Overlay

rnd = random.Random(1)
bad = words = 0
with Overlay("sdram", board="tangnano20k") as ol:
    t0 = time.perf_counter()
    for i in range(200):
        n = rnd.randint(1, 1000)
        off = rnd.randrange(0, (8 << 20) // 4 - n) * 4
        data = [rnd.getrandbits(32) for _ in range(n)]
        ol.sdram.write(off, data)
        got = ol.sdram.read(off, n)
        if got != data:
            bad += 1
            print(f"round {i}: n={n} off=0x{off:X} first diff at {next(k for k in range(n) if got[k] != data[k])}")
        words += 2 * n
    dt = time.perf_counter() - t0
print(f"200 rounds, {words} words in {dt:.2f} s -> {words / dt:.0f} words/s, {bad} bad rounds")

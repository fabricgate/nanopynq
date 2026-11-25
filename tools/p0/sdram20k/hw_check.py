"""Hardware check of the Tang Nano 20K SDRAM design (Overlay("sdram", board="tangnano20k")).

Usage: uv run python tools/p0/sdram20k/hw_check.py [--no-download] [--steps 1,2,3,4,5]

Steps: 1 RD_LAT sweep 0..5 (one full 8 MB run each), 2 ten full self-tests, 3 injected error mode,
4 host writes/reads 10 000 random words, 5 self-test on the first 4 MB while the host uses the last 4 MB.
Prints a table per step and exits 1 if a step fails. Step 1 only fails if the default RD_LAT is not
inside the zero-error range. Needs NANOPYNQ_OPENFPGALOADER and the oss-cad-suite lib dir on PATH.
"""

import argparse
import random
import sys
import time

from nanopynq import Overlay
from nanopynq.drivers.sdram import ERRORS

MB = 1 << 20
HALF = 4 * MB


def step1(ol):
    t, rows = ol.sdram_test, []
    default = t.rd_lat
    for lat in range(6):
        t.rd_lat = lat
        r = t.run()
        rows.append((lat, r.errors, r.first_error))
        print(f"  RD_LAT={lat}: errors={r.errors} first={r.first_error}", flush=True)
    t.rd_lat = default
    good = [lat for lat, e, _ in rows if e == 0]
    print(f"  zero-error RD_LAT values: {good}; default {default}")
    return default in good


def step2(ol):
    ok = True
    for i in range(10):
        t0 = time.perf_counter()
        r = ol.sdram_test.run()
        dt = time.perf_counter() - t0
        ok &= r.errors == 0
        print(f"  run {i + 1}: errors={r.errors} {dt:.2f} s", flush=True)
    return ok


def step3(ol):
    start, length = 0x1000, 0x10000
    r = ol.sdram_test.run(passes=3, start=start, length=length, inject=True)
    print(f"  errors={r.errors} first={r.first_error} (expected first offset {start + length // 2:#x})")
    return r.errors == 3 and r.first_error is not None and r.first_error[0] == start + length // 2


def host_roundtrip(ol, offset, n, seed):
    rnd = random.Random(seed)
    data = [rnd.getrandbits(32) for _ in range(n)]
    t0 = time.perf_counter()
    ol.sdram.write(offset, data)
    t1 = time.perf_counter()
    back = ol.sdram.read(offset, n)
    t2 = time.perf_counter()
    return back == data, n / (t1 - t0), n / (t2 - t1)


def step4(ol):
    rnd = random.Random(4)  # 10 000 distinct random word offsets over the whole 8 MB, single-word accesses
    offs = rnd.sample(range(0, 8 * MB, 4), 10000)
    data = [rnd.getrandbits(32) for _ in offs]
    t0 = time.perf_counter()
    for o, v in zip(offs, data):
        ol.sdram.write(o, v)
    t1 = time.perf_counter()
    back = [ol.sdram.read(o) for o in offs]
    t2 = time.perf_counter()
    bad = sum(x != y for x, y in zip(back, data))
    print(f"  mismatches={bad} of {len(offs)}; write {len(offs) / (t1 - t0):.0f} words/s, "
          f"read {len(offs) / (t2 - t1):.0f} words/s")
    return bad == 0


def step5(ol):
    # The transport is not thread safe, so start the test by hand, do the host traffic while it runs
    # (the SDRAM arbiter serves both), then poll until it is done.
    from nanopynq.drivers.sdram import CTRL, LENGTH, PASSES, START, STATUS

    t = ol.sdram_test
    t.write(PASSES, 20)
    t.write(START, 0)
    t.write(LENGTH, HALF // 4)
    t.write(CTRL, 1)
    running = t.read(STATUS) & 1
    ok, w, r = host_roundtrip(ol, HALF + 0x4000, 2000, 5)
    still = t.read(STATUS) & 1
    t_end = time.monotonic() + 120
    while t.read(STATUS) & 1:
        if time.monotonic() > t_end:
            t.write(CTRL, 0b10)
            raise TimeoutError("self-test did not finish")
        time.sleep(0.05)
    passes = t.read(STATUS) >> 16
    errors = t.read(ERRORS)
    print(f"  running at start={running}, still running after host traffic={still}, passes done={passes}")
    print(f"  test errors={errors}; host match={ok} (write {w:.0f}, read {r:.0f} words/s)")
    if not still:
        print("  FAIL: the self-test ended before the host traffic did (no overlap)")
    return errors == 0 and ok and passes == 20 and bool(running) and bool(still)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--steps", default="1,2,3,4,5")
    a = ap.parse_args()
    steps = {1: step1, 2: step2, 3: step3, 4: step4, 5: step5}
    results = {}
    with Overlay("sdram", board="tangnano20k", download=not a.no_download) as ol:
        for n in map(int, a.steps.split(",")):
            print(f"step {n}", flush=True)
            results[n] = steps[n](ol)
    print("\n step | result")
    for n, ok in results.items():
        print(f"  {n}   | {'PASS' if ok else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

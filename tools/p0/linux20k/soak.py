"""Long run of the 20K host link: random register and SDRAM traffic for --minutes, a line per minute.

Usage: uv run python tools/p0/linux20k/soak.py --design base|sdram --minutes 80 [--seed 1]

Every round: a random 32-bit value to sys.scratch (0x8) and back, sys.id and sys.design_id against the .npq,
a random LED bit and back. base: also a random unmapped read (0xDEADBEEF). sdram: also a random burst of
1..1000 words written and read back, and one whole-SDRAM self-test pass every 30 s.
On an exception the link is closed and reopened with download=False (3 tries, then exit 2).
Exit code 1 on any mismatch.
"""

import argparse
import random
import time
from collections import Counter

from nanopynq import Overlay

ID, SCRATCH, DESIGN_ID, LEDS, SDRAM = 0x0, 0x8, 0xC, 0x1000, 0x80_0000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", choices=["base", "sdram"], required=True)
    ap.add_argument("--minutes", type=float, required=True)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    stats, errors = Counter(), Counter()
    ol = Overlay(a.design, board="tangnano20k")
    want_did = ol.manifest.design_id
    t_end = time.monotonic() + a.minutes * 60
    t_log = t_test = time.monotonic()
    t0 = time.monotonic()

    def check(what, want, got):
        stats["checks"] += 1
        if want != got:
            stats["mismatch"] += 1
            if stats["mismatch"] <= 5:
                print(f"mismatch {what}: wanted 0x{want:08X} got 0x{got:08X}", flush=True)

    while time.monotonic() < t_end:
        try:
            t = ol._transport
            v = rnd.getrandbits(32)
            t.write(SCRATCH, v)
            check("scratch", v, t.read(SCRATCH))
            check("id", 0x4E505131, t.read(ID))
            check("design_id", want_did, t.read(DESIGN_ID))
            v = rnd.getrandbits(6)
            t.write(LEDS, v)
            check("leds", v, t.read(LEDS))
            stats["words"] += 7
            if a.design == "base":
                addr = rnd.randrange(0x3000, 1 << 32, 4)
                check(f"unmapped 0x{addr:08X}", 0xDEADBEEF, t.read(addr))
                stats["words"] += 1
            else:
                n = rnd.randint(1, 1000)
                off = rnd.randrange(0, (8 << 20) // 4 - n) * 4
                data = [rnd.getrandbits(32) for _ in range(n)]
                ol.sdram.write(off, data)
                got = ol.sdram.read(off, n)
                stats["words"] += 2 * n
                if got != data:
                    k = next(i for i in range(n) if got[i] != data[i])
                    check(f"burst n={n} off=0x{off:X} word {k}", data[k], got[k])
                else:
                    stats["checks"] += 1
                if time.monotonic() - t_test > 30:
                    r = ol.sdram_test.run(passes=1)
                    stats["selftests"] += 1
                    stats["selftest_errors"] += r.errors
                    t_test = time.monotonic()
        except Exception as e:  # count it, reopen the link, go on
            errors[type(e).__name__] += 1
            print(f"{time.monotonic() - t0:.0f} s {type(e).__name__}: {e}", flush=True)
            ol.close()
            for attempt in range(3):
                try:
                    ol = Overlay(a.design, board="tangnano20k", download=False)
                    break
                except Exception as e2:
                    print(f"  reopen {attempt + 1}: {type(e2).__name__}: {e2}", flush=True)
                    time.sleep(2)
            else:
                return 2
        if time.monotonic() - t_log >= 60:
            t_log = time.monotonic()
            el = t_log - t0
            print(f"{el / 60:.0f} min: {dict(stats)} errors {dict(errors)} {stats['words'] / el:.0f} words/s",
                  flush=True)
    ol.close()
    el = time.monotonic() - t0
    print(f"done {el / 60:.1f} min: {dict(stats)} errors {dict(errors)} {stats['words'] / el:.0f} words/s")
    return 1 if stats["mismatch"] or stats["selftest_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

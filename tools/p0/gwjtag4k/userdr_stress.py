"""Random write/read round trips through IR 0x42 (32-bit user DR)."""
import random, sys
from pathlib import Path
src = (Path(__file__).with_name("jtagdiag_capture.py")).read_text().split("khz = int(")[0]
exec(src)
n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
rnd = random.Random(1)
m = Mpsse(1000); m.drain(); m.tms("11111"); ir(m, 0x42)
bad = 0
prev = None
for i in range(n):
    v = rnd.getrandbits(32)
    got = dr(m, v, 32)
    if prev is not None and got != prev:
        bad += 1
        if bad <= 3: print(f"mismatch #{i}: wrote {prev:#010x} read {got:#010x}")
    prev = v
m.tms("11111"); m.close()
print(f"{n - 1} round trips, {bad} mismatches")

"""Read the GW1NS-4 user flash (FLASH256K, 32 KB) through uflash_reader in the EMCU-shaped design
(reports/report_4k_peripherals.md 3.8). Read only: the design ties PROG / ERASE / NVSTR to 0.

Build:  tools/p0/uflash4k/build_emcu.py DIR
Run (Git Bash, openFPGALoader and libusb on PATH):
    PATH="$OSS/bin:$OSS/lib:$PATH" uv run python tools/p0/uflash4k/uflash_check.py DIR [--keep] [--save F]
        [--expect FILE]
Reads all 8192 words twice and compares; prints a summary (constant? Cortex-M vector table?). --expect
compares the image (little-endian words, as the M3 sees them) with FILE, the rest of the 32 KB is listed.
"""

import argparse
import sys
from collections import Counter

from nanopynq import Overlay

WORDS = 8192

ap = argparse.ArgumentParser()
ap.add_argument("design")
ap.add_argument("--keep", action="store_true")
ap.add_argument("--save")
ap.add_argument("--expect")
args = ap.parse_args()

ol = Overlay(args.design, board="tangnano4k", download=not args.keep)
try:
    ip = ol.uflash
    a = ip._transport.read(ip.description["phys_addr"], WORDS)
    b = ip._transport.read(ip.description["phys_addr"], WORDS)
finally:
    ol.close()

image = b"".join(w.to_bytes(4, "little") for w in a)
if args.save:
    open(args.save, "wb").write(image)
diff = [i for i in range(WORDS) if a[i] != b[i]]
common = Counter(a).most_common(3)
print(f"two reads: {len(diff)} words differ" + (f" (first at word {diff[0]})" if diff else ""))
print("most common words:", ", ".join(f"0x{w:08x} x{n}" for w, n in common))
print("first 8 words:", " ".join(f"{w:08x}" for w in a[:8]))
sp, reset = a[0], a[1]
print(f"vector table? SP 0x{sp:08x} ({'SRAM' if 0x2000_0000 <= sp <= 0x2000_4000 else 'no'}), "
      f"reset 0x{reset:08x} ({'thumb, in flash' if reset & 1 and reset < 0x8000 else 'no'})")
ok = not diff
if args.expect:
    want = open(args.expect, "rb").read()
    n = len(want) // 4
    got = image[:len(want)]
    bad = [i for i in range(n) if got[4 * i:4 * i + 4] != want[4 * i:4 * i + 4]]
    print(f"--expect {args.expect}: {len(want)} bytes, {n} words, {len(bad)} differ"
          + (f" (first at word {bad[0]}: got {got[4*bad[0]:4*bad[0]+4].hex()} want {want[4*bad[0]:4*bad[0]+4].hex()})"
             if bad else ""))
    rest = Counter(a[n:])
    print("after the image:", ", ".join(f"0x{w:08x} x{c}" for w, c in rest.most_common(3)))
    ok &= not bad
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

"""Drive a short JTAG sequence and read back the on-chip recorder of GW_JTAG outputs (jtagdiag/top.v)."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from jtag_mpsse_min import Mpsse

def shift(m, value, nbits):
    nbytes = (nbits - 1) // 8
    rest = nbits - 1 - nbytes * 8
    cmd = bytearray()
    if nbytes:
        cmd += bytes([0x39, nbytes - 1, 0]) + (value & ((1 << (8 * nbytes)) - 1)).to_bytes(nbytes, "little")
    if rest:
        cmd += bytes([0x3B, rest - 1, (value >> (8 * nbytes)) & ((1 << rest) - 1)])
    cmd += bytes([0x6B, 0, (((value >> (nbits - 1)) & 1) << 7) | 0x01]) + b"\x87"
    m.write(bytes(cmd))
    resp = m.read(nbytes + (1 if rest else 0) + 1)
    out = int.from_bytes(resp[:nbytes], "little")
    if rest:
        out |= (resp[nbytes] >> (8 - rest)) << (8 * nbytes)
    out |= ((resp[-1] >> 7) & 1) << (nbits - 1)
    return out

def ir(m, code):
    m.tms("01100"); shift(m, code, 8); m.tms("10")

def dr(m, value, n):
    m.tms("100"); v = shift(m, value, n); m.tms("10"); return v

khz = int(sys.argv[1]) if len(sys.argv) > 1 else 20
nbits = int(sys.argv[2]) if len(sys.argv) > 2 else 4
pattern = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0b1011
m = Mpsse(khz)
m.drain()
m.tms("11111")
ir(m, 0x42)                 # en1 rises at Update-IR -> recorder arms
m.tms("000")                # three idle clocks in Run-Test/Idle
dr(m, pattern, nbits)       # the scan under study
m.tms("000")
ir(m, 0x43)
dr(m, 0, 32)                # first scan: loads entry 0 at Update-DR
rows = []
for _ in range(48):
    rows.append(dr(m, 0, 32))
m.tms("11111")
m.close()
names = ["tck", "tdi", "sdr", "udr", "en1", "en2"]
prev_ts = None
print(f"TCK {khz} kHz, DR {nbits} bits pattern {pattern:#x} (LSB first); ts in 27 MHz ticks")
print(" idx    ts   dt  " + " ".join(f"{n:>3}" for n in names))
for v in rows:
    idx = (v >> 22) & 0x3F
    ts = (v >> 6) & 0xFFFF
    st = v & 0x3F
    dt = "" if prev_ts is None else ts - prev_ts
    prev_ts = ts
    print(f"{idx:4d} {ts:5d} {str(dt):>4}  " + " ".join(f"{(st >> i) & 1:>3}" for i in range(6)))

"""Throwaway: user IR scan + 32-bit DR scan on Tang Nano 4K through the BL702 (MPSSE subset)."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from jtag_mpsse_min import Mpsse

import os
WNEG = int(os.environ.get('WNEG', '1')); RNEG = int(os.environ.get('RNEG', '0'))
OPB = 0x38 | WNEG | (RNEG << 2); OPb = OPB | 0x02; OPT = 0x6A | WNEG | (RNEG << 2)
def shift(m, value, nbits, last_tms=True):
    """Shift nbits LSB-first; the final bit leaves the Shift state with TMS=1. Returns TDO bits."""
    out = 0
    nbytes = (nbits - 1) // 8
    rest = nbits - 1 - nbytes * 8
    cmd = bytearray()
    if nbytes:
        cmd += bytes([OPB, nbytes - 1, 0]) + (value & ((1 << (8 * nbytes)) - 1)).to_bytes(nbytes, "little")
    if rest:
        cmd += bytes([OPb, rest - 1, (value >> (8 * nbytes)) & ((1 << rest) - 1)])
    last = (value >> (nbits - 1)) & 1
    cmd += bytes([OPT, 0, (last << 7) | 0x01])  # one TMS=1 clock, TDI=last bit, read TDO
    cmd += b"\x87"
    m.write(bytes(cmd))
    resp = m.read(nbytes + (1 if rest else 0) + 1)
    out = int.from_bytes(resp[:nbytes], "little")
    if rest:
        out |= (resp[nbytes] >> (8 - rest)) << (8 * nbytes)
    out |= ((resp[-1] >> 7) & 1) << (nbits - 1)
    return out

def ir(m, code, irlen=8):
    m.tms("01100")             # TLR/RTI -> Shift-IR (from Test-Logic-Reset)
    shift(m, code, irlen)      # ends in Exit1-IR
    m.tms("10")                # Update-IR -> Run-Test/Idle

def dr(m, value, n=32):
    m.tms("100")               # RTI -> Select-DR -> Capture-DR -> Shift-DR
    v = shift(m, value, n)     # ends in Exit1-DR
    m.tms("10")                # Update-DR -> RTI
    return v

khz = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
m = Mpsse(khz)
m.drain()
irc = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x42
m.tms("11111")
ir(m, irc)
dr(m, 0)
N = int(os.environ.get('NBITS', '32'))
for pat in (0x00000001, 0x80000000, 0x12345678, 0xFFFFFFFF):
    dr(m, pat, N)
    print(f"N={N} wrote 0x{pat:08x} read 0x{dr(m, 0, N):09x}")
m.tms("11111")
m.close()

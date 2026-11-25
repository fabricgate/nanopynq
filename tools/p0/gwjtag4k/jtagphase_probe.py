"""Phase probe for jtagphase_top.v: shows when the host samples TDO."""
import sys
from pathlib import Path
src = (Path(__file__).with_name("jtagdiag_capture.py")).read_text().split("khz = int(")[0]   # reuse shift/ir/dr only
exec(src)
m = Mpsse(1000); m.drain(); m.tms("11111")
for code in (0x42, 0x43):
    ir(m, code)
    v = dr(m, 0, 16)
    print(f"IR {code:#x}: bits (first sampled first) " + "".join(str((v >> i) & 1) for i in range(16)))
    m.tms("11111")
m.close()

"""Read the results of emcu_cfg.c through the JTAG bridge of emcu_cfg_top.v (reports/report_4k_mcu_tools.md 8).
The design must already be running (written with the firmware by Gowin Programmer op 30 or openFPGALoader
--mcufw); nothing is loaded. Run (Git Bash): PATH="$OSS/bin:$OSS/lib:$PATH" uv run python \
    tools/p0/emcu4k/emcu_cfg_check.py DIR      (DIR from build_emcu_cfg.py)
"""
import sys
import time

from nanopynq import Overlay

ol = Overlay(sys.argv[1], board="tangnano4k", download=False)
try:
    t = ol._transport
    a = t.read(0x10000, 22)
    time.sleep(1)
    b = t.read(0x10000, 22)
finally:
    ol.close()
print("APB2 slots 1..12:", " ".join(f"{x:08x}" for x in a[0:12]))
print(f"result=0x{a[12]:02x} memtest_err={a[14]} heartbeat {a[13]} -> {b[13]} (1 s)")
print("AHB2 registers:", " ".join(f"{x:08x}" for x in a[16:20]), f"| UART0 TX falls {a[20]} | GPIO oen/out 0x{a[21]:08x}")
ok = a[12] == 0x3F and a[14] == 0 and b[13] > a[13] and all(a[i] == 0xC0DE0001 + i for i in range(12))
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

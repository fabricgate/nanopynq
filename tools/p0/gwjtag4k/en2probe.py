"""Check that the enable_er2_o wire (Q1 at (0,0)) is ER2's enable, using en2probe_top.v."""
import sys
from pathlib import Path
exec((Path(__file__).with_name("jtagdiag_capture.py")).read_text().split("khz = int(")[0])

LIVE = ["en1", "en2", "both", "udr", "rti1", "rti2", "tlr", "pdr"]

def status(m):
    ir(m, 0x42)
    v = dr(m, 0, 32)
    live = {n: (v >> i) & 1 for i, n in enumerate(LIVE)}
    return {"c_en2": v >> 24, "c_en1": (v >> 16) & 0xFF, "c_rti2": (v >> 8) & 0xFF, **live}

def show(tag, s):
    print(f"{tag:<34} " + " ".join(f"{k}={v}" for k, v in s.items()))

m = Mpsse(1000)
m.drain()
m.tms("11111")
fails = []
def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond: fails.append(what)

s0 = status(m); show("IR 0x42", s0)
check(s0["en1"] == 1 and s0["en2"] == 0, "while ER1 is selected: en1=1, en2=0")

ir(m, 0x43)
er2 = [dr(m, 0, 32) for _ in range(3)]
print("ER2 reads (tdo_er2_i = en2 & ~en1):", [f"{v:#010x}" for v in er2])
check(all(v == 0xFFFFFFFF for v in er2), "while ER2 is selected: en2=1 and en1=0 during Shift-DR")
m.tms("0000")                                       # Run-Test/Idle with IR 0x43
s1 = status(m); show("after IR 0x43 (+RTI), IR 0x42", s1)
check((s1["c_en2"] - s0["c_en2"]) & 0xFF == 1, "en2 rose once for one IR 0x43 selection")
check((s1["c_en1"] - s0["c_en1"]) & 0xFF == 1, "en1 rose once (re-selected)")
check((s1["c_rti2"] - s0["c_rti2"]) & 0xFF >= 1, "run_test_idle_er2_o rose in RTI with IR 0x43")

ir(m, 0x11); idc = dr(m, 0, 32)                     # IDCODE: neither ER1 nor ER2
m.tms("0000")
s2 = status(m); show("after IR 0x11 (IDCODE), IR 0x42", s2)
print(f"IDCODE {idc:#010x}")
check(s2["c_en2"] == s1["c_en2"], "en2 stays low for a non-user instruction")
check(s2["both"] == 0, "en1 and en2 were never high together")

for _ in range(5):
    ir(m, 0x43); dr(m, 0, 8); ir(m, 0x42)
s3 = status(m); show("after 5 x (IR 0x43, IR 0x42)", s3)
check((s3["c_en2"] - s2["c_en2"]) & 0xFF == 5, "en2 rose 5 times for 5 selections")

m.tms("11111"); m.close()
print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)

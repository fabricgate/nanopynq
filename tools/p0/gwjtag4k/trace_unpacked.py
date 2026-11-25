"""Trace every OBUF input of a gowin_unpack netlist back through the routing assigns.

Usage: trace_unpacked.py <unpacked.v> [wire ...]
With wire names (e.g. R1C1_C1), trace those instead of the OBUF inputs.
A leading backtick in the output marks a wire whose driver the unpacker did not find.
"""
import re, sys

txt = open(sys.argv[1]).read()
drv = {}
for d, s in re.findall(r"assign (\S+) = (\S+);", txt):
    drv.setdefault(d, []).append(s)

def trace(w):
    path, seen = [w], set()
    while w in drv and w not in seen:
        seen.add(w)
        if len(drv[w]) > 1:
            path.append(f"MULTI{drv[w]}")
            break
        w = drv[w][0]
        path.append(w)
    return ' <- '.join(path)

if len(sys.argv) > 2:
    for w in sys.argv[2:]:
        print(trace(w))
else:
    for i, o in re.findall(r"OBUF \S+ \(\s*\.I\((\S+)\),\s*\.O\((\S+)\)", txt):
        print(o, trace(i))

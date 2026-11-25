"""Overlay("base", board="tangnano20k", download=False) on whatever is on the board; logs every bridge
read/write. Load another design first (e.g. openFPGALoader -b tangnano20k <other>.fs).

Usage: uv run python tools/p0/linux20k/mismatch_20k.py
"""
from nanopynq import Overlay
from nanopynq.transport.jtagbridge import JTAGBridge

log = []


def open_logged(link):
    b = JTAGBridge.open(link)
    r, w = b.read, b.write
    b.read = lambda a, *k, **kw: (log.append(f"R 0x{a:X}"), r(a, *k, **kw))[1]
    b.write = lambda a, *k, **kw: (log.append(f"W 0x{a:X}"), w(a, *k, **kw))[1]
    return b


try:
    with Overlay("base", board="tangnano20k", download=False, open_jtag=open_logged) as ol:
        print("opened, no error")
except Exception as e:
    print(f"{type(e).__name__}: {e}")
print("accesses:", log)

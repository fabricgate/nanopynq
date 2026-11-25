"""Linux: the state right after plugging in (ftdi_sio on both interfaces, made without root by attaching
ftdi_sio to Interface 0 again), then Overlay("base", board="tangnano20k").

Usage: uv run python tools/p0/linux20k/fresh_overlay.py [--before-fix]
--before-fix: run with transport/mpsse.py of be83437, the commit before the fix (run from the repository root)."""
import subprocess
import sys

import libusb_package

import nanopynq.transport.mpsse as mp
from nanopynq import Overlay

d = libusb_package.find(idVendor=0x0403, idProduct=0x6010)
if not d.is_kernel_driver_active(0):
    d.attach_kernel_driver(0)
print("if0 ftdi_sio:", d.is_kernel_driver_active(0), "if1 ftdi_sio:", d.is_kernel_driver_active(1))
if "--before-fix" in sys.argv:
    src = subprocess.run(["git", "show", "be83437:src/nanopynq/transport/mpsse.py"], capture_output=True,
                         text=True, check=True).stdout
    exec(compile(src, "mpsse@be83437", "exec"), mp.__dict__)
try:
    with Overlay("base", board="tangnano20k") as ol:
        print(f"OK id 0x{ol._transport.read(0x0):08X} design_id 0x{ol._transport.read(0xC):08X}")
except Exception as e:
    print(f"{type(e).__name__}: {e}")

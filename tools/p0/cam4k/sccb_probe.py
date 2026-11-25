"""P0 spike: build sccb_probe_top.v, program the Tang Nano 4K, start XCLK, read the OV2640 ID over a
bit-banged SCCB and watch VSYNC. Throwaway; not part of the package.

Usage (Git Bash; OSS/OVL/CHIPDB as for tools/build_base.py, openFPGALoader as for Overlay):
    uv run python tools/p0/cam4k/sccb_probe.py [--no-build]
"""

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from build_base import build_jtag_local  # noqa: E402
from nanopynq.boards import get_board  # noqa: E402
from nanopynq.program import program_sram  # noqa: E402
from nanopynq.transport.jtagbridge import JTAGBridge  # noqa: E402

OUTS, INS = 0x1000, 0x2000
LED, SCL_LOW, SDA_LOW, XCLK_ON = 1, 2, 4, 8
WR, RD = 0x60, 0x61  # OV2640 SCCB address


class Sccb:
    def __init__(self, jb):
        self.jb = jb
        self.base = LED | XCLK_ON

    def _set(self, scl_low: bool, sda_low: bool) -> None:
        self.jb.write(OUTS, self.base | (SCL_LOW if scl_low else 0) | (SDA_LOW if sda_low else 0))

    def _sda(self) -> int:
        return (self.jb.read(INS) >> 3) & 1

    def start(self):
        self._set(False, False); self._set(False, True); self._set(True, True)

    def stop(self):
        self._set(True, True); self._set(False, True); self._set(False, False)

    def write_byte(self, b: int) -> int:
        for i in range(7, -1, -1):
            low = not (b >> i) & 1
            self._set(True, low); self._set(False, low); self._set(True, low)
        self._set(True, False); self._set(False, False)
        ack = self._sda()  # 0 = the sensor pulled SDA low
        self._set(True, False)
        return ack

    def read_byte(self) -> int:
        v = 0
        for _ in range(8):
            self._set(False, False)
            v = (v << 1) | self._sda()
            self._set(True, False)
        self._set(False, False); self._set(True, False)  # NACK
        return v

    def write_reg(self, reg: int, val: int) -> tuple[int, int, int]:
        self.start(); acks = (self.write_byte(WR), self.write_byte(reg), self.write_byte(val)); self.stop()
        return acks

    def read_reg(self, reg: int) -> tuple[int, tuple[int, int, int]]:
        self.start(); a = (self.write_byte(WR), self.write_byte(reg)); self.stop()
        self.start(); b = self.write_byte(RD); v = self.read_byte(); self.stop()
        return v, (*a, b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    board = get_board("tangnano4k")
    fs = HERE / "build" / "sccb_probe.fs"
    if not a.no_build:
        fs.parent.mkdir(exist_ok=True)
        sources = sorted((ROOT / "src" / "nanopynq" / "rtl").glob("*.v")) + [HERE / "sccb_probe_top.v"]
        built = build_jtag_local(sources, HERE / "sccb_probe.cst", board, fs.parent, seed=1)  # logs stay in build/
        fs.write_bytes(built.read_bytes())
    program_sram(board, fs)
    jb = JTAGBridge.open(board.host_link)
    try:
        print(f"sysinfo id 0x{jb.read(0x0):08X}")
        jb.write(OUTS, LED)                     # XCLK off, lines released
        print(f"lines before XCLK: SCL={(jb.read(INS) >> 2) & 1} SDA={(jb.read(INS) >> 3) & 1}")
        jb.write(OUTS, LED | XCLK_ON)
        time.sleep(0.2)
        s = Sccb(jb)
        print("select sensor bank (0xFF=0x01), acks:", s.write_reg(0xFF, 0x01))
        for name, reg in (("PIDH", 0x0A), ("PIDL", 0x0B), ("MIDH", 0x1C), ("MIDL", 0x1D)):
            v, acks = s.read_reg(reg)
            print(f"{name} (0x{reg:02X}) = 0x{v:02X}  acks {acks}")
        def watch(label, n=2000):
            ones, edges, last = [0, 0, 0], [0, 0, 0], None
            t0 = time.perf_counter()
            for _ in range(n):
                v = jb.read(INS) >> 4
                bits = [(v >> i) & 1 for i in range(3)]
                for i in range(3):
                    ones[i] += bits[i]
                    edges[i] += last is not None and bits[i] != last[i]
                last = bits
            dt = time.perf_counter() - t0
            for i, name in enumerate(("VSYNC", "HSYNC", "PCLK")):
                print(f"{label} {name}: high {ones[i]}/{n}, {edges[i]} transitions in {dt:.2f} s")

        watch("default")
        print("COM7 soft reset (0x12=0x80), acks:", s.write_reg(0x12, 0x80))
        time.sleep(0.3)
        watch("after reset")
    finally:
        jb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

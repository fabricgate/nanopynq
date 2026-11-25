"""P0 spike: talk to the Tang Nano 4K's embedded HyperRAM through hram_probe (one HyperBus transaction
at a time). Builds hram_probe_top.v with the patched toolchain, refuses to program if any HyperRAM
signal landed on a bonded top-row pad (the JTAG pins live there), reads ID0/ID1/CR0, then finds the
write latency by writing and reading back. Throwaway; not part of the package.

Usage (Git Bash; OSS/OVL/CHIPDB as for tools/build_base.py, openFPGALoader as for Overlay):
    uv run python tools/p0/psram4k/hram_probe.py [--no-build]
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from build_base import build_jtag_local  # noqa: E402
from nanopynq.boards import get_board  # noqa: E402
from nanopynq.program import program_sram  # noqa: E402
from nanopynq.transport.jtagbridge import JTAGBridge  # noqa: E402

BASE = 0x5000
CA_HI, CA_LO, WDATA, CTRL, STATUS, LOG = (BASE + o for o in (0x0, 0x4, 0x8, 0xC, 0x10, 0x40))
SCALAR = ("O_hpram_ck", "O_hpram_ck_n", "O_hpram_cs_n", "O_hpram_reset_n", "IO_hpram_rwds")
RENAME = "cd top; " + "; ".join(f"rename {p} {p}[0]" for p in SCALAR) + "; cd .."


def check_placement(pnr_json: Path) -> None:
    cells = json.loads(pnr_json.read_text())["modules"]["top"]["cells"]
    ios = {n: c["attributes"].get("NEXTPNR_BEL", "") for n, c in cells.items()
           if c["type"] in ("IBUF", "OBUF", "IOBUF", "TBUF")}
    top_row = sorted(b for b in ios.values() if "Y0/" in b)
    # clk (pin 45) and led (pin 10) are the only top-row IOs; the JTAG pads are also on that row
    if len(ios) != 17 or top_row != ["X12Y0/IOBA", "X6Y0/IOBA"]:
        raise SystemExit(f"refusing to program: {len(ios)} IOs, top row {top_row}")
    print("placement: 13 HyperRAM IOs + 2 buttons on row 19, only clk and led on the top row")


def run(jb, ca: int, write: bool = False, data: int = 0, lat: int = 0, maxcyc: int = 24) -> dict:
    jb.write(CA_HI, ca >> 16)
    jb.write(CA_LO, ca & 0xFFFF)
    jb.write(WDATA, data)
    jb.write(CTRL, 1 | int(write) << 1 | (lat & 0xF) << 4 | (maxcyc & 0xFF) << 8)
    st = jb.read(STATUS)
    if st & 1:
        raise RuntimeError("still busy")
    return {"got2": bool(st & 2), "word": st >> 16, "log": jb.read(LOG, 32)}


def show_log(log: list[int], n: int = 32) -> str:
    return " ".join(f"{'R' if v >> 8 & 1 else 'r'}{v & 0xFF:02X}" for v in log[:n])


def mem_ca(read: bool, word_addr: int) -> int:
    return int(read) << 47 | 1 << 45 | (word_addr >> 3) << 16 | (word_addr & 7)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    board = get_board("tangnano4k")
    out = HERE / "build" / "probe"
    if not a.no_build:
        out.mkdir(parents=True, exist_ok=True)
        sources = sorted((ROOT / "src" / "nanopynq" / "rtl").glob("*.v")) + [HERE / "hram_probe.v", HERE / "hram_probe_top.v"]
        build_jtag_local(sources, HERE / "hram_probe.cst", board, out, seed=1, synth_extra=RENAME)
    check_placement(out / "pnr.json")
    program_sram(board, out / "top.fs")
    jb = JTAGBridge.open(board.host_link)
    try:
        print(f"sysinfo id 0x{jb.read(0x0):08X}")
        for name, ca in (("ID0", 0xE000_0000_0000), ("ID1", 0xE000_0000_0001), ("CR0", 0xE000_0100_0000)):
            r = run(jb, ca)
            print(f"{name}: got2={r['got2']} word=0x{r['word']:04X}  log: {show_log(r['log'], 24)}")
        addr = 0x100
        for lat in range(3, 17):
            pattern = (0xA500 | lat << 4 | lat) & 0xFFFF
            run(jb, mem_ca(False, addr), write=True, data=pattern, lat=lat)
            r = run(jb, mem_ca(True, addr))
            print(f"write latency {lat:2d}: wrote 0x{pattern:04X} read 0x{r['word']:04X} got2={r['got2']}"
                  + ("  <== match" if r["word"] == pattern and r["got2"] else ""))
    finally:
        jb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

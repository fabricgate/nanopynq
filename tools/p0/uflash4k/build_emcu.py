"""Build tools/p0/uflash4k/uflash_emcu_top.v with the local GW1NS-4 toolchain (OSS, OVL, CHIPDB as for
tools/build_base.py) into DIR: a design folder (base.fs + manifest.yaml) for uflash_check.py, plus pnr.json
etc. No gowin_pack -c (Apicula's EMCU examples build without it). reports/report_4k_peripherals.md 3.8.

Run: uv run python tools/p0/uflash4k/build_emcu.py DIR
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import build_base as b  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
board = b.get_board("tangnano4k")
board.pack_args[:] = [a for a in board.pack_args if a != "-c"]
src = sorted(b.RTL.glob("*.v")) + [Path(__file__).with_name("uflash_emcu_top.v")]
fs = b.build_jtag_local(src, b.GATEWARE / "boards/tangnano4k/tangnano4k.cst", board, out, 1)
(out / "base.fs").write_bytes(fs.read_bytes())
sha = hashlib.sha256(fs.read_bytes()).hexdigest()
extra = """  uflash: {base: "0x10000", addr_range: "0x8000", type: "nanopynq:uflash_reader:1.0", parameters: {words: 8192}, registers: {}}
"""
text = b.MANIFEST.format(board="tangnano4k", design="uflash_emcu", extra=extra, family=b.DEVICE_FAMILY["tangnano4k"],
                         sha=sha, transport="jtag", leds=b.LED_WIDTH["tangnano4k"], btns=b.BTN_WIDTH)
(out / "manifest.yaml").write_bytes(text.encode("utf-8"))
print("base.fs sha256", sha)

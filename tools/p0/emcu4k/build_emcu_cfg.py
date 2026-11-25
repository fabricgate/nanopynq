"""Build tools/p0/emcu4k/emcu_cfg_top.v (EMCU with every EMPU-IP option wired by hand) into DIR as a design
folder (base.fs + manifest.yaml), with the local GW1NS-4 toolchain (OSS, OVL, CHIPDB as for tools/build_base.py).
No gowin_pack -c (Apicula's EMCU examples build without it). reports/report_4k_mcu_tools.md 8.

Run: uv run python tools/p0/emcu4k/build_emcu_cfg.py DIR
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import build_base as b  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
board = b.get_board("tangnano4k")
board.pack_args[:] = [a for a in board.pack_args if a != "-c"]
src = sorted(b.RTL.glob("*.v")) + [HERE / "emcu_cfg_top.v"]
fs = b.build_jtag_local(src, HERE / "emcu_cfg.cst", board, out, 1)
(out / "base.fs").write_bytes(fs.read_bytes())
sha = hashlib.sha256(fs.read_bytes()).hexdigest()
extra = '  emcu_cfg: {base: "0x10000", type: "local:emcu_cfg:0", registers: {}}\n'
(out / "manifest.yaml").write_bytes(b.MANIFEST.format(
    board="tangnano4k", design="emcu_cfg", extra=extra, family=b.DEVICE_FAMILY["tangnano4k"], sha=sha,
    transport="jtag", leds=b.LED_WIDTH["tangnano4k"], btns=b.BTN_WIDTH).encode("utf-8"))
print("base.fs sha256", sha)

"""Rebuild a bundled design: gateware -> base.fs + base.npq + build.json in data/designs/<board>-<design>.

Usage: uv run python tools/build_base.py --board tangnano9k|tangnano4k|tangnano20k|tangmega138kpro [--design base|camera|camstream|sdram|ddr3] [--seed N]
       [--out DIR]

- The order of spec 5.6: the ips, their design_id (passed to the top's DESIGN_ID), the build, then base.npq.
- yosys reads exactly the .v files listed in DESIGNS, in that order: an unused file in the list changes the .fs
  (reports/report_build_reproducibility.md).
- build.json records how the .fs was built (commit, tools, seed, sources); it is not part of the .npq.

- base: gateware/boards/<board>/top.v. camera (Tang Nano 4K only): camera_top.v + camera.cst.
  camstream (Tang Nano 4K only): camstream_top.v + camstream.cst, with the SiP HyperRAM. Its 1-bit
  HyperRAM ports get the [0] names after synthesis, and the build refuses the bitstream unless the
  HyperRAM sits on the bottom row and the top row holds only the design's own pins (check_placement).

- UART boards (9K, Mega 138K Pro) build with the pinned YoWASP tools (needs `uv sync --extra build`).
- JTAG boards (4K) use GW_JTAG, which the pip tools cannot place on GW1NS-4 yet (it is in Apicula
  master since YosysHQ/apicula#578, not in a release). They build with the oss-cad-suite yosys/nextpnr,
  an Apicula that has it and the chipdb regenerated from that Apicula (tools/p0/gwjtag4k/README.md).
  Set OSS (oss-cad-suite folder), OVL (the folder holding that apycula/) and CHIPDB (chipdb-GW1NS-4 .bin).
- The Tang Nano 20K (GW2A-18C) is a JTAG board too. Its GW_JTAG is in Apicula releases, so OVL can be any recent
  Apicula and CHIPDB the oss-cad-suite's own chipdb-GW2A-18C.bin (report_gwjtag_9k20k.md section 6 used
  oss-cad-suite 2026-11-15, whose nextpnr has the GW2A ALU carry fix 6030081a15).
  sdram (Tang Nano 20K only): sdram_top.v, the onboard SDRAM (window 0x80_0000, self-test 0x3000); SDRAM pins
  are placed by name (tangnano20k.cst unchanged). Packed without -c (NO_COMPRESS) as a precaution: a compressed
  file whose key is 0 is rejected by openFPGALoader v1.2.0's parser (reports/report_sdram20k.md section 4).
- ddr3 (Tang Mega 138K Pro only): ddr3_top.v + ddr3.cst, the onboard DDR3 (1 GiB window at 0x4000_0000, self-test
  0x3000) through e-karge's controller and 2to1 PHY (src/nanopynq/rtl/ddr3/, SystemVerilog; CK 50 MHz). It needs
  the GW5A IO block registers, the 138C IDDR (HAS_5A_IDES) and the GW5A IODELAY with dynamic delay, which only the
  Apicula / nextpnr forks have so far (upstream tools build a .fs that does not work, or fail): set DDR3_OVL (the fork Apicula, with its GW5AST-138C.msgpack.xz), DDR3_CHIPDB (the
  nextpnr chipdb from it) and DDR3_NEXTPNR (the fork nextpnr-himbaechel, e.g. a wrapper around a docker image),
  plus OSS for yosys. How they are built: reports/report_ddr3_138k_survey.md. Its .fs cannot be compressed
  (every byte value occurs), so it is about 35 MB.
--out writes there instead of the bundled design folder (e.g. other seeds for hardware stress tests).
"""

import argparse
import hashlib
import importlib.metadata as md
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from nanopynq.boards import BoardInfo, get_board, npq_family, npq_link
from nanopynq.build.gowin import build_gowin, chparam_design_id
from nanopynq.errors import BuildError
from nanopynq.npq import design_id, write_npq

ROOT = Path(__file__).resolve().parent.parent
GATEWARE = ROOT / "gateware"
RTL = ROOT / "src" / "nanopynq" / "rtl"  # the shared RTL ships in the wheel, for nanopynq build
DEVICE_FAMILY = {
    "tangnano9k": "gw1n-9c",
    "tangnano4k": "gw1ns-4",
    "tangnano20k": "gw2a-18c",
    "tangmega138kpro": "gw5ast-138c",
}
LED_WIDTH = {
    "tangnano9k": 6,
    "tangnano4k": 1,
    "tangnano20k": 6,
    "tangmega138kpro": 6,
}  # keep in sync with gateware/boards/<board>/top.v
BTN_WIDTH = 2

# Address map of src/nanopynq/rtl/base_regs.v and sysinfo.v.
MANIFEST = """\
schema: fabricgate-platform/v1
runtime: nanopynq
board: {board}
device_family: {family}
design_ref: local/{board}-{design}:0.1.0
artifacts: {{bitstream: {{file: base.fs, sha256: {sha}}}}}
transport: {transport}
ips:
  sys:     {{base: "0x0000", type: "nanopynq:sysinfo:1.0", registers: {{id: {{offset: "0x0", width: 32, access: ro}}, version: {{offset: "0x4", width: 32, access: ro}}, scratch: {{offset: "0x8", width: 32, access: rw}}}}}}
  leds:    {{base: "0x1000", type: "nanopynq:gpio_out:1.0", parameters: {{width: {leds}}}, registers: {{data: {{offset: "0x0", width: {leds}, access: rw}}}}}}
  buttons: {{base: "0x2000", type: "nanopynq:gpio_in:1.0", parameters: {{width: {btns}}}, registers: {{data: {{offset: "0x0", width: {btns}, access: ro}}}}}}
{extra}"""
# The bundled designs' sys: sysinfo 1.1 with the design_id register (src/nanopynq/rtl/sysinfo.v).
SYS_1_1 = {
    "base": "0x0000",
    "type": "nanopynq:sysinfo:1.1",
    "registers": {
        "id": {"offset": "0x0", "width": 32, "access": "ro"},
        "version": {"offset": "0x4", "width": 32, "access": "ro"},
        "scratch": {"offset": "0x8", "width": 32, "access": "rw"},
        "design_id": {"offset": "0xc", "width": 32, "access": "ro"},
    },
}
# Inputs whose uncommitted changes make build.json say "dirty".
BUILD_INPUTS = (
    "gateware",
    "src/nanopynq/rtl",
    "tools/build_base.py",
    "src/nanopynq/build",
    "src/nanopynq/npq.py",
    "src/nanopynq/data/boards.yaml",
    "pyproject.toml",
    "uv.lock",
)

# Tang Nano 4K HyperRAM: nextpnr places the SiP pins by the names O_hpram_ck[0] etc., which a [0:0] port
# does not produce, and a [1:0] port would put the non-existent second channel on the JTAG pads
# (reports/report_p0_psram4k.md). So the ports are 1 bit, renamed after synthesis.
HPRAM_SCALAR = ("O_hpram_ck", "O_hpram_ck_n", "O_hpram_cs_n", "O_hpram_reset_n", "IO_hpram_rwds")
HPRAM_RENAME = "cd top; " + "; ".join(f"rename {p} {p}[0]" for p in HPRAM_SCALAR) + "; cd .."
# Where channel 0 lands (report_p0_psram4k.md table 1). The JTAG pads (TDI/TDO/TMS/TCK) and DONE are on the
# top row, so insisting on the exact top row keeps them free.
HPRAM_BELS = {
    "X22Y19/IOBA",
    "X14Y19/IOBB",
    "X14Y19/IOBA",
    "X4Y19/IOBB",
    "X28Y19/IOBB",
    "X6Y19/IOBA",
    "X6Y19/IOBB",
    "X13Y19/IOBA",
    "X13Y19/IOBB",
    "X23Y19/IOBB",
    "X24Y19/IOBA",
    "X24Y19/IOBB",
    "X28Y19/IOBA",
}
# camera.cst's pins on the top row: clk 45, led 10, cam_scl 44, cam_sda 46, cam_vsync 43, cam_href 42,
# cam_pclk 41, cam_d[6] 39, cam_d[7] 40 (the same bels as in the camera overlay)
TOP_ROW_CAMERA = {
    "X12Y0/IOBA",
    "X6Y0/IOBA",
    "X16Y0/IOBB",
    "X12Y0/IOBB",
    "X16Y0/IOBA",
    "X19Y0/IOBB",
    "X19Y0/IOBA",
    "X25Y0/IOBA",
    "X25Y0/IOBB",
}

# Designs packed without -c (see the docstring).
NO_COMPRESS = {"sdram"}

# src/nanopynq/rtl files each top uses (checked by yosys' hierarchy -check in tests/test_build_base.py)
UART_BASE = ("base_regs.v", "base_soc.v", "regbus_gpio.v", "sysinfo.v", "uart_rx.v", "uart_tx.v", "uartbone_bridge.v")
# ddr3_ctrl.sv `includes ddr3_cmd/init/calib.sv as "ddr3/...": yosys gets -incdir RTL (yosys_reads)
DDR3_RTL = (
    "base_regs.v",
    "regbus_gpio.v",
    "sysinfo.v",
    "uart_rx.v",
    "uart_tx.v",
    "uartbone_bridge.v",
    "ddr3_arb.v",
    "ddr3_port.v",
    "ddr3_test.v",
    "ddr3/ddr3_ctrl.sv",
    "ddr3/ddr3_phy_2to1.sv",
)
# Designs built with the Apicula / nextpnr forks: design -> prefix of their environment variables
FORK_TOOLS = {"ddr3": "DDR3_"}
# How the fork Apicula's chip database was built (it cannot be read back from the files): the docker image of
# Apicula's CI, `make apycula/<device>.msgpack.xz` (Gowin 1.9.11/1.9.12 .fse files do not parse)
FORK_DB_IMAGE = "pepijndevos/apicula:1.9.10.03"
JTAG_BASE = ("base_regs.v", "jtag_bridge.v", "regbus_gpio.v", "sysinfo.v")

# design -> (top file, constraint file or None for <board>.cst, {board: src/nanopynq/rtl files read before the top},
#            extra manifest ips, yosys commands after synthesis, placement to insist on: (IOs, top-row bels) or None)
DESIGNS = {
    "base": (
        "top.v",
        None,
        {"tangnano9k": UART_BASE, "tangnano4k": JTAG_BASE, "tangnano20k": JTAG_BASE, "tangmega138kpro": UART_BASE},
        "",
        "",
        None,
    ),
    "camera": (
        "camera_top.v",
        "camera.cst",
        {
            "tangnano4k": (
                "base_regs.v",
                "capture.v",
                "dvp_frontend.v",
                "i2c_master.v",
                "jtag_bridge.v",
                "regbus_gpio.v",
                "sysinfo.v",
            )
        },
        """  cam_i2c:     {base: "0x3000", type: "nanopynq:i2c_master:1.0", registers: {cmd: {offset: "0x0", width: 16, access: wo}, status: {offset: "0x4", width: 16, access: ro}}}
  cam_dvp:     {base: "0x4000", type: "nanopynq:dvp:1.0", registers: {ctrl: {offset: "0x0", width: 4, access: rw}, frames: {offset: "0x4", width: 32, access: ro}, pclks: {offset: "0x8", width: 32, access: ro}, lines: {offset: "0xc", width: 32, access: ro}}}
  cam_capture: {base: "0x10000", addr_range: "0x10000", type: "nanopynq:capture:1.0", parameters: {capacity: 20480}, registers: {ctrl: {offset: "0x0", width: 1, access: wo}, status: {offset: "0x4", width: 3, access: ro}, length: {offset: "0x8", width: 32, access: ro}, capacity: {offset: "0xc", width: 32, access: ro}}}
""",
        "",
        None,
    ),
    "camstream": (
        "camstream_top.v",
        "camstream.cst",
        {
            "tangnano4k": (
                "base_regs.v",
                "dvp_frontend.v",
                "frame_ring.v",
                "hyperram_ctrl.v",
                "i2c_master.v",
                "jtag_bridge.v",
                "regbus_gpio.v",
                "sysinfo.v",
            )
        },
        """  cam_i2c:  {base: "0x3000", type: "nanopynq:i2c_master:1.0", registers: {cmd: {offset: "0x0", width: 16, access: wo}, status: {offset: "0x4", width: 16, access: ro}}}
  cam_dvp:  {base: "0x4000", type: "nanopynq:dvp:1.0", registers: {ctrl: {offset: "0x0", width: 4, access: rw}, frames: {offset: "0x4", width: 32, access: ro}, pclks: {offset: "0x8", width: 32, access: ro}, lines: {offset: "0xc", width: 32, access: ro}}}
  cam_ring: {base: "0x20000", addr_range: "0x2000", type: "nanopynq:frame_ring:1.0", parameters: {slot_words: 16384, slots: 256, window: 1024}, registers: {ctrl: {offset: "0x0", width: 2, access: wo}, wseq: {offset: "0x4", width: 32, access: ro}, rseq: {offset: "0x8", width: 32, access: rw}, dropped: {offset: "0xc", width: 32, access: ro}, fetch: {offset: "0x10", width: 32, access: wo}, status: {offset: "0x14", width: 3, access: ro}, slot_len: {offset: "0x18", width: 24, access: ro}, slot_info: {offset: "0x1c", width: 32, access: ro}}, streams: {video: {dir: read, mtu: 400, register: window, framing: slot-header32}}}
""",
        HPRAM_RENAME,
        (31, TOP_ROW_CAMERA),
    ),
    # Hardware checks (build with --out; not bundled)
    # camhdmi: 31 IOs as camstream + the 8 TMDS pads on the right edge (X37); the same top row
    "camhdmi": (
        "camhdmi_top.v",
        "camhdmi.cst",
        {
            "tangnano4k": (
                "base_regs.v",
                "bus_cdc.v",
                "cam_fb.v",
                "dvp_frontend.v",
                "fb_display.v",
                "hyperram_ctrl.v",
                "i2c_master.v",
                "jtag_bridge.v",
                "regbus_gpio.v",
                "sysinfo.v",
                "tmds_encoder.v",
                "video_timing.v",
            )
        },
        """  cam_i2c:  {base: "0x3000", type: "nanopynq:i2c_master:1.0", registers: {cmd: {offset: "0x0", width: 16, access: wo}, status: {offset: "0x4", width: 16, access: ro}}}
  cam_dvp:  {base: "0x4000", type: "nanopynq:dvp:1.0", registers: {ctrl: {offset: "0x0", width: 4, access: rw}, frames: {offset: "0x4", width: 32, access: ro}, pclks: {offset: "0x8", width: 32, access: ro}, lines: {offset: "0xc", width: 32, access: ro}}}
  cam_fb:   {base: "0x6000", type: "nanopynq:cam_fb:1.0", parameters: {width: 320, height: 240, buffers: 3, hdmi: "640x480@60"}, registers: {ctrl: {offset: "0x0", width: 1, access: rw}, frames: {offset: "0x4", width: 32, access: ro}, bad: {offset: "0x8", width: 32, access: ro}, hframes: {offset: "0xc", width: 32, access: ro}, status: {offset: "0x10", width: 9, access: ro}}}
""",
        HPRAM_RENAME,
        (39, TOP_ROW_CAMERA),
    ),
    "sdram": (
        "sdram_top.v",
        None,
        {
            "tangnano20k": (
                "base_regs.v",
                "jtag_bridge.v",
                "regbus_gpio.v",
                "sdram_arb.v",
                "sdram_ctrl.v",
                "sdram_port.v",
                "sdram_test.v",
                "sysinfo.v",
            )
        },
        """  sdram_test: {base: "0x3000", type: "nanopynq:sdram_test:1.0", registers: {ctrl: {offset: "0x0", width: 3, access: wo}, status: {offset: "0x4", width: 32, access: ro}, passes: {offset: "0x8", width: 16, access: rw}, start: {offset: "0xc", width: 21, access: rw}, length: {offset: "0x10", width: 22, access: rw}, errors: {offset: "0x14", width: 32, access: ro}, first_err_addr: {offset: "0x18", width: 32, access: ro}, first_err_data: {offset: "0x1c", width: 32, access: ro}, first_err_exp: {offset: "0x20", width: 32, access: ro}, rd_lat: {offset: "0x24", width: 3, access: rw}}}
  sdram: {base: "0x800000", addr_range: "0x800000", type: "nanopynq:sdram:1.0", parameters: {size: 8388608}, registers: {}}
""",
        "",
        None,
    ),
    "ddr3": (
        "ddr3_top.v",
        "ddr3.cst",
        {"tangmega138kpro": DDR3_RTL},
        """  ddr3_test: {base: "0x3000", type: "nanopynq:ddr3_test:1.0", registers: {ctrl: {offset: "0x0", width: 3, access: wo}, status: {offset: "0x4", width: 32, access: ro}, passes: {offset: "0x8", width: 16, access: rw}, start: {offset: "0xc", width: 28, access: rw}, length: {offset: "0x10", width: 29, access: rw}, errors: {offset: "0x14", width: 32, access: ro}, first_err_addr: {offset: "0x18", width: 32, access: ro}, first_err_data: {offset: "0x1c", width: 32, access: ro}, first_err_exp: {offset: "0x20", width: 32, access: ro}, calib: {offset: "0x24", width: 32, access: ro}, wr_cycles: {offset: "0x28", width: 32, access: ro}, rd_cycles: {offset: "0x2c", width: 32, access: ro}}}
  ddr3: {base: "0x40000000", addr_range: "0x40000000", type: "nanopynq:ddr3:1.0", parameters: {size: 1073741824}, registers: {}}
""",
        "",
        None,
    ),
    "pllcheck": (
        "pll_top.v",
        None,
        {"tangnano4k": ("base_regs.v", "clk_meter.v", "jtag_bridge.v", "regbus_gpio.v", "sysinfo.v")},
        """  pll_meter: {base: "0x5000", type: "nanopynq:clk_meter:1.0", parameters: {gate_hz: 10, channels: [clkout_126m, clkdiv5_25m2, clkoutd_31m5]}, registers: {status: {offset: "0x0", width: 11, access: ro}, count0: {offset: "0x4", width: 24, access: ro}, count1: {offset: "0x8", width: 24, access: ro}, count2: {offset: "0xc", width: 24, access: ro}}}
""",
        "",
        None,
    ),
    "pwm": (
        "pwm_top.v",
        None,
        {"tangnano4k": ("base_regs.v", "clk_meter.v", "jtag_bridge.v", "pwm_timer.v", "regbus_gpio.v", "sysinfo.v")},
        """  pwm: {base: "0x7000", type: "nanopynq:pwm_timer:1.0", parameters: {clock_hz: 27000000}, registers: {ctrl: {offset: "0x0", width: 1, access: rw}, period: {offset: "0x4", width: 32, access: rw}, duty: {offset: "0x8", width: 32, access: rw}, count: {offset: "0xc", width: 32, access: ro}, wraps: {offset: "0x10", width: 32, access: ro}}}
  pwm_meter: {base: "0x5000", type: "nanopynq:clk_meter:1.0", parameters: {gate_hz: 10, channels: [pwm]}, registers: {status: {offset: "0x0", width: 9, access: ro}, count0: {offset: "0x4", width: 24, access: ro}}}
""",
        "",
        None,
    ),
    "spiflash": (
        "spiflash_top.v",
        "spiflash.cst",
        {"tangnano4k": ("base_regs.v", "jtag_bridge.v", "regbus_gpio.v", "spi_master.v", "sysinfo.v")},
        """  flash_spi: {base: "0x8000", type: "nanopynq:spi_master:1.0", parameters: {sck_hz: 6750000, mode: 0}, registers: {ctrl: {offset: "0x0", width: 3, access: rw}, data: {offset: "0x4", width: 32, access: rw}, status: {offset: "0x8", width: 1, access: ro}}}
""",
        "",
        None,
    ),
    "hdmi": (
        "hdmi_top.v",
        "hdmi.cst",
        {
            "tangnano4k": (
                "base_regs.v",
                "hdmi_testpat.v",
                "jtag_bridge.v",
                "regbus_gpio.v",
                "sysinfo.v",
                "tmds_encoder.v",
                "video_timing.v",
            )
        },
        """  video: {base: "0x6000", type: "nanopynq:hdmi_testpat:1.0", parameters: {width: 640, height: 480, fps: 60}, registers: {ctrl: {offset: "0x0", width: 1, access: rw}, color: {offset: "0x4", width: 24, access: rw}, frames: {offset: "0x8", width: 32, access: ro}}}
""",
        "",
        None,
    ),
}


def sources(board_id: str, design: str) -> list[Path]:
    top, _, rtl, *_ = DESIGNS[design]
    return [RTL / f for f in rtl[board_id]] + [GATEWARE / "boards" / board_id / top]


def _manifest(board_id: str, design: str, sha: str) -> str:
    jtag = get_board(board_id).host_link["kind"] == "jtag"
    return MANIFEST.format(
        board=board_id,
        design=design,
        extra=DESIGNS[design][3],
        family=DEVICE_FAMILY[board_id],
        sha=sha,
        transport="jtag" if jtag else "uart",
        leds=LED_WIDTH[board_id],
        btns=BTN_WIDTH,
    )


def ips(board_id: str, design: str) -> dict:
    """The design's ips in the .npq form: the manifest template's, with sys as sysinfo 1.1 (spec 6)."""
    out = yaml.safe_load(_manifest(board_id, design, "0" * 64))["ips"]
    out["sys"] = SYS_1_1
    return out


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def _oss_path(oss: Path) -> str:
    """PATH for the oss-cad-suite tools: on Windows their DLLs are in lib, and without it they do not start."""
    return os.pathsep.join([str(oss / "bin"), str(oss / "lib"), os.environ["PATH"]])


def _version_line(exe: str | None, *args: str, path: str) -> str | None:
    if exe is None:
        return None
    r = subprocess.run([exe, *args], capture_output=True, text=True, env=dict(os.environ, PATH=path))
    return ((r.stdout or r.stderr).strip().splitlines() or [None])[0]


def tools_record(jtag: bool, env_prefix: str = "") -> dict:
    """The tool versions; no absolute paths (the record ships with the design). env_prefix: the fork tools of
    FORK_TOOLS (their Apicula commit and DB, the chipdb, and what <prefix>NEXTPNR --source-commit prints)."""
    if env_prefix:
        oss, ovl = _env_path("OSS"), _env_path(env_prefix + "OVL")
        chipdb, nextpnr = _env_path(env_prefix + "CHIPDB"), _env_cmd(env_prefix + "NEXTPNR")
        path = _oss_path(oss)
        git = lambda *a: subprocess.run(["git", "-C", str(ovl), *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
        return {
            "oss_cad_suite": (oss / "VERSION").read_text().strip() if (oss / "VERSION").is_file() else None,
            "yosys": _version_line(shutil.which("yosys", path=path), "-V", path=path),
            "apicula": {
                "commit": git("rev-parse", "HEAD"),
                "dirty": bool(git("status", "--porcelain", "-uno")),
                "db": {p.name: _sha256(p) for p in sorted((ovl / "apycula").glob("*.msgpack.xz"))},
                "db_image": FORK_DB_IMAGE,
            },
            "nextpnr": _version_line(nextpnr[0], *nextpnr[1:], "--source-commit", path=path),
            "chipdb": {"file": chipdb.name, "sha256": _sha256(chipdb)},
        }
    if not jtag:
        return {
            p: md.version(p)
            for p in ("yowasp-yosys", "yowasp-nextpnr-himbaechel-gowin", "Apycula", "yowasp-runtime", "wasmtime")
        }
    oss, ovl, chipdb = _env_path("OSS"), _env_path("OVL"), _env_path("CHIPDB")
    path = _oss_path(oss)
    apycula = sorted((ovl / "apycula").rglob("*.py"))
    tree = hashlib.sha256("".join(f"{p.relative_to(ovl).as_posix()} {_sha256(p)}\n" for p in apycula).encode())
    return {
        "oss_cad_suite": (oss / "VERSION").read_text().strip() if (oss / "VERSION").is_file() else None,
        "yosys": _version_line(shutil.which("yosys", path=path), "-V", path=path),
        "nextpnr": _version_line(shutil.which("nextpnr-himbaechel", path=path), "--version", path=path),
        "ovl_apycula_py_sha256": tree.hexdigest(),  # sha256 over "<path> <sha256>" lines of OVL/apycula/**/*.py
        "chipdb": {"file": chipdb.name, "sha256": _sha256(chipdb)},
        "pack": "apycula==0.35 with PYTHONPATH=OVL",
    }


def build_record(board_id: str, design: str, seed: int, srcs: list[Path], cst: Path, fs_sha: str, tools: dict) -> dict:
    return {
        "design": f"{board_id}-{design}",
        "command": f"uv run python tools/build_base.py --board {board_id} --design {design} --seed {seed}",
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no", "--", *BUILD_INPUTS)),
        "seed": seed,
        "sources": [{"file": p.relative_to(ROOT).as_posix(), "sha256": _sha256(p)} for p in [*srcs, cst]],
        "tools": tools,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.machine()}",
        "bitstream_sha256": fs_sha,
    }


def _env_path(name: str) -> Path:
    v = os.environ.get(name)
    if not v or not Path(v).exists():
        sys.exit(f"{name} is not set or does not exist ({v!r}); see this script's docstring")
    return Path(v)


def _env_cmd(name: str) -> list[str]:
    """The command in environment variable `name` (a path); a .sh script goes through bash (Windows cannot run it)."""
    exe = _env_path(name)
    return (
        [shutil.which("bash", path=os.environ.get("PATH")) or "bash", str(exe)] if exe.suffix == ".sh" else [str(exe)]
    )


def check_placement(pnr_json: Path, n_ios: int, top_row: set[str]) -> None:
    """Refuse a placement that does not have exactly n_ios IOs, all 13 HyperRAM channel-0 bels and exactly
    top_row on the top row (Y0). By bel: the IO cell names do not say which port they are."""
    cells = json.loads(Path(pnr_json).read_text())["modules"]["top"]["cells"]
    bels = [
        c["attributes"].get("NEXTPNR_BEL", "") for c in cells.values() if c["type"] in ("IBUF", "OBUF", "IOBUF", "TBUF")
    ]
    on_top = {b for b in bels if "Y0/" in b}
    problems = []
    if len(bels) != n_ios:
        problems.append(f"{len(bels)} IOs, expected {n_ios}")
    if HPRAM_BELS - set(bels):
        problems.append(f"HyperRAM bels not used: {sorted(HPRAM_BELS - set(bels))}")
    if on_top != top_row:
        problems.append(f"top row {sorted(on_top)}, expected {sorted(top_row)}")
    if problems:
        raise SystemExit("refusing this bitstream: " + "; ".join(problems))
    print(f"  placement: {len(bels)} IOs, the 13 HyperRAM ones on row 19, the top row as expected")


def yosys_reads(sources: list[Path]) -> str:
    """yosys read commands, in the order given. Plain Verilog only: one read_verilog (as before). With
    SystemVerilog: one read_verilog per file, .sv with -defer -sv and -I RTL (ddr3_ctrl.sv `includes "ddr3/..."; YoWASP
    yosys 0.70 ignores `read -incdir` there, and takes -I only unquoted). -defer elaborates a module only with the
    parameters of its instance: e-karge's ddr3_phy_2to1 has a GW2A branch whose IODELAY ports the GW5A cell library
    lacks, so elaborated with its defaults (GW5A = 0) it fails hierarchy -check."""
    if not any(Path(s).suffix == ".sv" for s in sources):
        return "read_verilog " + " ".join(f'"{Path(s).as_posix()}"' for s in sources)
    if any(c.isspace() for c in RTL.as_posix()):  # yosys takes -I only unquoted
        raise ValueError(f"the repository path has a space ({RTL}); yosys cannot take it as an include dir")
    sv = f" -defer -sv -I {RTL.as_posix()}"
    return "; ".join(f'read_verilog{sv if Path(s).suffix == ".sv" else ""} "{Path(s).as_posix()}"' for s in sources)


def build_jtag_local(
    sources: list[Path],
    cst: Path,
    board: BoardInfo,
    out_dir: Path,
    seed: int,
    synth_extra: str = "",
    design_id: int | None = None,
    design: str = "base",
    env_prefix: str = "",
) -> Path:
    """Same steps as build_gowin, with the local toolchain: OSS yosys, the Apicula in <prefix>OVL, the nextpnr
    chipdb <prefix>CHIPDB, and nextpnr-himbaechel from OSS, or <prefix>NEXTPNR when the prefix is set (FORK_TOOLS).
    synth_extra: yosys commands run after synth_gowin, before the netlist is written."""
    oss, ovl, chipdb = _env_path("OSS"), _env_path(env_prefix + "OVL"), _env_path(env_prefix + "CHIPDB")
    env = dict(os.environ, PATH=_oss_path(oss), PYTHONPATH=str(ovl))
    synth_json, pnr_json, fs = out_dir / "synth.json", out_dir / "pnr.json", out_dir / "top.fs"
    synth = (
        f"{yosys_reads(sources)}; {chparam_design_id(design_id)}"
        f"synth_gowin -top top {' '.join(board.synth_args)}; {synth_extra}; "
        f'write_json "{synth_json.as_posix()}"'
    )
    pack_args = [a for a in board.pack_args if not (design in NO_COMPRESS and a == "-c")]
    steps = (
        ("synth", [shutil.which("yosys", path=env["PATH"]), "-q", "-p", synth]),
        (
            "pnr",
            [
                *(
                    _env_cmd(env_prefix + "NEXTPNR")
                    if env_prefix
                    else [shutil.which("nextpnr-himbaechel", path=env["PATH"])]
                ),
                "--json",
                synth_json.as_posix(),
                "--write",
                pnr_json.as_posix(),
                "--device",
                board.device,
                *(["--vopt", f"family={board.family}"] if board.family else []),
                "--vopt",
                "cst=" + Path(cst).as_posix(),
                "--chipdb",
                chipdb.as_posix(),
                "--seed",
                str(seed),
            ],
        ),
        (
            "pack",
            [
                "uv",
                "run",
                "-q",
                "--no-project",
                "--with",
                "msgspec",
                "--with",
                "apycula==0.35",
                "python",
                "-m",
                "apycula.gowin_pack",
                "-d",
                board.pack_device,
                *pack_args,
                "-o",
                fs.as_posix(),
                pnr_json.as_posix(),
            ],
        ),
    )
    for step, cmd in steps:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        log = (r.stdout or "") + (r.stderr or "")
        (out_dir / f"{step}.log").write_text(log, encoding="utf-8")
        if r.returncode != 0:
            raise BuildError(step, r.returncode, log)
        if step == "pnr":
            for line in log.splitlines():
                keys = ("GW_JTAG:", "BSRAM:", "PLLVR:", "Max frequency", "dedicated routing")
                if any(k in line for k in keys) or ("timing" in line.lower() and "fail" in line.lower()):
                    print("  nextpnr:", line.strip())
    fs.write_bytes(fs.read_bytes().replace(b"\r\n", b"\n"))  # Apycula writes CRLF on Windows
    return fs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, choices=sorted(DEVICE_FAMILY))
    ap.add_argument("--design", default="base", choices=sorted(DESIGNS))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    board_id, board = args.board, get_board(args.board)
    _top, cst_name, boards, _extra, synth_extra, placement = DESIGNS[args.design]
    if board_id not in boards:
        sys.exit(f"design {args.design!r} is only for {', '.join(boards)}")

    srcs = sources(board_id, args.design)
    cst = GATEWARE / "boards" / board_id / (cst_name or f"{board_id}.cst")
    jtag = board.host_link["kind"] == "jtag"
    the_ips = ips(board_id, args.design)
    did = design_id(the_ips)
    prefix = FORK_TOOLS.get(args.design, "")
    record_tools = tools_record(jtag, prefix)  # before building: a missing OSS / OVL / CHIPDB stops here
    dest = args.out or ROOT / "src" / "nanopynq" / "data" / "designs" / f"{board_id}-{args.design}"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if jtag or prefix:
            fs = build_jtag_local(
                srcs,
                cst,
                board,
                Path(tmp),
                args.seed,
                synth_extra=synth_extra,
                design_id=did,
                env_prefix=prefix,
                design=args.design,
            )
            if placement:
                check_placement(Path(tmp) / "pnr.json", *placement)
        else:
            fs = build_gowin(srcs, cst, board, Path(tmp), seed=args.seed, design_id=did)
        shutil.copyfile(fs, dest / "base.fs")
    sha = _sha256(dest / "base.fs")
    (dest / "manifest.yaml").unlink(missing_ok=True)  # the .npq wins over it; a stale one only misleads
    write_npq(dest / "base.fs", board_id, npq_family(board), npq_link(board, "jtag" if jtag else "uart"), the_ips)
    record = build_record(board_id, args.design, args.seed, srcs, cst, sha, record_tools)
    (dest / "build.json").write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))
    print(f"{dest}\n  base.fs sha256 {sha}\n  design_id 0x{did:08x}")


if __name__ == "__main__":
    main()

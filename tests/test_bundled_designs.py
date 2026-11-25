import sys
from pathlib import Path

import pytest
import yaml

from nanopynq.npq import Npq, load_design
from nanopynq.resolve import resolve_design

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_base

# rebuilt with sysinfo 1.1 and a .npq; the others still need the OSS / OVL / CHIPDB tools to be rebuilt
NPQ = {
    ("tangnano9k", "base"),
    ("tangnano20k", "base"),
    ("tangnano20k", "sdram"),
    ("tangmega138kpro", "base"),
    ("tangmega138kpro", "ddr3"),
}
BUNDLED = [
    ("tangnano9k", "base"),
    ("tangnano4k", "base"),
    ("tangnano20k", "base"),
    ("tangnano4k", "camera"),
    ("tangnano4k", "camstream"),
    ("tangnano20k", "sdram"),
    ("tangmega138kpro", "base"),
    ("tangmega138kpro", "ddr3"),
]


@pytest.mark.parametrize("board, design", BUNDLED)
def test_bundled_design_has_one_kind_of_metadata(board, design):
    d = resolve_design(design, board)
    files = {p.name for p in d.iterdir()}
    if (board, design) in NPQ:
        assert {"base.fs", "base.npq", "build.json"} <= files and "manifest.yaml" not in files
        assert isinstance(load_design(d), Npq)
    else:
        assert "manifest.yaml" in files and not any(f.endswith(".npq") for f in files)


@pytest.mark.parametrize("board, design", sorted(NPQ))
def test_rebuilt_design_matches_the_build_tool(board, design):
    m = load_design(resolve_design(design, board))
    assert m.ips["sys"]["type"] == "nanopynq:sysinfo:1.1"
    assert m.design_id == build_base.design_id(build_base.ips(board, design))
    assert (board, design) != ("tangnano9k", "base") or m.design_id == 0xABF78D8C  # spec 5.4


@pytest.mark.parametrize("board", ["tangnano9k", "tangnano4k", "tangnano20k", "tangmega138kpro"])
def test_bundled_manifest_valid_and_hash_matches(board):
    m = load_design(resolve_design("base", board))
    assert m.board == board and set(m.ips) == {"sys", "leds", "buttons"}


@pytest.mark.parametrize(
    "board,led_width", [("tangnano9k", 6), ("tangnano4k", 1), ("tangnano20k", 6), ("tangmega138kpro", 6)]
)
def test_bundled_ips_match_gateware_address_map(board, led_width):
    ips = load_design(resolve_design("base", board)).ips
    assert (ips["sys"]["phys_addr"], ips["leds"]["phys_addr"], ips["buttons"]["phys_addr"]) == (0x0, 0x1000, 0x2000)
    assert ips["leds"]["parameters"]["width"] == led_width
    assert ips["leds"]["registers"]["data"]["width"] == led_width
    assert ips["buttons"]["parameters"]["width"] == 2
    assert ips["buttons"]["registers"]["data"]["access"] == "ro"
    assert (ips["sys"]["registers"]["id"]["offset"], ips["sys"]["registers"]["version"]["offset"]) == (0x0, 0x4)


@pytest.mark.parametrize("board", ["tangnano9k", "tangnano4k", "tangnano20k", "tangmega138kpro"])
def test_bundled_sys_has_scratch(board):
    regs = load_design(resolve_design("base", board)).ips["sys"]["registers"]
    assert regs["scratch"] == {"offset": 0x8, "width": 32, "access": "rw"}


@pytest.mark.parametrize(
    "board,transport",
    [("tangnano9k", "uart"), ("tangnano4k", "jtag"), ("tangnano20k", "jtag"), ("tangmega138kpro", "uart")],
)
def test_bundled_manifest_transport_matches_host_link(board, transport):
    d = resolve_design("base", board)
    m = load_design(d)
    if isinstance(m, Npq):
        assert m.link["kind"] == transport
    else:
        assert yaml.safe_load((d / "manifest.yaml").read_text(encoding="utf-8"))["transport"] == transport


def test_bundled_camera_manifest_ips():
    ips = load_design(resolve_design("camera", "tangnano4k")).ips
    assert {n: (ip["phys_addr"], ip["type"]) for n, ip in ips.items() if n.startswith("cam_")} == {
        "cam_i2c": (0x3000, "nanopynq:i2c_master:1.0"),
        "cam_dvp": (0x4000, "nanopynq:dvp:1.0"),
        "cam_capture": (0x10000, "nanopynq:capture:1.0"),
    }
    assert ips["cam_capture"]["addr_range"] == 0x10000 and ips["cam_capture"]["parameters"]["capacity"] == 20480
    assert set(ips) >= {"sys", "leds", "buttons"}


def test_bundled_camstream_manifest():
    ips = load_design(resolve_design("camstream", "tangnano4k")).ips
    assert {n: (ip["phys_addr"], ip["type"]) for n, ip in ips.items()} == {
        "sys": (0x0, "nanopynq:sysinfo:1.0"),
        "leds": (0x1000, "nanopynq:gpio_out:1.0"),
        "buttons": (0x2000, "nanopynq:gpio_in:1.0"),
        "cam_i2c": (0x3000, "nanopynq:i2c_master:1.0"),
        "cam_dvp": (0x4000, "nanopynq:dvp:1.0"),
        "cam_ring": (0x20000, "nanopynq:frame_ring:1.0"),
    }
    ring = ips["cam_ring"]
    assert ring["addr_range"] == 0x2000
    assert ring["streams"] == {"video": {"dir": "read", "mtu": 400, "register": "window", "framing": "slot-header32"}}
    assert {r: v["offset"] for r, v in ring["registers"].items()} == {
        "ctrl": 0x0,
        "wseq": 0x4,
        "rseq": 0x8,
        "dropped": 0xC,
        "fetch": 0x10,
        "status": 0x14,
        "slot_len": 0x18,
        "slot_info": 0x1C,
    }
    assert ips["cam_dvp"]["registers"]["pclks"]["offset"] == 0x8


def test_overlay_opens_the_rebuilt_9k_base_with_a_matching_board():
    from nanopynq import Overlay
    from tests.fakes import FakeTransport

    t = FakeTransport({0x0: 0x4E505131, 0x4: 0x0001_0001, 0xC: 0xABF78D8C})
    ol = Overlay(
        "base",
        board="tangnano9k",
        download=False,
        transport=t,
        programmer=pytest.fail,
        open_port=pytest.fail,
        open_jtag=pytest.fail,
    )
    assert ol.manifest.design_id == 0xABF78D8C


def _jtag_20k(regs):
    from nanopynq import Overlay
    from nanopynq.transport.jtagbridge import JTAGBridge
    from tests.fakes import FakeJtagBridgeDevice

    dev = FakeJtagBridgeDevice(regs)
    return dev, lambda: Overlay(
        "base",
        board="tangnano20k",
        download=False,
        programmer=pytest.fail,
        open_port=pytest.fail,
        open_jtag=lambda link: JTAGBridge(dev),
    )


def test_overlay_opens_the_rebuilt_20k_base_over_jtag_with_a_matching_board():
    dev, open_ = _jtag_20k({0: 0x4E505131, 1: 0x0001_0001, 3: 0xABF78D8C})
    ol = open_()
    assert ol.manifest.design_id == 0xABF78D8C
    ol.leds[0].on()
    assert dev.regs[0x1000 // 4] == 1


def test_overlay_stops_on_a_20k_running_another_design_before_writing():
    from nanopynq.errors import DesignMismatch

    regs = {0: 0x4E505131, 1: 0x0001_0001, 3: 0x12345678}
    dev, open_ = _jtag_20k(dict(regs))
    with pytest.raises(DesignMismatch, match="0x12345678"):
        open_()
    assert dev.regs == regs and dev.closed == 1


def test_bundled_sdram_manifest():
    ips = load_design(resolve_design("sdram", "tangnano20k")).ips
    assert {n: (ip["phys_addr"], ip["type"]) for n, ip in ips.items()} == {
        "sys": (0x0, "nanopynq:sysinfo:1.1"),
        "leds": (0x1000, "nanopynq:gpio_out:1.0"),
        "buttons": (0x2000, "nanopynq:gpio_in:1.0"),
        "sdram_test": (0x3000, "nanopynq:sdram_test:1.0"),
        "sdram": (0x800000, "nanopynq:sdram:1.0"),
    }
    assert ips["sdram"]["addr_range"] == 0x800000 and ips["sdram"]["parameters"]["size"] == 8388608
    regs = {r: (v["offset"], v["width"], v["access"]) for r, v in ips["sdram_test"]["registers"].items()}
    assert regs == {
        "ctrl": (0x0, 3, "wo"),
        "status": (0x4, 32, "ro"),
        "passes": (0x8, 16, "rw"),
        "start": (0xC, 21, "rw"),
        "length": (0x10, 22, "rw"),
        "errors": (0x14, 32, "ro"),
        "first_err_addr": (0x18, 32, "ro"),
        "first_err_data": (0x1C, 32, "ro"),
        "first_err_exp": (0x20, 32, "ro"),
        "rd_lat": (0x24, 3, "rw"),
    }


def test_bundled_ddr3_manifest():
    ips = load_design(resolve_design("ddr3", "tangmega138kpro")).ips
    assert {n: (ip["phys_addr"], ip["type"]) for n, ip in ips.items()} == {
        "sys": (0x0, "nanopynq:sysinfo:1.1"),
        "leds": (0x1000, "nanopynq:gpio_out:1.0"),
        "buttons": (0x2000, "nanopynq:gpio_in:1.0"),
        "ddr3_test": (0x3000, "nanopynq:ddr3_test:1.0"),
        "ddr3": (0x4000_0000, "nanopynq:ddr3:1.0"),
    }
    assert ips["ddr3"]["addr_range"] == 0x4000_0000 and ips["ddr3"]["parameters"]["size"] == 1 << 30
    regs = {r: (v["offset"], v["width"], v["access"]) for r, v in ips["ddr3_test"]["registers"].items()}
    assert regs == {
        "ctrl": (0x0, 3, "wo"),
        "status": (0x4, 32, "ro"),
        "passes": (0x8, 16, "rw"),
        "start": (0xC, 28, "rw"),
        "length": (0x10, 29, "rw"),
        "errors": (0x14, 32, "ro"),
        "first_err_addr": (0x18, 32, "ro"),
        "first_err_data": (0x1C, 32, "ro"),
        "first_err_exp": (0x20, 32, "ro"),
        "calib": (0x24, 32, "ro"),
        "wr_cycles": (0x28, 32, "ro"),
        "rd_cycles": (0x2C, 32, "ro"),
    }

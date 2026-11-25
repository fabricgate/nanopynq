"""cocotb tests for src/nanopynq/rtl/cam_fb.v through sim_camfb_top.v (cam_fb + hyperram_ctrl + the HyperRAM
model). Small frames, two builds (sizes from the environment, set by test_sim_cam_fb): W = 320 bytes per
line (20 bursts, the camhdmi width) x H = 4 lines, and W = 16 x H = 136 (line numbers above 127).
The pytest entry point needs iverilog: `pytest -m sim`.
"""

import os
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from hyperram_model import HyperRAMModel

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
W, H, STRIDE = (int(os.environ.get(k, d)) for k, d in (("W", 320), ("H", 4), ("STRIDE", 1024)))
BASE = 0x6000
CTRL, FRAMES, BAD, HFRAMES, STATUS = (BASE + o for o in (0x0, 0x4, 0x8, 0xC, 0x10))


async def bus(dut, addr, value=None):
    await FallingEdge(dut.clk)
    dut.bus_adr.value = addr >> 2
    dut.bus_we.value = value is not None
    dut.bus_dat_w.value = value or 0
    dut.bus_stb.value = 1
    for _ in range(20):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.bus_ack.value):
            got = int(dut.bus_dat_r.value)
            break
    else:
        raise TimeoutError(f"no ack for 0x{addr:x}")
    await FallingEdge(dut.clk)
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    return got


def pattern(seed, n=W * H):
    return bytes((i * 7 + seed * 31 + (i // W) * 13) & 0xFF for i in range(n))


async def send_frame(dut, data, gap=200 + 2 * W):  # a line job (W/16 bursts) fits in a gap
    """Play a camera frame on the write port (wclk), bytes in lines of W with gaps between lines."""
    await RisingEdge(dut.wclk)
    dut.wstart.value = 1
    await RisingEdge(dut.wclk)
    dut.wstart.value = 0
    for i, b in enumerate(data):
        if i and i % W == 0:
            dut.wvalid.value = 0
            await ClockCycles(dut.wclk, gap)
        dut.wvalid.value = 1
        dut.wdata.value = b
        await RisingEdge(dut.wclk)
    dut.wvalid.value = 0
    await ClockCycles(dut.wclk, gap)
    dut.wend.value = 1
    await RisingEdge(dut.wclk)
    dut.wend.value = 0
    await ClockCycles(dut.wclk, gap)


class LineBuffer:
    """Collects the line-buffer writes: entry address -> 32-bit word."""

    def __init__(self, dut):
        self.dut, self.mem = dut, {}
        cocotb.start_soon(self.run())

    async def run(self):
        while True:
            await RisingEdge(self.dut.clk)
            await ReadOnly()
            if int(self.dut.lb_we.value):
                self.mem[int(self.dut.lb_addr.value)] = int(self.dut.lb_data.value)

    def line(self, half):
        return b"".join(self.mem.get(half << 7 | e, 0xDEADBEEF).to_bytes(4, "little") for e in range(W // 4))


async def request(dut, line, wait=300 + 120 * W // 16):  # ~101 clocks per burst at 27 MHz (3.5)
    dut.req_line.value = line
    dut.req_t.value = 1 - int(dut.req_t.value)
    await ClockCycles(dut.clk, wait)


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 37, unit="ns").start())
    cocotb.start_soon(Clock(dut.wclk, 101, unit="ns").start())
    for s in (
        "bus_stb",
        "bus_we",
        "bus_adr",
        "bus_dat_w",
        "wstart",
        "wvalid",
        "wdata",
        "wend",
        "req_t",
        "req_line",
        "frame_t",
    ):
        getattr(dut, s).value = 0
    ram = HyperRAMModel(dut)
    lb = LineBuffer(dut)
    dut.rst.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0
    return ram, lb


def ram_bytes(ram, buf, line):
    words = [ram.mem.get(buf * STRIDE + line * W // 2 + j, None) for j in range(W // 2)]
    assert None not in words, (buf, line)
    return b"".join(w.to_bytes(2, "little") for w in words)


@cocotb.test()
async def frame_is_written_and_lines_read_back(dut):
    ram, lb = await setup(dut)
    await bus(dut, CTRL, 1)
    img = pattern(1)
    await send_frame(dut, img)
    assert await bus(dut, FRAMES) == 1
    assert await bus(dut, BAD) == 0
    st = await bus(dut, STATUS)
    assert st >> 8 & 1 and st & 3 == 1, hex(st)  # first frame into buffer 1
    for y in range(H):
        assert ram_bytes(ram, 1, y) == img[y * W : (y + 1) * W], y
    for y in range(H):
        await request(dut, y)
        assert lb.line(y & 1) == img[y * W : (y + 1) * W], (y, lb.line(y & 1).hex())
    assert (await bus(dut, STATUS)) >> 2 & 3 == 1  # displayed switched on the line-0 request
    assert not ram.errors, ram.errors
    for t in ram.log:
        assert t["clks"] < 108, t  # every CS# low under tCSM (4 us = 108 clocks at 27 MHz)


@cocotb.test()
async def short_frame_is_bad_and_nothing_is_shown(dut):
    _ram, lb = await setup(dut)
    await bus(dut, CTRL, 1)
    await send_frame(dut, pattern(2)[: W * H - W])  # one line short
    assert await bus(dut, FRAMES) == 0
    assert await bus(dut, BAD) == 1
    assert (await bus(dut, STATUS)) >> 8 & 1 == 0
    await request(dut, 0)
    assert lb.mem == {}  # no reads before a completed frame


@cocotb.test()
async def three_buffers_never_write_the_shown_one(dut):
    ram, lb = await setup(dut)
    await bus(dut, CTRL, 1)
    imgs = [pattern(s) for s in (3, 4, 5, 6)]
    await send_frame(dut, imgs[0])  # -> buffer 1, completed 1
    await request(dut, 0)  # displayed 1
    await send_frame(dut, imgs[1])  # -> not {1}: buffer 0
    st = await bus(dut, STATUS)
    assert (st & 3, st >> 2 & 3) == (0, 1), hex(st)
    await send_frame(dut, imgs[2])  # completed 0, displayed 1 -> buffer 2
    st = await bus(dut, STATUS)
    assert (st & 3, st >> 2 & 3) == (2, 1), hex(st)
    for y in range(H):  # buffer 1 still holds the shown frame
        assert ram_bytes(ram, 1, y) == imgs[0][y * W : (y + 1) * W]
    await request(dut, 0)  # displayed 2
    await send_frame(dut, imgs[3])  # completed 2, displayed 2 -> buffer 0
    st = await bus(dut, STATUS)
    assert (st & 3, st >> 2 & 3) == (0, 2), hex(st)
    assert await bus(dut, FRAMES) == 4 and await bus(dut, BAD) == 0
    await request(dut, 0)
    assert lb.line(0) == imgs[3][:W]


@cocotb.test()
async def disabled_writes_nothing_and_counts_display_frames(dut):
    ram, _lb = await setup(dut)
    await send_frame(dut, pattern(7))
    assert await bus(dut, FRAMES) == 0 and await bus(dut, BAD) == 0
    assert not any(t["write"] for t in ram.log)
    for _ in range(3):
        dut.frame_t.value = 1 - int(dut.frame_t.value)
        await ClockCycles(dut.clk, 10)
    assert await bus(dut, HFRAMES) == 3


@pytest.mark.sim
@pytest.mark.parametrize("w,h,stride", [(320, 4, 1024), (16, 136, 2048)])
def test_sim_cam_fb(w, h, stride):
    from cocotb_tools.runner import get_runner

    build = HERE / f"sim_build_camfb_{w}x{h}"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "cam_fb.v", RTL / "hyperram_ctrl.v", HERE / "sim_camfb_top.v"],
        hdl_toplevel="sim_camfb_top",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"W": w, "H": h, "STRIDE": stride},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="sim_camfb_top",
            test_module="test_cam_fb",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
            extra_env={"W": str(w), "H": str(h), "STRIDE": str(stride)},
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

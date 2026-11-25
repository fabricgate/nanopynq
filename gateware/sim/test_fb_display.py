"""cocotb tests for src/nanopynq/rtl/fb_display.v: the line buffer is loaded through its clk port, the TMDS
words are decoded with test_video's decoder. Default build: SH = 1 (320x240 shown 2x). The pytest entry point needs
iverilog: `pytest -m sim`.
"""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from test_video import visible_lines

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
W, S = 320, 2  # source bytes per line, scale
LINE_A = bytes((x * 3 + 1) & 0xFF for x in range(W))
LINE_B = bytes((255 - x) & 0xFF for x in range(W))


async def load(dut, half, line):
    for e in range(W // 4):
        await FallingEdge(dut.clk)
        dut.lb_we.value = 1
        dut.lb_addr.value = half << 7 | e
        dut.lb_data.value = int.from_bytes(line[4 * e : 4 * e + 4], "little")
    await FallingEdge(dut.clk)
    dut.lb_we.value = 0


async def setup(dut, have=1):
    cocotb.start_soon(Clock(dut.clk, 37, unit="ns").start())
    cocotb.start_soon(Clock(dut.pclk, 40, unit="ns").start())
    dut.lb_we.value = 0
    dut.have_frame.value = have
    dut.prst.value = 1
    await load(dut, 0, LINE_A)
    await load(dut, 1, LINE_B)
    await ClockCycles(dut.pclk, 4)
    dut.prst.value = 0


async def to_frame_start(dut):
    """Return in the vertical back porch, so the next visible line is line 0."""
    while True:
        await RisingEdge(dut.pclk)
        await ReadOnly()
        if not int(dut.vs.value):
            break
    while True:
        await RisingEdge(dut.pclk)
        await ReadOnly()
        if int(dut.vs.value):
            return


def gray_line(src):
    return [b << 16 | b << 8 | b for b in src for _ in range(S)]


@cocotb.test()
async def scales_each_pixel_to_2x2(dut):
    await setup(dut)
    await to_frame_start(dut)
    lines = await visible_lines(dut, 12)
    want_a, want_b = gray_line(LINE_A), gray_line(LINE_B)
    for y, got in enumerate(lines):
        want = want_a if (y // S) % 2 == 0 else want_b
        assert got == want, (y, [hex(v) for v in got[:12]], [hex(v) for v in want[:12]])


@cocotb.test()
async def requests_next_lines_and_line_0_ahead(dut):
    await setup(dut)
    reqs = []

    async def watch():
        prev = int(dut.req_t.value)
        while True:
            await RisingEdge(dut.pclk)
            await ReadOnly()
            if int(dut.req_t.value) != prev:
                prev = int(dut.req_t.value)
                reqs.append((int(dut.vt.v.value), int(dut.req_line.value)))

    cocotb.start_soon(watch())
    await to_frame_start(dut)
    reqs.clear()
    await to_frame_start(dut)  # one whole frame of requests
    lines = [r[1] for r in reqs]
    assert lines == [0, *list(range(1, 240))], lines  # from the back porch: line 0 at v = 520 comes first
    vs = [r[0] for r in reqs]
    assert vs[:4] == [520, 0, 2, 4] and vs[239] == 476, vs  # v as the toggle is seen


@cocotb.test()
async def black_until_a_frame_exists(dut):
    await setup(dut, have=0)
    await to_frame_start(dut)
    lines = await visible_lines(dut, 2)
    assert all(v == 0 for line in lines for v in line)


@pytest.mark.sim
def test_sim_fb_display():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_fbdisp"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "fb_display.v", RTL / "video_timing.v", RTL / "tmds_encoder.v"],
        hdl_toplevel="fb_display",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="fb_display",
            test_module="test_fb_display",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

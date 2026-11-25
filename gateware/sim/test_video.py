"""cocotb tests for src/nanopynq/rtl/tmds_encoder.v and video_timing.v. Pytest entry points need iverilog:
`pytest -m sim`.

tmds_encoder is compared word for word with a Python model of the DVI 1.0 encoder (section 3.2.3), and the
words must decode back to the input. video_timing is checked against 640x480@60 (800 x 525 total,
negative syncs of 96 and 2).
"""

import itertools
import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
CTRL = {(0, 0): 0b1101010100, (0, 1): 0b0010101011, (1, 0): 0b0101010100, (1, 1): 0b1010101011}  # (c1, c0)


def tmds_model():
    """Generator: send (d, c0, c1, de), get the 10-bit word (bit 0 is sent first)."""
    cnt = 0
    q = None
    while True:
        d, c0, c1, de = yield q
        if not de:
            cnt = 0
            q = CTRL[(c1, c0)]
            continue
        n1d = bin(d).count("1")
        xnor = n1d > 4 or (n1d == 4 and not d & 1)
        qm = d & 1
        for i in range(1, 8):
            b = ((qm >> (i - 1)) ^ (d >> i)) & 1
            qm |= (b ^ xnor) << i
        qm |= (0 if xnor else 1) << 8
        q8 = (qm >> 8) & 1
        n1q = bin(qm & 0xFF).count("1")
        n0q = 8 - n1q
        if cnt == 0 or n1q == n0q:
            q = ((1 - q8) << 9) | (q8 << 8) | (qm & 0xFF if q8 else ~qm & 0xFF)
            cnt += (n1q - n0q) if q8 else (n0q - n1q)
        elif (cnt > 0 and n1q > n0q) or (cnt < 0 and n0q > n1q):
            q = (1 << 9) | (q8 << 8) | (~qm & 0xFF)
            cnt += 2 * q8 + (n0q - n1q)
        else:
            q = (q8 << 8) | (qm & 0xFF)
            cnt += -2 * (1 - q8) + (n1q - n0q)


def tmds_decode(q):
    d = q & 0xFF
    if q >> 9 & 1:
        d = ~d & 0xFF
    out = d & 1
    for i in range(1, 8):
        b = ((d >> i) ^ (d >> (i - 1))) & 1
        out |= (b if q >> 8 & 1 else 1 - b) << i
    return out


@cocotb.test()
async def tmds_matches_model_and_decodes(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    rnd = random.Random(1)
    model = tmds_model()
    next(model)
    # random pixels with blanking runs, plus the bytes that stress the disparity rules
    stim = [(0, 0, 0, 0)] * 4
    for k in range(3000):
        de = 0 if k % 50 >= 45 else 1
        d = rnd.choice([0x00, 0xFF, 0x0F, 0xF0, 0x55, 0xAA, 0x10, rnd.getrandbits(8)])
        stim.append((d, rnd.getrandbits(1), rnd.getrandbits(1), de))
    want = [model.send(s) for s in stim]
    got = []
    for s in stim:
        dut.d.value, dut.c0.value, dut.c1.value, dut.de.value = s
        await RisingEdge(dut.clk)
        await ReadOnly()
        got.append(int(dut.q.value))
        await cocotb.triggers.FallingEdge(dut.clk)
    # inputs change on the falling edge; after the rising edge q already holds the word for that input
    for k, (s, w, g) in enumerate(zip(stim, want, got, strict=True)):
        assert g == w, (k, s, f"{g:010b}", f"{w:010b}")
        if s[3]:
            assert tmds_decode(g) == s[0], (k, s)
    disparity = 0
    for s, g in zip(stim, got, strict=True):
        disparity = 0 if not s[3] else disparity + 2 * bin(g).count("1") - 10
        assert abs(disparity) <= 10, disparity


@cocotb.test()
async def timing_640x480(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    rows = []  # per line: (de pixels, hsync-low clocks, vsync low at line start)
    de_n = hs_n = 0
    prev_hs = 1
    await RisingEdge(dut.clk)
    while len(rows) < 525 * 2 + 1:
        await RisingEdge(dut.clk)
        await ReadOnly()
        de, hs, vs = int(dut.de.value), int(dut.hsync.value), int(dut.vsync.value)
        de_n += de
        hs_n += 1 - hs
        if prev_hs == 1 and hs == 0:  # a line boundary at each hsync falling edge
            rows.append((de_n, hs_n, vs))
            de_n = hs_n = 0
        prev_hs = hs
    rows = rows[1:]  # the first line may be partial
    frame = rows[:525]
    assert all(r[1] == 96 for r in frame[1:]), {r[1] for r in frame}
    assert sorted({r[0] for r in frame}) == [0, 640], {r[0] for r in frame}
    assert sum(1 for r in frame if r[0] == 640) == 480
    assert sum(1 for r in frame if r[2] == 0) == 2  # vsync low for 2 lines
    # hsync period: 800 clocks
    t = []
    prev = int(dut.hsync.value)
    for _ in range(2000):
        await RisingEdge(dut.clk)
        await ReadOnly()
        hs = int(dut.hsync.value)
        if prev == 1 and hs == 0:
            t.append(cocotb.utils.get_sim_time("ns"))
        prev = hs
    assert {round(b - a) for a, b in itertools.pairwise(t)} == {8000}


BARS = [0xFFFFFF, 0xFFFF00, 0x00FFFF, 0x00FF00, 0xFF00FF, 0xFF0000, 0x0000FF, 0x000000]


async def bus(dut, addr, data=None):
    await cocotb.triggers.FallingEdge(dut.clk)
    dut.bus_adr.value = addr >> 2
    dut.bus_we.value = data is not None
    dut.bus_dat_w.value = data or 0
    dut.bus_stb.value = 1
    for _ in range(20):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.bus_ack.value):
            got = int(dut.bus_dat_r.value)
            break
    else:
        raise TimeoutError(f"no ack for 0x{addr:x}")
    await cocotb.triggers.FallingEdge(dut.clk)
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    return got


async def visible_lines(dut, n):
    """Decode the next n whole visible lines from the three TMDS channels -> list of 640 RGB values."""
    lines, run = [], []
    while len(lines) < n:
        await RisingEdge(dut.pclk)
        await ReadOnly()
        words = [int(dut.tmds0.value), int(dut.tmds1.value), int(dut.tmds2.value)]
        if words[1] in CTRL.values():  # channel 1 sends only control code 00 while blanking
            if len(run) == 640:
                lines.append(run)
            run = []
        else:
            b, g, r = (tmds_decode(w) for w in words)
            run.append(r << 16 | g << 8 | b)
    return lines


@cocotb.test()
async def testpat_bars_solid_and_frames(dut):
    cocotb.start_soon(Clock(dut.clk, 37, unit="ns").start())
    cocotb.start_soon(Clock(dut.pclk, 40, unit="ns").start())
    for s in ("bus_stb", "bus_we", "bus_adr", "bus_dat_w"):
        getattr(dut, s).value = 0
    dut.rst.value = 1
    dut.prst.value = 1
    await ClockCycles(dut.pclk, 4)
    dut.rst.value = 0
    dut.prst.value = 0
    base = 0x6000
    # The encoders send control codes during reset, so the first 480 whole lines are y = 0..479 of the
    # first frame: white border lines at both ends, bars between.
    lines = await visible_lines(dut, 480)
    assert await bus(dut, base + 8) == 1  # one frame start (at reset release), none while in reset
    white = [0xFFFFFF] * 640
    bars = [0xFFFFFF if x in (0, 639) else BARS[x // 80] for x in range(640)]
    assert lines[0] == white and lines[-1] == white
    bad = [y for y, line in enumerate(lines[1:-1], 1) if line != bars]
    assert not bad, (bad[:5], [i for i, (a, b) in enumerate(zip(lines[bad[0]], bars, strict=True)) if a != b][:8])

    await bus(dut, base + 4, 0x123456)
    await bus(dut, base, 1)
    assert await bus(dut, base) == 1 and await bus(dut, base + 4) == 0x123456
    await visible_lines(dut, 1)  # let the new settings cross to the pixel clock
    (line,) = await visible_lines(dut, 1)
    assert line == [0x123456] * 640


def _run(toplevel, sources, testcase):
    from cocotb_tools.runner import get_runner

    build = HERE / f"sim_build_video_{toplevel}"
    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel=toplevel,
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel=toplevel,
            test_module="test_video",
            test_dir=HERE,
            testcase=testcase,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")


@pytest.mark.sim
def test_sim_tmds_encoder():
    _run("tmds_encoder", [RTL / "tmds_encoder.v"], "tmds_matches_model_and_decodes")


@pytest.mark.sim
def test_sim_video_timing():
    _run("video_timing", [RTL / "video_timing.v"], "timing_640x480")


@pytest.mark.sim
def test_sim_hdmi_testpat():
    _run(
        "hdmi_testpat",
        [RTL / "hdmi_testpat.v", RTL / "video_timing.v", RTL / "tmds_encoder.v"],
        "testpat_bars_solid_and_frames",
    )

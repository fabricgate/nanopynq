"""cocotb tests for src/nanopynq/rtl/sdram_port.v (host window) and sdram_arb.v, through sim_sdram_top
(sdram_ctrl + sdram_arb + sdram_port, master b exposed) against sdram_model.SDRAMModel.
The same file is the pytest entry point: `pytest -m sim`."""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, with_timeout

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
CLK_NS = 37.037  # the board clock is 27 MHz
BASE_WORD = 0x80_0000 >> 2  # bus word address of the window


async def setup(dut, wait_init=True):
    from sdram_model import SDRAMModel

    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns", period_high=18.519).start())
    dut.rst.value = 1
    for s in (dut.bus_stb, dut.bus_we, dut.b_valid, dut.b_write):
        s.value = 0
    for s in (dut.bus_adr, dut.bus_dat_w, dut.b_addr, dut.b_wdata, dut.b_wmask):
        s.value = 0
    await ClockCycles(dut.clk, 2)
    ram = SDRAMModel(dut)
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    if wait_init:
        await with_timeout(RisingEdge(dut.init_done), 250, "us")
    return ram


async def bus(dut, adr, we=0, dat=0, limit=30):
    """One bus access (stb held until ack). Returns (read data, clocks from stb to ack)."""
    await FallingEdge(dut.clk)
    dut.bus_adr.value, dut.bus_we.value, dut.bus_dat_w.value, dut.bus_stb.value = adr, we, dat, 1
    n = 0
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        n += 1
        if int(dut.bus_ack.value):
            val = int(dut.bus_dat_r.value)
            break
        assert n <= limit, f"no ack within {limit} clocks"
    await RisingEdge(dut.clk)  # like jtag_bridge: stb is still high where it samples ack, then drops
    await FallingEdge(dut.clk)
    dut.bus_stb.value = 0
    await FallingEdge(dut.clk)  # the bridge needs a gap before the next strobe; ack is a 1 clock pulse
    assert not int(dut.bus_ack.value) and not int(dut.bus_dat_r.value)
    return val, n


@cocotb.test()
async def test_port_write_read(dut):
    ram = await setup(dut)
    rng = random.Random(1)
    exp = {}
    for k in [*rng.sample(range(0x1F_FFFF), 98), 0, 0x1F_FFFF]:  # 100 words, both ends of the 8 MB
        exp[k] = rng.getrandbits(32)
        await bus(dut, BASE_WORD + k, 1, exp[k])
    for k, v in exp.items():
        got, _ = await bus(dut, BASE_WORD + k)
        assert got == v, f"word {k:#x}: {got:#x} != {v:#x}"
    assert int(dut.init_done.value) and not ram.errors, ram.errors


@cocotb.test()
async def test_port_during_init(dut):
    await setup(dut, wait_init=False)
    assert not int(dut.init_done.value)
    for we in (0, 1, 0):
        got, n = await bus(dut, BASE_WORD + 5, we, 0xDEAD_BEEF, limit=3)
        assert got == 0 and n <= 3
    assert not int(dut.init_done.value)  # all of that happened during init


@cocotb.test()
async def test_port_latency_under_load(dut):
    ram = await setup(dut)
    rng = random.Random(2)
    stop = False
    b_bad = []
    b_exp, b_reads = {}, []

    async def master_b():
        """Back to back commands on b in its own address range (bank 3; the window words used here are in
        bank 0); every read is checked against what b wrote."""
        for i in range(0x40):  # fill first
            a = 0x18_0000 + i
            b_exp[a] = rng.getrandbits(32)
            await put(a, True, b_exp[a])
        while not stop:
            a = 0x18_0000 + rng.randrange(0x40)
            await put(a, False, 0)

    async def put(a, w, d):
        await FallingEdge(dut.clk)
        dut.b_valid.value, dut.b_write.value, dut.b_addr.value = 1, int(w), a
        dut.b_wdata.value, dut.b_wmask.value = d, 0xF
        while True:
            await ReadOnly()
            ready = int(dut.b_ready.value)
            await RisingEdge(dut.clk)
            if ready:
                break
            await FallingEdge(dut.clk)
        if not w:
            b_reads.append(a)

    async def mon_b():
        i = 0
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if int(dut.b_rd_valid.value):
                if int(dut.b_rd_data.value) != b_exp[b_reads[i]]:
                    b_bad.append((i, b_reads[i]))
                i += 1

    cocotb.start_soon(mon_b())
    task = cocotb.start_soon(master_b())
    exp, worst = {}, 0
    for _ in range(100):
        k = rng.randrange(0x1_0000)
        exp[k] = rng.getrandbits(32)
        _, n = await bus(dut, BASE_WORD + k, 1, exp[k])
        worst = max(worst, n)
    for k, v in exp.items():
        got, n = await bus(dut, BASE_WORD + k)
        worst = max(worst, n)
        assert got == v, f"word {k:#x}: {got:#x} != {v:#x}"
    stop = True
    await task
    await FallingEdge(dut.clk)
    dut.b_valid.value = 0
    dut._log.info(f"worst ack latency under load: {worst} clocks")
    assert worst <= 30
    assert len(b_reads) > 30, "master b made too few reads"
    assert not b_bad, f"master b read wrong data: {b_bad[:5]}"
    assert not ram.errors, ram.errors


@cocotb.test()
async def test_port_ignores_other_addresses(dut):
    await setup(dut)
    # The port's own outputs (not the combined bus): 0x3000 (byte) is a base register address.
    await FallingEdge(dut.clk)
    dut.bus_adr.value, dut.bus_we.value, dut.bus_stb.value = 0x3000 >> 2, 0, 1
    for _ in range(40):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert not int(dut.hit.value)
        assert not int(dut.port.bus_ack.value)
        assert int(dut.port.bus_dat_r.value) == 0
    await FallingEdge(dut.clk)
    dut.bus_we.value = 1
    dut.bus_dat_w.value = 0x1234
    for _ in range(40):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert not int(dut.port.bus_ack.value)
    await FallingEdge(dut.clk)
    dut.bus_stb.value = 0


@pytest.mark.sim
def test_sim_sdram_port():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_sdram_top"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "sdram_ctrl.v", RTL / "sdram_arb.v", RTL / "sdram_port.v", HERE / "sim_sdram_top.v"],
        hdl_toplevel="sim_sdram_top",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="sim_sdram_top",
            test_module="test_sdram_port",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

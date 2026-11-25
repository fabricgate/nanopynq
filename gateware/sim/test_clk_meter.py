"""cocotb tests for src/nanopynq/rtl/clk_meter.v. The pytest entry point needs iverilog: `pytest -m sim`.

Periods keep the board's ratios (27 MHz reference; 126, 25.2 and 31.5 MHz measured) with a short gate:
GATE = 270 reference cycles of 42 ns = 11340 ns -> 1260, 252 and 315 edges.
"""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
BASE, GATE = 0x5000, 270
PERIODS_NS = (9, 45, 36)
EXPECTED = tuple(GATE * 42 // p for p in PERIODS_NS)  # (1260, 252, 315)


async def bus_read(dut, addr):
    await FallingEdge(dut.clk)
    dut.bus_adr.value = addr >> 2
    dut.bus_we.value = 0
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
    return got


async def setup(dut, running=(True, True, True), lock=1):
    cocotb.start_soon(Clock(dut.clk, 42, unit="ns").start())
    for i, (p, on) in enumerate(zip(PERIODS_NS, running, strict=True)):
        if on:
            cocotb.start_soon(Clock(dut.mclk[i], p, unit="ns").start())
        else:
            dut.mclk[i].value = 0
    dut.lock.value = lock
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    dut.bus_adr.value = 0
    dut.bus_dat_w.value = 0
    dut.rst.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0


@cocotb.test()
async def counts_edges_per_gate(dut):
    await setup(dut)
    await ClockCycles(dut.clk, 3 * GATE + 20)  # the first gate after reset is partial; take a later one
    status = await bus_read(dut, BASE)
    assert status & 1 == 1, hex(status)  # lock
    assert (status >> 8) & 0b111 == 0b111, hex(status)  # every channel has a count
    for i, want in enumerate(EXPECTED):
        got = await bus_read(dut, BASE + 4 + 4 * i)
        assert abs(got - want) <= 1, (i, got, want)


@cocotb.test()
async def stopped_clock_and_lock_low(dut):
    await setup(dut, running=(True, False, True), lock=0)
    await ClockCycles(dut.clk, 3 * GATE + 20)
    status = await bus_read(dut, BASE)
    assert status & 1 == 0, hex(status)
    assert (status >> 8) & 0b111 == 0b101, hex(status)  # channel 1 never finished a gate
    assert await bus_read(dut, BASE + 8) == 0


@cocotb.test()
async def outside_its_window_reads_zero(dut):
    await setup(dut)
    await ClockCycles(dut.clk, 3 * GATE + 20)
    assert await bus_read(dut, BASE + 0x10) == 0
    assert int(dut.hit.value) == 0


@pytest.mark.sim
def test_sim_clk_meter():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_clkmeter"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "clk_meter.v"],
        hdl_toplevel="clk_meter",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": BASE, "GATE": GATE},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="clk_meter",
            test_module="test_clk_meter",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

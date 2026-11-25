"""cocotb tests for examples/tangnano9k_chaser/chaser.v. The pytest entry point needs iverilog: `pytest -m sim`.

The simulation runs the chaser with CLK_HZ = 1000, so RATE = 100 steps every 10 clocks."""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
CHASER = HERE.parent.parent / "examples" / "tangnano9k_chaser" / "chaser.v"
CLK_HZ = 1000
CTRL, PATTERN, RATE, CURRENT, STEPS = (0x7000 + 4 * i for i in range(5))


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


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    dut.bus_adr.value = 0
    dut.bus_dat_w.value = 0
    dut.rst.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0


async def steps_over(dut, clocks):
    """STEPS read twice, `clocks` apart (from the first read's start to the second's)."""
    s0 = await bus(dut, STEPS)
    await ClockCycles(dut.clk, clocks - 3)  # a read takes 3 clocks from strobe to the next falling edge
    return await bus(dut, STEPS) - s0


async def next_step(dut, limit=200):
    """Waits for STEPS to move (bounded, so a chaser that never steps fails instead of hanging); returns CURRENT."""
    s = await bus(dut, STEPS)
    for _ in range(limit):
        if await bus(dut, STEPS) != s:
            return int(dut.current.value)
    raise AssertionError(f"no step within {limit} reads")


@cocotb.test()
async def the_first_cell_starts_a_chase(dut):
    """What the notebook's generated cell writes: ctrl=1, pattern=2, rate=3 (here 30 per 10,000 clocks)."""
    await setup(dut)
    await bus(dut, CTRL, 1)
    await bus(dut, PATTERN, 0b000010)
    assert await bus(dut, CURRENT) == 0b000010 and int(dut.run.value) == 1
    await bus(dut, RATE, 3)
    assert abs(await steps_over(dut, 10_000) - 30) <= 1
    assert bin(await bus(dut, CURRENT)).count("1") == 1  # still one LED, somewhere else


@cocotb.test()
async def a_rate_above_one_byte_is_kept_whole(dut):
    await setup(dut)
    await bus(dut, PATTERN, 0b000001)
    await bus(dut, CTRL, 1)
    await bus(dut, RATE, 300)  # 0x12c: a rate cut to 8 bits would be 44
    assert await bus(dut, RATE) == 300
    assert abs(await steps_over(dut, 1000) - 300) <= 1


@cocotb.test()
async def steps_forward_and_back_and_wraps(dut):
    await setup(dut)
    await bus(dut, RATE, 100)
    await bus(dut, PATTERN, 0b100001)
    await bus(dut, CTRL, 1)
    seen = [await next_step(dut) for _ in range(7)]
    assert seen == [0b000011, 0b000110, 0b001100, 0b011000, 0b110000, 0b100001, 0b000011]
    await bus(dut, CTRL, 0b11)  # reverse
    assert await next_step(dut) == 0b100001


@cocotb.test()
async def rate_zero_holds_and_a_pattern_restarts(dut):
    await setup(dut)
    await bus(dut, PATTERN, 0b000001)
    await bus(dut, CTRL, 1)
    await ClockCycles(dut.clk, 200)
    assert await bus(dut, CURRENT) == 0b000001 and await bus(dut, STEPS) == 0  # RATE is 0
    await bus(dut, RATE, 10)  # a step every 100 clocks
    await next_step(dut)
    await ClockCycles(dut.clk, 50)  # half way to the next step
    await bus(dut, PATTERN, 0b000101)
    assert await bus(dut, CURRENT) == 0b000101
    s = await bus(dut, STEPS)
    await ClockCycles(dut.clk, 80)  # a restart waits a whole step; a kept accumulator would step after ~50
    assert await bus(dut, CURRENT) == 0b000101 and await bus(dut, STEPS) == s
    assert await bus(dut, RATE) == 10 and await bus(dut, PATTERN) == 0b000101 and await bus(dut, CTRL) == 1


@cocotb.test()
async def clearing_run_stops_and_clears_steps(dut):
    await setup(dut)
    await bus(dut, PATTERN, 0b000001)
    await bus(dut, RATE, 500)
    await bus(dut, CTRL, 1)
    await ClockCycles(dut.clk, 50)
    assert await bus(dut, STEPS) > 0
    await bus(dut, CTRL, 0)
    assert int(dut.run.value) == 0 and await bus(dut, STEPS) == 0
    held = await bus(dut, CURRENT)
    await ClockCycles(dut.clk, 50)
    assert await bus(dut, CURRENT) == held  # stopped where it was
    assert await bus(dut, 0x7014) == 0  # outside the window: reads 0


@pytest.mark.sim
def test_sim_chaser():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_chaser"
    runner = get_runner("icarus")
    runner.build(
        sources=[CHASER],
        hdl_toplevel="chaser",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": 0x7000, "WIDTH": 6, "CLK_HZ": CLK_HZ},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="chaser",
            test_module="test_chaser",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

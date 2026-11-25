"""cocotb tests for examples/tangnano9k_button_counter/button_counter.v. The pytest entry point needs iverilog:
`pytest -m sim`. The simulation filters bounce over DEBOUNCE = 10 clocks (20 ms at 27 MHz on the board)."""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
COUNTER = HERE.parent.parent / "examples" / "tangnano9k_button_counter" / "button_counter.v"
DEBOUNCE = 10
COUNT0, COUNT1 = 0x7000, 0x7004


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
    dut.pressed.value = 0
    dut.rst.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0


async def level(dut, button, value, clocks):
    await FallingEdge(dut.clk)
    dut.pressed.value = (int(dut.pressed.value) & ~(1 << button)) | (value << button)
    await ClockCycles(dut.clk, clocks)


async def bounce(dut, button, settle, clocks=3, times=6):
    """The contact chatters (each level shorter than DEBOUNCE), then settles."""
    for k in range(times):
        await level(dut, button, k % 2, clocks)
    await level(dut, button, settle, 3 * DEBOUNCE)


async def counts(dut):
    return await bus(dut, COUNT0), await bus(dut, COUNT1)


@cocotb.test()
async def a_press_counts_once_and_a_release_does_not(dut):
    await setup(dut)
    assert await counts(dut) == (0, 0)  # what the notebook's first cell shows on a fresh board
    await level(dut, 0, 1, 3 * DEBOUNCE)
    assert await counts(dut) == (1, 0)
    await level(dut, 0, 0, 3 * DEBOUNCE)
    assert await counts(dut) == (1, 0)


@cocotb.test()
async def bounce_is_not_counted(dut):
    await setup(dut)
    await bounce(dut, 0, settle=1)
    assert await counts(dut) == (1, 0)
    await bounce(dut, 0, settle=0)  # chatter on release
    assert await counts(dut) == (1, 0)


@cocotb.test()
async def a_level_counts_only_after_debounce_clocks(dut):
    """The boundary: DEBOUNCE - 1 clocks pressed is not a press, DEBOUNCE clocks is (the sync flops only delay)."""
    await setup(dut)
    await level(dut, 1, 1, DEBOUNCE - 1)
    await level(dut, 1, 0, 3 * DEBOUNCE)
    assert await counts(dut) == (0, 0)
    await level(dut, 1, 1, DEBOUNCE)
    await level(dut, 1, 0, 3 * DEBOUNCE)
    assert await counts(dut) == (0, 1)


@cocotb.test()
async def short_pulses_do_not_add_up(dut):
    """Each return to the stable level restarts the wait, so short pulses never sum to a press."""
    await setup(dut)
    for _ in range(4):
        await level(dut, 1, 1, DEBOUNCE - 2)
        await level(dut, 1, 0, 3)
    await level(dut, 1, 0, 3 * DEBOUNCE)
    assert await counts(dut) == (0, 0)
    await bounce(dut, 0, settle=1, times=30)  # a long chatter: 45 clocks on each side in total
    assert await counts(dut) == (1, 0)


@cocotb.test()
async def the_buttons_count_apart_and_writes_are_ignored(dut):
    await setup(dut)
    for _ in range(2):
        await level(dut, 1, 1, 2 * DEBOUNCE)
        await level(dut, 1, 0, 2 * DEBOUNCE)
    await level(dut, 0, 1, 2 * DEBOUNCE)
    await level(dut, 0, 0, 2 * DEBOUNCE)
    assert await counts(dut) == (1, 2)
    await bus(dut, COUNT0, 99)
    assert await counts(dut) == (1, 2)
    assert await bus(dut, 0x7008) == 0  # outside the window: reads 0


@pytest.mark.sim
def test_sim_button_counter():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_button_counter"
    runner = get_runner("icarus")
    runner.build(
        sources=[COUNTER],
        hdl_toplevel="button_counter",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": 0x7000, "DEBOUNCE": DEBOUNCE},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="button_counter",
            test_module="test_button_counter",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

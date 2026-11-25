"""cocotb tests for src/nanopynq/rtl/pwm_timer.v. The pytest entry point needs iverilog: `pytest -m sim`."""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
BASE = 0x7000
CTRL, PERIOD, DUTY, COUNT, WRAPS = (BASE + o for o in (0x0, 0x4, 0x8, 0xC, 0x10))


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


async def sample(dut, n):
    """pwm on n consecutive clocks."""
    out = []
    for _ in range(n):
        await RisingEdge(dut.clk)
        await ReadOnly()
        out.append(int(dut.pwm.value))
    return out


def runs(bits):
    """Lengths of the high runs that start and end inside bits."""
    s = "".join(map(str, bits)).strip("1")
    return [len(r) for r in s.split("0") if r]


@cocotb.test()
async def duty_period_and_wraps(dut):
    await setup(dut)
    await bus(dut, PERIOD, 10)
    await bus(dut, DUTY, 3)
    assert await sample(dut, 30) == [0] * 30  # disabled: low
    await bus(dut, CTRL, 1)
    bits = await sample(dut, 100)
    assert runs(bits) and set(runs(bits)) == {3}, bits
    assert sum(bits[10:90]) == 24, bits  # 3 of every 10 clocks
    w0 = await bus(dut, WRAPS)
    await ClockCycles(dut.clk, 200)
    w1 = await bus(dut, WRAPS)
    assert w1 - w0 in (20, 21, 22), (w0, w1)  # 200 clocks + the read itself, 10 clocks a period
    assert await bus(dut, COUNT) < 10


@cocotb.test()
async def new_duty_takes_effect_at_the_period_end(dut):
    await setup(dut)
    await bus(dut, PERIOD, 20)
    await bus(dut, DUTY, 5)
    await bus(dut, CTRL, 1)
    await ClockCycles(dut.clk, 45)
    await bus(dut, DUTY, 15)
    bits = await sample(dut, 120)
    assert set(runs(bits)) <= {5, 15} and 15 in runs(bits), runs(bits)  # no runs of other lengths


@cocotb.test()
async def zero_and_full_duty(dut):
    await setup(dut)
    await bus(dut, PERIOD, 8)
    await bus(dut, DUTY, 0)
    await bus(dut, CTRL, 1)
    await ClockCycles(dut.clk, 20)
    assert await sample(dut, 40) == [0] * 40
    await bus(dut, DUTY, 8)
    await ClockCycles(dut.clk, 20)
    assert await sample(dut, 40) == [1] * 40


@cocotb.test()
async def disable_stops_and_clears(dut):
    await setup(dut)
    await bus(dut, PERIOD, 10)
    await bus(dut, DUTY, 5)
    await bus(dut, CTRL, 1)
    await ClockCycles(dut.clk, 100)
    await bus(dut, CTRL, 0)
    assert await sample(dut, 30) == [0] * 30
    assert await bus(dut, WRAPS) == 0
    assert await bus(dut, COUNT) == 0
    assert await bus(dut, PERIOD) == 10 and await bus(dut, DUTY) == 5 and await bus(dut, CTRL) == 0


@cocotb.test()
async def outside_its_window(dut):
    await setup(dut)
    assert await bus(dut, BASE + 0x14) == 0
    assert int(dut.hit.value) == 0


@pytest.mark.sim
def test_sim_pwm_timer():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_pwm"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "pwm_timer.v"],
        hdl_toplevel="pwm_timer",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": BASE},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="pwm_timer",
            test_module="test_pwm_timer",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

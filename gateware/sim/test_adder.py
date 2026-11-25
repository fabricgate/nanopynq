"""cocotb tests for examples/tangnano9k_adder/adder.v. The pytest entry point needs iverilog: `pytest -m sim`."""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
ADDER = HERE.parent.parent / "examples" / "tangnano9k_adder" / "adder.v"


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


@cocotb.test()
async def adds_and_carries(dut):
    await setup(dut)
    await bus(dut, 0x7000, 3)
    await bus(dut, 0x7004, 4)
    assert await bus(dut, 0x7008) == 7 and await bus(dut, 0x700C) == 0
    await bus(dut, 0x7000, 0xFFFF_FFFF)
    await bus(dut, 0x7004, 2)
    assert await bus(dut, 0x7008) == 1 and await bus(dut, 0x700C) == 1
    assert await bus(dut, 0x7000) == 0xFFFF_FFFF  # a reads back what was written
    await bus(dut, 0x7008, 99)
    assert await bus(dut, 0x7008) == 1  # sum is ro: a write changes nothing


@pytest.mark.sim
def test_sim_adder():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_adder"
    runner = get_runner("icarus")
    runner.build(
        sources=[ADDER],
        hdl_toplevel="adder",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": 0x7000},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="adder",
            test_module="test_adder",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

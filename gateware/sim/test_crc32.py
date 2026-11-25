"""cocotb tests for examples/tangnano9k_crc32/crc32.v. The pytest entry point needs iverilog: `pytest -m sim`."""

import random
import zlib
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
CRC32 = HERE.parent.parent / "examples" / "tangnano9k_crc32" / "crc32.v"
INIT, DATA, CRC, LENGTH = 0x7000, 0x7004, 0x7008, 0x700C


async def bus(dut, addr, value=None):
    """One bus access, with stb held through the ack edge as uartbone_bridge does (a write must be taken once)."""
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
    await RisingEdge(dut.clk)  # the bridge drops stb only after the clock that saw ack
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


async def feed(dut, data):
    await bus(dut, INIT, 0)
    for b in data:
        await bus(dut, DATA, b)
    return await bus(dut, CRC), await bus(dut, LENGTH)


@cocotb.test()
async def the_check_value(dut):
    await setup(dut)
    assert (await bus(dut, CRC), await bus(dut, LENGTH)) == (0, 0)  # the first cell, on a fresh board: crc32(b"")
    assert await feed(dut, b"123456789") == (0xCBF43926, 9)


@cocotb.test()
async def matches_zlib_on_random_bytes(dut):
    await setup(dut)
    rng = random.Random(1602)
    for n in (1, 2, 7, 64, 300):
        data = bytes(rng.randrange(256) for _ in range(n))
        assert await feed(dut, data) == (zlib.crc32(data), n), n


@cocotb.test()
async def init_starts_over_and_only_the_low_byte_counts(dut):
    await setup(dut)
    await feed(dut, b"abc")
    await bus(dut, INIT, 1)
    assert (await bus(dut, CRC), await bus(dut, LENGTH)) == (0, 0)
    await bus(dut, DATA, 0xFFFF_FF41)  # only 0x41 ("A") is taken
    assert (await bus(dut, CRC), await bus(dut, LENGTH)) == (zlib.crc32(b"A"), 1)
    assert await bus(dut, INIT) == 0 and await bus(dut, DATA) == 0  # write-only: read 0
    await bus(dut, CRC, 5)
    await bus(dut, LENGTH, 5)
    assert (await bus(dut, CRC), await bus(dut, LENGTH)) == (zlib.crc32(b"A"), 1)  # read-only: writes do nothing
    assert await bus(dut, 0x7010) == 0  # outside the window: reads 0
    await bus(dut, 0x1000, 0x3F)  # writes to other IPs (here the LEDs' address) leave the CRC alone
    await bus(dut, 0x1004, 0x42)
    await bus(dut, 0x7010, 0x42)
    assert (await bus(dut, CRC), await bus(dut, LENGTH)) == (zlib.crc32(b"A"), 1)


@pytest.mark.sim
def test_sim_crc32():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_crc32"
    runner = get_runner("icarus")
    runner.build(
        sources=[CRC32],
        hdl_toplevel="crc32",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": 0x7000},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="crc32",
            test_module="test_crc32",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

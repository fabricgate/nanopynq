"""cocotb tests for src/nanopynq/rtl/sdram_test.v (self-test engine on master b of sdram_arb), through
sim_sdram_test_top (the board-top bus gating) against sdram_model.SDRAMModel. LENGTH is 512 words to keep
the runs short. The same file is the pytest entry point: `pytest -m sim`."""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, with_timeout

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
CLK_NS = 37.037  # the board clock is 27 MHz
BASE_WORD = 0x80_0000 >> 2  # bus word address of the SDRAM window
T = 0x3000 >> 2  # bus word address of sdram_test's registers
CTRL, STATUS, PASSES, START, LENGTH, ERRORS, ERR_ADDR, ERR_DATA, ERR_EXP, RD_LAT = (T + i for i in range(10))
LEN = 512


async def setup(dut):
    from sdram_model import SDRAMModel

    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns", period_high=18.519).start())
    dut.rst.value = 1
    for s in (dut.bus_stb, dut.bus_we, dut.bus_adr, dut.bus_dat_w):
        s.value = 0
    await ClockCycles(dut.clk, 2)
    ram = SDRAMModel(dut)
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await with_timeout(RisingEdge(dut.init_done), 250, "us")
    return ram


async def bus(dut, adr, we=0, dat=0, limit=40):
    """One bus access (stb held until ack, through the ack edge like jtag_bridge). Returns the read data."""
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
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.bus_stb.value = 0
    await FallingEdge(dut.clk)
    assert not int(dut.bus_ack.value)  # (bus_dat_r follows bus_adr, as in pwm_timer; only ack is a pulse)
    return val


async def start(dut, passes, start_w=0, length=LEN, ctrl=0b001):
    await bus(dut, PASSES, 1, passes)
    await bus(dut, START, 1, start_w)
    await bus(dut, LENGTH, 1, length)
    await bus(dut, CTRL, 1, ctrl)


async def wait_done(dut, timeout_us=20000):
    async def poll():
        while True:
            st = await bus(dut, STATUS)
            if not st & 1:
                return st

    return await with_timeout(poll(), timeout_us, "us")


@cocotb.test()
async def test_selftest_passes(dut):
    ram = await setup(dut)
    await start(dut, 3)
    st = await wait_done(dut)
    assert st >> 16 == 3
    assert await bus(dut, ERRORS) == 0
    assert await bus(dut, ERR_ADDR) == 0
    assert not ram.errors, ram.errors


@cocotb.test()
async def test_selftest_inject(dut):
    await setup(dut)
    await start(dut, 2, start_w=100, ctrl=0b101)
    await wait_done(dut)
    assert await bus(dut, ERRORS) == 2
    assert await bus(dut, ERR_ADDR) == 0x8000_0000 | (100 + LEN // 2)
    data, exp = await bus(dut, ERR_DATA), await bus(dut, ERR_EXP)
    assert data == exp ^ 0xFFFF_FFFF
    await start(dut, 1, start_w=100)  # a new start clears the record
    await wait_done(dut)
    assert await bus(dut, ERRORS) == 0 and await bus(dut, ERR_ADDR) == 0


@cocotb.test()
async def test_selftest_catches_model_fault(dut):
    ram = await setup(dut)
    await start(dut, 1)

    async def flip_after_writes():
        while LEN - 1 not in ram.mem:  # the last write of the pass has been stored
            await RisingEdge(dut.clk)
        ram.mem[10] ^= 1

    await with_timeout(cocotb.start_soon(flip_after_writes()), 5000, "us")
    await wait_done(dut)
    assert await bus(dut, ERRORS) >= 1
    assert await bus(dut, ERR_ADDR) == 0x8000_0000 | 10


@cocotb.test()
async def test_selftest_leaves_outside_alone(dut):
    ram = await setup(dut)
    rng = random.Random(3)
    await start(dut, 1000, start_w=1024)
    exp = {}
    for k in range(1024):
        exp[k] = rng.getrandbits(32)
        await bus(dut, BASE_WORD + k, 1, exp[k])
    for k, v in exp.items():
        assert await bus(dut, BASE_WORD + k) == v, f"word {k}"
    st = await bus(dut, STATUS)
    assert st & 1 and st >> 16 >= 1, "the self-test should have been running (and completed a pass)"
    await bus(dut, CTRL, 1, 0b10)
    await wait_done(dut)
    assert await bus(dut, ERRORS) == 0
    assert not ram.errors, ram.errors


@cocotb.test()
async def test_rd_lat_register(dut):
    await setup(dut)
    assert await bus(dut, RD_LAT) == 2
    await bus(dut, RD_LAT, 1, 4)
    assert await bus(dut, RD_LAT) == 4
    await start(dut, 1)
    await wait_done(dut)
    assert await bus(dut, ERRORS) > 0
    await bus(dut, RD_LAT, 1, 2)
    await start(dut, 1)
    await wait_done(dut)
    assert await bus(dut, ERRORS) == 0


@cocotb.test()
async def test_start_ignored_when_out_of_range(dut):
    ram = await setup(dut)
    await bus(dut, BASE_WORD + 5, 1, 0x1234_5678)
    await bus(dut, START, 1, 1024)  # LENGTH is still the default 0x20_0000: would wrap onto words below START
    await bus(dut, CTRL, 1, 1)
    await ClockCycles(dut.clk, 300)
    assert await bus(dut, STATUS) == 0 and await bus(dut, BASE_WORD + 5) == 0x1234_5678
    await start(dut, 1, start_w=0, length=0x20_0001)  # longer than 8 MB
    await ClockCycles(dut.clk, 300)
    assert await bus(dut, STATUS) == 0
    await start(dut, 0x1_0000)  # stored as 0 (16 bits): ignored
    assert await bus(dut, PASSES) == 0
    await ClockCycles(dut.clk, 300)
    assert await bus(dut, STATUS) == 0
    await start(dut, 1, start_w=0x1F_FF00, length=256)  # ends exactly at 2^21: allowed
    st = await wait_done(dut)
    assert st >> 16 == 1 and await bus(dut, ERRORS) == 0
    assert not ram.errors, ram.errors


@cocotb.test()
async def test_runs_use_different_values(dut):
    ram = await setup(dut)
    await start(dut, 1)
    await wait_done(dut)
    first = {a: ram.mem[a] for a in range(LEN)}
    await start(dut, 1)
    await wait_done(dut)
    assert all(ram.mem[a] != first[a] for a in range(LEN))
    assert await bus(dut, ERRORS) == 0


@cocotb.test()
async def test_stop(dut):
    await setup(dut)
    await start(dut, 1000)
    await bus(dut, CTRL, 1, 0b10)
    await ClockCycles(dut.clk, 100)
    assert await bus(dut, STATUS) & 1 == 0


@cocotb.test()
async def test_registers(dut):
    await setup(dut)
    assert [await bus(dut, a) for a in (PASSES, START, LENGTH)] == [1, 0, 0x20_0000]
    for a, v in ((PASSES, 7), (START, 0x1F_FFFF), (LENGTH, 0x20_0000)):
        await bus(dut, a, 1, v)
        assert await bus(dut, a) == v


@pytest.mark.sim
def test_sim_sdram_test():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_sdram_test"
    runner = get_runner("icarus")
    runner.build(
        sources=[
            RTL / "sdram_ctrl.v",
            RTL / "sdram_arb.v",
            RTL / "sdram_port.v",
            RTL / "sdram_test.v",
            HERE / "sim_sdram_test_top.v",
        ],
        hdl_toplevel="sim_sdram_test_top",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="sim_sdram_test_top",
            test_module="test_sdram_test",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

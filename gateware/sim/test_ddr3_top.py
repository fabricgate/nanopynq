"""cocotb tests for src/nanopynq/rtl/ddr3_port.v (the 1 GiB host window at 0x4000_0000) and ddr3_test.v (the
self-test at 0x3000) through sim_ddr3_top (ddr3_arb, the board-top bus gating) against ddr3_ctrl_model.
LENGTH is 512 words to keep the runs short. The same file is the pytest entry point: `pytest -m sim`."""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, with_timeout

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
WIN = 0x4000_0000 >> 2  # bus word address of the DDR3 window (1 GiB)
T = 0x3000 >> 2  # bus word address of ddr3_test's registers
CTRL, STATUS, PASSES, START, LENGTH, ERRORS, ERR_ADDR, ERR_DATA, ERR_EXP, CALIB, WR_CYCLES, RD_CYCLES = (
    T + i for i in range(12)
)
LEN = 512
FULL = 0x1000_0000  # words in 1 GiB


async def setup(dut, calib_done=1, calib_fail=0):
    """calib_done, calib_fail as e-karge's ddr3_ctrl gives them: a failed calibration is done = 1, fail = 1."""
    from ddr3_ctrl_model import Ddr3CtrlModel

    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.rst.value = 1
    for s in (dut.bus_stb, dut.bus_we, dut.bus_adr, dut.bus_dat_w, dut.calib_fail, dut.rd_delay):
        s.value = 0
    dut.init_done.value = calib_done
    dut.calib_done.value = calib_done
    dut.calib_fail.value = calib_fail
    model = Ddr3CtrlModel(dut)
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 5)
    return model


async def bus(dut, adr, we=0, dat=0, limit=400):
    """One bus access (stb held until ack, through the ack edge like uartbone_bridge). Returns the read data."""
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
    assert not int(dut.bus_ack.value)
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


# --- ddr3_port ---


@cocotb.test()
async def test_window_write_read(dut):
    model = await setup(dut)
    rng = random.Random(1)
    words = {0: rng.getrandbits(32), 0x0ABC_DEF: rng.getrandbits(32), FULL - 1: rng.getrandbits(32)}
    for w, v in words.items():
        await bus(dut, WIN + w, 1, v)
    for w, v in words.items():
        assert model.mem[w] == v
        assert await bus(dut, WIN + w) == v


@cocotb.test()
async def test_window_answers_only_its_gigabyte(dut):
    await setup(dut)
    for adr, hit in ((WIN - 1, 0), (WIN, 1), (WIN + FULL - 1, 1), (WIN + FULL, 0), (0x3FFF_FFFF, 0)):
        await FallingEdge(dut.clk)
        dut.bus_adr.value = adr
        await ReadOnly()
        assert int(dut.port_hit.value) == hit, hex(adr)


@cocotb.test()
async def test_access_before_ready_is_acked_and_dropped(dut):
    model = await setup(dut, calib_done=0)
    assert await bus(dut, WIN + 5, 1, 0x1234_5678, limit=4) == 0
    assert await bus(dut, WIN + 5, limit=4) == 0
    await ClockCycles(dut.clk, 20)
    assert model.log == [] and 5 not in model.mem


@cocotb.test()
async def test_access_after_failed_calibration_is_acked_and_dropped(dut):
    model = await setup(dut, calib_done=1, calib_fail=1)
    assert await bus(dut, WIN + 5, 1, 0x1234_5678, limit=4) == 0
    assert await bus(dut, WIN + 5, limit=4) == 0
    await ClockCycles(dut.clk, 20)
    assert model.log == [] and 5 not in model.mem


# --- ddr3_test ---


@cocotb.test()
async def test_selftest_passes(dut):
    model = await setup(dut)
    await start(dut, 3)
    st = await wait_done(dut)
    assert st >> 16 == 3
    assert await bus(dut, ERRORS) == 0 and await bus(dut, ERR_ADDR) == 0
    writes = [burst for _, op, _, burst in model.log if op == "wr"]
    assert writes == [1] * (3 * LEN // 8)


@cocotb.test()
async def test_selftest_counts_cycles(dut):
    await setup(dut)
    await start(dut, 1)
    await wait_done(dut)
    wr1, rd1 = await bus(dut, WR_CYCLES), await bus(dut, RD_CYCLES)
    assert wr1 >= LEN // 8 and rd1 >= LEN // 8, (wr1, rd1)
    await start(dut, 1)
    await wait_done(dut)
    wr2, rd2 = await bus(dut, WR_CYCLES), await bus(dut, RD_CYCLES)
    assert LEN // 8 <= wr2 < 3 * wr1 // 2 and LEN // 8 <= rd2 < 3 * rd1 // 2, (wr1, rd1, wr2, rd2)  # cleared at start


@cocotb.test()
async def test_start_ignored_unless_multiple_of_eight(dut):
    model = await setup(dut)
    for start_w, length in ((4, LEN), (0, 12)):
        await start(dut, 1, start_w=start_w, length=length)
        await ClockCycles(dut.clk, 100)
        assert await bus(dut, STATUS) == 0 and model.log == [], (start_w, length)


@cocotb.test()
async def test_errors_count_words_and_first_is_lowest(dut):
    model = await setup(dut)
    await start(dut, 1)

    async def flip_after_writes():
        while LEN - 1 not in model.mem:
            await RisingEdge(dut.clk)
        model.mem[21] ^= 0x100
        model.mem[18] ^= 1

    await with_timeout(cocotb.start_soon(flip_after_writes()), 5000, "us")
    await wait_done(dut)
    assert await bus(dut, ERRORS) == 2
    assert await bus(dut, ERR_ADDR) == 0x8000_0000 | 18
    assert await bus(dut, ERR_DATA) ^ await bus(dut, ERR_EXP) == 1


@cocotb.test()
async def test_selftest_inject(dut):
    await setup(dut)
    base = FULL - LEN  # the last words of the gigabyte
    await start(dut, 2, start_w=base, ctrl=0b101)
    await wait_done(dut)
    assert await bus(dut, ERRORS) == 2
    assert await bus(dut, ERR_ADDR) == 0x8000_0000 | (base + LEN // 2)
    data, exp = await bus(dut, ERR_DATA), await bus(dut, ERR_EXP)
    assert data == exp ^ 0xFFFF_FFFF


@cocotb.test()
async def test_selftest_catches_model_fault(dut):
    model = await setup(dut)
    await start(dut, 1)

    async def flip_after_writes():
        while LEN - 1 not in model.mem:
            await RisingEdge(dut.clk)
        model.mem[10] ^= 1

    await with_timeout(cocotb.start_soon(flip_after_writes()), 5000, "us")
    await wait_done(dut)
    assert await bus(dut, ERRORS) >= 1
    assert await bus(dut, ERR_ADDR) == 0x8000_0000 | 10


@cocotb.test()
async def test_start_beyond_one_gigabyte_is_ignored(dut):
    await setup(dut)
    await bus(dut, START, 1, 1024)  # LENGTH is still the default (1 GiB): would run past the end
    await bus(dut, CTRL, 1, 1)
    await ClockCycles(dut.clk, 100)
    assert await bus(dut, STATUS) == 0
    await start(dut, 1, start_w=0, length=FULL + 1)
    await ClockCycles(dut.clk, 100)
    assert await bus(dut, STATUS) == 0
    await start(dut, 1, start_w=FULL - 256, length=256)  # ends exactly at 1 GiB: allowed
    st = await wait_done(dut)
    assert st >> 16 == 1 and await bus(dut, ERRORS) == 0


@cocotb.test()
async def test_start_ignored_before_ready(dut):
    model = await setup(dut, calib_done=0)
    await start(dut, 1)
    await ClockCycles(dut.clk, 100)
    assert await bus(dut, STATUS) == 0 and model.log == []


@cocotb.test()
async def test_start_ignored_after_failed_calibration(dut):
    model = await setup(dut, calib_done=1, calib_fail=1)
    await start(dut, 1)
    await ClockCycles(dut.clk, 100)
    assert await bus(dut, STATUS) == 0 and model.log == []


@cocotb.test()
async def test_registers(dut):
    await setup(dut)
    assert [await bus(dut, a) for a in (PASSES, START, LENGTH)] == [1, 0, FULL]
    for a, v in ((PASSES, 7), (START, FULL - 1), (LENGTH, FULL)):
        await bus(dut, a, 1, v)
        assert await bus(dut, a) == v


@cocotb.test()
async def test_calib_register_shows_ready_fail_and_delays(dut):
    await setup(dut)
    delays = 63 | 5 << 6 | 40 << 12 | 1 << 18  # lanes 0..3 = 63, 5, 40, 1 (6 bits each)
    dut.rd_delay.value = delays
    assert await bus(dut, CALIB) == (delays << 8) | 0b011
    dut.calib_fail.value = 1  # a failed calibration: done and fail
    assert await bus(dut, CALIB) == (delays << 8) | 0b111


@cocotb.test()
async def test_stop(dut):
    await setup(dut)
    await start(dut, 1000)
    await bus(dut, CTRL, 1, 0b10)
    await ClockCycles(dut.clk, 100)
    assert await bus(dut, STATUS) & 1 == 0


@pytest.mark.sim
def test_sim_ddr3_top():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_ddr3_top"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "ddr3_arb.v", RTL / "ddr3_port.v", RTL / "ddr3_test.v", HERE / "sim_ddr3_top.v"],
        hdl_toplevel="sim_ddr3_top",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="sim_ddr3_top",
            test_module="test_ddr3_top",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

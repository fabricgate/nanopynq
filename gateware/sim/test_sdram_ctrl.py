"""cocotb tests for src/nanopynq/rtl/sdram_ctrl.v (the module itself is the toplevel) against
sdram_model.SDRAMModel. The same file is the pytest entry point: `pytest -m sim`."""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, with_timeout
from cocotb.utils import get_sim_time

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
CLK_NS = 37.037  # the board clock is 27 MHz


async def setup(dut, rd_lat=2):
    from sdram_model import SDRAMModel

    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns", period_high=18.519).start())
    dut.rst.value = 1
    dut.rd_lat.value = rd_lat
    dut.cmd_valid.value = 0
    dut.cmd_write.value = 0
    dut.cmd_addr.value = 0
    dut.cmd_wdata.value = 0
    dut.cmd_wmask.value = 0
    await ClockCycles(dut.clk, 2)
    ram = SDRAMModel(dut)
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await with_timeout(RisingEdge(dut.init_done), 250, "us")
    return ram


async def run(dut, cmds):
    """Drive cmds = [(write, addr, wdata, wmask)] back to back, cmd_valid high throughout; return the
    words read. Checks that every accepted read has its rd_valid before cmd_ready is high again."""
    got, reads = [], 0

    async def collect():
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if int(dut.cmd_ready.value):
                assert len(got) == reads, "cmd_ready high before rd_valid of the last read"
            if int(dut.rd_valid.value):
                got.append(int(dut.rd_data.value))

    mon = cocotb.start_soon(collect())
    for write, addr, wdata, wmask in cmds:
        await FallingEdge(dut.clk)
        dut.cmd_valid.value, dut.cmd_write.value, dut.cmd_addr.value = 1, int(write), addr
        dut.cmd_wdata.value, dut.cmd_wmask.value = wdata, wmask
        while not int(dut.cmd_ready.value):  # cmd_ready does not depend on cmd_*
            await FallingEdge(dut.clk)
        await RisingEdge(dut.clk)  # taken at this edge
        reads += not write
    await FallingEdge(dut.clk)
    dut.cmd_valid.value = 0
    for _ in range(30):  # the last access (and a refresh) ends: its WRITE has reached the model too
        if int(dut.cmd_ready.value):
            break
        await FallingEdge(dut.clk)
    mon.cancel()
    assert len(got) == reads, f"{len(got)} of {reads} reads returned"
    return got


def writes(words):
    return [(True, a, w, 0xF) for a, w in words.items()]


def reads(addrs):
    return [(False, a, 0, 0) for a in addrs]


@cocotb.test()
async def test_init_sequence(dut):
    ram = await setup(dut)
    await ClockCycles(dut.clk, 1)  # the model takes MRS half a clock after the controller drives it
    assert [name for _, name in ram.log] == ["PRECHARGE", "REFRESH", "REFRESH", "MRS"]
    assert ram.log[0][0] >= 200_000
    assert ram.errors == []


@cocotb.test()
async def test_write_read_random(dut):
    ram = await setup(dut, rd_lat=2)
    rnd = random.Random(1)
    addrs = [0, 0x1FFFFF, *rnd.sample(range(1, 0x1FFFFF), 198)]
    words = {a: rnd.getrandbits(32) for a in addrs}
    await run(dut, writes(words))
    assert ram.mem == words  # the model's {bank, row, col} decode matches cmd_addr
    assert await run(dut, reads(addrs)) == list(words.values())
    assert ram.errors == []


@cocotb.test()
async def test_byte_mask(dut):
    ram = await setup(dut)
    await run(dut, [(True, 0x12345, 0xFFFFFFFF, 0xF), (True, 0x12345, 0x00000000, 0b0101)])
    assert await run(dut, reads([0x12345])) == [0xFF00FF00]
    assert ram.errors == []


@cocotb.test()
async def test_refresh_under_load(dut):
    ram = await setup(dut)
    rnd = random.Random(2)
    addrs = rnd.sample(range(1 << 21), 300)
    words = {a: rnd.getrandbits(32) for a in addrs}
    t0, n0 = get_sim_time(unit="ns"), len(ram.log)
    got = await run(dut, writes(words) + reads(addrs))
    assert get_sim_time(unit="ns") - t0 >= 40_000
    assert [name for _, name in ram.log[n0:]].count("REFRESH") >= 2
    assert got == list(words.values())
    assert ram.errors == []


@cocotb.test()
async def test_wrong_rd_lat_fails(dut):
    ram = await setup(dut, rd_lat=4)
    rnd = random.Random(3)
    addrs = rnd.sample(range(1 << 21), 20)
    words = {a: rnd.getrandbits(32) for a in addrs}
    await run(dut, writes(words))
    assert await run(dut, reads(addrs)) != list(words.values())
    assert ram.errors == []


@pytest.mark.sim
def test_sim_sdram_ctrl():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_sdram"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "sdram_ctrl.v"],
        hdl_toplevel="sdram_ctrl",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="sdram_ctrl",
            test_module="test_sdram_ctrl",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

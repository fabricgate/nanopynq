"""cocotb tests for src/nanopynq/rtl/hyperram_ctrl.v (the module itself is the toplevel) against
hyperram_model.HyperRAMModel. The same file is the pytest entry point: `pytest -m sim`."""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
CLK_NS = 37.037  # the board clock is 27 MHz
TCSM_NS = 4000


async def setup(dut):
    from hyperram_model import HyperRAMModel

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.cmd_valid.value = 0
    dut.cmd_write.value = 0
    dut.cmd_addr.value = 0
    dut.cmd_len.value = 0
    dut.wd_data.value = 0
    dut.rst.value = 1
    ram = HyperRAMModel(dut)
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)
    return ram


async def transact(dut, write, addr, n=None, words=()):
    """One command; returns the words read (empty for a write)."""
    words, got, i = list(words), [], 0
    n = len(words) if write else n
    await FallingEdge(dut.clk)
    dut.cmd_valid.value, dut.cmd_write.value, dut.cmd_addr.value, dut.cmd_len.value = 1, int(write), addr, n
    dut.wd_data.value = words[0] if words else 0
    accepted, take, ready = False, 0, int(dut.cmd_ready.value)
    for _ in range(2000):
        await RisingEdge(dut.clk)
        await ReadOnly()
        accepted = accepted or bool(ready)  # cmd_valid and cmd_ready were both high at this edge
        i += take  # wd_ready was high in the clock that just ended: the controller took words[i]
        take, ready = int(dut.wd_ready.value), int(dut.cmd_ready.value)
        if int(dut.rd_valid.value):
            got.append(int(dut.rd_data.value))
        done = int(dut.done.value)
        await FallingEdge(dut.clk)
        if accepted:
            dut.cmd_valid.value = 0
        dut.wd_data.value = words[i] if i < len(words) else 0
        if done:
            assert i == len(words), f"{i} words taken of {len(words)}"
            return got
    raise TimeoutError("no done")


@cocotb.test()
async def burst8_round_trip(dut):
    ram = await setup(dut)
    rnd = random.Random(1)
    for addr in (0x0, 0x1F8, 0x1FC, 0x3FFFF8, rnd.randrange(1 << 22)):
        words = [rnd.randrange(1 << 16) for _ in range(8)]
        await transact(dut, True, addr, words=words)
        assert [ram.mem.get(addr + k) for k in range(8)] == words
        assert await transact(dut, False, addr, 8) == words
    assert ram.errors == []


@cocotb.test()
async def single_word_round_trip(dut):
    ram = await setup(dut)
    await transact(dut, True, 0x12345, words=[0xA55A])
    assert ram.mem == {0x12345: 0xA55A}
    assert await transact(dut, False, 0x12345, 1) == [0xA55A]
    assert ram.errors == []


@cocotb.test()
async def transactions_stay_under_tcsm(dut):  # Review Focus 4
    ram = await setup(dut)
    await transact(dut, True, 0x100, words=list(range(8)))  # frame data
    await transact(dut, True, 0x0, words=[1, 2])  # slot header
    await transact(dut, False, 0x100, 4)  # window fetch
    assert [t["edges"] // 2 for t in ram.log] == [24, 18, 21]  # CA 3 + latency 13/14 + words
    await transact(dut, False, 0x100, 8)  # the longest read the controller can do
    assert all(t["clks"] * CLK_NS < TCSM_NS for t in ram.log), [t["clks"] for t in ram.log]
    assert ram.errors == []


@cocotb.test()
async def cs_high_between_back_to_back_commands(dut):
    ram = await setup(dut)
    for k in range(3):
        await transact(dut, True, 8 * k, words=[k] * 8)
    assert all(t["gap"] >= 2 for t in ram.log[1:]), [t["gap"] for t in ram.log]
    assert ram.errors == []


@pytest.mark.sim
def test_sim_hyperram_ctrl():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_hram"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "hyperram_ctrl.v"],
        hdl_toplevel="hyperram_ctrl",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="hyperram_ctrl",
            test_module="test_hyperram_ctrl",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

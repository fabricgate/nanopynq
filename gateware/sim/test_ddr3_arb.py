"""cocotb tests for src/nanopynq/rtl/ddr3_arb.v (two masters and the refresh onto e-karge's ddr3_ctrl) against
ddr3_ctrl_model.Ddr3CtrlModel. The same file is the pytest entry point: `pytest -m sim`."""

import itertools
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
REFRESH_CYCLES = 390  # ddr3_arb's default: 7.8 us at 50 MHz


def words(*w):
    """A burst (256 bits, word 0 in the low bits) from its 8 words."""
    return sum(v << 32 * j for j, v in enumerate(w))


async def setup(dut, ready=1):
    from ddr3_ctrl_model import Ddr3CtrlModel

    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.rst.value = 1
    dut.ready.value = ready
    for m in "ab":
        for s in ("valid", "write", "addr", "wdata", "wmask"):
            getattr(dut, f"{m}_{s}").value = 0
    model = Ddr3CtrlModel(dut)
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    return model


async def access(dut, m, write, addr, wdata=0, wmask=None, limit=2000):
    """One access by master m ("a": one word, "b": 8 words, 256-bit wdata / rd_data and a 32-bit wmask): valid held
    until taken; for a read, wait for rd_valid. Returns the read data (None for a write). wmask defaults to all
    bytes."""
    sig = lambda n: getattr(dut, f"{m}_{n}")  # noqa: E731
    wmask = (0xF if m == "a" else 0xFFFF_FFFF) if wmask is None else wmask
    await FallingEdge(dut.clk)
    sig("valid").value, sig("write").value, sig("addr").value = 1, write, addr
    sig("wdata").value, sig("wmask").value = wdata, wmask
    for _ in range(limit):  # taken at the clock edge where valid and ready are both high
        await ReadOnly()  # the masters change their inputs only at falling edges
        taken = int(sig("ready").value)
        await RisingEdge(dut.clk)
        if taken:
            break
        await FallingEdge(dut.clk)
    else:
        raise AssertionError(f"master {m} was never taken")
    await FallingEdge(dut.clk)
    sig("valid").value = 0
    if write:
        return None
    for _ in range(limit):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(sig("rd_valid").value):
            return int(sig("rd_data").value)
    raise AssertionError(f"master {m}: no rd_valid")


@cocotb.test()
async def test_write_then_read_returns_the_word(dut):
    model = await setup(dut)
    await access(dut, "a", 1, 0x0ABC_DEF, 0x1234_5678)
    await ClockCycles(dut.clk, 2)  # the pulse goes out one clock after the request is taken
    assert model.mem[0x0ABC_DEF] == 0x1234_5678
    assert await access(dut, "a", 0, 0x0ABC_DEF) == 0x1234_5678
    await access(dut, "b", 1, 0xFFF_FFFF, words(*range(1, 9)), wmask=0x0000_00F0)  # word 1 of the burst only
    await ClockCycles(dut.clk, 2)
    assert model.mem[0xFFF_FFF9] == 2
    assert [a for a in model.mem if a >> 3 == 0xFFF_FFFF >> 3] == [0xFFF_FFF9]


@cocotb.test()
async def test_b_burst_write_then_read_returns_eight_words(dut):
    model = await setup(dut)
    data = words(*(0x1000_0000 * j + 0x55 for j in range(8)))
    await access(dut, "b", 1, 0x100, data)
    await ClockCycles(dut.clk, 2)
    assert [model.mem[0x100 + j] for j in range(8)] == [0x1000_0000 * j + 0x55 for j in range(8)]
    assert await access(dut, "b", 0, 0x103) == data
    assert [x[3] for x in model.log if x[1] == "wr"] == [1]


@cocotb.test()
async def test_a_word_after_b_burst_writes_one_word(dut):
    model = await setup(dut)
    await access(dut, "b", 1, 0x100, words(*[0xBBBB_BBBB] * 8))
    await access(dut, "a", 1, 0x105, 0xAAAA_AAAA)
    await ClockCycles(dut.clk, 2)
    assert [x[3] for x in model.log if x[1] == "wr"] == [1, 0]
    assert [model.mem[0x100 + j] for j in range(8)] == [0xBBBB_BBBB] * 5 + [0xAAAA_AAAA] + [0xBBBB_BBBB] * 2


@cocotb.test()
async def test_a_wins_over_b(dut):
    model = await setup(dut)
    await ClockCycles(dut.clk, 30)  # past the controller's start-up
    ta = cocotb.start_soon(access(dut, "a", 1, 1, 0xA))
    tb = cocotb.start_soon(access(dut, "b", 1, 2, 0xB))
    await ta
    await tb
    await ClockCycles(dut.clk, 2)
    ops = [x for x in model.log if x[1] != "ref"]
    assert [x[2] for x in ops] == [1, 2]


@cocotb.test()
async def test_read_data_goes_to_its_master(dut):
    model = await setup(dut)
    model.mem[7] = 0x7777
    seen_a = []

    async def watch_a():
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if int(dut.a_rd_valid.value):
                seen_a.append(int(dut.a_rd_data.value))

    cocotb.start_soon(watch_a())
    assert await access(dut, "b", 0, 7) == 0x7777 << 32 * 7
    assert seen_a == []


@cocotb.test()
async def test_nothing_before_ready(dut):
    model = await setup(dut, ready=0)
    await FallingEdge(dut.clk)
    dut.a_valid.value, dut.a_write.value = 1, 1
    for _ in range(3 * REFRESH_CYCLES):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert not int(dut.rd.value) and not int(dut.wr.value) and not int(dut.refresh.value)
        assert not int(dut.a_ready.value)
    assert model.log == []


@cocotb.test()
async def test_refresh_keeps_up_under_load(dut):
    model = await setup(dut)

    async def hammer(m, base):
        i = 0
        while True:
            await access(dut, m, i & 1, base + i, i)
            i += 1

    cocotb.start_soon(hammer("a", 0))  # back to back: b would wait for ever behind it (fixed priority)
    await ClockCycles(dut.clk, 20 * REFRESH_CYCLES)
    refs = [c for c, op, _, _ in model.log if op == "ref"]
    gaps = [b - a for a, b in itertools.pairwise(refs)]
    assert len(refs) >= 18, refs
    assert max(gaps) <= REFRESH_CYCLES + 25, gaps  # one access (at most 21 clocks) may delay a refresh
    assert sum(op != "ref" for _, op, _, _ in model.log) > 100  # the master still got through


@pytest.mark.sim
def test_sim_ddr3_arb():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_ddr3_arb"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "ddr3_arb.v"],
        hdl_toplevel="ddr3_arb",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="ddr3_arb",
            test_module="test_ddr3_arb",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

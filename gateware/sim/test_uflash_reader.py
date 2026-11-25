"""cocotb tests for src/nanopynq/rtl/uflash_reader.v. The pytest entry point needs iverilog: `pytest -m sim`.

The flash is flash256k_model.v (our own read model; Gowin's prim_sim.v is not used): word w holds
w * 0x9E3779B1, DOUT is X until 24 ns after SE rises, and err counts protocol violations.
"""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
BASE, WORDS = 0x10000, 8192


def word(w):
    return (w * 0x9E3779B1) & 0xFFFF_FFFF


async def bus(dut, addr, value=None, max_clocks=20):
    """One bus cycle like jtag_bridge: stb held until ack. Returns (data, clocks to ack) or None."""
    await FallingEdge(dut.clk)
    dut.bus_adr.value = addr >> 2
    dut.bus_we.value = value is not None
    dut.bus_dat_w.value = value or 0
    dut.bus_stb.value = 1
    got = None
    for n in range(1, max_clocks + 1):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.bus_ack.value):
            got = (int(dut.bus_dat_r.value), n)  # int() fails on X: DOUT sampled too early
            break
    await FallingEdge(dut.clk)
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    return got


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 37, unit="ns").start())  # about 27 MHz
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    dut.bus_adr.value = 0
    dut.bus_dat_w.value = 0
    dut.rst.value = 1
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


def check_clean(dut):
    assert int(dut.flash.err.value) == 0, "flash protocol violation (see flash256k_model.v)"
    for p in ("PROG", "ERASE", "NVSTR"):
        assert str(getattr(dut.flash, p).value) == "0", p
    assert int(dut.flash.DIN.value) == 0


@cocotb.test()
async def reads_words(dut):
    """Edges of the X / Y split, the last word and random words read back right, idle data bus 0."""
    await setup(dut)
    rng = random.Random(8)
    reads0 = int(dut.flash.reads.value)  # tests share one simulation
    ws = [0, 1, 63, 64, 65, 4095, 4096, WORDS - 1] + [rng.randrange(WORDS) for _ in range(40)]
    for w in ws:
        got = await bus(dut, BASE + 4 * w)
        assert got is not None, f"no ack for word {w}"
        assert got[0] == word(w), f"word {w}: 0x{got[0]:08x} != 0x{word(w):08x}"
        assert got[1] <= 6
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.bus_dat_r.value) == 0  # OR-ed into the shared read bus
    assert int(dut.flash.reads.value) - reads0 == len(ws)
    check_clean(dut)


@cocotb.test()
async def writes_ignored_and_range(dut):
    """Writes ack without touching the flash; addresses outside the window neither hit nor ack."""
    await setup(dut)
    reads0 = int(dut.flash.reads.value)
    got = await bus(dut, BASE + 4 * 5, value=0x1234_5678)
    assert got is not None and got[1] == 1
    assert int(dut.flash.reads.value) == reads0
    for addr in (BASE - 4, BASE + 4 * WORDS):
        await FallingEdge(dut.clk)
        dut.bus_adr.value = addr >> 2
        await ReadOnly()
        assert not int(dut.hit.value)
        assert await bus(dut, addr, max_clocks=8) is None
    assert (await bus(dut, BASE + 4 * 5))[0] == word(5)  # still reads
    check_clean(dut)


@pytest.mark.sim
def test_sim_uflash_reader():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_uflash"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "uflash_reader.v", HERE / "flash256k_model.v"],
        hdl_toplevel="uflash_reader",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": BASE},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="uflash_reader",
            test_module="test_uflash_reader",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

"""cocotb tests for src/nanopynq/rtl/bus_cdc.v: a register bus on clk (27 MHz-like) carried to a slave on
sclk (81 MHz-like). The slave is played here: 16 words of memory, ack 1-3 sclk after stb.
The pytest entry point needs iverilog: `pytest -m sim`.
"""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
BASE, WORDS = 0x6000, 5


class Slave:
    def __init__(self, dut):
        self.dut, self.mem, self.strobes = dut, {}, 0
        cocotb.start_soon(self.run())

    async def run(self):
        d = self.dut
        d.s_ack.value = 0
        d.s_dat_r.value = 0
        while True:
            await RisingEdge(d.sclk)
            await ReadOnly()
            if not int(d.s_stb.value):
                continue
            self.strobes += 1
            adr, we, dat = int(d.s_adr.value), int(d.s_we.value), int(d.s_dat_w.value)
            await FallingEdge(d.sclk)
            for _ in range(random.randint(0, 2)):
                await FallingEdge(d.sclk)
            if we:
                self.mem[adr] = dat
            d.s_dat_r.value = 0 if we else self.mem.get(adr, 0)
            d.s_ack.value = 1
            await FallingEdge(d.sclk)
            d.s_ack.value = 0
            d.s_dat_r.value = 0xFFFF_FFFF  # garbage after the ack: must not reach the master
            await RisingEdge(d.sclk)  # s_stb drops the clock after s_ack


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 37, unit="ns").start())
    cocotb.start_soon(Clock(dut.sclk, 12.3, unit="ns").start())
    for s in ("bus_stb", "bus_we", "bus_adr", "bus_dat_w"):
        getattr(dut, s).value = 0
    slave = Slave(dut)
    dut.rst.value = 1
    dut.srst.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0
    dut.srst.value = 0
    return slave


async def bus(dut, addr, value=None, limit=20):
    """One bus cycle like jtag_bridge: stb held until ack, dropped the clock after. Returns (data, clocks)."""
    await FallingEdge(dut.clk)
    dut.bus_adr.value = addr >> 2
    dut.bus_we.value = value is not None
    dut.bus_dat_w.value = value or 0
    dut.bus_stb.value = 1
    for n in range(1, limit + 1):  # noqa: B007 (n is the clock count returned below)
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.hit.value) == 1
        if int(dut.bus_ack.value):
            got = int(dut.bus_dat_r.value)
            break
        assert int(dut.bus_dat_r.value) == 0  # OR-ed into the shared read bus
    else:
        raise TimeoutError(f"no ack for 0x{addr:x}")
    await FallingEdge(dut.clk)
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.bus_ack.value) == 0 and int(dut.bus_dat_r.value) == 0  # one-clock ack
    return got, n


@cocotb.test()
async def writes_and_reads_cross_once_each(dut):
    slave = await setup(dut)
    random.seed(1)
    want = {}
    for _i in range(40):
        a = BASE + 4 * random.randrange(WORDS)
        if random.random() < 0.5:
            v = random.getrandbits(32)
            _, n = await bus(dut, a, v)
            want[a] = v
        else:
            got, n = await bus(dut, a)
            assert got == want.get(a, 0), (hex(a), hex(got))
        assert n <= 12, n  # well before the bridge's next scan
    assert slave.strobes == 40
    assert slave.mem == {(a >> 2): v for a, v in want.items()}


@cocotb.test()
async def outside_the_range_is_not_ours(dut):
    slave = await setup(dut)
    for a in (BASE - 4, BASE + 4 * WORDS, 0x0):
        await FallingEdge(dut.clk)
        dut.bus_adr.value = a >> 2
        dut.bus_stb.value = 1
        for _ in range(15):
            await RisingEdge(dut.clk)
            await ReadOnly()
            assert int(dut.hit.value) == 0 and int(dut.bus_ack.value) == 0 and int(dut.bus_dat_r.value) == 0
        await FallingEdge(dut.clk)
        dut.bus_stb.value = 0
    await ClockCycles(dut.clk, 10)
    assert slave.strobes == 0


@pytest.mark.sim
def test_sim_bus_cdc():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_buscdc"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "bus_cdc.v"],
        hdl_toplevel="bus_cdc",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": BASE, "WORDS": WORDS},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="bus_cdc",
            test_module="test_bus_cdc",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

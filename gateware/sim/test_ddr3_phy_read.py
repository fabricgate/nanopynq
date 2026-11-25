"""cocotb tests for the read capture of e-karge's ddr3_phy_slow (src/nanopynq/rtl/ddr3/ddr3_phy_slow.sv): the plain
fabric capture registers (IDDR=0) and the IDDR in the IO blocks (IDDR=1) must pick the same DQ samples for every
read delay. DQ changes every half clk cycle, 5 ns after each clk edge, and counts up, so a sample tells when it was
taken. The same file is the pytest entry point: `pytest -m sim`."""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
H0 = 4 * (6 - 1) - 2  # ddr3_phy_slow's H0 for CL 6: the sample of beat 0 at read delay 0


class Dq:
    """Drives DQ with n (every byte lane) and counts n up every half clk cycle."""

    def __init__(self, dut):
        self.dut, self.n = dut, 0

    async def run(self):
        await RisingEdge(self.dut.clk)
        while True:
            await Timer(5, "ns")
            self.n += 1
            self.dut.tb_dq.value = (self.n & 0xFF) * 0x0101_0101
            await Timer(5, "ns")


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.phy_rd.value = 0
    dut.phy_rd_delay.value = 0
    dut.tb_dq.value = 0
    dut.tb_dq_en.value = 1
    dq = Dq(dut)
    cocotb.start_soon(dq.run())
    for _ in range(4):
        await RisingEdge(dut.clk)
    return dq


async def read(dut, dq, delays):
    """One READ with the read delays of lanes 0..3; returns the DQ count at the edge that takes the READ and
    the bursts of both PHYs."""
    while True:  # phy_rd high in a ce cycle: taken at the next rising edge
        await FallingEdge(dut.clk)
        if int(dut.ce.value):
            break
    dut.phy_rd_delay.value = sum(d << (3 * lane) for lane, d in enumerate(delays))
    dut.phy_rd.value = 1
    await RisingEdge(dut.clk)
    n0 = dq.n
    await FallingEdge(dut.clk)
    dut.phy_rd.value = 0
    got = {}
    for _ in range(200):
        await RisingEdge(dut.clk)
        await ReadOnly()
        for i in (0, 1):
            if i not in got and int(getattr(dut, f"rvalid{i}").value):
                got[i] = int(getattr(dut, f"rdata{i}").value)
        if len(got) == 2:
            return n0, got[0], got[1]
    raise AssertionError(f"no read data from {set((0, 1)) - set(got)}")


def beats(burst):
    """[beat][lane] bytes of a 256-bit burst."""
    return [[(burst >> (32 * j + 8 * lane)) & 0xFF for lane in range(4)] for j in range(8)]


@cocotb.test()
async def plain_capture_takes_the_sample_of_each_delay(dut):
    """The reference: beat j of a lane with delay d is the DQ value at H0 + d + 2j half cycles after the READ edge."""
    dq = await setup(dut)
    for delays in ([d] * 4 for d in range(8)):
        n0, plain, _ = await read(dut, dq, delays)
        want = [[(n0 + H0 + delays[lane] + 2 * j) & 0xFF for lane in range(4)] for j in range(8)]
        assert beats(plain) == want, (delays, n0)


@cocotb.test()
async def iddr_capture_reads_the_same_beats(dut):
    dq = await setup(dut)
    for delays in [[d] * 4 for d in range(8)] + [[0, 3, 5, 7], [7, 2, 1, 4]]:
        _, plain, iddr = await read(dut, dq, delays)
        assert beats(iddr) == beats(plain), delays


@pytest.mark.sim
def test_sim_ddr3_phy_read():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_ddr3_phy_read"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "ddr3" / "ddr3_phy_slow.sv", HERE / "gowin_io_model.v", HERE / "sim_ddr3_phy_read.v"],
        hdl_toplevel="sim_ddr3_phy_read",
        build_dir=build,
        always=True,
        build_args=["-g2012"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="sim_ddr3_phy_read",
            test_module="test_ddr3_phy_read",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

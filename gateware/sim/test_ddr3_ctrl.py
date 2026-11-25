"""cocotb tests for the burst write of e-karge's ddr3_ctrl (src/nanopynq/rtl/ddr3/ddr3_ctrl.sv) against PhyModel, a
stand-in for the PHY side: it keeps the written bursts per (bank, row, column of the burst) and answers each read 4
ce cycles later with the stored burst. The controller runs on every other clock (ce), as with ddr3_phy_slow. Every
test first waits for the init and the read calibration to pass on this model. The same file is the pytest entry
point: `pytest -m sim`."""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
CMD_ACT, CMD_NOP = 0b011, 0b111
ONES = (1 << 256) - 1


class PhyModel:
    def __init__(self, dut):
        self.dut = dut
        self.mem: dict[tuple[int, int, int], int] = {}  # (bank, row, column & 0x3F8) -> 256-bit burst
        self.writes: list[tuple[int, int]] = []  # (phy_wdata, phy_wmask) of every write
        self.row = {}
        dut.ce.value = 0
        dut.phy_ready.value = 1
        dut.phy_rvalid.value = 0
        dut.phy_rdata.value = 0
        cocotb.start_soon(self._run())

    async def _run(self):
        dut, ce, wait, burst = self.dut, 0, None, 0
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if ce:  # the controller just updated its PHY outputs
                cmd, ba, a = int(dut.phy_cmd.value), int(dut.phy_ba.value), int(dut.phy_addr.value)
                if cmd == CMD_ACT:
                    self.row[ba] = a
                key = (ba, self.row.get(ba, 0), a & 0x3F8)
                if int(dut.phy_wr.value):
                    data, mask = int(dut.phy_wdata.value), int(dut.phy_wmask.value)
                    self.writes.append((data, mask))
                    keep = sum(0xFF << 8 * i for i in range(32) if mask >> i & 1)
                    self.mem[key] = (self.mem.get(key, 0) & keep) | (data & ~keep & ONES)
                if int(dut.phy_rd.value):
                    wait, burst = 4, self.mem.get(key, 0)
                elif wait is not None:
                    wait -= 1
            await FallingEdge(dut.clk)
            ce ^= 1
            dut.ce.value = ce
            if ce and wait == 0:
                dut.phy_rvalid.value, dut.phy_rdata.value, wait = 1, burst, None
            elif ce:
                dut.phy_rvalid.value = 0


def word_addr(ba, row, col):
    return ba << 25 | row << 10 | col


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.rst.value = 1
    for s in ("rd", "wr", "refresh", "addr", "din", "be", "burst", "din_burst", "be_burst"):
        getattr(dut, s).value = 0
    phy = PhyModel(dut)
    for _ in range(5):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    for _ in range(200_000):
        await RisingEdge(dut.clk)
        if int(dut.calib_done.value) and not int(dut.busy.value):
            break
    else:
        raise AssertionError("no calib_done")
    assert not int(dut.calib_fail.value)
    return phy


async def request(dut, **sigs):
    """One request (rd or wr with its inputs) while busy is low; waits until busy drops again. Returns dout_burst
    for a read."""
    await FallingEdge(dut.clk)
    while int(dut.busy.value):
        await FallingEdge(dut.clk)
    for k, v in sigs.items():
        getattr(dut, k).value = v
    await FallingEdge(dut.clk)
    dut.rd.value, dut.wr.value = 0, 0
    got = None
    for _ in range(2000):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.data_ready.value):
            got = int(dut.dout_burst.value)
        if not int(dut.busy.value):
            return got
    raise AssertionError("busy did not drop")


def words(*w):
    return sum(v << 32 * j for j, v in enumerate(w))


@cocotb.test()
async def burst_write_sends_the_eight_words_with_their_byte_enables(dut):
    phy = await setup(dut)
    data = words(*(0x1111_1111 * (j + 1) for j in range(8)))
    await request(dut, wr=1, burst=1, addr=word_addr(2, 0x1234, 0x15), din_burst=data, be_burst=0xFFFF_FFFF)
    assert phy.writes[-1] == (data, 0)
    assert phy.mem[(2, 0x1234, 0x10)] == data


@cocotb.test()
async def word_write_is_unchanged(dut):
    phy = await setup(dut)
    await request(dut, wr=1, burst=0, addr=word_addr(1, 7, 0x13), din=0xCAFE_F00D, be=0b0011)
    data, mask = phy.writes[-1]
    assert data == words(*[0xCAFE_F00D] * 8)
    assert mask == 0xFFFF_FFFF & ~(0b0011 << 4 * 3)


@cocotb.test()
async def partial_burst_keeps_the_masked_bytes(dut):
    await setup(dut)
    a = word_addr(5, 0x0ABC, 0x208)
    old = words(*(0xA0A0_0000 + j for j in range(8)))
    await request(dut, wr=1, burst=1, addr=a, din_burst=old, be_burst=0xFFFF_FFFF)
    await request(dut, wr=1, burst=1, addr=a, din_burst=words(*[0x5555_5555] * 8), be_burst=0x0000_000F)
    got = await request(dut, rd=1, addr=a + 3)
    assert got == (old & ~0xFFFF_FFFF) | 0x5555_5555


@pytest.mark.sim
def test_sim_ddr3_ctrl():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_ddr3_ctrl"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "ddr3" / "ddr3_ctrl.sv"],
        includes=[RTL],
        hdl_toplevel="ddr3_ctrl",
        build_dir=build,
        always=True,
        build_args=["-g2012"],
        timescale=("1ns", "1ps"),
        parameters={
            "DQ_W": 32,
            "ROW_W": 15,
            "COL_W": 10,
            "BA_W": 3,
            "NPH": 1,
            "TCK_PS": 40000,
            "CL": 6,
            "CWL": 6,
            "NWR": 5,
            "CAL_DW": 3,
            "CAL_STEPS": 8,
            "SIM": 1,
        },
    )
    try:
        runner.test(
            hdl_toplevel="ddr3_ctrl",
            test_module="test_ddr3_ctrl",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

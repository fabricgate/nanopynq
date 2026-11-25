"""cocotb tests for the JTAG bridge + base registers (gateware/sim/sim_jtag_top.v).

GW_JTAG itself is not simulated; drive_tck() reproduces what was measured on the Tang Nano 4K
(reports/report_jtag_bridge_spike.md sections 12-13):
- tdi_o, shift_dr_capture_dr_o and update_dr_o change on the rising edge of TCK
  (shift_dr is 1 while the TAP is in Shift-DR after that edge, update_dr while in Update-DR)
- the TDO pad takes tdo_er1_i at the falling edge, and the host reads it during the next high phase
The same file is the pytest entry point: `pytest -m sim` (needs iverilog on PATH).
"""

import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
DONE = 1 << 63
HALF = 7  # board clocks per TCK half period: 27 MHz vs the BL702's ~2 MHz


def cmd(addr, write=False, data=0):
    return (1 << 63) | (int(write) << 62) | ((addr // 4) << 32) | data


class Tap:
    def __init__(self, dut, half=HALF):
        self.dut, self.half, self.pad = dut, half, 0

    async def clock(self, tdi, state_after):
        """One TCK period; returns the TDO the host reads in its high phase."""
        d = self.dut
        seen = self.pad
        d.jtag_tck.value = 1
        d.jtag_tdi.value = tdi
        d.jtag_shift_dr.value = int(state_after == "shift")
        d.jtag_update_dr.value = int(state_after == "update")
        await ClockCycles(d.clk, self.half)
        d.jtag_tck.value = 0
        self.pad = int(d.jtag_tdo.value)
        await ClockCycles(d.clk, self.half)
        return seen

    async def dr_scan(self, value, nbits=64):
        """Run-Test/Idle -> Shift-DR -> nbits -> Update-DR -> Run-Test/Idle."""
        for state in ("select", "capture", "shift"):
            await self.clock(0, state)
        out = 0
        for i in range(nbits):
            bit = await self.clock((value >> i) & 1, "shift" if i < nbits - 1 else "exit1")
            out |= bit << i
        await self.clock(0, "update")
        await self.clock(0, "idle")
        return out


async def setup(dut, half=HALF):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for s in (dut.jtag_tck, dut.jtag_tdi, dut.jtag_shift_dr, dut.jtag_update_dr):
        s.value = 0
    dut.jtag_enable.value = 1  # IR 0x42 loaded
    dut.buttons.value = 0
    dut.rst.value = 1
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 5)
    return Tap(dut, half)


@cocotb.test()
async def read_id(dut):
    tap = await setup(dut)
    await tap.dr_scan(cmd(0x0))
    assert await tap.dr_scan(0) == DONE | 0x4E505131


@cocotb.test()
async def nop_scan_returns_zero(dut):
    tap = await setup(dut)
    await tap.dr_scan(0)
    assert await tap.dr_scan(0) == 0


@cocotb.test()
async def write_leds_then_read(dut):
    tap = await setup(dut)
    await tap.dr_scan(cmd(0x1000, write=True, data=0b101))
    assert await tap.dr_scan(cmd(0x1000)) == DONE
    assert int(dut.leds.value) == 0b101
    assert await tap.dr_scan(0) == DONE | 0b101


@cocotb.test()
async def pipelined_reads(dut):
    tap = await setup(dut)
    await tap.dr_scan(cmd(0x0))
    assert await tap.dr_scan(cmd(0x4)) == DONE | 0x4E505131
    assert await tap.dr_scan(cmd(0x9000)) == DONE | 0x00010001
    assert await tap.dr_scan(0) == DONE | 0xDEADBEEF


@cocotb.test()
async def design_id_defaults_to_zero(dut):
    tap = await setup(dut)  # sim_jtag_top leaves DESIGN_ID at its default
    await tap.dr_scan(cmd(0xC))
    assert await tap.dr_scan(0) == DONE | 0


@cocotb.test()
async def scratch_random_round_trips(dut):
    tap = await setup(dut)
    rnd = random.Random(1)
    for _ in range(64):
        v = rnd.getrandbits(32)
        await tap.dr_scan(cmd(0x8, write=True, data=v))
        await tap.dr_scan(cmd(0x8))
        assert await tap.dr_scan(0) == DONE | v


@cocotb.test()
async def slow_tck(dut):
    tap = await setup(dut, half=20)
    await tap.dr_scan(cmd(0x0))
    assert await tap.dr_scan(0) == DONE | 0x4E505131


@pytest.mark.sim
def test_sim_jtag():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_jtag"
    sources = [*sorted(RTL.glob("*.v")), HERE / "sim_jtag_top.v"]
    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="sim_jtag_top",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:  # runner.test raises SystemExit(1) when any cocotb test fails
        runner.test(
            hdl_toplevel="sim_jtag_top",
            test_module="test_jtag_bridge",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

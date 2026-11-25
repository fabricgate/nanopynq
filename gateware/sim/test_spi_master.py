"""cocotb tests for src/nanopynq/rtl/spi_master.v. The pytest entry point needs iverilog: `pytest -m sim`.

A mode-0 slave model records MOSI on SCK rising edges and shifts MISO out on falling edges (the first
bit is on the line once CS# falls), like an SPI NOR flash.
"""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Edge, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
BASE = 0x8000
CTRL, DATA, STATUS = BASE, BASE + 4, BASE + 8


async def bus(dut, addr, value=None):
    await FallingEdge(dut.clk)
    dut.bus_adr.value = addr >> 2
    dut.bus_we.value = value is not None
    dut.bus_dat_w.value = value or 0
    dut.bus_stb.value = 1
    for _ in range(20):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.bus_ack.value):
            got = int(dut.bus_dat_r.value)
            break
    else:
        raise TimeoutError(f"no ack for 0x{addr:x}")
    await FallingEdge(dut.clk)
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    return got


class Slave:
    def __init__(self, dut, reply: bytes):
        self.dut, self.reply, self.got_bits, self.sck_while_cs_high = dut, reply, [], 0
        cocotb.start_soon(self.run())

    def bits_out(self):
        for byte in self.reply:
            for i in range(7, -1, -1):
                yield (byte >> i) & 1
        while True:
            yield 1

    async def run(self):
        dut = self.dut
        dut.miso.value = 1
        while True:
            await Edge(dut.cs_n)
            if int(dut.cs_n.value):
                continue
            out = self.bits_out()
            dut.miso.value = next(out)
            while not int(dut.cs_n.value):
                await Edge(dut.sck)
                if int(dut.cs_n.value):
                    break
                if int(dut.sck.value):
                    self.got_bits.append(int(dut.mosi.value))
                else:
                    dut.miso.value = next(out)

    def got(self):
        b = self.got_bits
        return bytes(int("".join(map(str, b[i : i + 8])), 2) for i in range(0, len(b) - len(b) % 8, 8))


async def setup(dut, reply=b""):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    dut.bus_adr.value = 0
    dut.bus_dat_w.value = 0
    dut.rst.value = 1
    slave = Slave(dut, reply)
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0
    return slave


async def xfer(dut, n, value):
    await bus(dut, CTRL, 1 | (n - 1) << 1)
    await bus(dut, DATA, value)
    for _ in range(100):
        if not await bus(dut, STATUS) & 1:
            break
    else:
        raise TimeoutError("busy")
    return await bus(dut, DATA)


@cocotb.test()
async def four_bytes_each_way(dut):
    slave = await setup(dut, bytes([0x85, 0x60, 0x16, 0xA5]))
    assert int(dut.cs_n.value) == 1 and int(dut.sck.value) == 0
    got = await xfer(dut, 4, 0x9F000102)
    await bus(dut, CTRL, 0)
    assert slave.got() == bytes([0x9F, 0x00, 0x01, 0x02]), slave.got().hex()
    assert got == 0x856016A5, hex(got)
    assert int(dut.cs_n.value) == 1 and int(dut.sck.value) == 0


@cocotb.test()
async def short_transfers_use_the_low_bytes(dut):
    slave = await setup(dut, bytes([0x11, 0x22, 0x33]))
    a = await xfer(dut, 1, 0xFFFFFF03)  # only 0x03 goes out
    b = await xfer(dut, 2, 0xFFFFABCD)  # then 0xAB, 0xCD
    await bus(dut, CTRL, 0)
    assert slave.got() == bytes([0x03, 0xAB, 0xCD]), slave.got().hex()
    assert a == 0x11 and b == 0x2233, (hex(a), hex(b))


@cocotb.test()
async def cs_stays_low_across_transfers_and_rises_on_request(dut):
    slave = await setup(dut, bytes(range(1, 9)))
    first = await xfer(dut, 4, 0)
    assert int(dut.cs_n.value) == 0
    second = await xfer(dut, 4, 0)
    assert (first, second) == (0x01020304, 0x05060708), (hex(first), hex(second))
    await bus(dut, CTRL, 0)
    assert int(dut.cs_n.value) == 1
    assert len(slave.got_bits) == 64


@cocotb.test()
async def outside_its_window(dut):
    await setup(dut)
    assert await bus(dut, BASE + 0xC) == 0
    assert int(dut.hit.value) == 0


@pytest.mark.sim
def test_sim_spi_master():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_spi"
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / "spi_master.v"],
        hdl_toplevel="spi_master",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        parameters={"BASE": BASE},
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="spi_master",
            test_module="test_spi_master",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

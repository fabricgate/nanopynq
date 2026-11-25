"""cocotb tests for the UARTBone bridge + base SoC (gateware/sim/sim_top.v).

The same file is the pytest entry point: `pytest -m sim` builds sim_top with Icarus and runs the
cocotb tests below (needs iverilog on PATH).
"""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
TIMEOUT_CYCLES = 2000  # must equal sim_top.v
BIT_CLKS = 4  # CLK_HZ=1_000_000, BAUD=250_000
DESIGN_ID = 0xABF78D8C  # must equal sim_top.v


async def uart_send_bytes(dut, data):
    for b in data:
        for level in [0] + [(b >> i) & 1 for i in range(8)] + [1]:
            dut.uart_rx.value = level
            await ClockCycles(dut.clk, BIT_CLKS)


async def uart_recv_byte(dut, limit=TIMEOUT_CYCLES):
    for _ in range(limit):
        await RisingEdge(dut.clk)
        if int(dut.uart_tx.value) == 0:
            break
    else:
        raise TimeoutError("no start bit on uart_tx")
    await ClockCycles(dut.clk, BIT_CLKS // 2)  # middle of start bit
    assert int(dut.uart_tx.value) == 0
    b = 0
    for i in range(8):
        await ClockCycles(dut.clk, BIT_CLKS)
        b |= int(dut.uart_tx.value) << i
    await ClockCycles(dut.clk, BIT_CLKS)
    assert int(dut.uart_tx.value) == 1, "bad stop bit"
    return b


def frame(cmd, addr, length, words=()):
    out = [cmd, length, *list((addr // 4).to_bytes(4, "big"))]
    for w in words:
        out += list(w.to_bytes(4, "big"))
    return out


async def uart_read_words(dut, addr, length=1, cmd=0x02):
    await uart_send_bytes(dut, frame(cmd, addr, length))
    got = []
    for _ in range(length):
        got.append(int.from_bytes(bytes([await uart_recv_byte(dut) for _ in range(4)]), "big"))
    return got


async def uart_read_word(dut, addr):
    return (await uart_read_words(dut, addr))[0]


async def uart_write_words(dut, addr, words, cmd=0x01):
    await uart_send_bytes(dut, frame(cmd, addr, len(words), words))
    await ClockCycles(dut.clk, 20)  # let the last bus write land


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 1, unit="us").start())
    dut.uart_rx.value = 1
    dut.buttons.value = 0
    dut.rst.value = 1
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 5)


@cocotb.test()
async def read_id(dut):
    await setup(dut)
    assert await uart_read_word(dut, 0x0) == 0x4E505131
    assert await uart_read_word(dut, 0x4) == 0x00010001


@cocotb.test()
async def design_id_reads_the_build_value(dut):
    await setup(dut)
    assert await uart_read_word(dut, 0xC) == DESIGN_ID
    await uart_write_words(dut, 0xC, [0x1234_5678])  # read-only: the write is dropped
    assert await uart_read_word(dut, 0xC) == DESIGN_ID
    assert await uart_read_word(dut, 0x8) == 0  # and it did not land in scratch


@cocotb.test()
async def write_then_read_leds(dut):
    await setup(dut)
    await uart_write_words(dut, 0x1000, [0b101])
    assert int(dut.leds.value) == 0b101
    assert await uart_read_word(dut, 0x1000) == 0b101


@cocotb.test()
async def buttons_reflect_input(dut):
    await setup(dut)
    dut.buttons.value = 0b10
    assert await uart_read_word(dut, 0x2000) == 0b10


@cocotb.test()
async def unmapped_reads_deadbeef(dut):
    await setup(dut)
    assert await uart_read_word(dut, 0x9000) == 0xDEADBEEF


@cocotb.test()
async def incomplete_frame_times_out_and_recovers(dut):
    await setup(dut)
    await uart_send_bytes(dut, [0x02, 0x01])  # stop mid-frame
    await ClockCycles(dut.clk, TIMEOUT_CYCLES + 10)
    assert await uart_read_word(dut, 0x0) == 0x4E505131


@cocotb.test()
async def scratch_read_write(dut):
    await setup(dut)
    assert await uart_read_word(dut, 0x8) == 0
    await uart_write_words(dut, 0x8, [0xA5A5_1234])
    assert await uart_read_word(dut, 0x8) == 0xA5A5_1234


@cocotb.test()
async def burst_incr_and_fixed(dut):
    await setup(dut)
    # incr read of sysinfo ID, VERSION, SCRATCH, DESIGN_ID (word addr 0..3), then unmapped
    assert await uart_read_words(dut, 0x0, 5) == [0x4E505131, 0x00010001, 0, DESIGN_ID, 0xDEADBEEF]
    # fixed read keeps the address
    assert await uart_read_words(dut, 0x0, 2, cmd=0x04) == [0x4E505131, 0x4E505131]
    # fixed write: last value wins; incr write to leds then unmapped is ignored
    await uart_write_words(dut, 0x1000, [1, 2, 0b110011], cmd=0x03)
    assert int(dut.leds.value) == 0b110011
    await uart_write_words(dut, 0x1000, [0b001, 0xFFFF_FFFF])  # 2nd word at 0x1004: unmapped
    assert int(dut.leds.value) == 0b001
    assert await uart_read_word(dut, 0x1000) == 0b001


@pytest.mark.sim
def test_sim():
    from cocotb_tools.runner import get_runner

    sources = [*sorted(RTL.glob("*.v")), HERE / "sim_top.v"]
    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="sim_top",
        build_dir=HERE / "sim_build",
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:  # runner.test raises SystemExit(1) when any cocotb test fails
        runner.test(
            hdl_toplevel="sim_top",
            test_module="test_bridge",
            test_dir=HERE,
            build_dir=HERE / "sim_build",
            results_xml=HERE / "sim_build" / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

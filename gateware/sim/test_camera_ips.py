"""cocotb tests for the add-on IPs behind base_regs' external slave port (gateware/sim/sim_regs_top.v).

The bus is driven directly. I2CDevice plays a register device (SCCB style, 7-bit address 0x30) on the
open-drain lines. The same file is the pytest entry point: `pytest -m sim` (needs iverilog on PATH).
"""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
I2C, DVP, CAP = 0x3000, 0x4000, 0x10000
CAP_WIN = CAP + 0x8000
DEPTH = 64  # words, must equal sim_regs_top.v
START, STOP, WRITE, READ_ACK, READ_NACK = 1, 2, 3, 4, 5


async def bus_access(dut, addr, data=None):
    await FallingEdge(dut.clk)
    dut.bus_adr.value = addr >> 2
    dut.bus_we.value = data is not None
    dut.bus_dat_w.value = data or 0
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


async def bus_read(dut, addr):
    return await bus_access(dut, addr)


async def bus_write(dut, addr, value):
    await bus_access(dut, addr, value)


async def i2c_cmd(dut, op, data=0):
    await bus_write(dut, I2C, op | (data << 8))
    for _ in range(500):
        status = await bus_read(dut, I2C + 4)
        if not status & 1:
            return status
    raise TimeoutError("i2c_master stayed busy")


class I2CDevice:
    """Register device on the I2C lines: write [reg, val...]; read returns regs[reg] (one byte, then NACK)."""

    def __init__(self, dut, addr=0x30, regs=None):
        self.dut, self.addr, self.regs = dut, addr, dict(regs or {})
        self.writes, self.pull, self.ptr = [], False, None
        cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        scl_p = sda_p = 1
        phase, bits, byte, nxt, out, set_ptr = "idle", 0, 0, "idle", 0, False
        while True:
            await RisingEdge(d.clk)
            scl = 0 if int(d.scl_low.value) else 1
            sda = 0 if (int(d.sda_low.value) or self.pull) else 1
            d.scl_in.value = scl
            d.sda_in.value = sda
            if scl and scl_p and sda_p and not sda:  # START
                phase, bits, byte, self.pull = "addr", 0, 0, False
            elif scl and scl_p and not sda_p and sda:  # STOP
                phase, self.pull = "idle", False
            elif scl and not scl_p:  # SCL rising: sample
                if phase in ("addr", "wr"):
                    byte, bits = (byte << 1) | sda, bits + 1
                elif phase == "mack":
                    phase = "idle"  # one-byte reads only
            elif not scl and scl_p:  # SCL falling: drive
                if phase == "addr" and bits == 8:
                    if byte >> 1 == self.addr:
                        self.pull, phase = True, "ack"
                        nxt = "rd" if byte & 1 else "wr"
                        set_ptr = not byte & 1
                        out = self.regs.get(self.ptr, 0xFF)
                    else:
                        phase = "idle"
                elif phase == "wr" and bits == 8:
                    if set_ptr:
                        self.ptr, set_ptr = byte, False
                    else:
                        self.writes.append((self.ptr, byte))
                        self.ptr += 1
                    self.pull, phase, nxt = True, "ack", "wr"
                elif phase == "ack":
                    self.pull, bits, byte, phase = False, 0, 0, nxt
                    if phase == "rd":
                        self.pull, bits = not (out >> 7) & 1, 1
                elif phase == "rd":
                    if bits < 8:
                        self.pull, bits = not (out >> (7 - bits)) & 1, bits + 1
                    else:
                        self.pull, phase = False, "mack"
            scl_p, sda_p = scl, sda


async def setup(dut, regs=None):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.pclk.value = 0
    dut.vsync.value = 0
    dut.href.value = 0
    dut.d.value = 0
    dut.bus_stb.value = 0
    dut.bus_we.value = 0
    dut.bus_adr.value = 0
    dut.bus_dat_w.value = 0
    dut.scl_in.value = 1
    dut.sda_in.value = 1
    dut.rst.value = 1
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 5)
    return I2CDevice(dut, regs=regs)


@cocotb.test()
async def i2c_write_reg_is_acked(dut):
    dev = await setup(dut)
    await i2c_cmd(dut, START)
    for b in (0x60, 0x0A, 0x55):
        assert not (await i2c_cmd(dut, WRITE, b)) & 0b10
    await i2c_cmd(dut, STOP)
    assert dev.writes == [(0x0A, 0x55)]


@cocotb.test()
async def i2c_read_returns_device_byte(dut):
    await setup(dut, regs={0x0A: 0x26})
    await i2c_cmd(dut, START)
    await i2c_cmd(dut, WRITE, 0x60)
    await i2c_cmd(dut, WRITE, 0x0A)
    await i2c_cmd(dut, STOP)
    await i2c_cmd(dut, START)
    assert not (await i2c_cmd(dut, WRITE, 0x61)) & 0b10
    status = await i2c_cmd(dut, READ_NACK)
    await i2c_cmd(dut, STOP)
    assert (status >> 8) & 0xFF == 0x26


@cocotb.test()
async def i2c_wrong_address_sets_nack_and_clears_busy(dut):
    await setup(dut)
    await i2c_cmd(dut, START)
    status = await i2c_cmd(dut, WRITE, 0x62)
    await i2c_cmd(dut, STOP)
    assert status & 0b10 and not status & 0b1


@cocotb.test()
async def base_regs_still_answer_with_ext_port(dut):
    await setup(dut)
    assert await bus_read(dut, 0x0) == 0x4E505131
    assert await bus_read(dut, 0x9000) == 0xDEADBEEF
    assert await bus_read(dut, I2C + 4) & 1 == 0


def frame_bytes(n, lines, width):
    return [(n * 64 + line * 16 + col) & 0xFF for line in range(lines) for col in range(width)]


class DvpSource:
    """OV2640-like DVP timing on pclk: a VSYNC high pulse between frames, HREF high per line.
    Data changes on the falling edge of PCLK; byte = frame*64 + line*16 + column (mod 256)."""

    def __init__(self, dut, lines=4, width=8, period_ns=23, frame_high=False):
        self.dut, self.lines, self.width, self.frame = dut, lines, width, 0
        self.blank = 0 if frame_high else 1  # VSYNC level between frames
        cocotb.start_soon(Clock(dut.pclk, period_ns, unit="ns").start())
        cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            d.vsync.value = self.blank
            for _ in range(6):
                await FallingEdge(d.pclk)
            d.vsync.value = 1 - self.blank
            for _ in range(4):
                await FallingEdge(d.pclk)
            for line in range(self.lines):
                for col in range(self.width):
                    d.href.value = 1
                    d.d.value = (self.frame * 64 + line * 16 + col) & 0xFF
                    await FallingEdge(d.pclk)
                d.href.value = 0
                for _ in range(3):
                    await FallingEdge(d.pclk)
            self.frame += 1


async def capture(dut, timeout_cycles=20000):
    await bus_write(dut, CAP, 1)  # arm
    for _ in range(timeout_cycles // 20):
        status = await bus_read(dut, CAP + 4)
        if status & 0b10:
            return status, await bus_read(dut, CAP + 8)
        await ClockCycles(dut.clk, 10)
    raise TimeoutError("capture never finished")


async def window(dut, length):
    words = [await bus_read(dut, CAP_WIN + 4 * i) for i in range((length + 3) // 4)]
    return list(b"".join(w.to_bytes(4, "little") for w in words))[:length]


@cocotb.test()
async def capture_one_frame_all_bytes(dut):
    await setup(dut)
    DvpSource(dut)
    assert await bus_read(dut, CAP + 12) == 4 * DEPTH
    status, length = await capture(dut)
    assert not status & 0b101 and length == 32
    data = await window(dut, 32)
    assert data == frame_bytes(data[0] // 64, 4, 8)
    assert data == await window(dut, 32)  # reading the window again gives the same bytes


@cocotb.test()
async def keep_even_bytes_halves_length(dut):
    await setup(dut)
    DvpSource(dut)
    await bus_write(dut, DVP, 0b010)  # keep = 1 (even bytes of each line)
    await ClockCycles(dut.clk, 20)
    _status, length = await capture(dut)
    assert length == 16
    data = await window(dut, 16)
    full = frame_bytes(data[0] // 64, 4, 8)
    assert data == [full[i] for i in range(32) if i % 2 == 0]


@cocotb.test()
async def arm_waits_for_next_frame_start(dut):
    await setup(dut)
    DvpSource(dut)
    for _ in range(200):  # wait until we are inside a frame (HREF high)
        await RisingEdge(dut.clk)
        if int(dut.href.value):
            break
    _status, length = await capture(dut)
    data = await window(dut, length)
    assert length == 32 and data == frame_bytes(data[0] // 64, 4, 8)


@cocotb.test()
async def overflow_sets_flag_and_stops(dut):
    await setup(dut)
    DvpSource(dut, lines=30, width=10)  # 300 bytes > 256
    status, length = await capture(dut, timeout_cycles=60000)
    assert status & 0b100 and length == 4 * DEPTH


@cocotb.test()
async def frame_while_vsync_high_with_ctrl_bit3(dut):
    await setup(dut)
    DvpSource(dut, frame_high=True)  # the OV2640 after its init table: VSYNC high during the frame
    await bus_write(dut, DVP, 0b1000)
    await ClockCycles(dut.clk, 20)
    _status, length = await capture(dut)
    data = await window(dut, length)
    assert length == 32 and data == frame_bytes(data[0] // 64, 4, 8)


@cocotb.test()
async def frames_counter_counts_vsync(dut):
    await setup(dut)
    src = DvpSource(dut)
    before = await bus_read(dut, DVP + 4)
    start = src.frame
    while src.frame < start + 3:
        await ClockCycles(dut.clk, 50)
    assert await bus_read(dut, DVP + 4) - before >= 2


@cocotb.test()
async def pclks_and_lines_of_last_frame(dut):
    await setup(dut)
    src = DvpSource(dut)  # frame level (VSYNC low) lasts 4 + 4 * (8 + 3) = 48 PCLK periods
    start = src.frame
    while src.frame < start + 3:
        await ClockCycles(dut.clk, 50)
    assert await bus_read(dut, DVP + 0xC) == 4
    assert await bus_read(dut, DVP + 8) == 48


@cocotb.test()
async def xclk_follows_ctrl(dut):
    await setup(dut)
    await ClockCycles(dut.clk, 10)
    assert int(dut.xclk.value) == 0
    await bus_write(dut, DVP, 0b001)
    seen = set()
    for _ in range(10):
        await RisingEdge(dut.clk)
        await ReadOnly()
        seen.add(int(dut.xclk.value))
    assert seen == {0, 1}


@pytest.mark.sim
def test_sim_camera_ips():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_regs"
    sources = [*sorted(RTL.glob("*.v")), HERE / "sim_regs_top.v"]
    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="sim_regs_top",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:  # runner.test raises SystemExit(1) when any cocotb test fails
        runner.test(
            hdl_toplevel="sim_regs_top",
            test_module="test_camera_ips",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

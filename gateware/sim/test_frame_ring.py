"""cocotb tests for src/nanopynq/rtl/frame_ring.v through gateware/sim/sim_ring_top.v: a DVP source on PCLK,
dvp_frontend, frame_ring, hyperram_ctrl and the HyperRAM model. The same file is the pytest entry
point: `pytest -m sim` (needs iverilog on PATH)."""

from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge
from hyperram_model import HyperRAMModel
from test_camera_ips import bus_read as rd
from test_camera_ips import bus_write as wr

HERE = Path(__file__).parent
RTL = HERE.parent.parent / "src" / "nanopynq" / "rtl"
RING, WIN = 0x20000, 0x21000
CTRL, WSEQ, RSEQ, DROPPED, FETCH, STATUS, SLOT_LEN, SLOT_INFO = (RING + 4 * i for i in range(8))
SLOT_WORDS, NSLOTS, SEQ_MOD = 256, 4, 16  # must equal sim_ring_top.v


def frame_data(f, n):
    """Bytes of source frame f: byte 0 is the frame number, so a slot tells which frame it holds."""
    return [f & 0xFF] + [(f * 5 + 3 * i) & 0xFF for i in range(1, n)]


class Source:
    """DVP timing on pclk, frame while VSYNC is low (dvp_frontend's default): vblank PCLKs of VSYNC high,
    then lines of `width` bytes with HREF high and `hblank` PCLKs between them. Data changes on the
    falling edge of PCLK."""

    def __init__(self, dut, lines=4, width=8, period_ns=23, vblank=200, hblank=3):
        self.dut, self.lines, self.width, self.vblank, self.hblank = dut, lines, width, vblank, hblank
        self.frame = 0
        cocotb.start_soon(Clock(dut.pclk, period_ns, unit="ns").start())
        cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            data = frame_data(self.frame, self.lines * self.width)
            d.vsync.value = 1
            for _ in range(self.vblank):
                await FallingEdge(d.pclk)
            d.vsync.value = 0
            for _ in range(4):
                await FallingEdge(d.pclk)
            for line in range(self.lines):
                for col in range(self.width):
                    d.href.value = 1
                    d.d.value = data[line * self.width + col]
                    await FallingEdge(d.pclk)
                d.href.value = 0
                for _ in range(self.hblank):
                    await FallingEdge(d.pclk)
            self.frame += 1


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for s in (dut.vsync, dut.href, dut.d, dut.bus_stb, dut.bus_we, dut.bus_adr, dut.bus_dat_w):
        s.value = 0
    dut.vsync.value = 1
    dut.rst.value = 1
    ram = HyperRAMModel(dut)
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 5)
    # The tests share one simulation: end a frame the previous test left open, let the ring finish it,
    # then start from WSEQ = RSEQ = DROPPED = 0.
    await wr(dut, CTRL, 0)
    pclk = cocotb.start_soon(Clock(dut.pclk, 23, unit="ns").start())
    await ClockCycles(dut.clk, 3000)
    pclk.cancel()
    await wr(dut, CTRL, 0b10)
    ram.log.clear()
    return ram


async def wait_for(dut, addr, cond, cycles=200000, what=""):
    for _ in range(cycles // 50):
        v = await rd(dut, addr)
        if cond(v):
            return v
        await ClockCycles(dut.clk, 40)
    raise TimeoutError(f"0x{addr:x} never satisfied {what}")


async def read_words(dut, word_addr, nwords):
    """FETCH nwords (a multiple of 8) from PSRAM word_addr; return the window as 32-bit words."""
    await wr(dut, FETCH, word_addr | (nwords // 8) << 24)
    await wait_for(dut, STATUS, lambda s: not s & 1, what="fetch done")
    return [await rd(dut, WIN + 4 * i) for i in range(nwords // 2)]


async def read_slot(dut, slot, nbytes):
    """Header (32 bits) and the first nbytes of data of a slot, through the fetch window."""
    words = await read_words(dut, slot * SLOT_WORDS, 8 * -(-(4 + nbytes) // 16))
    raw = b"".join(w.to_bytes(4, "little") for w in words)
    return int.from_bytes(raw[:4], "little"), list(raw[4 : 4 + nbytes])


def check_ram(ram):
    assert ram.errors == []
    assert max(t["edges"] for t in ram.log) <= 2 * 24  # Review Focus 4: every transaction <= 24 CK cycles
    for t in ram.log:
        if t["write"] and t["bytes"]:
            last = t["addr"] + (t["bytes"] + 1) // 2 - 1
            assert t["addr"] // SLOT_WORDS == last // SLOT_WORDS, f"write crosses a slot: {t}"


@cocotb.test()
async def frames_land_in_successive_slots(dut):
    ram = await setup(dut)
    Source(dut)
    assert await rd(dut, SLOT_INFO) == NSLOTS << 16 | SLOT_WORDS
    await wr(dut, CTRL, 1)
    await wait_for(dut, WSEQ, lambda v: v >= 3, what="3 frames")
    assert await rd(dut, SLOT_LEN) == 32 and await rd(dut, DROPPED) == 0 and not await rd(dut, STATUS) & 2
    firsts = []
    for s in range(3):
        hdr, data = await read_slot(dut, s, 32)
        assert (hdr & 0xFFFF, (hdr >> 16) & 0x7FFF, hdr >> 31) == (32, s, 0)
        assert data == frame_data(data[0], 32)
        firsts.append(data[0])
    assert firsts == [firsts[0], (firsts[0] + 1) & 0xFF, (firsts[0] + 2) & 0xFF]
    check_ram(ram)


@cocotb.test()
async def full_ring_drops_and_counts(dut):  # Review Focus 1
    ram = await setup(dut)
    Source(dut)
    await wr(dut, CTRL, 1)
    await wait_for(dut, DROPPED, lambda v: v >= 2, what="2 drops")
    assert await rd(dut, WSEQ) == NSLOTS
    slot0 = await read_slot(dut, 0, 32)  # the host is reading slot 0 (RSEQ = 0)
    dropped = await rd(dut, DROPPED)
    await wait_for(dut, DROPPED, lambda v: v >= dropped + 2, what="2 more drops")
    assert await read_slot(dut, 0, 32) == slot0  # not overwritten while it is being read
    assert await rd(dut, WSEQ) == NSLOTS
    await wr(dut, RSEQ, 1)  # slot 0 is free again
    await wait_for(dut, WSEQ, lambda v: v == NSLOTS + 1, what="one more frame")
    hdr, data = await read_slot(dut, 0, 32)
    assert ((hdr >> 16) & 0x7FFF, hdr >> 31) == (NSLOTS, 0)
    assert data == frame_data(data[0], 32) and data[0] != slot0[1][0]
    await wr(dut, CTRL, 0b10)  # off, counters to 0
    assert [await rd(dut, a) for a in (WSEQ, RSEQ, DROPPED)] == [0, 0, 0]
    check_ram(ram)


@cocotb.test()
async def seq_wraps(dut):  # Review Focus 3: 4-bit WSEQ/RSEQ here, 32 bits on the board
    ram = await setup(dut)
    Source(dut)
    await wr(dut, CTRL, 1)
    for k in range(30):  # RSEQ goes 0..15, 0..14
        used = await wait_for(dut, WSEQ, lambda w: (w - k) % SEQ_MOD > 0, what=f"frame {k}")  # noqa: B023 (awaited here)
        assert (used - k) % SEQ_MOD <= NSLOTS
        hdr, data = await read_slot(dut, k % NSLOTS, 32)
        assert ((hdr >> 16) & 0x7FFF, hdr >> 31) == (k % SEQ_MOD, 0)
        assert data == frame_data(data[0], 32)
        await wr(dut, RSEQ, (k + 1) % SEQ_MOD)
    dropped = await rd(dut, DROPPED)  # stop reading at RSEQ = 14: full is WSEQ = 2, not empty
    await wait_for(dut, DROPPED, lambda v: v >= dropped + 2, what="drops across the wrap")
    assert await rd(dut, WSEQ) == (30 + NSLOTS) % SEQ_MOD
    check_ram(ram)


async def odd_length_frames(dut, width):
    ram = await setup(dut)
    Source(dut, lines=3, width=width)
    n = 3 * width
    await wr(dut, CTRL, 1)
    await wait_for(dut, WSEQ, lambda v: v >= 3, what="3 frames")
    firsts = []
    for s in range(3):
        hdr, data = await read_slot(dut, s, n)
        assert (hdr & 0xFFFF, hdr >> 31) == (n, 0)
        assert data == frame_data(data[0], n)
        firsts.append(data[0])
    assert firsts == [firsts[0], (firsts[0] + 1) & 0xFF, (firsts[0] + 2) & 0xFF]
    check_ram(ram)


@cocotb.test()
async def frame_of_21_bytes(dut):  # the last FIFO entry holds 1 byte (an odd number of words)
    await odd_length_frames(dut, 7)


@cocotb.test()
async def frame_of_15_bytes(dut):  # the last FIFO entry holds 3 bytes
    await odd_length_frames(dut, 5)


@cocotb.test()
async def fifo_overflow_marks_frame_bad(dut):  # Review Focus 2: PCLK much faster than the PSRAM writes
    ram = await setup(dut)
    Source(dut, lines=10, width=32, period_ns=4, hblank=1)
    await wr(dut, CTRL, 1)
    await wait_for(dut, WSEQ, lambda v: v >= 3, what="3 frames")
    for s in range(3):  # also once the FIFO pointers have wrapped
        hdr, _ = await read_slot(dut, s, 0)
        assert hdr & 0xFFFF == 320 and hdr >> 31 == 1, f"slot {s}: 0x{hdr:08x}"
    assert await rd(dut, STATUS) & 2
    check_ram(ram)


@cocotb.test()
async def frame_larger_than_slot_is_cut_and_marked_bad(dut):
    ram = await setup(dut)
    Source(dut, lines=20, width=32, period_ns=100)  # 640 bytes > 508 per slot, slow enough for the FIFO
    await wr(dut, CTRL, 1)
    await wait_for(dut, WSEQ, lambda v: v >= 1, cycles=400000, what="a frame")
    hdr, data = await read_slot(dut, 0, 2 * SLOT_WORDS - 4)
    assert hdr & 0xFFFF == 640 and hdr >> 31 == 1
    assert data == frame_data(data[0], 640)[: 2 * SLOT_WORDS - 4]
    assert not await rd(dut, STATUS) & 2
    check_ram(ram)


@cocotb.test()
async def fetch_window_reads_back_slot(dut):
    ram = await setup(dut)
    for i in range(16):
        ram.mem[0x108 + i] = (0x1111 * i + 7) & 0xFFFF
    await wr(dut, FETCH, 0x108 | 2 << 24)
    assert await rd(dut, STATUS) & 1  # still fetching
    await wait_for(dut, STATUS, lambda s: not s & 1, what="fetch done")
    got = [await rd(dut, WIN + 4 * i) for i in range(8)]
    assert got == [ram.mem[0x109 + 2 * i] << 16 | ram.mem[0x108 + 2 * i] for i in range(8)]
    check_ram(ram)


async def reset_mid_frame(dut, state):
    """Off and CTRL[1] while the clk side is in `state` (1 = writing the data, 2 = writing the header) of an
    accepted frame: that frame must not come back as the new run's frame 0 (slot 0 still holds the old one)."""
    ram = await setup(dut)
    src = Source(dut, lines=15, width=32, period_ns=100)  # 480 bytes, slow enough for the 32-word FIFO
    await wr(dut, CTRL, 1)
    await wait_for(dut, WSEQ, lambda v: v >= 1, cycles=400000, what="a frame")
    old0 = await read_slot(dut, 0, 32)
    for _ in range(200000):
        await ClockCycles(dut.clk, 1)
        if int(dut.ring.st.value) == state and int(dut.ring.accept.value) and int(dut.ring.wseq.value) >= 1:
            break
    else:
        raise TimeoutError(f"never in state {state}")
    await wr(dut, CTRL, 0)
    await wr(dut, CTRL, 0b10)
    f = src.frame  # the frame being sent now, or the next one in vblank
    await wr(dut, CTRL, 1)
    await wait_for(dut, WSEQ, lambda v: v >= 1, cycles=800000, what="the new run's first frame")
    hdr, data = await read_slot(dut, 0, 480)
    assert ((hdr >> 16) & 0x7FFF, hdr >> 31) == (0, 0)
    assert data == frame_data(data[0], 480) and data[0] != old0[1][0]
    assert data[0] in (f & 0xFF, (f + 1) & 0xFF)
    check_ram(ram)


@cocotb.test()
async def reset_while_writing_data_drops_that_frame(dut):
    await reset_mid_frame(dut, 1)


@cocotb.test()
async def reset_while_writing_header_drops_that_frame(dut):
    await reset_mid_frame(dut, 2)


@cocotb.test()
async def fetch_timeout_is_flagged(dut):
    ram = await setup(dut)
    for i in range(16):
        ram.mem[0x40 + i] = i
    ram.mute_reads = 1  # the first 4-word read gets no RWDS edges
    await wr(dut, FETCH, 0x40 | 2 << 24)
    assert await wait_for(dut, STATUS, lambda s: not s & 1, what="fetch done") & 4
    await wr(dut, FETCH, 0x40 | 2 << 24)  # the next fetch clears it
    assert not await wait_for(dut, STATUS, lambda s: not s & 1, what="fetch done") & 4
    assert [await rd(dut, WIN + 4 * i) for i in range(8)] == [(2 * i + 1) << 16 | 2 * i for i in range(8)]


@pytest.mark.sim
def test_sim_frame_ring():
    from cocotb_tools.runner import get_runner

    build = HERE / "sim_build_ring"
    sources = [*sorted(RTL.glob("*.v")), HERE / "sim_ring_top.v"]
    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="sim_ring_top",
        build_dir=build,
        always=True,
        build_args=["-g2005"],
        timescale=("1ns", "1ps"),
    )
    try:
        runner.test(
            hdl_toplevel="sim_ring_top",
            test_module="test_frame_ring",
            test_dir=HERE,
            build_dir=build,
            results_xml=build / "results.xml",
            timescale=("1ns", "1ps"),
        )
    except SystemExit as e:
        pytest.fail(f"cocotb tests failed (see the log above): {e}")

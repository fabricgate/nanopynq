"""Load a Gowin bitstream (.fs) into the FPGA's SRAM over JTAG, without openFPGALoader.

The sequence follows openFPGALoader v1.2.0's Gowin SRAM path (read and rewritten, not copied) as tried
on the 9K and 20K in #23 (reports/report_webusb.md, section 1): erase, then the bitstream in one DR
scan, then DONE_FINAL. openFPGALoader's closing 0x0A + checksum + 0x08 step is left out: on the 20K it
could set DONE_FINAL even with bad data. Success here is DONE_FINAL; Overlay then checks the design's
IDs (sys.id / sys.version / sys.design_id) against the .npq.

GW5A (Tang Mega 138K Pro), from openFPGALoader master's programSRAM / eraseSRAM (read 2026-11-21): RELOAD and
NOOP, about 1M idle clocks, then the erase at least twice (until DONE_FINAL is clear after the second or a later
pass), with 10 ms of clocks after ERASE_SRAM on the GW5AST-138. openFPGALoader's recovery of a FPGA that reports
BAD_COMMAND, TIMEOUT or AUTO_BOOT_2ND_FAIL (0x3F) is left out: such a FPGA is refused before the erase.
"""

from pathlib import Path

from nanopynq.errors import ProgramError
from nanopynq.transport.jtag import Jtag

IDCODE, STATUS = 0x11, 0x41
CONFIG_ENABLE, CONFIG_DISABLE, ERASE_SRAM, XFER_DONE, INIT_ADDR, XFER_WRITE, NOOP = (
    0x15,
    0x3A,
    0x05,
    0x09,
    0x12,
    0x17,
    0x02,
)
RELOAD = 0x3C
CRC_ERROR, MEMORY_ERASE, SYSTEM_EDIT_MODE, DONE_FINAL = 1 << 0, 1 << 5, 1 << 7, 1 << 13
# A healthy GW1N reports POR, READY and VLD (9K 0x0003f020, 4K 0x0001f020); the GW2A never does (20K 0x00006020).
GW1N_OK = 1 << 16 | 1 << 15 | 1 << 12
FAMILIES = ("gw1n", "gw2a", "gw5a")  # the families load_sram has a sequence for
# A GW5A reporting BAD_COMMAND, TIMEOUT or AUTO_BOOT_2ND_FAIL needs openFPGALoader's 0x3F recovery, which this loader
# leaves out.
GW5A_ERROR = 1 << 1 | 1 << 3 | 1 << 4
GW5A_ERASE_PASSES = 4
GW5A_RELOAD_CLOCKS, GW5A_ERASE_CLOCKS = 1_000_000, 60_000  # openFPGALoader: 1M clocks; 10 ms at 6 MHz
_POWER_CYCLE = "Unplug the board to power-cycle it, then load again."
_POWER_CYCLE_DC = "Switch the board's power off and on (it runs from its DC jack, not USB), then load again."
BITS = {
    0: "CRC_ERROR",
    1: "BAD_COMMAND",
    2: "ID_VERIFY_FAILED",
    3: "TIMEOUT",
    4: "AUTO_BOOT_2ND_FAIL",
    5: "MEMORY_ERASE",
    6: "PREAMBLE",
    7: "SYSTEM_EDIT_MODE",
    12: "GOWIN_VLD",
    13: "DONE_FINAL",
    15: "READY",
    16: "POR",
}
_REV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))  # the FPGA takes each byte MSB first


def flags(status: int) -> str:
    return ",".join(n for b, n in BITS.items() if status >> b & 1) or "none"


def _describe(status: int) -> str:
    return f"status 0x{status:08x} ({flags(status)})"


def read_fs(path: Path) -> bytes:
    """The bytes to send: every non-comment line of '0'/'1' (header lines included), 8 characters per
    byte, the first character the byte's MSB."""
    out = bytearray()
    with open(path, encoding="ascii", errors="replace") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if len(line) % 8 or not set(line) <= {"0", "1"}:
                raise ProgramError(
                    f"{path}: line {n} is not a bitstream line (8n characters of 0/1): {line[:40]!r}", ""
                )
            out += int(line, 2).to_bytes(len(line) // 8, "big")
    if not out:
        raise ProgramError(f"{path}: no bitstream lines", "")
    return bytes(out)


def _instruction(jtag: Jtag, ir: int) -> None:
    """Run-Test/Idle -> Shift-IR, 8 bits -> Run-Test/Idle, then 6 idle clocks."""
    jtag.tms("1100")
    jtag.shift(ir, 8)
    jtag.tms("10")
    jtag.tms("000000")
    jtag.flush()


def _read32(jtag: Jtag, ir: int) -> int:
    jtag.tms("1100")
    jtag.shift(ir, 8)
    jtag.tms("10")
    jtag.tms("000000")
    jtag.tms("100")
    jtag.shift(0xFFFFFFFF, 32)
    jtag.tms("10")
    return jtag.flush()[-1]  # the DR scan's TDO (the first value is the IR capture)


def _poll(jtag: Jtag, mask: int, value: int, what: str, max_polls: int) -> int:
    for _ in range(max_polls):
        s = _read32(jtag, STATUS)
        if s & mask == value:
            return s
    raise ProgramError(f"SRAM load failed: timeout waiting for {what}: {_describe(s)}", _describe(s))


def _erase(jtag: Jtag, max_polls: int, idle_clocks: int = 0) -> None:
    """One erase pass: CONFIG_ENABLE, ERASE_SRAM (then idle_clocks, if any), XFER_DONE, CONFIG_DISABLE."""
    _instruction(jtag, CONFIG_ENABLE)
    _poll(jtag, SYSTEM_EDIT_MODE, SYSTEM_EDIT_MODE, "SYSTEM_EDIT_MODE", max_polls)
    _instruction(jtag, ERASE_SRAM)
    _instruction(jtag, NOOP)
    if idle_clocks:
        jtag.idle(idle_clocks)
    _poll(jtag, MEMORY_ERASE, MEMORY_ERASE, "MEMORY_ERASE", max_polls)
    _instruction(jtag, XFER_DONE)
    _instruction(jtag, NOOP)
    _instruction(jtag, CONFIG_DISABLE)
    _instruction(jtag, NOOP)
    _poll(jtag, SYSTEM_EDIT_MODE, 0, "SYSTEM_EDIT_MODE to clear", max_polls)


def _erase_gw5a(jtag: Jtag, max_polls: int) -> None:
    """RELOAD, idle clocks, refuse an error state, then erase until DONE_FINAL is clear after pass 2 or later."""
    _instruction(jtag, RELOAD)
    _instruction(jtag, NOOP)
    jtag.idle(GW5A_RELOAD_CLOCKS)
    s = _read32(jtag, STATUS)
    if s & GW5A_ERROR:
        raise ProgramError(
            f"SRAM load refused: the FPGA reports an error state ({_describe(s)}) that this loader does not clear. "
            f"{_POWER_CYCLE_DC} If it comes back, load with openFPGALoader, which clears it on a GW5A: "
            "Overlay(..., programmer=nanopynq.program.program_sram_openfpgaloader).",
            _describe(s),
        )
    for n in range(1, GW5A_ERASE_PASSES + 1):
        _erase(jtag, max_polls, GW5A_ERASE_CLOCKS)
        s = _read32(jtag, STATUS)
        if n >= 2 and not s & DONE_FINAL:
            return
    raise ProgramError(
        f"SRAM load failed: DONE_FINAL is still set after {GW5A_ERASE_PASSES} erase passes: "
        f"{_describe(s)}. {_POWER_CYCLE_DC}",
        _describe(s),
    )


def load_sram(jtag: Jtag, data: bytes, idcode: int, family: str, max_polls: int = 2000) -> None:
    """Erase the SRAM and load data (from read_fs) into it. family is "gw1n", "gw2a" or "gw5a"; idcode is the
    board's IDCODE without the version nibble. Raises ProgramError on any failure."""
    if max_polls < 1:
        raise ValueError(f"max_polls must be at least 1, not {max_polls}")
    if family not in FAMILIES:  # spec 5.2: before anything is erased, and before the board is touched
        raise ProgramError(
            f"SRAM load refused: nanopynq has no loading sequence for the family {family!r} "
            f"(it has {', '.join(FAMILIES)})",
            f"family {family!r}",
        )
    jtag.tms("11111")  # Test-Logic-Reset
    jtag.tms("0")  # Run-Test/Idle
    jtag.flush()
    got = _read32(jtag, IDCODE) & 0x0FFFFFFF  # the top nibble is the silicon version (9K: 0x1100481b)
    s = _read32(jtag, STATUS)
    # A GW1N with POR, READY or VLD clear is not fit to configure (Gowin UG290, figure 7-16, stops on POR or VLD):
    # after a failed load a 9K read 0x00021020 and the IDCODE of its non-C sibling until a power cycle, and the 4K
    # whose flash was written in that state (0x00023020) never came back. Refuse before erasing anything.
    unfit = family == "gw1n" and s & GW1N_OK != GW1N_OK
    if got != idcode:
        why = (
            f"The FPGA is also not ready ({_describe(s)}; POR, READY and VLD must be set), and a GW1N in that "
            f"state reports another IDCODE. {_POWER_CYCLE}"
            if unfit
            else "Is the board option right, and is this the only board connected?"
        )
        raise ProgramError(
            f"SRAM load refused: the FPGA's IDCODE is 0x{got:08x}, expected 0x{idcode:08x} for this board. {why}",
            f"idcode 0x{got:08x}, {_describe(s)}",
        )
    if unfit:
        raise ProgramError(
            f"SRAM load refused: the FPGA is not ready to be configured ({_describe(s)}; POR, READY "
            f"and VLD must be set). {_POWER_CYCLE}",
            _describe(s),
        )
    if family == "gw2a" and s & CRC_ERROR:
        raise ProgramError(
            f"SRAM load refused: the FPGA reports CRC_ERROR from an earlier load ({_describe(s)}). {_POWER_CYCLE} "
            "If it comes back, load with openFPGALoader, which tries to clear this state on a GW2A: "
            "Overlay(..., programmer=nanopynq.program.program_sram_openfpgaloader).",
            _describe(s),
        )

    if family == "gw5a":
        _erase_gw5a(jtag, max_polls)
    else:
        _erase(jtag, max_polls)

    _instruction(jtag, CONFIG_ENABLE)  # write
    _instruction(jtag, INIT_ADDR)
    _instruction(jtag, XFER_WRITE)
    jtag.tms("100")  # Run-Test/Idle -> Shift-DR
    jtag.shift_bytes(data.translate(_REV))  # shift_bytes sends each byte LSB first
    jtag.tms("10")
    jtag.flush()
    _instruction(jtag, CONFIG_DISABLE)
    _instruction(jtag, NOOP)
    s = _read32(jtag, STATUS)
    if not s & DONE_FINAL:
        raise ProgramError(
            f"SRAM load failed: DONE_FINAL is not set after the bitstream: {_describe(s)}. "
            "Is the .fs built for this board? If it is, part of the USB transfer may have been lost: "
            "load again.",
            _describe(s),
        )

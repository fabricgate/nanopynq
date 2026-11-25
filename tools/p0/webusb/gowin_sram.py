"""Prototype: load a Gowin .fs into SRAM over nanopynq's Mpsse (the sequence the WebUSB page will use).

Usage: uv run python tools/p0/webusb/gowin_sram.py FILE.fs [--usercode] [--norev]
       uv run python tools/p0/webusb/gowin_sram.py --status
--usercode adds openFPGALoader's 0x0A + 32-bit value + 0x08 step, with the .fs header's CheckSum as the value
(openFPGALoader sends its own computed checksum; not needed on the 20K); --norev sends each byte in
the wrong bit order (the FPGA must then end up unconfigured: the check that DONE_FINAL means something).
Results: reports/report_webusb.md. Tang Nano 20K only so far.
Sequence after openFPGALoader's Gowin SRAM path (researched, reimplemented): erase (0x15, 0x05, 0x02, poll
MEMORY_ERASE, 0x09, 0x02, 0x3A, 0x02), then 0x15, 0x12, 0x17, the bitstream in one DR scan, [0x0A + checksum,
0x08], 0x3A, 0x02, DONE_FINAL.
"""
import sys
import time

from nanopynq.transport.mpsse import Mpsse

STATUS, NOOP = 0x41, 0x02
BITS = {0: "CRC_ERROR", 1: "BAD_COMMAND", 2: "ID_VERIFY_FAILED", 3: "TIMEOUT", 5: "MEMORY_ERASE", 6: "PREAMBLE",
        7: "SYSTEM_EDIT_MODE", 12: "GOWIN_VLD", 13: "DONE_FINAL", 15: "READY", 16: "POR"}


def flags(s):
    return ",".join(n for b, n in BITS.items() if s >> b & 1)


def fs_bytes(path):
    """Non-comment lines of '0'/'1', 8 characters per byte, MSB first (the order the FPGA takes them)."""
    out = bytearray()
    for line in open(path, encoding="ascii"):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        assert len(line) % 8 == 0 and set(line) <= {"0", "1"}, line[:40]
        out += int(line, 2).to_bytes(len(line) // 8, "big")
    return bytes(out)


def checksum(path):
    """The .fs header's //CheckSum (openFPGALoader computes its own, which can differ: 0xa758 vs 0xac96 for the 20K base)."""
    for line in open(path, encoding="ascii"):
        if line.startswith("//CheckSum:"):
            return int(line.split(":")[1], 16)
    return 0


REV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


class Tap:
    def __init__(self, m: Mpsse):
        self.m = m

    def cmd(self, ir):  # Run-Test/Idle -> Shift-IR, 8 bits, -> Run-Test/Idle, 6 idle clocks
        self.m.tms("1100")
        self.m.shift(ir, 8)
        self.m.tms("10")
        self.m.tms("000000")
        self.m.flush()

    def reg32(self, ir):
        self.m.tms("1100")
        self.m.shift(ir, 8)
        self.m.tms("10")
        self.m.tms("000000")
        self.m.tms("100")
        self.m.shift(0xFFFFFFFF, 32)
        self.m.tms("10")
        return self.m.flush()[-1]

    def poll(self, mask, value, what, tries=2000):
        for _ in range(tries):
            s = self.reg32(STATUS)
            if s & mask == value:
                return s
        raise RuntimeError(f"timeout waiting for {what}: status 0x{s:08x} {flags(s)}")

    def dr_bytes(self, data: bytes):
        """One DR scan of data, each byte MSB first on the wire; ends in Run-Test/Idle."""
        self.m.tms("100")
        wire = data if "--norev" in sys.argv else data.translate(REV)  # shift_bytes sends each byte LSB first
        self.m.shift_bytes(wire)  # sends the queued TMS first, ends in Exit1-DR
        self.m.tms("10")
        self.m.flush()


def status_only():
    m = Mpsse.open(0x0403, 0x6010)
    try:
        t = Tap(m)
        m.tms("11111"); m.tms("0"); m.flush()
        s = t.reg32(STATUS)
        print(f"status 0x{s:08x} {flags(s)}; usercode 0x{t.reg32(0x13):08x}")
    finally:
        m.close()


def main():
    if sys.argv[1] == "--status":
        return status_only()
    path, usercode = sys.argv[1], "--usercode" in sys.argv
    data = fs_bytes(path)
    m = Mpsse.open(0x0403, 0x6010)
    try:
        t = Tap(m)
        m.tms("11111")
        m.tms("0")
        m.flush()
        t0 = time.perf_counter()
        print(f"{len(data)} bytes; idcode 0x{t.reg32(0x11):08x}; status 0x{(s := t.reg32(STATUS)):08x} {flags(s)}")
        # erase
        t.cmd(0x15)
        t.poll(1 << 7, 1 << 7, "SYSTEM_EDIT_MODE")
        t.cmd(0x05)
        t.cmd(NOOP)
        t.poll(1 << 5, 1 << 5, "MEMORY_ERASE")
        t.cmd(0x09)
        t.cmd(NOOP)
        t.cmd(0x3A)
        t.cmd(NOOP)
        s = t.poll(1 << 7, 0, "edit mode off")
        print(f"erased: status 0x{s:08x} {flags(s)}  {time.perf_counter() - t0:.2f} s")
        # write
        t.cmd(0x15)
        t.cmd(0x12)
        t.cmd(0x17)
        t1 = time.perf_counter()
        t.dr_bytes(data)
        t2 = time.perf_counter()
        if usercode:
            t.cmd(0x0A)
            m.tms("100")
            m.shift(checksum(path), 32)
            m.tms("10")
            m.flush()
            t.cmd(0x08)
        t.cmd(0x3A)
        t.cmd(NOOP)
        s = t.reg32(STATUS)
        print(f"data {t2 - t1:.2f} s ({len(data) / (t2 - t1) / 1024:.0f} KB/s); status 0x{s:08x} {flags(s)}; "
              f"{'DONE' if s >> 13 & 1 else 'FAIL'}; total {time.perf_counter() - t0:.2f} s")
        return 0 if s >> 13 & 1 else 1
    finally:
        m.close()


if __name__ == "__main__":
    sys.exit(main())

"""Program the SPI flash design and check the board's P25Q32 (reports/report_4k_peripherals.md, step 6).

Build:  tools/build_base.py --board tangnano4k --design spiflash --out DIR
Run (Git Bash, openFPGALoader and libusb on PATH):
    PATH="$OSS/bin:$OSS/lib:$PATH" uv run python tools/p0/flash4k/flash_check.py DIR [--keep] [--write]
Read-only unless --write: JEDEC ID, status register, the same 256 bytes read twice, the first 16 bytes
of every 64 KB block, and a search for a 4 KB sector that is all 0xFF from the top of the flash down.
--write uses only such a sector: erase, program one 256-byte page, read it back, erase again (back to
all 0xFF). It refuses if the status register shows block protection or no blank sector is found.
"""

import argparse
import sys
import time

from nanopynq import Overlay

SIZE, SECTOR, PAGE = 4 * 1024 * 1024, 4096, 256
JEDEC = bytes([0x85, 0x60, 0x16])  # PUYA, P25Q series, 2^22 bytes

ap = argparse.ArgumentParser()
ap.add_argument("design")
ap.add_argument("--keep", action="store_true")
ap.add_argument("--write", action="store_true")
args = ap.parse_args()


class Flash:
    def __init__(self, ip):
        self.ip = ip

    def xfer(self, data: bytes) -> bytes:
        """One CS# low transaction: send data, return the bytes received."""
        out = bytearray()
        for i in range(0, len(data), 4):
            chunk = data[i:i + 4]
            self.ip.write(0x0, 1 | (len(chunk) - 1) << 1)
            self.ip.write(0x4, int.from_bytes(chunk, "big"))
            while self.ip.read(0x8) & 1:
                pass
            out += self.ip.read(0x4).to_bytes(4, "big")[4 - len(chunk):]
        self.ip.write(0x0, 0)
        return bytes(out)

    def jedec(self) -> bytes:
        return self.xfer(b"\x9f\0\0\0")[1:]

    def status(self) -> int:
        return self.xfer(b"\x05\0")[1]

    def read(self, addr: int, n: int) -> bytes:
        return self.xfer(bytes([0x03]) + addr.to_bytes(3, "big") + bytes(n))[4:]

    def wait(self, timeout: float) -> None:
        t_end = time.monotonic() + timeout
        while self.status() & 1:  # WIP
            if time.monotonic() > t_end:
                raise TimeoutError("flash still busy")

    def erase_sector(self, addr: int) -> None:
        self.xfer(b"\x06")
        assert self.status() & 2, "write enable did not latch"
        self.xfer(bytes([0x20]) + addr.to_bytes(3, "big"))
        self.wait(1.0)

    def program(self, addr: int, data: bytes) -> None:
        self.xfer(b"\x06")
        assert self.status() & 2, "write enable did not latch"
        self.xfer(bytes([0x02]) + addr.to_bytes(3, "big") + data)
        self.wait(0.1)


ol = Overlay(args.design, board="tangnano4k", download=not args.keep)
ok = True
try:
    f = Flash(ol.flash_spi)
    jid = f.jedec()
    print(f"JEDEC ID {jid.hex(' ')} (want {JEDEC.hex(' ')})")
    ok &= jid == JEDEC
    sr = f.status()
    print(f"status register 0x{sr:02x} (WIP {sr & 1}, WEL {sr >> 1 & 1}, BP {sr >> 2 & 0x1f:05b}, SRP {sr >> 7})")
    a, b = f.read(0, PAGE), f.read(0, PAGE)
    print(f"0x000000 read twice: {'same' if a == b else 'DIFFERENT'}; first 16 bytes {a[:16].hex(' ')}")
    ok &= a == b
    used = [blk for blk in range(SIZE // 0x10000) if f.read(blk * 0x10000, 16) != b"\xff" * 16]
    print(f"64 KB blocks whose first 16 bytes are not all 0xFF: {len(used)} of 64 {used[:16]}")
    blank = None
    for addr in range(SIZE - SECTOR, SIZE - 16 * SECTOR - 1, -SECTOR):
        if f.read(addr, SECTOR) == b"\xff" * SECTOR:
            blank = addr
            break
    print(f"blank 4 KB sector: {'none in the top 16' if blank is None else f'0x{blank:06x}'}")
    if args.write:
        if blank is None or sr & 0x7c:  # BP0..BP4
            print("STOP: no verified blank sector, or the status register shows protection; nothing written")
            ok = False
        else:
            pattern = bytes((i * 37 + 11) & 0xFF for i in range(PAGE))
            f.erase_sector(blank)
            f.program(blank, pattern)
            back = f.read(blank, PAGE)
            print(f"page at 0x{blank:06x}: programmed and read back {'the same' if back == pattern else 'DIFFERENT'}")
            ok &= back == pattern
            ok &= f.read(blank + PAGE, 16) == b"\xff" * 16  # the next page stays erased
            f.erase_sector(blank)
            restored = f.read(blank, SECTOR) == b"\xff" * SECTOR
            print(f"sector erased again: {'all 0xFF' if restored else 'NOT all 0xFF'}")
            ok &= restored
finally:
    ol.close()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

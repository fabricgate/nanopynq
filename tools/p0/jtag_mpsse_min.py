"""P0 spike: a minimal FTDI-MPSSE JTAG driver over pyusb that sends only basic
opcodes (TMS clocking 0x4B/0x6B, byte/bit write+read 0x39/0x3B, clock divisor 0x86,
GPIO 0x80, loopback off 0x85, send immediate 0x87). It checks whether the Tang
Nano's BL702 FT2232 emulation answers JTAG reads that pyftdi could not get
(reports/report_jtag_bridge_spike.md). Throwaway; not part of the package.

Run (Git Bash):
    PATH="$OSS/lib:$PATH" \
        uv run --with pyusb python tools/p0/jtag_mpsse_min.py --expect 0x100981b
"""

import argparse
import sys
import time

import usb.core
import usb.util

VID, PID = 0x0403, 0x6010
IFACE_INDEX = 1  # FTDI wIndex for interface A
EP_OUT, EP_IN, PKT = 0x02, 0x81, 64

# GPIO low byte: bit0 TCK, bit1 TDI, bit2 TDO (in), bit3 TMS
DIR = 0x0B


class Mpsse:
    def __init__(self, khz: int):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise SystemExit("device 0403:6010 not found")
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)
        ctrl = lambda req, val: self.dev.ctrl_transfer(0x40, req, val, IFACE_INDEX, None, 1000)
        ctrl(0x00, 0)              # reset
        ctrl(0x00, 1)              # purge RX
        ctrl(0x00, 2)              # purge TX
        ctrl(0x09, 2)              # latency timer 2 ms
        ctrl(0x0B, 0x0000)         # bitmode reset
        ctrl(0x0B, 0x0200 | DIR)   # MPSSE
        time.sleep(0.05)
        self.drain()
        div = max(0, int(6000 / khz) - 1)  # FT2232D: 12 MHz / ((1+div)*2)
        self.write(bytes([0x85, 0x86, div & 0xFF, div >> 8, 0x80, 0x08, DIR]))

    def write(self, data: bytes) -> None:
        self.dev.write(EP_OUT, data, 1000)

    def read(self, n: int, timeout: float = 1.0) -> bytes:
        out = bytearray()
        t_end = time.perf_counter() + timeout
        while len(out) < n and time.perf_counter() < t_end:
            raw = bytes(self.dev.read(EP_IN, 512, 1000))
            for i in range(0, len(raw), PKT):  # strip 2 modem-status bytes per packet
                out += raw[i + 2:i + PKT]
        return bytes(out)

    def drain(self) -> bytes:
        junk = bytearray()
        try:
            while True:
                raw = bytes(self.dev.read(EP_IN, 512, 50))
                if len(raw) <= 2:
                    break
                for i in range(0, len(raw), PKT):
                    junk += raw[i + 2:i + PKT]
        except usb.core.USBTimeoutError:
            pass
        return bytes(junk)

    # --- JTAG primitives -------------------------------------------------
    def tms(self, bits: str) -> None:
        """Clock TMS with the given bit string (first char first), TDI low."""
        val = 0
        for i, b in enumerate(bits):
            val |= int(b) << i
        self.write(bytes([0x4B, len(bits) - 1, val]))

    def shift_read_bytes(self, nbytes: int) -> bytes:
        """Shift nbytes of zeros on TDI, read TDO (LSB first). Stays in Shift-xR."""
        n = nbytes - 1
        self.write(bytes([0x39, n & 0xFF, n >> 8]) + bytes(nbytes) + b"\x87")
        return self.read(nbytes)

    def close(self) -> None:
        usb.util.release_interface(self.dev, 0)
        usb.util.dispose_resources(self.dev)


def read_idcode(m: Mpsse) -> int:
    m.tms("11111")   # Test-Logic-Reset (IDCODE is the default instruction)
    m.tms("0100")    # -> Run-Test/Idle -> Select-DR -> Capture-DR -> Shift-DR
    data = m.shift_read_bytes(4)
    m.tms("11")      # leave towards Update-DR / Select-DR
    m.tms("11111")
    return int.from_bytes(data, "little") if len(data) == 4 else -1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--khz", type=int, default=1000)
    ap.add_argument("--repeat", type=int, default=200)
    ap.add_argument("--expect", type=lambda s: int(s, 0))
    args = ap.parse_args(argv)

    m = Mpsse(args.khz)
    try:
        leftover = m.drain()
        if leftover:
            print("unexpected bytes after setup:", leftover.hex())
        idcode = read_idcode(m)
        print(f"idcode 0x{idcode:08x}")
        if args.expect is not None and idcode != args.expect:
            print(f"expected 0x{args.expect:08x}; pending bytes: {m.drain().hex()}")
            return 1
        t0 = time.perf_counter()
        for _ in range(args.repeat):
            if read_idcode(m) != idcode:
                print("mismatch during repeat")
                return 1
        dt = time.perf_counter() - t0
        print(f"{args.repeat} IDCODE reads in {dt:.3f} s -> {args.repeat / dt:.0f} reads/s")
    finally:
        m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

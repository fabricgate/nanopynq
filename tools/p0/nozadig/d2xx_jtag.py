"""#50 probe: drive interface A of the Tang Nano debugger through FTDI D2XX (Windows' default driver, no Zadig).

Usage: uv run --with ftd2xx python tools/p0/nozadig/d2xx_jtag.py [FILE.fs]
  IDCODE and the status register; with a .fs also an SRAM load (the sequence of tools/p0/webusb/gowin_sram.py).
  The bitstream goes through Mpsse.shift_bytes (write-only). Needs FTDI's ftd2xx.dll (installed with the FTDI driver). Results:
  reports/report_no_zadig.md. D2XX lists interface B first: the device is picked by its description ending in " A".
"""
import sys
import time
from pathlib import Path

import ftd2xx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webusb"))
import gowin_sram  # noqa: E402
from nanopynq.transport.mpsse import DIR, Mpsse  # noqa: E402
from nanopynq.errors import TransportTimeout  # noqa: E402


class D2xxMpsse(Mpsse):
    """nanopynq's Mpsse with the USB calls replaced by D2XX (which strips the modem-status bytes itself)."""

    def __init__(self, h):
        super().__init__(dev=None, pkt=64)
        self.h = h

    @classmethod
    def open_d2xx(cls, index):
        h = ftd2xx.open(index)
        h.resetDevice()
        h.purge(ftd2xx.defines.PURGE_RX | ftd2xx.defines.PURGE_TX)
        h.setLatencyTimer(2)
        h.setTimeouts(1000, 1000)
        h.setBitMode(0, 0)
        h.setBitMode(DIR, 0x02)  # MPSSE
        time.sleep(0.05)
        m = cls(h)
        m._drain()
        m._write(bytes([0x85, 0x86, 5, 0, 0x80, 0x08, DIR]))
        return m

    def _write(self, data, expected=0):
        n = self.h.write(bytes(data))
        if n != len(data):
            raise TransportTimeout(expected, 0)

    def _read(self, n):
        out = bytearray()
        end = time.perf_counter() + 1.0
        while len(out) < n and time.perf_counter() < end:
            k = self.h.getQueueStatus()
            if k:
                out += self.h.read(min(k, n - len(out)))
        if len(out) < n:
            raise TransportTimeout(n, len(out))
        return bytes(out)

    def _drain(self):
        while self.h.getQueueStatus():
            self.h.read(self.h.getQueueStatus())

    def close(self):
        self.h.close()


def main():
    n = ftd2xx.createDeviceInfoList()
    for i in range(n):
        print(i, ftd2xx.getDeviceInfoDetail(i))
    idx = next(i for i in range(n) if ftd2xx.getDeviceInfoDetail(i)["description"].endswith(b" A"))
    m = D2xxMpsse.open_d2xx(idx)
    try:
        m.tms("11111")
        m.tms("0100")
        m.shift(0, 32)
        m.tms("10")
        print(f"device {idx}: IDCODE 0x{m.flush()[0]:08x}")
        t = gowin_sram.Tap(m)
        s = t.reg32(gowin_sram.STATUS)
        print(f"status 0x{s:08x} {gowin_sram.flags(s)}; usercode 0x{t.reg32(0x13):08x}")
    finally:
        m.close()
    if len(sys.argv) > 1:
        gowin_sram.Mpsse.open = classmethod(lambda cls, vid, pid: D2xxMpsse.open_d2xx(idx))
        sys.argv = [sys.argv[0], sys.argv[1]]
        return gowin_sram.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

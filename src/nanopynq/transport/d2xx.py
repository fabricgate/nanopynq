"""JTAG over the Tang Nano's debugger through FTDI's D2XX (ftd2xx.dll), on Windows' FTDI driver.

With Interface 0 left on FTDI's driver (FTDIBUS), libusb cannot open it, but D2XX can put interface A in
MPSSE mode (#50: IDCODE, SRAM loads and the JTAG bridge on the 9K and 20K). D2xxMpsse replaces only the
USB layer of Mpsse; the MPSSE commands, shift_bytes' per-chunk wait and the bridge are Mpsse's own.

ftd2xx.dll is not shipped with nanopynq: it comes with FTDI's driver. FTDI's terms allow its use with
genuine FTDI parts; using it with the boards' FT2232-compatible debuggers was the owner's decision
(2026-11-20).
"""

import ctypes
import time
from typing import Any

from nanopynq.errors import PortNotFound, PortOpenError, TransportTimeout
from nanopynq.transport.mpsse import DIR, READ_TIMEOUT, Mpsse

_OPENED, _HIGH_SPEED = 1, 2  # FT_FLAGS_OPENED, FT_FLAGS_HISPEED
_PURGE_RX, _PURGE_TX = 1, 2


class D2xx:
    """The few ftd2xx.dll calls nanopynq needs. Every call raises OSError when the driver reports an error."""

    def __init__(self) -> None:
        # OSError if missing; AttributeError off Windows (no WinDLL), which is also why mypy off Windows rejects it
        self.dll = ctypes.WinDLL("ftd2xx.dll")  # type: ignore[attr-defined, unused-ignore]

    def _call(self, name: str, *args: Any) -> None:
        status = getattr(self.dll, name)(*args)
        if status:
            raise OSError(f"{name} failed (FT_STATUS {status})")

    def devices(self) -> list[dict[str, Any]]:
        n = ctypes.c_ulong()
        self._call("FT_CreateDeviceInfoList", ctypes.byref(n))
        out = []
        for i in range(n.value):
            flags, kind, usb_id, loc = (ctypes.c_ulong() for _ in range(4))
            serial, desc, handle = ctypes.create_string_buffer(16), ctypes.create_string_buffer(64), ctypes.c_void_p()
            self._call(
                "FT_GetDeviceInfoDetail",
                ctypes.c_ulong(i),
                ctypes.byref(flags),
                ctypes.byref(kind),
                ctypes.byref(usb_id),
                ctypes.byref(loc),
                serial,
                desc,
                ctypes.byref(handle),
            )
            out.append(
                {
                    "index": i,
                    "flags": flags.value,
                    "id": usb_id.value,
                    "serial": serial.value.decode("ascii", "replace"),
                    "description": desc.value.decode("ascii", "replace"),
                }
            )
        return out

    def open(self, index: int) -> ctypes.c_void_p:
        handle = ctypes.c_void_p()
        self._call("FT_Open", ctypes.c_int(index), ctypes.byref(handle))
        return handle

    def setup(self, handle: ctypes.c_void_p) -> None:
        """Reset, purge, 2 ms latency, 1 s timeouts, then MPSSE (bit mode reset first)."""
        self._call("FT_ResetDevice", handle)
        self._call("FT_Purge", handle, ctypes.c_ulong(_PURGE_RX | _PURGE_TX))
        self._call("FT_SetLatencyTimer", handle, ctypes.c_ubyte(2))
        ms = ctypes.c_ulong(int(READ_TIMEOUT * 1000))
        self._call("FT_SetTimeouts", handle, ms, ms)
        self._call("FT_SetBitMode", handle, ctypes.c_ubyte(0), ctypes.c_ubyte(0))
        self._call("FT_SetBitMode", handle, ctypes.c_ubyte(DIR), ctypes.c_ubyte(0x02))

    def write(self, handle: ctypes.c_void_p, data: bytes) -> int:
        done = ctypes.c_ulong()
        self._call("FT_Write", handle, ctypes.c_char_p(bytes(data)), ctypes.c_ulong(len(data)), ctypes.byref(done))
        return done.value

    def read(self, handle: ctypes.c_void_p, n: int) -> bytes:
        """Up to n bytes: FT_Read returns early only at the read timeout set in setup()."""
        buf, got = ctypes.create_string_buffer(n), ctypes.c_ulong()
        self._call("FT_Read", handle, buf, ctypes.c_ulong(n), ctypes.byref(got))
        return buf.raw[: got.value]

    def queued(self, handle: ctypes.c_void_p) -> int:
        n = ctypes.c_ulong()
        self._call("FT_GetQueueStatus", handle, ctypes.byref(n))
        return n.value

    def purge_rx(self, handle: ctypes.c_void_p) -> None:
        self._call("FT_Purge", handle, ctypes.c_ulong(_PURGE_RX))

    def close(self, handle: ctypes.c_void_p) -> None:
        self._call("FT_Close", handle)


class D2xxMpsse(Mpsse):
    """Mpsse with its USB calls on D2XX (which strips the modem-status bytes itself)."""

    def __init__(self, d2xx: D2xx, handle: ctypes.c_void_p, pkt: int) -> None:
        super().__init__(dev=None, pkt=pkt)  # pkt: 512 on a high-speed debugger (BL616), else 64 (BL702)
        self.d2xx, self.handle = d2xx, handle

    @classmethod
    # The third argument is an injected D2xx (tests), where Mpsse.open takes an injected USB find.
    def open(cls, vid: int, pid: int, d2xx: D2xx | None = None) -> "D2xxMpsse":  # type: ignore[override]
        try:
            d2xx = d2xx or D2xx()
            devs = d2xx.devices()
        except (OSError, AttributeError) as e:
            raise PortNotFound(f"FTDI's D2XX driver (ftd2xx.dll) cannot be used: {e}") from e
        mine = [d for d in devs if d["id"] == (vid << 16 | pid) and d["description"].endswith(" A")]
        free = [d for d in mine if not d["flags"] & _OPENED]
        if not free:
            if mine:  # interface A itself is listed as open
                raise PortOpenError(
                    "the board's JTAG interface (D2XX) is open in another program: close a previous Overlay "
                    "(ol.close()), openFPGALoader or a WebUSB page, or unplug and replug the USB cable"
                )
            # An entry that is open elsewhere (or unreadable) lists no ID or name (#50), so it may be anything,
            # e.g. the 9K's interface B while interface A is on WinUSB: do not call it our JTAG interface.
            unknown = sum(1 for d in devs if d["flags"] & _OPENED)
            note = f" ({unknown} FTDI device(s) open in another program or unreadable)" if unknown else ""
            raise PortNotFound(
                f"no USB device {vid:04x}:{pid:04x} on FTDI's driver (D2XX) found{note}; connect the board"
            )
        if len(free) > 1:
            serials = ", ".join(d["serial"] for d in free)
            raise PortNotFound(f"multiple boards {vid:04x}:{pid:04x} connected ({serials}); connect only one")
        dev = free[0]
        try:
            handle = d2xx.open(dev["index"])
        except OSError as e:
            raise PortOpenError(f"could not open the board's JTAG interface through D2XX: {e}") from e
        m = cls(d2xx, handle, 512 if dev["flags"] & _HIGH_SPEED else 64)
        try:
            d2xx.setup(handle)
            time.sleep(0.05)
            m._setup()
        except (OSError, TransportTimeout) as e:
            m.close()
            raise PortOpenError(f"could not set up the board's JTAG interface through D2XX: {e}") from e
        return m

    def _write(self, data: bytes, expected: int = 0) -> None:
        try:
            if self.d2xx.write(self.handle, data) != len(data):
                raise TransportTimeout(expected, 0)
        except OSError as e:
            raise TransportTimeout(expected, 0) from e

    def _read(self, n: int) -> bytes:
        try:
            out = self.d2xx.read(self.handle, n)
        except OSError as e:
            raise TransportTimeout(n, 0) from e
        if len(out) < n:
            raise TransportTimeout(n, len(out))
        return out

    def _drain(self) -> None:
        try:
            while k := self.d2xx.queued(self.handle):
                self.d2xx.read(self.handle, k)
        except OSError as e:
            raise TransportTimeout(0, 0) from e

    def _purge_rx(self, expected: int) -> None:
        try:
            self.d2xx.purge_rx(self.handle)
        except OSError as e:
            raise TransportTimeout(expected, 0) from e
        self._drain()

    def close(self) -> None:
        try:
            self.d2xx.close(self.handle)
        except OSError:
            pass  # e.g. the board was unplugged: nothing left to free

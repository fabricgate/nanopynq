"""The JTAG operations nanopynq needs from a debugger, and the one place that opens a debugger.

The Gowin SRAM loader (nanopynq.gowin) and the JTAG bridge client (jtagbridge.py) use only these
operations, so another debugger (D2XX, CH552, CMSIS-DAP, ...) is one more class here plus a choice in
open_jtag. Today Mpsse is the only one.
"""

from collections.abc import Callable
from typing import Any, Protocol


class Jtag(Protocol):
    msb_first: bool  # shift_bytes / idle send their data MSB first (same bits on the wire); see transport/mpsse.py

    @property
    def max_read(self) -> int:
        """TDO bytes one flush() can return."""

    def tms(self, bits: str) -> None:
        """Queue TMS clocks, first character first, TDI low."""

    def idle(self, clocks: int) -> None:
        """Clock at least `clocks` TCK cycles (may round up) with TMS held where the last tms() left it (0 in
        Run-Test/Idle) and TDI low. Sends what is queued first (its TDO is dropped: flush() first if it is
        needed) and returns once every clock is out. clocks < 1 is a ValueError."""

    def shift(self, value: int, nbits: int) -> None:
        """Queue an nbits TDI/TDO shift (LSB first) whose last bit goes with TMS=1 (to Exit1-xR)."""

    def shift_bytes(self, data: bytes) -> None:
        """In Shift-DR: send what is queued (the TDO of queued shift() calls is dropped: flush() first if it
        is needed), then clock data out without returning TDO, each byte LSB first, the last bit with TMS=1
        (to Exit1-DR). Returns once every byte is out."""

    def flush(self) -> list[int]:
        """Send everything queued; return the TDO of each queued shift() in order."""

    def close(self) -> None:
        """Release the debugger."""


def open_jtag(vid: int, pid: int, find: Callable[..., Any] | None = None) -> Jtag:
    """libusb first (Interface 0 on WinUSB after Zadig, or Linux); on Windows, if libusb finds the board but
    cannot open it (PortOpenError: e.g. Interface 0 is on Windows' own FTDI driver), FTDI's D2XX. libusb counts
    every board whatever its driver, so when it finds none or several (PortNotFound) D2XX is not tried: it could
    only find nothing, or silently pick the one board on FTDI's driver. When D2XX finds no board either, the
    libusb error stands: it carries the setup hint. An injected find (a fake USB bus) never falls through to
    the real D2XX."""
    import sys

    from nanopynq.errors import PortNotFound, PortOpenError
    from nanopynq.transport.mpsse import Mpsse

    try:
        return Mpsse.open(vid, pid, find)
    except PortOpenError as libusb_error:
        if sys.platform != "win32" or find is not None:
            raise
        from nanopynq.transport.d2xx import D2xxMpsse

        try:
            return D2xxMpsse.open(vid, pid)
        except PortNotFound:
            raise libusb_error from None

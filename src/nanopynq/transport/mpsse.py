"""JTAG over the Tang Nano's BL702 / BL616 (FT2232-compatible, interface A) with pyusb.

The BL702 rejects the read-only MPSSE opcodes (0x28/0x2C/0x2A/0x2E) and the write-on-rising-edge
ones (0x38/0x3C), so this sends only 0x39/0x3B (write -ve, read +ve), 0x4B/0x6B (TMS), 0x80, 0x85,
0x86 and 0x87 (reports/report_jtag_bridge_spike.md sections 4 and 10), plus the write-only 0x19/0x1B
(write -ve, no read) in shift_bytes, checked on the BL702 and the BL616 (reports/report_sram_loader.md).
With msb_first (the Tang Mega 138K Pro's BL616, whose firmware clocks 0x19 at about 0.47 MHz), shift_bytes and idle
send their data as 0x11 (MSB first, write -ve, no read) instead, at most 4096 bytes per command: about 2.6 MHz
(reports/report_tangmega138kpro.md).
shift_bytes ends each chunk with one byte through 0x39 and waits for its TDO byte, so the host never runs
ahead of the debugger (section 3.1 there).
"""

import sys
import time
from collections.abc import Callable
from typing import Any

from nanopynq.errors import PortNotFound, PortOpenError, TransportTimeout

IFACE_INDEX = 1  # FTDI wIndex for interface A
EP_OUT, EP_IN = 0x02, 0x81
DIR = 0x0B  # GPIO low byte: bit0 TCK, bit1 TDI, bit2 TDO (in), bit3 TMS
KHZ = 1000  # TCK ignores the divisor: about 2 MHz on the BL702 (report 13.1), 3.5 MHz on the BL616
READ_TIMEOUT = 1.0
MSB_CMD_MAX = 4096  # bytes per 0x11 command: 16 KB broke on the 138K Pro's BL616 (it read the rest as commands)
_REV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


def _driver_hint() -> str:
    if sys.platform == "win32":
        return (
            "Windows: keep FTDI's driver on 'Interface 0' of the board (nanopynq then uses its D2XX), or use "
            "Zadig to replace the driver of only 'Interface 0' with WinUSB."
        )
    return (
        "Linux: install the udev rule 99-nanopynq.rules (in nanopynq's data folder; "
        "python -m nanopynq doctor prints the command) and re-plug the board."
    )


def encode_shift(value: int, nbits: int) -> bytes:
    """Clock nbits of value out on TDI (LSB first) while reading TDO; the last bit goes with TMS=1."""
    nbytes = (nbits - 1) // 8
    rest = nbits - 1 - nbytes * 8
    cmd = bytearray()
    if nbytes:
        n = nbytes - 1
        cmd += bytes([0x39, n & 0xFF, n >> 8]) + (value & ((1 << (8 * nbytes)) - 1)).to_bytes(nbytes, "little")
    if rest:
        cmd += bytes([0x3B, rest - 1, (value >> (8 * nbytes)) & ((1 << rest) - 1)])
    cmd += bytes([0x6B, 0, (((value >> (nbits - 1)) & 1) << 7) | 0x01])
    return bytes(cmd)


def _resp_len(nbits: int) -> int:
    return (nbits - 1) // 8 + (1 if (nbits - 1) % 8 else 0) + 1


def decode_shift(resp: bytes, nbits: int) -> int:
    """TDO bits of one encode_shift(): bit-mode bytes come MSB-aligned, the TMS bit is bit 7."""
    nbytes = (nbits - 1) // 8
    rest = nbits - 1 - nbytes * 8
    out = int.from_bytes(resp[:nbytes], "little")
    if rest:
        out |= (resp[nbytes] >> (8 - rest)) << (8 * nbytes)
    out |= ((resp[-1] >> 7) & 1) << (nbits - 1)
    return out


def _serial(dev: Any) -> str:  # a pyusb Device (no type information)
    try:
        return str(dev.serial_number)
    except (ValueError, NotImplementedError, OSError):  # usb.core.USBError is an OSError
        return "?"


class Mpsse:
    msb_first = False  # send shift_bytes / idle data as 0x11 (MSB first); program_sram sets it from boards.yaml

    def __init__(self, dev: Any, pkt: int = 64) -> None:
        self.dev = dev
        self.pkt = pkt  # IN packet size: 64 on the BL702 (full speed), 512 on the BL616 (high speed)
        self._cmd = bytearray()
        self._shifts: list[int] = []
        self._stale = False  # set when a flush did not finish

    @classmethod
    def open(cls, vid: int, pid: int, find: Callable[..., Any] | None = None) -> "Mpsse":
        import usb.core
        import usb.util

        if find is None:
            import libusb_package

            find = libusb_package.find
        devs = list(find(find_all=True, idVendor=vid, idProduct=pid))
        if not devs:
            raise PortNotFound(f"no USB device {vid:04x}:{pid:04x} found; connect the board. {_driver_hint()}")
        if len(devs) > 1:
            serials = ", ".join(_serial(d) for d in devs)
            raise PortNotFound(f"multiple boards {vid:04x}:{pid:04x} connected ({serials}); connect only one")
        dev = devs[0]
        claimed = False
        try:
            try:
                if dev.is_kernel_driver_active(0):
                    try:
                        dev.detach_kernel_driver(0)
                    except usb.core.USBError:
                        # nanopynq's udev rule unbinds ftdi_sio right after it binds: it may get there first
                        if dev.is_kernel_driver_active(0):
                            raise
            except NotImplementedError:  # Windows
                pass
            try:
                dev.get_active_configuration()
            except usb.core.USBError:  # not configured yet
                # Only then: Linux refuses SET_CONFIGURATION (EBUSY) while ftdi_sio holds Interface 1.
                dev.set_configuration()
            usb.util.claim_interface(dev, 0)
            claimed = True
            ep_in = usb.util.find_descriptor(dev.get_active_configuration()[(0, 0)], bEndpointAddress=EP_IN)
            m = cls(dev, ep_in.wMaxPacketSize)
            for req, val in (
                (0x00, 0),
                (0x00, 1),
                (0x00, 2),  # reset, purge RX, purge TX
                (0x09, 2),  # latency timer 2 ms
                (0x0B, 0x0000),
                (0x0B, 0x0200 | DIR),
            ):  # bitmode reset, MPSSE
                dev.ctrl_transfer(0x40, req, val, IFACE_INDEX, None, 1000)
            time.sleep(0.05)
            m._setup()
        except (usb.core.USBError, NotImplementedError, TransportTimeout) as e:
            # NotImplementedError: libusb NOT_SUPPORTED, e.g. no WinUSB driver on the interface
            try:
                if claimed:
                    usb.util.release_interface(dev, 0)
            except usb.core.USBError:
                pass
            usb.util.dispose_resources(dev)
            hint = f" {_driver_hint()}" if sys.platform == "win32" else ""
            raise PortOpenError(
                f"could not open the board's JTAG interface: {e}. If a previous Overlay holds it, call "
                f"ol.close() on it; make sure no other program (openFPGALoader included) is using it; otherwise "
                f"unplug and replug "
                f"the USB cable.{hint}"
            ) from e
        return m

    def _write(self, data: bytes, expected: int = 0) -> None:
        import usb.core

        try:
            self.dev.write(EP_OUT, data, 1000)
        except usb.core.USBError as e:  # includes USBTimeoutError: the BL702 stopped taking data
            raise TransportTimeout(expected, 0) from e

    def _read(self, n: int) -> bytes:
        import usb.core

        out = bytearray()
        t_end = time.perf_counter() + READ_TIMEOUT
        while len(out) < n and time.perf_counter() < t_end:
            try:
                raw = bytes(self.dev.read(EP_IN, 512, 100))
            except usb.core.USBTimeoutError:
                continue
            except usb.core.USBError as e:
                raise TransportTimeout(n, len(out)) from e
            for i in range(0, len(raw), self.pkt):  # strip 2 modem-status bytes per packet
                out += raw[i + 2 : i + self.pkt]
        if len(out) < n:
            raise TransportTimeout(n, len(out))
        return bytes(out[:n])

    def _drain(self) -> None:
        import usb.core

        try:
            while len(bytes(self.dev.read(EP_IN, 512, 50))) > 2:
                pass
        except usb.core.USBTimeoutError:
            pass
        except usb.core.USBError as e:
            raise TransportTimeout(0, 0) from e

    def _setup(self) -> None:
        """MPSSE is on: drop what is pending, then loopback off, the TCK divisor and the pin directions."""
        self._drain()
        div = max(0, int(6000 / KHZ) - 1)
        self._write(bytes([0x85, 0x86, div & 0xFF, div >> 8, 0x80, 0x08, DIR]))

    def _purge_rx(self, expected: int) -> None:
        """Drop whatever the debugger still has for us (after a failed flush)."""
        import usb.core

        try:
            self.dev.ctrl_transfer(0x40, 0x00, 1, IFACE_INDEX, None, 1000)  # purge RX
        except usb.core.USBError as e:
            raise TransportTimeout(expected, 0) from e
        self._drain()

    @property
    def max_read(self) -> int:
        """TDO bytes one flush can return: the BL702 (64-byte packets) answers at most 1024 per
        write-and-read-back, the BL616 was checked with 4096 (reports/report_webusb.md)."""
        return 1024 if self.pkt == 64 else 4096

    @property
    def _write_chunk(self) -> int:
        """Bytes per USB write in shift_bytes. The BL702 (64-byte packets) drops what is past about 1 KB of one
        transfer without refusing it: on the 9K a 2048-byte write left the FPGA unconfigured, 1024 loaded
        (2026-11-20). The BL616 took 16 KiB writes."""
        return 1024 if self.pkt == 64 else 0x4000

    def shift_bytes(self, data: bytes) -> None:
        """In Shift-DR: clock data out, each byte LSB first, the last bit with TMS=1 (to Exit1-DR). Sends what
        is queued first, so no byte goes out before the TMS that reaches Shift-DR; the TDO of those queued
        shifts is dropped. Returns once every byte is out.

        Each chunk goes out write-only (0x19), except its last byte, which is read back (0x39); the host waits
        for that one TDO byte before the next chunk. Without that wait the host ran ahead of the debugger: on
        the 9K (BL702) about one load in four failed, and a failed one once left the FPGA with POR clear and a
        wrong IDCODE until a power cycle. With it, 40 loads of 40 passed in 0.36 s (all read back, 0x39: 0.48 s).
        """
        if not data:
            raise ValueError("shift_bytes needs at least one byte")
        if self._cmd:
            self.flush()
        body, last = data[:-1], data[-1]
        try:
            for i in range(0, len(body), self._write_chunk):
                head, tail = (
                    body[i : i + self._write_chunk - 1],
                    body[i + self._write_chunk - 1 : i + self._write_chunk],
                )
                if not tail:  # the final, shorter chunk
                    head, tail = head[:-1], head[-1:]
                self._write(
                    self._data_out(head) + bytes([0x39, 0, 0]) + tail + b"\x87", 1
                )  # 0x19 / 0x11 no read; 0x39 1 byte read
                self._read(1)
            self._write(
                bytes(
                    [
                        0x1B,
                        6,
                        last & 0x7F,  # 0x1B: 7 bits out, no read
                        0x6B,
                        0x00,
                        (last >> 7) << 7 | 0x01,
                        0x87,
                    ]
                ),
                1,
            )
            self._read(1)
        except BaseException:
            self._stale = True  # the 0x6B answer may still arrive: the next flush drops it
            raise

    def tms(self, bits: str) -> None:
        """Queue TMS clocks, first character first, TDI low."""
        self._cmd += bytes([0x4B, len(bits) - 1, sum(int(b) << i for i, b in enumerate(bits))])

    def _data_out(self, data: bytes) -> bytes:
        """Write-only commands that clock data out, each byte LSB first: one 0x19, or with msb_first the same bits
        as 0x11 commands (bytes bit-reversed) of at most MSB_CMD_MAX bytes."""
        if not data:
            return b""
        if not self.msb_first:
            return bytes([0x19, (len(data) - 1) & 0xFF, (len(data) - 1) >> 8]) + data
        data, out = data.translate(_REV), bytearray()
        for i in range(0, len(data), MSB_CMD_MAX):
            c = data[i : i + MSB_CMD_MAX]
            out += bytes([0x11, (len(c) - 1) & 0xFF, (len(c) - 1) >> 8]) + c
        return bytes(out)

    def idle(self, clocks: int) -> None:
        """Clock at least `clocks` TCK cycles (whole bytes of 8) with TMS held where the last tms() left it and TDI
        low. Sends what is queued first (its TDO is dropped) and returns once every clock is out.

        The BL616 answers 0x8F (clocks without data) with 0xFA "bad command" (2026-11-21), so this clocks zero
        bytes with the data commands of shift_bytes, paced the same way: each chunk ends with its last byte read
        back (0x39) and the host waits for it."""
        if clocks < 1:
            raise ValueError(f"idle needs clocks >= 1, not {clocks}")
        if self._cmd:
            self.flush()
        n = -(-clocks // 8)
        try:
            for i in range(0, n, self._write_chunk):
                k = min(self._write_chunk, n - i)
                self._write(self._data_out(bytes(k - 1)) + bytes([0x39, 0, 0, 0, 0x87]), 1)
                self._read(1)
        except BaseException:
            self._stale = True
            raise

    def shift(self, value: int, nbits: int) -> None:
        """Queue an nbits TDI/TDO shift that leaves Shift-xR on its last bit."""
        self._cmd += encode_shift(value, nbits)
        self._shifts.append(nbits)

    def flush(self) -> list[int]:
        """Send everything queued in one USB write; return the TDO of each queued shift in order."""
        cmd, shifts = bytes(self._cmd) + b"\x87", self._shifts
        self._cmd, self._shifts = bytearray(), []
        n = sum(_resp_len(k) for k in shifts)
        if self._stale:  # a failed flush may still deliver its answer: drop it before this one
            self._purge_rx(n)
            self._stale = False
        try:
            self._write(cmd, n)
            resp = self._read(n)
        except BaseException:
            self._stale = True
            raise
        out, i = [], 0
        for n in shifts:
            out.append(decode_shift(resp[i : i + _resp_len(n)], n))
            i += _resp_len(n)
        return out

    def close(self) -> None:
        import usb.core
        import usb.util

        try:
            usb.util.release_interface(self.dev, 0)
        except usb.core.USBError:
            pass  # e.g. the board was unplugged: nothing left to release, and callers close in a finally
        finally:
            usb.util.dispose_resources(self.dev)

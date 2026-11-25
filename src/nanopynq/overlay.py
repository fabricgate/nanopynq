"""Overlay: verify the design, program the board, open the host link (UART or JTAG) and check the sysinfo ID."""

import sys
import time
import warnings

from nanopynq.boards import get_board, uart_link
from nanopynq.errors import (
    BoardNotResponding,
    BridgeError,
    DesignMismatch,
    ManifestError,
    PortOpenError,
    TransportTimeout,
)
from nanopynq.ip import driver_for
from nanopynq.npq import SYSINFO, Npq, load_design
from nanopynq.program import program_sram
from nanopynq.resolve import bundled_boards, resolve_design
from nanopynq.transport.jtagbridge import JTAGBridge
from nanopynq.transport.serialport import find_port
from nanopynq.transport.uartbone import UARTBone

SYSINFO_ID = 0x4E505131
SYS_VERSION, SYS_DESIGN_ID = 0x4, 0xC  # sys is at 0x0 (V10)
ID_ATTEMPTS = 3
ID_RETRY_DELAY = 0.5
_sleep = time.sleep  # tests patch this


def _open_serial(port, baudrate):
    import serial

    return serial.Serial(port, baudrate, timeout=1.0)


def _open_hint() -> str:
    if sys.platform == "win32":
        return (
            "Windows: a previous Overlay in this kernel probably still holds the port; "
            "call ol.close() on it, or restart the kernel."
        )
    return "Linux: you may not be in the 'dialout' group; run 'sudo usermod -aG dialout $USER' and log in again."


class Overlay:
    def __init__(
        self,
        design="base",
        board: str | None = None,
        download: bool = True,
        port: str | None = None,
        transport=None,
        programmer=program_sram,
        open_port=None,
        open_jtag=None,
    ):
        if board is None and bundled_boards(str(design)):
            raise ValueError(
                f"board is required for design {str(design)!r}; choose one of {bundled_boards(str(design))}"
            )
        self._cache: dict = {}
        self._link = None  # what close() closes: the serial port or the JTAG bridge
        self.design_dir = resolve_design(design, board)
        self.manifest = load_design(
            self.design_dir, check_bitstream=download
        )  # checked before programming; no .fs read if not downloading
        if board is not None and board != self.manifest.board:
            raise ManifestError(f"board {board!r} does not match manifest board {self.manifest.board!r}")
        self.board = get_board(self.manifest.board)
        link = self.board.host_link
        if isinstance(self.manifest, Npq):  # the file's link (spec 10.7); USB VID / PID stay from boards.yaml
            kind = self.manifest.link["kind"]
            if kind != link["kind"] and not (kind == "uart" and uart_link(self.board)):  # the 20K's second link
                raise ManifestError(
                    f"{self.design_dir}: link.kind is {self.manifest.link['kind']!r}, but nanopynq talks to "
                    f"{self.board.board_id} over {link['kind']!r}; rebuild the design for this board"
                )
            link = {**link, **self.manifest.link}
        self._link_kind = link["kind"]  # the link in use, which on the 20K need not be host_link's
        if download:
            programmer(self.board, self.manifest.bitstream)
        self._transport = transport
        if transport is None and link["kind"] == "jtag":
            try:  # PortNotFound / PortOpenError pass through: they carry their own next step
                self._link = self._transport = (open_jtag or JTAGBridge.open)(link)
            except (TransportTimeout, BridgeError):
                self._not_responding(None)
        elif transport is None:
            baud = link["baudrate"]
            port = port or find_port(self.board)
            try:
                serial_port = (open_port or _open_serial)(port, baud)
            except OSError as e:  # serial.SerialException is an OSError
                raise PortOpenError(f"could not open serial port {port}: {e}. {_open_hint()}") from e
            self._link = serial_port
            self._transport = UARTBone(serial_port, baud)
        try:
            self._check_id()
            self._check_design(download)
        except BaseException:  # never leave the port / USB interface held by an Overlay nobody got back
            self.close()
            raise

    def _check_id(self) -> None:
        sysinfo = self.manifest.ips.get("sys")
        if sysinfo is None or "id" not in sysinfo["registers"]:
            self.close()
            raise ManifestError("manifest has no 'sys' ip with an 'id' register")
        addr = sysinfo["phys_addr"] + sysinfo["registers"]["id"]["offset"]
        got = None
        for attempt in range(ID_ATTEMPTS):
            if attempt:
                _sleep(ID_RETRY_DELAY)
            try:
                got = self._transport.read(addr)
            except TransportTimeout:
                got = None
            except BridgeError as e:
                got = e
            if got == SYSINFO_ID:
                return
        self._not_responding(got)

    def _check_design(self, download: bool) -> None:
        """Spec 5.7 step 6 and 5.8: sys.version, then sys.design_id against the .npq. Reads only sys."""
        where = f"the design in {self.design_dir}"
        if not isinstance(self.manifest, Npq):
            if not download:
                warnings.warn(
                    f"{where} has a manifest.yaml and no design_id, so the design on the board was not "
                    "checked against it (download=False). Use download=True, or rebuild the design to "
                    "get a .npq.",
                    stacklevel=3,
                )
            return
        want = self.manifest.design_id
        declared = self.manifest.ips["sys"]["type"]
        m = SYSINFO.fullmatch(declared)
        assert m is not None  # load_design checked sys.type (V10)
        v = self._transport.read(SYS_VERSION)
        got = (v >> 16, v & 0xFFFF)
        fix = (
            "The .fs just programmed does not carry it: rebuild the design (tools/build_base.py writes the .fs "
            "and the .npq together)."
            if download
            else "Run Overlay(..., download=True) to program this design, or open the .npq of the design on the board."
        )
        if got < (1, 1):
            if (int(m[1]), int(m[2])) >= (1, 1):
                raise DesignMismatch(
                    f"the board runs sysinfo {got[0]}.{got[1]} (sys.version 0x{v:08X}, a build without a design ID), "
                    f"but {where} declares {declared} with design_id 0x{want:08x}. {fix}"
                )
            if not download:
                warnings.warn(
                    f"the board runs sysinfo {got[0]}.{got[1]}, which has no design_id, so the design on "
                    f"the board was not checked against {where} (download=False).",
                    stacklevel=3,
                )
            return
        did = self._transport.read(SYS_DESIGN_ID)
        if did != want:
            seen = "0x00000000 (built without a design ID)" if did == 0 else f"0x{did:08x}"
            raise DesignMismatch(
                f"the board runs another design: sys.design_id is {seen}, {where} has 0x{want:08x}. {fix}"
            )

    def _not_responding(self, got) -> None:
        self.close()
        if got is None:
            seen = "no response"
        elif isinstance(got, BridgeError):
            seen = f"bad JTAG response 0x{got.response:016X}"
        else:
            seen = f"0x{got:08X}"
        if self._link_kind == "jtag":
            raise BoardNotResponding(
                f"sysinfo ID check over JTAG failed ({seen}, expected 0x{SYSINFO_ID:08X}). Either the board "
                "is not running this design, or its onboard debugger (BL702) has stopped answering: unplug "
                "and replug the USB cable (USBを抜き差しして), then run Overlay(...) again. It re-programs "
                "the board first."
            )
        # Only the 9K's BL702 cannot take JTAG and UART together; the BL616 (20K, 138K Pro) can.
        why = (
            "The Tang onboard debugger cannot use JTAG and UART at the same time"
            if self.board.host_link.get("exclusive_with_jtag")
            else "The onboard debugger may have stopped answering"
        )
        raise BoardNotResponding(
            f"sysinfo ID check failed ({seen}, expected 0x{SYSINFO_ID:08X}). {why}: unplug and replug the USB "
            "cable (USBを抜き差しして), then run Overlay(...) again. It re-programs the board and then opens "
            "the port (replugging cuts power and erases the design from SRAM). download=False is only "
            "for reopening within the same power cycle."
        )

    @property
    def ip_dict(self) -> dict[str, dict]:
        return self.manifest.ips

    def __getattr__(self, name):
        if (
            name.startswith("_") or name == "manifest" or name not in self.manifest.ips
        ):  # no recursion if __init__ failed
            raise AttributeError(name)
        if name not in self._cache:
            desc = self.manifest.ips[name]
            self._cache[name] = driver_for(desc["type"])(desc, self._transport)
        return self._cache[name]

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(self.manifest.ips))

    def __repr__(self) -> str:
        rows = "\n".join(f"  {n}: {d['type']} @ 0x{d['phys_addr']:X}" for n, d in self.ip_dict.items())
        return f"Overlay(board={self.manifest.board!r}):\n{rows}"

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._link is not None:
            if hasattr(self._link, "close"):
                self._link.close()
            self._link = None

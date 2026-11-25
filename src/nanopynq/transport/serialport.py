"""Pick the board's host-link serial port from the connected USB serial devices."""

from nanopynq.boards import BoardInfo
from nanopynq.errors import PortNotFound

_HINT = "pass port='COMx' (or '/dev/ttyUSBx') explicitly"


def _ftdi_serial(p) -> str | None:
    """Windows with FTDI's driver gives no location; its serial is the chip's plus A / B for the interface."""
    sn = getattr(p, "serial_number", None) or ""
    return sn if not p.location and len(sn) > 1 and sn[-1] in "AB" else None


def _iface(p) -> int:
    # Linux/pyserial location looks like "1-1:1.1"; the trailing number is the USB interface.
    if sn := _ftdi_serial(p):
        return "AB".index(sn[-1])
    tail = (p.location or "").rsplit(".", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _chip(p) -> str:
    sn = _ftdi_serial(p)
    return sn[:-1] if sn else (p.location or p.device).split(":")[0]


def find_port(board: BoardInfo, ports=None) -> str:
    link = board.host_link
    if "usb_vid" not in link:
        raise PortNotFound(f"{board.board_id} has no onboard USB-UART; connect an external adapter and {_HINT}")
    if ports is None:
        from serial.tools import list_ports

        ports = list_ports.comports()
    found = [p for p in ports if p.vid == link["usb_vid"] and p.pid == link["usb_pid"]]
    # FT2232-style: all interfaces of one chip share the location prefix; UART is the highest (B side).
    chips = {_chip(p) for p in found}
    # One chip shows each interface once; two ports on one interface are two boards (a shared serial).
    if len(chips) == 1 and len({_iface(p) for p in found}) == len(found):
        return max(found, key=_iface).device
    if not chips:
        raise PortNotFound(
            f"no USB serial port matching {board.board_id} "
            f"({link['usb_vid']:04x}:{link['usb_pid']:04x}) found; connect the board or {_HINT}"
        )
    cands = ", ".join(f"{p.device} ({p.location})" for p in found)
    raise PortNotFound(f"multiple boards match {board.board_id}: {cands}; {_HINT}")

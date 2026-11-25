"""Setup checks for `python -m nanopynq doctor`. Each check returns (ok, message)."""

import os
import shutil
import sys
from collections.abc import Callable, Iterable
from importlib.resources import files
from pathlib import Path
from typing import Any

from nanopynq.boards import BoardInfo, get_board
from nanopynq.errors import PortNotFound, PortOpenError, TransportTimeout
from nanopynq.program import find_openfpgaloader
from nanopynq.transport.jtag import Jtag
from nanopynq.transport.jtag import open_jtag as _open_jtag
from nanopynq.transport.jtagbridge import JTAGBridge
from nanopynq.transport.serialport import find_port

UDEV_DIRS = (Path("/etc/udev/rules.d"), Path("/lib/udev/rules.d"), Path("/usr/lib/udev/rules.d"))
BUILD_TOOLS = ("yowasp-yosys", "yowasp-nextpnr-himbaechel-gowin", "gowin_pack")
OPTIONAL = {"yowasp"}  # reported, but never makes the exit code 1

Check = Callable[[], tuple[bool, str]]


def check_python() -> tuple[bool, str]:
    v = sys.version_info
    if v >= (3, 11):
        return True, f"Python {v.major}.{v.minor}.{v.micro}"
    return False, f"Python {v.major}.{v.minor} is too old; install Python 3.11 or newer"


def check_ofl() -> tuple[bool, str]:
    return True, str(find_openfpgaloader())  # ProgrammerNotFound text already carries the next step


def check_yowasp() -> tuple[bool, str]:
    missing = [t for t in BUILD_TOOLS if not shutil.which(t)]
    if missing:
        return False, "build tools missing (" + ", ".join(missing) + "); to build, run: pip install nanopynq[build]"
    return True, "build tools installed"


def check_udev(dirs: Iterable[str | Path] = UDEV_DIRS) -> tuple[bool, str]:
    rules = [
        r for d in dirs for pat in ("*nanopynq*.rules", "*openfpgaloader*.rules") for r in sorted(Path(d).glob(pat))
    ]
    if rules:
        return True, str(rules[0])
    bundled = files("nanopynq") / "data" / "99-nanopynq.rules"
    return False, (
        f"no udev rule for the board found; run: sudo cp {bundled} /etc/udev/rules.d/ "
        "&& sudo udevadm control --reload-rules && sudo udevadm trigger, then re-plug the board"
    )


def check_port(board: BoardInfo) -> tuple[bool, str]:
    port = find_port(board)
    if sys.platform.startswith("linux") and not os.access(port, os.R_OK | os.W_OK):
        return False, f"{port} is not readable/writable; run: sudo usermod -aG dialout $USER, then log in again"
    return True, port


def check_usb(board: BoardInfo, open_bridge: Callable[[dict[str, Any]], JTAGBridge] | None = None) -> tuple[bool, str]:
    link = board.host_link
    try:
        (open_bridge or JTAGBridge.open)(link).close()
    except (PortNotFound, PortOpenError, TransportTimeout) as e:  # their text carries the next step
        return False, str(e)
    return True, f"JTAG on USB {link['usb_vid']:04x}:{link['usb_pid']:04x} interface 0 opened"


def check_jtag(board: BoardInfo, open_jtag: Callable[[int, int], Jtag] = _open_jtag) -> tuple[bool, str]:
    """Open and close the debugger's JTAG (Interface 0), as programming does; no bridge needed (9K)."""
    link = board.host_link
    try:
        open_jtag(link["usb_vid"], link["usb_pid"]).close()
    except (PortNotFound, PortOpenError, TransportTimeout) as e:  # their text carries the next step
        return False, str(e)
    return True, f"JTAG on USB {link['usb_vid']:04x}:{link['usb_pid']:04x} interface 0 opened"


def check_zadig() -> tuple[bool, str]:
    return True, (
        "nanopynq uses FTDI's driver (D2XX) when 'Interface 0' of the board is not on WinUSB, so Zadig "
        "is optional; it is needed for the WebUSB page and for openFPGALoader (Zadig: replace the driver "
        "of only 'Interface 0' with WinUSB, leave Interface 1, the UART, alone)"
    )


def default_checks(board_id: str) -> dict[str, Check]:
    board = get_board(board_id)
    checks: dict[str, Check] = {"python": check_python}
    if board.programmer["tool"] == "openfpgaloader":
        checks["ofl"] = check_ofl
    checks["yowasp"] = check_yowasp
    if board.host_link["kind"] == "jtag":
        checks["usb"] = lambda: check_usb(board)  # programming and talking both go over JTAG
    else:
        checks["usb"] = lambda: check_jtag(board)  # programming goes over JTAG, talking over the UART
        checks["port"] = lambda: check_port(board)
    if sys.platform == "win32":
        checks["zadig"] = check_zadig
    elif sys.platform.startswith("linux"):
        checks["udev"] = check_udev
    return checks


def run_checks(checks: dict[str, Check]) -> int:
    failed = False
    for name, check in checks.items():
        try:
            ok, msg = check()
        except Exception as e:  # a crashing check is a failed check, not a crashed doctor
            ok, msg = False, f"{type(e).__name__}: {e}"
        if ok:
            print(f"OK {name}: {msg}" if msg else f"OK {name}")
        else:
            print(f"NG {name}: {msg}")
            failed = failed or name not in OPTIONAL
    return 1 if failed else 0

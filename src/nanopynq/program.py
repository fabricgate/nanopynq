import os
import shutil
import subprocess
import sys
from pathlib import Path

from .boards import BoardInfo
from .errors import ProgramError, ProgrammerNotFound
from .gowin import load_sram, read_fs
from .transport.jtag import open_jtag

_ENV = "NANOPYNQ_OPENFPGALOADER"


def _install_hint() -> str:
    if sys.platform == "win32":
        return "Windows (MSYS2): pacman -S mingw-w64-ucrt-x86_64-openFPGALoader"
    return "Linux: sudo apt install openfpgaloader"


def _usb_hint() -> str:
    held = " If a previous Overlay still has the board open, call ol.close() on it first."
    if sys.platform == "win32":
        return "Windows: use Zadig to replace the driver of only 'Interface 0' of the board with WinUSB." + held
    return (
        "Linux: install the udev rule 99-nanopynq.rules (in nanopynq's data folder; "
        "python -m nanopynq doctor prints the command) and re-plug the board." + held
    )


def find_openfpgaloader() -> Path:
    env = os.environ.get(_ENV)
    found = env or shutil.which("openFPGALoader")
    if not found or (env and not Path(env).is_file()):
        raise ProgrammerNotFound(
            "openFPGALoader not found"
            + (f" ({_ENV}={env} is not a file)" if env else "")
            + f". Put it on PATH or set {_ENV} to its full path. {_install_hint()}"
        )
    return Path(found)


def program_sram(board: BoardInfo, bitstream: Path, open_jtag=open_jtag) -> None:
    """Load bitstream into the FPGA's SRAM the way boards.yaml's programmer.tool says: "nanopynq" is
    nanopynq's own Gowin sequence over the debugger's JTAG, "openfpgaloader" runs openFPGALoader.
    Pass programmer=program_sram_openfpgaloader to Overlay to use openFPGALoader for any board."""
    p = board.programmer
    if p["tool"] == "openfpgaloader":
        return program_sram_openfpgaloader(board, bitstream)
    if p["tool"] != "nanopynq":
        raise ValueError(f"{board.board_id}: programmer.tool is {p['tool']!r}; use 'nanopynq' or 'openfpgaloader'")
    data = read_fs(bitstream)  # a bad file fails here, before the USB interface is claimed
    link = board.host_link
    jtag = open_jtag(link["usb_vid"], link["usb_pid"])
    jtag.msb_first = bool(p.get("msb_first", False))  # the 138K Pro's debugger is slow LSB first
    try:
        load_sram(jtag, data, p["idcode"], p["family"])
    finally:
        jtag.close()  # never leave Interface 0 claimed: the bridge or openFPGALoader opens it next


def program_sram_openfpgaloader(board: BoardInfo, bitstream: Path, run=subprocess.run, exe: Path | None = None) -> None:
    exe = exe or find_openfpgaloader()
    cmd = [str(exe), "-b", board.programmer["board"], str(bitstream)]
    r = run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ProgramError(
            f"openFPGALoader failed (exit {r.returncode}):\n{r.stderr}\n{_install_hint()}\n{_usb_hint()}", r.stderr
        )

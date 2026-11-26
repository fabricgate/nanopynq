from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml


@dataclass(frozen=True)
class BoardInfo:
    board_id: str
    device: str
    family: str | None
    pack_device: str
    synth_args: list[str]
    pack_args: list[str]
    programmer: dict[str, Any]
    host_link: dict[str, Any]
    io_voltage: dict[str, float]
    clock_hz: int
    # a UART besides a JTAG host_link (the 20K): {baudrate}; USB IDs from host_link
    uart_link: dict[str, Any] | None = None


def _load() -> dict[str, BoardInfo]:
    raw = yaml.safe_load(files("nanopynq").joinpath("data/boards.yaml").read_text(encoding="utf-8"))
    return {k: BoardInfo(board_id=k, **v) for k, v in raw.items()}


_BOARDS = _load()


def get_board(board_id: str) -> BoardInfo:
    return _BOARDS[board_id]


def list_boards() -> list[str]:
    return sorted(_BOARDS)


def uart_link(board: BoardInfo) -> dict[str, Any] | None:
    """The UART link of the board ({kind, baudrate}): host_link when it is UART, else uart_link; None if neither."""
    if board.host_link["kind"] == "uart":
        return {"kind": "uart", "baudrate": board.host_link["baudrate"]}
    if board.uart_link is not None:
        return {"kind": "uart", "baudrate": board.uart_link["baudrate"]}
    return None


def npq_family(board: BoardInfo) -> str:
    """bitstream.family of a .npq built for the board (spec 5.2)."""
    return str(board.programmer["family"])


def npq_link(board: BoardInfo, kind: str) -> dict[str, Any]:
    """The link of a .npq built for the board (spec 5.2): `kind` with the board's UART baud rate when it is "uart",
    and the USB IDs of its debugger as the file writes them. ValueError when the board lacks what the file needs."""
    link: dict[str, Any] = {"kind": kind}
    if kind == "uart":
        uart = uart_link(board)
        if uart is None:
            raise ValueError(f"{board.board_id}: boards.yaml gives no UART link")
        link["baudrate"] = uart["baudrate"]
    host = board.host_link
    if "usb_vid" not in host or "usb_pid" not in host:
        raise ValueError(f"{board.board_id}: boards.yaml host_link has no usb_vid / usb_pid, which a .npq needs")
    return {**link, "usb_vid": f"0x{host['usb_vid']:04x}", "usb_pid": f"0x{host['usb_pid']:04x}"}

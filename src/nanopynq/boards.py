from dataclasses import dataclass
from importlib.resources import files

import yaml


@dataclass(frozen=True)
class BoardInfo:
    board_id: str
    device: str
    family: str | None
    pack_device: str
    synth_args: list[str]
    pack_args: list[str]
    programmer: dict
    host_link: dict
    io_voltage: dict[str, float]
    clock_hz: int
    uart_link: dict | None = None  # a UART besides a JTAG host_link (the 20K): {baudrate}; USB IDs from host_link


def _load() -> dict[str, BoardInfo]:
    raw = yaml.safe_load(files("nanopynq").joinpath("data/boards.yaml").read_text(encoding="utf-8"))
    return {k: BoardInfo(board_id=k, **v) for k, v in raw.items()}


_BOARDS = _load()


def get_board(board_id: str) -> BoardInfo:
    return _BOARDS[board_id]


def list_boards() -> list[str]:
    return sorted(_BOARDS)


def uart_link(board: BoardInfo) -> dict | None:
    """The UART link of the board ({kind, baudrate}): host_link when it is UART, else uart_link; None if neither."""
    if board.host_link["kind"] == "uart":
        return {"kind": "uart", "baudrate": board.host_link["baudrate"]}
    if board.uart_link is not None:
        return {"kind": "uart", "baudrate": board.uart_link["baudrate"]}
    return None

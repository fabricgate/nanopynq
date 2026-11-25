"""The register buses an overlay reads and writes through: UARTBone (serial) and JTAGBridge (JTAG)."""

from typing import Protocol, overload


class Transport(Protocol):
    """32-bit words at byte addresses. read() without a length returns one word, with a length a list."""

    @overload
    def read(self, addr: int, length: None = None, burst: str = "incr") -> int: ...
    @overload
    def read(self, addr: int, length: int, burst: str = "incr") -> list[int]: ...
    def write(self, addr: int, data: int | list[int], burst: str = "incr") -> None: ...
    def close(self) -> None: ...

"""Host client for the LiteX UARTBone wire protocol (no LiteX dependency)."""

from typing import Protocol, overload

from nanopynq.errors import TransportTimeout

_CMD = {"incr": (0x01, 0x02), "fixed": (0x03, 0x04)}  # burst -> (write, read)


class SerialPort(Protocol):
    """What UARTBone needs of a port: pyserial's Serial, or the browser's port (nanopynq.browser)."""

    def reset_input_buffer(self) -> None: ...
    def write(self, data: bytes, /) -> int | None: ...
    def read(self, size: int, /) -> bytes: ...


class UARTBone:
    def __init__(self, port: SerialPort, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate

    @staticmethod
    def max_write_burst_length(baudrate: int) -> int:
        # LiteX: keep a write frame within the 100 ms * 0.5 bridge timeout.
        return max(1, min(255, (int(0.1 * 0.5 / (10 / baudrate)) - 6) // 4))

    def _frame(self, cmd: int, addr: int, length: int) -> bytes:
        return bytes([cmd, length]) + (addr // 4).to_bytes(4, "big")

    def _check(self, addr: int, burst: str) -> int:
        if addr % 4:
            raise ValueError(f"address 0x{addr:x} is not 4-byte aligned")
        if burst not in _CMD:
            raise ValueError(f"burst must be 'incr' or 'fixed', not {burst!r}")
        return 4 if burst == "incr" else 0

    @overload
    def read(self, addr: int, length: None = None, burst: str = "incr") -> int: ...
    @overload
    def read(self, addr: int, length: int, burst: str = "incr") -> list[int]: ...
    def read(self, addr: int, length: int | None = None, burst: str = "incr") -> int | list[int]:
        step = self._check(addr, burst)
        n = 1 if length is None else length
        if n < 1:
            raise ValueError("length must be >= 1")
        words: list[int] = []
        while len(words) < n:
            k = min(255, n - len(words))
            self.port.reset_input_buffer()
            self.port.write(self._frame(_CMD[burst][1], addr + step * len(words), k))
            buf = b""
            while len(buf) < 4 * k:
                chunk = self.port.read(4 * k - len(buf))
                if not chunk:
                    raise TransportTimeout(4 * k, len(buf))
                buf += chunk
            words += [int.from_bytes(buf[i : i + 4], "big") for i in range(0, 4 * k, 4)]
        return words[0] if length is None else words

    def write(self, addr: int, data: int | list[int], burst: str = "incr") -> None:
        step = self._check(addr, burst)
        words = [data] if isinstance(data, int) else list(data)
        most = self.max_write_burst_length(self.baudrate)
        for i in range(0, len(words), most):
            part = words[i : i + most]
            self.port.reset_input_buffer()
            self.port.write(
                self._frame(_CMD[burst][0], addr + step * i, len(part)) + b"".join(w.to_bytes(4, "big") for w in part)
            )

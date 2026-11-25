"""The Python side of the browser notebook: the pyserial.Serial stand-in nanopynq talks through, and a time.sleep that
the Stop button ends.

Pyodide runs in a Web Worker. `link` is the page's JavaScript over the Web Serial port the user chose; every call
blocks in the Worker and returns its result. It needs open(baudRate), close(), resetInput(), write(bytes) and
read(n, timeoutMs) (bytes-like).

Stop writes SIGINT into Pyodide's interrupt buffer, which Pyodide turns into KeyboardInterrupt in whatever Python runs
next. Not imported from pyodide, so it runs (and is tested) in CPython.
"""

import functools
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from nanopynq.overlay import Overlay

TIMEOUT_MS = 1000  # the timeout nanopynq gives pyserial (overlay._open_serial)
NAP_S = 0.05  # how soon a Stop ends a sleep

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _stop_unwrapped(f: Callable[_P, _R]) -> Callable[_P, _R]:
    """Pyodide reports a KeyboardInterrupt that lands while it converts between Python and JavaScript as an error
    caused by it (ConversionError): raise the KeyboardInterrupt itself, so that a Stop is a Stop to the cell."""

    @functools.wraps(f)
    def call(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return f(*args, **kwargs)
        except Exception as e:
            if isinstance(e.__cause__, KeyboardInterrupt):
                raise e.__cause__ from None
            raise

    return call


class WebSerialPort:
    """What UARTBone uses of pyserial.Serial (write, read, reset_input_buffer), and close."""

    def __init__(self, link: Any, baudrate: int) -> None:
        self._link = link
        try:
            self._open(baudrate)
        except Exception as e:  # Overlay turns an OSError into PortOpenError, with its hint
            raise OSError(str(e)) from e

    @_stop_unwrapped
    def _open(self, baudrate: int) -> None:
        self._link.open(baudrate)

    @_stop_unwrapped
    def reset_input_buffer(self) -> None:
        self._link.resetInput()

    @_stop_unwrapped
    def write(self, data: bytes) -> int:
        self._link.write(data)
        return len(data)

    @_stop_unwrapped
    def read(self, n: int) -> bytes:
        """Like pyserial: at most n bytes, fewer (or none) when the timeout passes."""
        return bytes(self._link.read(n, TIMEOUT_MS))

    @_stop_unwrapped
    def close(self) -> None:
        self._link.close()


def overlay_factory(link: Any) -> Callable[..., Overlay]:
    """Overlay for the page: the board is programmed beforehand (download=False), the port is the one the page chose."""
    return functools.partial(
        Overlay, download=False, port="webserial", open_port=lambda _port, baudrate: WebSerialPort(link, baudrate)
    )


def stoppable_sleep(nap: Callable[[float], None], check: Callable[[], None]) -> Callable[[float], None]:
    """time.sleep for the page: naps of at most NAP_S, then check() raises KeyboardInterrupt after a Stop
    (pyodide.checkInterrupt). Without it a blinking loop does not stop: Pyodide looks at its interrupt buffer only
    every so many bytecodes, and its own time.sleep (asyncio underneath) loses the KeyboardInterrupt. nap(ms) blocks."""

    @_stop_unwrapped
    def sleep(seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            nap(min(left, NAP_S) * 1000)
            check()

    return functools.wraps(time.sleep)(sleep)

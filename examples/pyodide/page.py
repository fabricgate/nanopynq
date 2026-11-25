"""The Python side of the Pyodide page: the pyserial.Serial stand-in nanopynq talks through, and a time.sleep that the
Stop button ends.

`link` is the page's JavaScript (link.mjs) over the Web Serial port the user chose. In mode A (Pyodide in a Worker)
every call blocks in the Worker and returns its result; in mode B (JSPI) open / close / write / read return promises
and `wait` is pyodide.ffi.run_sync. resetInput is synchronous in both.

Stop: mode A writes SIGINT into Pyodide's interrupt buffer, which Pyodide turns into KeyboardInterrupt in whatever
Python runs next. Mode B cannot: under JSPI that is often Pyodide's own asyncio code inside run_sync, which prints the
KeyboardInterrupt and goes on. So in B, `check` (stop_check) raises it, at the start of each transaction and in sleep.
"""

import functools
import time

import nanopynq

TIMEOUT_MS = 1000  # the timeout nanopynq gives pyserial (overlay._open_serial)
NAP_S = 0.05  # how soon a Stop ends a sleep


def _now(x):
    return x


def _nothing():
    pass


def _stop_unwrapped(f):
    """Pyodide reports a KeyboardInterrupt that lands while it converts between Python and JavaScript as an error
    caused by it (ConversionError): raise the KeyboardInterrupt itself, so that a Stop is a Stop to the cell."""

    @functools.wraps(f)
    def call(*args):
        try:
            return f(*args)
        except Exception as e:
            if isinstance(e.__cause__, KeyboardInterrupt):
                raise e.__cause__ from None
            raise

    return call


def stop_check(stopped):
    """Mode B's check: KeyboardInterrupt once Stop was pressed. stopped() is the page's flag, cleared when read."""

    def check() -> None:
        if stopped():
            raise KeyboardInterrupt

    return check


class WebSerialPort:
    """What UARTBone uses of pyserial.Serial (write, read, reset_input_buffer), and close."""

    def __init__(self, link, baudrate: int, wait=_now, check=_nothing):
        self._link, self._wait, self._check = link, wait, check
        try:
            self._open(baudrate)
        except Exception as e:  # Overlay turns an OSError into PortOpenError, with its hint
            raise OSError(str(e)) from e

    @_stop_unwrapped
    def _open(self, baudrate: int) -> None:
        self._wait(self._link.open(baudrate))

    @_stop_unwrapped
    def reset_input_buffer(self) -> None:
        self._check()  # UARTBone starts every transaction here: a Stop never leaves an answer on its way
        self._link.resetInput()

    @_stop_unwrapped
    def write(self, data: bytes) -> int:
        self._wait(self._link.write(data))
        return len(data)

    @_stop_unwrapped
    def read(self, n: int) -> bytes:
        """Like pyserial: at most n bytes, fewer (or none) when the timeout passes."""
        return bytes(self._wait(self._link.read(n, TIMEOUT_MS)))

    @_stop_unwrapped
    def close(self) -> None:
        self._wait(self._link.close())


def overlay_factory(link, wait=_now, check=_nothing):
    """Overlay for the page: the board is programmed beforehand (download=False), the port is the one the page chose."""
    return functools.partial(
        nanopynq.Overlay,
        download=False,
        port="webserial",
        open_port=lambda _port, baudrate: WebSerialPort(link, baudrate, wait, check),
    )


def stoppable_sleep(nap, check, wait=_now):
    """time.sleep for the page: naps of at most NAP_S, then check() raises KeyboardInterrupt after a Stop
    (pyodide.checkInterrupt in mode A, stop_check in mode B). Without it a blinking loop does not stop: Pyodide looks
    at its interrupt buffer only every so many bytecodes, and its own time.sleep (asyncio underneath) loses the
    KeyboardInterrupt. nap(ms) blocks (mode A) or returns a promise for `wait` (mode B)."""

    @_stop_unwrapped
    def sleep(seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            wait(nap(min(left, NAP_S) * 1000))
            check()

    return functools.wraps(time.sleep)(sleep)

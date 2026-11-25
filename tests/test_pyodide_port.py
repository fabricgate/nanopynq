"""examples/pyodide/page.py, the Python side of the Pyodide page, in CPython with a fake page link."""

import importlib.util

import pytest

from nanopynq.errors import BoardNotResponding, PortOpenError, TransportTimeout
from nanopynq.transport.uartbone import UARTBone
from tests.fakes import FakeUARTBoneDevice
from tests.jsrun import ROOT

_spec = importlib.util.spec_from_file_location("page", ROOT / "examples" / "pyodide" / "page.py")
page = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(page)
WebSerialPort, overlay_factory, stoppable_sleep, stop_check = (
    page.WebSerialPort,
    page.overlay_factory,
    page.stoppable_sleep,
    page.stop_check,
)

BAUD = 115200
# word address -> value: sysinfo 1.1 of the bundled tangnano9k-base (sys.id, sys.version, sys.design_id)
BOARD = {0: 0x4E505131, 1: 0x00010001, 3: 0xABF78D8C}


class FakeLink:
    """The page's link as mode A gives it to Python: every call returns its result."""

    def __init__(self, dev: FakeUARTBoneDevice, fail_open: bool = False):
        self.dev, self.fail_open, self.calls = dev, fail_open, []

    def open(self, baud):
        self.calls.append(("open", baud))
        if self.fail_open:
            raise RuntimeError("Failed to open serial port.")

    def close(self):
        self.calls.append(("close",))

    def resetInput(self):
        self.dev.reset_input_buffer()

    def write(self, data):
        self.dev.write(bytes(data))

    def read(self, n, timeout_ms):
        return self.dev.read(n)  # in the browser a Uint8Array of at most n bytes, empty after the timeout


def test_uartbone_puts_the_same_bytes_on_the_wire_as_over_pyserial():
    ref = FakeUARTBoneDevice(dict(BOARD))
    UARTBone(ref, BAUD).read(0x0)
    UARTBone(ref, BAUD).write(0x1000, [1, 2, 3])

    dev = FakeUARTBoneDevice(dict(BOARD))
    bone = UARTBone(WebSerialPort(FakeLink(dev), BAUD), BAUD)
    assert bone.read(0x0) == 0x4E505131
    bone.write(0x1000, [1, 2, 3])
    assert dev.received == ref.received


def test_a_silent_board_is_a_transport_timeout():
    port = WebSerialPort(FakeLink(FakeUARTBoneDevice(dict(BOARD), truncate_after=2)), BAUD)
    with pytest.raises(TransportTimeout):
        UARTBone(port, BAUD).read(0x0)


def test_mode_b_waits_on_every_call_that_returns_a_promise():
    """In mode B the link returns promises and wait is pyodide.ffi.run_sync; resetInput is synchronous there."""
    made, waited = [], []

    class Promised:
        def __init__(self, value):
            self.value = value
            made.append(self)

    class PromiseLink(FakeLink):
        def open(self, baud):
            return Promised(super().open(baud))

        def close(self):
            return Promised(super().close())

        def write(self, data):
            return Promised(super().write(data))

        def read(self, n, timeout_ms):
            return Promised(super().read(n, timeout_ms))

    def wait(p):
        assert isinstance(p, Promised), f"waited on {p!r}, not a promise"
        waited.append(p)
        return p.value

    link = PromiseLink(FakeUARTBoneDevice(dict(BOARD)))
    port = WebSerialPort(link, BAUD, wait)
    bone = UARTBone(port, BAUD)
    assert bone.read(0x0) == 0x4E505131
    bone.write(0x1000, 1)
    port.close()
    assert len(made) == 5 and waited == made  # open, write + read, write, close: each one waited on, in order


def test_a_stop_while_python_crosses_into_javascript_is_a_keyboard_interrupt():
    """Pyodide raises a KeyboardInterrupt that lands while it converts an argument as a ConversionError from it."""

    class ConversionError(Exception):  # pyodide.ffi.ConversionError
        pass

    class StopInConversion(FakeLink):
        def write(self, data):
            raise ConversionError("could not convert") from KeyboardInterrupt()

    port = WebSerialPort(StopInConversion(FakeUARTBoneDevice(dict(BOARD))), BAUD)
    with pytest.raises(KeyboardInterrupt):
        UARTBone(port, BAUD).write(0x1000, 1)


def test_the_page_overlay_drives_the_board_without_programming_it():
    dev = FakeUARTBoneDevice({**BOARD, 0x2000 // 4: 0b10})
    link = FakeLink(dev)
    Overlay = overlay_factory(link)
    ol = Overlay("base", board="tangnano9k")
    ol.leds[0].on()
    assert dev.regs[0x1000 // 4] == 1
    assert [ol.buttons[0].read(), ol.buttons[1].read()] == [0, 1]
    ol.close()
    assert link.calls == [("open", BAUD), ("close",)]  # opened at the design's baud rate, closed by Overlay.close


def test_a_port_that_does_not_open_is_overlays_port_open_error():
    with pytest.raises(PortOpenError, match="Failed to open serial port"):
        overlay_factory(FakeLink(FakeUARTBoneDevice(), fail_open=True))("base", board="tangnano9k")


def test_a_board_that_does_not_answer_is_board_not_responding(monkeypatch):
    monkeypatch.setattr("nanopynq.overlay._sleep", lambda s: None)
    link = FakeLink(FakeUARTBoneDevice(truncate_after=0))
    with pytest.raises(BoardNotResponding):
        overlay_factory(link)("base", board="tangnano9k")
    assert link.calls[-1] == ("close",)


@pytest.fixture
def clock(monkeypatch):
    """A monotonic clock that moves only when a nap says so. The real one is too coarse for these tests on Windows
    (GetTickCount64, 15.6 ms steps): a 50 ms nap could read as 62.5 ms and end the sleep a nap early (#69)."""
    now = [0.0]
    monkeypatch.setattr(page.time, "monotonic", lambda: now[0])

    def advance(ms):
        now[0] += ms / 1000

    return advance


def test_sleep_waits_in_short_naps_and_looks_for_stop_after_each(clock):
    naps, checks = [], []

    def nap(ms):
        naps.append(ms)
        clock(ms)

    stoppable_sleep(nap, lambda: checks.append(1))(0.12)
    assert naps == pytest.approx([50, 50, 20])
    assert len(checks) == len(naps)


def test_sleep_ends_at_the_first_stop():
    naps = []

    def stop():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        stoppable_sleep(naps.append, stop)(10)
    assert len(naps) == 1


def test_sleep_in_mode_b_waits_on_the_promise_of_each_nap(clock):
    waited = []

    def wait(promise):
        waited.append(promise)
        clock(promise[1])

    stoppable_sleep(lambda ms: ("promise", ms), lambda: None, wait)(0.06)
    assert [p[0] for p in waited] == ["promise", "promise"]
    assert [p[1] for p in waited] == pytest.approx([50, 10])


def test_sleep_refuses_a_negative_time_as_time_sleep_does():
    with pytest.raises(ValueError):
        stoppable_sleep(lambda ms: None, lambda: None)(-1)


def test_mode_b_stops_between_transactions_never_inside_one():
    """An answer still on its way would be read by the next transaction as its own: Stop waits for the transaction."""
    stop = []
    dev = FakeUARTBoneDevice(dict(BOARD))

    class StopDuringWrite(FakeLink):
        def write(self, data):
            super().write(data)
            stop.append(1)  # Stop pressed while the board answers

    bone = UARTBone(WebSerialPort(StopDuringWrite(dev), BAUD, check=stop_check(lambda: bool(stop))), BAUD)
    assert bone.read(0x0) == 0x4E505131  # the transaction under way finishes
    with pytest.raises(KeyboardInterrupt):
        bone.read(0x0)
    assert dev.frames == 1  # the next one does not start


def test_stop_check_raises_once_per_stop():
    flags = [True, False]
    check = stop_check(lambda: flags.pop(0))
    with pytest.raises(KeyboardInterrupt):
        check()
    check()  # cleanup code in an except KeyboardInterrupt still runs

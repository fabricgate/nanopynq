"""nanopynq.browser, the Python side of the browser notebook (Pyodide in a Worker), in CPython with a fake link."""

import pytest

from nanopynq.browser import WebSerialPort, overlay_factory, stoppable_sleep
from nanopynq.errors import BoardNotResponding, PortOpenError, TransportTimeout
from nanopynq.transport.uartbone import UARTBone
from tests.fakes import FakeUARTBoneDevice
from tests.test_overlay_npq import _npq

BAUD = 115200
# word address -> value: sysinfo 1.1 of the bundled tangnano9k-base (sys.id, sys.version, sys.design_id)
BOARD = {0: 0x4E505131, 1: 0x00010001, 3: 0xABF78D8C}


class FakeLink:
    """The page's link as the Worker gives it to Python: every call returns its result."""

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


def test_the_page_overlay_opens_from_an_npq_alone(tmp_path):
    _npq(tmp_path)
    (tmp_path / "base.fs").unlink()  # the page has no bitstream: the board is programmed beforehand
    ol = overlay_factory(FakeLink(FakeUARTBoneDevice(dict(BOARD))))(tmp_path / "base.npq")
    assert ol.leds is not None


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
    monkeypatch.setattr("nanopynq.browser.time.monotonic", lambda: now[0])

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


def test_sleep_refuses_a_negative_time_as_time_sleep_does():
    with pytest.raises(ValueError):
        stoppable_sleep(lambda ms: None, lambda: None)(-1)

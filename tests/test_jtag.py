"""transport/jtag.py open_jtag: libusb first, then (Windows only) FTDI's D2XX."""

import sys

import pytest

from nanopynq.errors import PortNotFound, PortOpenError
from nanopynq.transport import d2xx, jtag, mpsse


@pytest.fixture
def paths(monkeypatch):
    """Replace both openers; `paths.libusb` / `paths.d2xx` are what each returns or raises."""
    calls = []

    class Paths:
        libusb = "libusb"
        d2xx = "d2xx"

    def opener(name):
        def open_(cls, vid, pid, *rest):
            calls.append(name)
            result = getattr(Paths, name)
            if isinstance(result, Exception):
                raise result
            return result

        return classmethod(open_)

    monkeypatch.setattr(mpsse.Mpsse, "open", opener("libusb"))
    monkeypatch.setattr(d2xx.D2xxMpsse, "open", opener("d2xx"))
    Paths.calls = calls
    return Paths


def test_open_jtag_prefers_libusb(paths, monkeypatch):  # Review Focus 2
    monkeypatch.setattr(sys, "platform", "win32")
    assert jtag.open_jtag(0x0403, 0x6010) == "libusb"
    assert paths.calls == ["libusb"]


def test_open_jtag_falls_back_to_d2xx_on_windows(paths, monkeypatch):
    # On FTDI's driver libusb finds the board but cannot open it ("Entity not found"): a PortOpenError.
    monkeypatch.setattr(sys, "platform", "win32")
    paths.libusb = PortOpenError("Entity not found")
    assert jtag.open_jtag(0x0403, 0x6010) == "d2xx"
    assert paths.calls == ["libusb", "d2xx"]


@pytest.mark.parametrize(
    "err",
    [
        PortNotFound("no USB device 0403:6010 found"),
        PortNotFound("multiple boards 0403:6010 connected (A1, B2); connect only one"),
    ],
)
def test_open_jtag_does_not_fall_back_when_libusb_finds_none_or_several(paths, monkeypatch, err):
    # libusb counts every 0403:6010 whatever its driver. With none there is nothing for D2XX either; with two (one
    # on WinUSB, one on FTDI's driver) D2XX would silently open the one on FTDI's driver.
    monkeypatch.setattr(sys, "platform", "win32")
    paths.libusb = err
    with pytest.raises(PortNotFound, match="0403:6010"):
        jtag.open_jtag(0x0403, 0x6010)
    assert paths.calls == ["libusb"]


def test_open_jtag_reports_libusb_error_when_d2xx_has_nothing(paths, monkeypatch):  # Review Focus 3
    monkeypatch.setattr(sys, "platform", "win32")
    paths.libusb = PortOpenError("libusb says: use Zadig")
    paths.d2xx = PortNotFound("no D2XX device")
    with pytest.raises(PortOpenError, match="libusb says"):
        jtag.open_jtag(0x0403, 0x6010)


def test_open_jtag_passes_d2xx_port_open_error(paths, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    paths.libusb = PortOpenError("libusb")
    paths.d2xx = PortOpenError("open in another program")
    with pytest.raises(PortOpenError, match="another program"):
        jtag.open_jtag(0x0403, 0x6010)


def test_open_jtag_no_fallback_off_windows(paths, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    paths.libusb = PortOpenError("busy")
    with pytest.raises(PortOpenError, match="busy"):
        jtag.open_jtag(0x0403, 0x6010)
    assert paths.calls == ["libusb"]


def test_open_jtag_with_an_injected_find_never_tries_d2xx(paths, monkeypatch):
    # find= is the seam tests use for a fake USB bus: falling back would reach a real board on FTDI's driver.
    monkeypatch.setattr(sys, "platform", "win32")
    paths.libusb = PortNotFound("no device on the fake bus")
    with pytest.raises(PortNotFound, match="fake bus"):
        jtag.open_jtag(0x0403, 0x6010, find=lambda **kw: [])
    assert paths.calls == ["libusb"]

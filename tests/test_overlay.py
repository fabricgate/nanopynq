import sys

import pytest

import nanopynq.overlay as overlay_mod
from nanopynq import DefaultIP, Overlay
from nanopynq.drivers.gpio import GPIOOut
from nanopynq.errors import BoardNotResponding, ManifestError, PortOpenError
from nanopynq.transport.jtagbridge import JTAGBridge
from tests.fakes import FakeJtagBridgeDevice, FakeUARTBoneDevice


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(overlay_mod, "_sleep", calls.append)
    return calls


def test_overlay_programs_then_opens_port_then_checks_id(tmp_design):
    order = []
    dev = FakeUARTBoneDevice({0: 0x4E505131})
    ol = Overlay(
        tmp_design,
        programmer=lambda b, f: order.append("program"),
        open_port=lambda p, baud: order.append("open") or dev,
        port="X",
    )
    assert order == ["program", "open"]
    ol.leds[0].on()
    assert dev.regs[0x1000 // 4] == 1


def test_programmer_receives_board_and_bitstream(tmp_design):
    got = []
    Overlay(
        tmp_design,
        programmer=lambda b, f: got.append((b.board_id, f)),
        port="X",
        open_port=lambda p, baud: FakeUARTBoneDevice({0: 0x4E505131}),
    )
    assert got == [("tangnano9k", (tmp_design / "base.fs").resolve())]


def test_download_false_skips_programming(tmp_design):
    Overlay(
        tmp_design,
        download=False,
        programmer=pytest.fail,
        port="X",
        open_port=lambda p, baud: FakeUARTBoneDevice({0: 0x4E505131}),
    )


def test_open_port_gets_port_and_baudrate(tmp_design):
    seen = []
    Overlay(
        tmp_design,
        download=False,
        port="COM9",
        open_port=lambda p, baud: seen.append((p, baud)) or FakeUARTBoneDevice({0: 0x4E505131}),
    )
    assert seen == [("COM9", 115200)]


def test_sha256_mismatch_refuses_to_program(tmp_design):  # Review Focus 4
    (tmp_design / "base.fs").write_bytes(b"tampered")
    with pytest.raises(ManifestError, match="sha256"):
        Overlay(tmp_design, programmer=pytest.fail, port="X", open_port=pytest.fail)


def test_missing_bitstream_refuses(tmp_design):  # Review Focus 4
    (tmp_design / "base.fs").unlink()
    with pytest.raises(ManifestError, match="not found"):
        Overlay(tmp_design, programmer=pytest.fail, port="X", open_port=pytest.fail)


def test_wrong_id_raises_board_not_responding_with_replug_hint(tmp_design, sleeps):  # Review Focus 1
    dev = FakeUARTBoneDevice({0: 0})
    with pytest.raises(BoardNotResponding, match=r"抜き差し|replug") as e:
        Overlay(tmp_design, programmer=lambda b, f: None, port="X", open_port=lambda p, b: dev)
    msg = str(e.value)
    assert "then run Overlay(...) again" in msg and "re-programs" in msg
    assert "reopen with Overlay(..., download=False)" not in msg  # replug erases SRAM: download=False cannot recover
    assert "download=False is only for reopening within the same power cycle" in msg
    assert sleeps == [0.5, 0.5]  # 3 attempts, 0.5 s apart


def test_silent_port_does_not_hang(tmp_design):  # Review Focus 1
    dev = FakeUARTBoneDevice({0: 0x4E505131}, truncate_after=0)
    dev.breaks = []
    dev.send_break = dev.breaks.append
    with pytest.raises(BoardNotResponding, match="no response"):
        Overlay(tmp_design, programmer=lambda b, f: None, port="X", open_port=lambda p, b: dev)
    assert dev.frames == 3  # each of the 3 attempts sent one read frame
    assert dev.breaks == [0.2]  # only after the first attempt


def test_id_retry_succeeds_on_later_attempt(tmp_design):
    class Flaky(FakeUARTBoneDevice):
        def read(self, n):
            self.reads = getattr(self, "reads", 0) + 1
            return b"" if self.reads == 1 else super().read(n)

    Overlay(tmp_design, download=False, port="X", open_port=lambda p, b: Flaky({0: 0x4E505131}))


def test_a_break_wakes_a_uart_that_is_silent_after_plugging_in(tmp_design):
    class SilentUntilBreak(FakeUARTBoneDevice):
        def send_break(self, duration):
            self.breaks.append(duration)

        def read(self, n):
            return super().read(n) if self.breaks else b""

    dev = SilentUntilBreak({0: 0x4E505131})
    dev.breaks = []
    Overlay(tmp_design, download=False, port="X", open_port=lambda p, b: dev)
    assert dev.breaks == [0.2] and dev.frames == 2  # one break after the first unanswered request, then it answers


def test_base_without_board_lists_boards():
    with pytest.raises(ValueError, match="tangnano9k"):
        Overlay("base")


def test_board_taken_from_manifest_and_mismatch_rejected(tmp_design):
    def mk(**kw):
        return Overlay(
            tmp_design, download=False, port="X", open_port=lambda p, b: FakeUARTBoneDevice({0: 0x4E505131}), **kw
        )

    assert mk().board.board_id == "tangnano9k"
    with pytest.raises(ManifestError, match="tangnano4k"):
        mk(board="tangnano4k")


def test_explicit_transport_skips_port(tmp_design):
    from tests.fakes import FakeTransport

    t = FakeTransport({0: 0x4E505131})
    ol = Overlay(tmp_design, download=False, transport=t, open_port=pytest.fail)
    ol.leds[1].on()
    assert t.regs[0x1000] == 2


def test_getattr_dispatch_cache_and_dir(tmp_design):
    ol = Overlay(tmp_design, download=False, port="X", open_port=lambda p, b: FakeUARTBoneDevice({0: 0x4E505131}))
    assert isinstance(ol.leds, GPIOOut) and ol.leds is ol.leds
    assert type(ol.sys) is DefaultIP
    assert set(ol.ip_dict) == {"sys", "leds", "buttons"}
    assert {"leds", "buttons", "sys"} <= set(dir(ol))
    with pytest.raises(AttributeError):
        _ = ol.nope


def test_close_closes_port(tmp_design):
    dev = FakeUARTBoneDevice({0: 0x4E505131})
    closed = []
    dev.close = lambda: closed.append(1)
    ol = Overlay(tmp_design, download=False, port="X", open_port=lambda p, b: dev)
    ol.close()
    ol.close()
    assert closed == [1]


def test_port_closed_when_id_check_fails(tmp_design):
    dev = FakeUARTBoneDevice({0: 0})
    closed = []
    dev.close = lambda: closed.append(1)
    with pytest.raises(BoardNotResponding):
        Overlay(tmp_design, download=False, port="X", open_port=lambda p, b: dev)
    assert closed == [1]


def test_repr_lists_ips(tmp_design):
    ol = Overlay(tmp_design, download=False, port="X", open_port=lambda p, b: FakeUARTBoneDevice({0: 0x4E505131}))
    r = repr(ol)
    assert "leds" in r and "nanopynq:gpio_out:1.0" in r and "0x1000" in r


def _raising_open(p, b):
    import serial

    raise serial.SerialException(f"could not open port {p!r}: PermissionError(13, 'Access is denied.')")


@pytest.mark.parametrize("platform, hint", [("win32", "ol.close()"), ("linux", "usermod -aG dialout")])
def test_port_open_failure_gives_os_specific_guidance(tmp_design, monkeypatch, platform, hint):
    monkeypatch.setattr(sys, "platform", platform)
    with pytest.raises(PortOpenError, match="Access is denied") as e:
        Overlay(tmp_design, download=False, port="COM9", open_port=_raising_open)
    assert hint in str(e.value) and "COM9" in str(e.value)


def test_context_manager_closes_port(tmp_design):
    dev = FakeUARTBoneDevice({0: 0x4E505131})
    closed = []
    dev.close = lambda: closed.append(1)
    with Overlay(tmp_design, download=False, port="X", open_port=lambda p, b: dev) as ol:
        assert ol.leds is not None
        assert closed == []
    assert closed == [1]


def test_uninitialised_overlay_does_not_recurse():
    ol = Overlay.__new__(Overlay)
    with pytest.raises(AttributeError):
        _ = ol.manifest
    with pytest.raises(AttributeError):
        _ = ol.leds
    with pytest.raises(AttributeError):
        repr(ol)  # not RecursionError


def test_jtag_board_programs_then_opens_bridge(tmp_design_4k):
    order, dev = [], FakeJtagBridgeDevice({0: 0x4E505131})
    ol = Overlay(
        tmp_design_4k,
        programmer=lambda b, f: order.append("program"),
        open_port=pytest.fail,
        open_jtag=lambda link: order.append(("open", link["kind"])) or JTAGBridge(dev),
    )
    assert order == ["program", ("open", "jtag")]
    ol.leds[0].on()
    assert dev.regs[0x1000 // 4] == 1


def test_jtag_bad_response_gives_jtag_specific_hint(tmp_design_4k, sleeps):  # Review Focus 4
    dev = FakeJtagBridgeDevice({0: 0x4E505131}, ignore_ir=True)
    with pytest.raises(BoardNotResponding) as e:
        Overlay(tmp_design_4k, programmer=lambda b, f: None, open_jtag=lambda link: JTAGBridge(dev))
    msg = str(e.value)
    assert "replug" in msg and "JTAG and UART" not in msg and "0xFFFFFFFFFFFFFFFF" in msg
    assert sleeps == [0.5, 0.5]
    assert dev.closed == 1


def test_jtag_silent_device_does_not_hang(tmp_design_4k):  # Review Focus 1
    with pytest.raises(BoardNotResponding, match="no response"):
        Overlay(
            tmp_design_4k,
            programmer=lambda b, f: None,
            open_jtag=lambda link: JTAGBridge(FakeJtagBridgeDevice(silent=True)),
        )


def test_jtag_open_errors_pass_through(tmp_design_4k):
    def boom(link):
        raise PortOpenError("held: ol.close()")

    with pytest.raises(PortOpenError):
        Overlay(tmp_design_4k, programmer=lambda b, f: None, open_jtag=boom)


def test_close_releases_bridge(tmp_design_4k):
    dev = FakeJtagBridgeDevice({0: 0x4E505131})
    ol = Overlay(tmp_design_4k, download=False, open_jtag=lambda link: JTAGBridge(dev))
    ol.close()
    ol.close()
    assert dev.closed == 1


def test_uart_board_never_opens_jtag(tmp_design):  # Review Focus 5
    Overlay(
        tmp_design,
        download=False,
        port="X",
        open_jtag=pytest.fail,
        open_port=lambda p, b: FakeUARTBoneDevice({0: 0x4E505131}),
    )


def test_importing_nanopynq_does_not_import_usb():  # Review Focus 5
    import subprocess

    r = subprocess.run(
        [sys.executable, "-c", "import nanopynq, sys; print('usb' in sys.modules)"], capture_output=True, text=True
    )
    assert r.stdout.strip() == "False", r.stderr


def test_jtag_unexpected_error_during_id_check_releases_bridge(tmp_design_4k):  # Review Focus 2
    class Interrupted(FakeJtagBridgeDevice):
        def flush(self):
            if self.flushes:  # reset() passes, the ID read is interrupted
                raise KeyboardInterrupt
            return super().flush()

    dev = Interrupted({0: 0x4E505131})
    with pytest.raises(KeyboardInterrupt):
        Overlay(tmp_design_4k, programmer=lambda b, f: None, open_jtag=lambda link: JTAGBridge(dev))
    assert dev.closed == 1

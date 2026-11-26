from nanopynq.__main__ import main
from nanopynq.boards import get_board
from nanopynq.doctor import check_jtag, check_udev, default_checks
from tests.fakes import FakeGowinDevice

NAMES = ["python", "ofl", "yowasp", "usb", "port", "udev", "zadig"]


def all_ok_checks():
    return {n: (lambda n=n: (True, f"{n} ok")) for n in NAMES}


def checks_with(**ng):
    """Replace checks by keyword: `name=None` makes it fail, `name=callable` overrides it."""
    checks = all_ok_checks()
    for name, fn in ng.items():
        checks[name] = (lambda n=name: (False, f"fix {n}")) if fn is None else fn
    return checks


def test_all_ok_exit_0(capsys):
    assert main(["doctor"], checks=all_ok_checks()) == 0
    out = capsys.readouterr().out
    assert "NG" not in out
    assert "OK python" in out


def test_missing_ofl_reports_ng_with_hint_exit_1(capsys):
    assert main(["doctor"], checks=checks_with(ofl=None)) == 1
    assert "NG ofl: fix ofl" in capsys.readouterr().out


def test_missing_port_exit_1(capsys):
    assert main(["doctor"], checks=checks_with(port=None)) == 1
    assert "NG port" in capsys.readouterr().out


def test_optional_yowasp_ng_is_reported_but_exit_0(capsys):
    assert main(["doctor"], checks=checks_with(yowasp=None)) == 0
    assert "NG yowasp: fix yowasp" in capsys.readouterr().out


def test_check_exception_becomes_ng(capsys):
    def boom():
        raise RuntimeError("kaput")

    assert main(["doctor"], checks=checks_with(ofl=boom)) == 1
    assert "NG ofl: RuntimeError: kaput" in capsys.readouterr().out


def test_default_checks_run_without_crashing(capsys):
    # Real environment: result varies, but every line is OK/NG and the exit code is 0 or 1.
    assert main(["doctor"]) in (0, 1)
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("OK python") for line in lines)
    assert all(line.split()[0] in ("OK", "NG") or line.startswith(" ") for line in lines if line)


def test_unknown_board_rejected():
    import pytest

    with pytest.raises(SystemExit):
        main(["doctor", "--board", "nope"])


def test_udev_ok_if_rule_in_any_dir(tmp_path):
    from nanopynq.doctor import check_udev

    etc, lib = tmp_path / "etc", tmp_path / "lib"
    etc.mkdir()
    lib.mkdir()
    ok, msg = check_udev([etc, lib])
    assert not ok and "99-nanopynq.rules /etc/udev/rules.d/" in msg and msg.count("sudo cp ") == 1
    assert "udevadm control --reload-rules && sudo udevadm trigger" in msg
    (lib / "60-openfpgaloader.rules").write_text("")
    ok, msg = check_udev([etc, tmp_path / "missing", lib])
    assert ok and "60-openfpgaloader.rules" in msg


def test_ofl_check_ng_when_env_path_missing(monkeypatch, tmp_path):
    from nanopynq.doctor import check_ofl, run_checks

    monkeypatch.setenv("NANOPYNQ_OPENFPGALOADER", str(tmp_path / "nope"))
    assert run_checks({"ofl": check_ofl}) == 1


def test_port_check_ng_without_access_on_linux(monkeypatch):
    import os
    import sys

    import nanopynq.doctor as doctor
    from nanopynq.boards import get_board

    monkeypatch.setattr(doctor, "find_port", lambda board: "/dev/ttyUSB1")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "access", lambda p, mode: False)
    ok, msg = doctor.check_port(get_board("tangnano9k"))
    assert not ok and "dialout" in msg
    monkeypatch.setattr(os, "access", lambda p, mode: True)
    assert doctor.check_port(get_board("tangnano9k")) == (True, "/dev/ttyUSB1")


def test_jtag_board_checks_usb_not_port():
    from nanopynq.doctor import default_checks

    checks = default_checks("tangnano4k")
    assert "usb" in checks and "port" not in checks
    assert "port" in default_checks("tangnano9k")


def test_check_usb_opens_and_closes_bridge():
    from nanopynq.boards import get_board
    from nanopynq.doctor import check_usb

    closed = []

    class Bridge:
        def close(self):
            closed.append(1)

    ok, msg = check_usb(get_board("tangnano4k"), open_bridge=lambda link: Bridge())
    assert ok and "0403:6010" in msg and closed == [1]


def test_check_usb_reports_open_error_text():
    from nanopynq.boards import get_board
    from nanopynq.doctor import check_usb
    from nanopynq.errors import PortOpenError

    def boom(link):
        raise PortOpenError("held by another Overlay: ol.close()")

    ok, msg = check_usb(get_board("tangnano4k"), open_bridge=boom)
    assert not ok and "ol.close()" in msg


def test_udev_accepts_nanopynq_rule(tmp_path):
    (tmp_path / "99-nanopynq.rules").write_text("x")
    assert check_udev(dirs=(tmp_path,))[0]


def test_udev_still_accepts_openfpgaloader_rule(tmp_path):
    (tmp_path / "99-openfpgaloader.rules").write_text("x")
    assert check_udev(dirs=(tmp_path,))[0]


def test_udev_says_when_no_installed_rule_frees_the_jtag_interface_for_a_browser(tmp_path):
    from importlib.resources import files

    old = "99-nanopynq.rules"  # a copy from before the unbind rule, or openFPGALoader's rule alone
    (tmp_path / old).write_text('ACTION=="add", ATTRS{idVendor}=="0403", MODE="0664"\n')
    ok, msg = check_udev(dirs=(tmp_path,))
    assert ok  # Python needs no more than the access rule: the exit code stays 0
    assert "from a browser" in msg and msg.count("sudo cp ") == 1 and "re-plug" in msg
    current = (files("nanopynq") / "data" / "99-nanopynq.rules").read_text(encoding="utf-8")
    (tmp_path / old).write_text(current)
    assert check_udev(dirs=(tmp_path,)) == (True, str(tmp_path / old))
    # an unreadable or odd file is not a crash
    (tmp_path / old).write_bytes(b"\xff\xfe")
    assert check_udev(dirs=(tmp_path,))[0]


def test_udev_missing_points_to_bundled_rule(tmp_path):
    ok, msg = check_udev(dirs=(tmp_path,))
    assert not ok and "99-nanopynq.rules" in msg


def test_default_checks_have_no_ofl_for_nanopynq_tool():
    for b in ("tangnano9k", "tangnano4k", "tangnano20k"):
        assert "ofl" not in default_checks(b) and "usb" in default_checks(b)


def test_9k_usb_check_opens_jtag_not_bridge():
    calls = []
    dev = FakeGowinDevice()
    ok, _ = check_jtag(get_board("tangnano9k"), open_jtag=lambda vid, pid: calls.append((vid, pid)) or dev)
    assert ok and calls == [(0x0403, 0x6010)] and dev.closed == 1


def test_zadig_is_only_for_webusb_and_openfpgaloader():
    from nanopynq.doctor import check_zadig

    ok, msg = check_zadig()
    assert ok and "WebUSB" in msg and "openFPGALoader" in msg and "D2XX" in msg


def test_bundled_rule_unbinds_the_serial_driver_from_the_jtag_interface_only():
    """#7: a browser (WebUSB) cannot open Interface 0 while ftdi_sio holds it. Interface 1 is the UART."""
    from importlib.resources import files

    lines = (files("nanopynq") / "data" / "99-nanopynq.rules").read_text(encoding="utf-8").splitlines()
    rules = [ln for ln in lines if ln and not ln.startswith("#")]
    (access,) = [ln for ln in rules if "RUN+=" not in ln]
    (unbind,) = [ln for ln in rules if "RUN+=" in ln]
    assert 'MODE="0664"' in access and 'TAG+="uaccess"' in access and "bInterfaceNumber" not in access
    for key in (
        'ACTION=="bind"',
        'DRIVER=="ftdi_sio"',
        'ATTR{bInterfaceNumber}=="00"',  # the interface itself, not a parent: Interface 1 never matches
        'ATTRS{idVendor}=="0403"',
        'ATTRS{idProduct}=="6010"',
        'ATTRS{manufacturer}=="SIPEED"',  # not every FT2232 adapter
        'ATTRS{product}=="JTAG Debugger|USB Debugger"',  # the Tang boards' debuggers (9K, 4K | 20K, 138K Pro)
    ):
        assert key in unbind, key
    assert unbind.endswith("""RUN+="/bin/sh -c 'echo %k > /sys/bus/usb/drivers/ftdi_sio/unbind'\"""")

"""tools/switch_iface0_driver.ps1: which INF it picks for Interface 0 (the part that runs without admin)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "switch_iface0_driver.ps1"
SHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not SHELL, reason="Windows PowerShell script")

ZADIG = """[Version]
Provider    = "libwdi"
[Devices]
%DeviceName% = USB_Install, USB\\{id}
[Strings]
DeviceID   = "{id}"
[USB_Install.Services]
Include    = winusb.inf
AddService = WinUSB,0x00000002,WinUSB_ServiceInstall
"""
FTDI = """[Version]
Provider=%FTDI%
[FtdiHw.NTamd64]
%USB\\VID_0403&PID_6010&MI_00.DeviceDesc%=FtdiBus.NTamd64,USB\\VID_0403&PID_6010&MI_00
[FtdiBus.NTamd64.Services]
AddService = FTDIBUS, 0x00000002, FtdiBus.NT.AddService, FtdiBus.NT.EventLog_Inst
"""


def find(infdir, service):
    cmd = f". '{SCRIPT}'; (Find-Iface0Inf {service} '{infdir}').Name"
    r = subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_picks_newest_winusb_and_the_ftdi_inf_for_interface0(tmp_path):
    files = {
        "oem1.inf": ZADIG.format(id="VID_0403&PID_6010&MI_00"),  # older Zadig run
        "oem2.inf": ZADIG.format(id="VID_0403&PID_6010&MI_00"),  # newer Zadig run
        "oem3.inf": ZADIG.format(id="VID_04B4&PID_00F9"),  # Zadig for another device
        "oem4.inf": FTDI,
        "readme.inf": FTDI,  # not an oem*.inf
    }
    for i, (name, text) in enumerate(files.items()):
        p = tmp_path / name
        p.write_text(text, encoding="ascii")
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    os.utime(tmp_path / "oem3.inf", (1_800_000_000, 1_800_000_000))  # newest file, wrong device
    assert find(tmp_path, "WinUSB") == "oem2.inf"
    assert find(tmp_path, "FTDIBUS") == "oem4.inf"


def test_driver_api_can_be_loaded_twice_in_one_session():
    # A second run in the same (elevated) window must not fail with TYPE_ALREADY_EXISTS.
    cmd = f". '{SCRIPT}'; Add-DriverApi; Add-DriverApi; [bool]('Win32.Drv' -as [type])"
    r = subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0 and r.stdout.strip() == "True", r.stderr


def run_elevated(tmp_path, to):
    # Space, ASCII quote and a typographic quote (PowerShell takes U+2018..U+201B as quotes too):
    # the path must survive the re-launch, not end the quoted string early.
    d = tmp_path / "it's Bob’s dir"  # noqa: RUF001 (the typographic quote is the point)
    d.mkdir(exist_ok=True)
    fake = d / "fake.ps1"
    fake.write_text("param($To)\n\"ran $To\"\nif ($To -eq 'bad') { throw 'boom' }\n", encoding="ascii")
    quoted = "".join(c * 2 if c in "'‘’‚‛" else c for c in str(fake))  # noqa: RUF001 (PowerShell's quotes)
    cmd = f". '{SCRIPT}'; Invoke-Elevated '{quoted}' {to} -NoRunAs"
    return subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )


def test_relaunch_shows_the_child_output_here(tmp_path):
    r = run_elevated(tmp_path, "winusb")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ran winusb"


def test_relaunch_reports_the_child_failure(tmp_path):
    r = run_elevated(tmp_path, "bad")
    assert r.returncode != 0
    assert "ran bad" in r.stdout and "boom" in r.stdout


def test_nothing_found_returns_nothing(tmp_path):
    (tmp_path / "oem1.inf").write_text(ZADIG.format(id="VID_04B4&PID_00F9"), encoding="ascii")
    assert find(tmp_path, "WinUSB") == ""

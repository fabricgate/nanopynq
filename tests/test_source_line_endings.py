import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_build_inputs_check_out_with_lf():
    # build.json records the sha256 of each .v / .cst as read from the working tree (tools/build_base.py);
    # with core.autocrlf they would be CRLF on Windows and match neither the commit nor a Linux build's record.
    files = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.v", "*.cst"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert files and [f for f in files if b"\r\n" in (ROOT / f).read_bytes()] == []


def test_udev_rule_checks_out_with_lf():
    # The rule ships inside the package; a wheel built from a Windows checkout must not carry CRLF to udev.
    rule = ROOT / "src" / "nanopynq" / "data" / "99-nanopynq.rules"
    assert b"\r\n" not in rule.read_bytes()

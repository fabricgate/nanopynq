import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import nanopynq.sensors.ov2640 as ov2640

ROOT = Path(__file__).resolve().parent.parent


def test_ov2640_names_both_upstream_licenses():
    doc = ov2640.__doc__
    assert "Espressif" in doc and "Apache" in doc  # ov2640_settings.h
    assert "OpenMV" in doc and "Ibrahim Abdelkader" in doc and "MIT" in doc  # ov2640.c, ov2640_regs.h


def test_notices_and_license_texts_exist():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "OpenMV" in notices and "MIT" in notices and "Apache" in notices
    assert "Permission is hereby granted" in (ROOT / "licenses" / "openmv-ov2640-LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in (ROOT / "licenses" / "esp32-camera-LICENSE").read_text(encoding="utf-8")


DDR3_RTL = ("ddr3_ctrl.sv", "ddr3_cmd.sv", "ddr3_init.sv", "ddr3_calib.sv", "ddr3_phy_slow.sv", "ddr3_phy_2to1.sv")


def test_gowin_ddr3_is_vendored_with_its_licence():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "e-karge/gowin-ddr3" in notices and "84a1a11" in notices and "nand2mario" in notices
    assert "Apache License" in (ROOT / "licenses" / "gowin-ddr3-LICENSE").read_text(encoding="utf-8")
    for f in DDR3_RTL:
        assert f in notices and (ROOT / "src" / "nanopynq" / "rtl" / "ddr3" / f).is_file()


CHANGED = ("ddr3_phy_slow.sv", "ddr3_ctrl.sv")


def test_the_changed_ddr3_files_say_so():  # Apache-2.0 4(b): changed files carry a notice
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for f in CHANGED:
        assert f"{f}` is changed" in notices, f
        head = (ROOT / "src" / "nanopynq" / "rtl" / "ddr3" / f).read_text(encoding="utf-8")[:600]
        assert "Changed for nanopynq" in head, f


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build the wheel")
def test_wheel_carries_the_license_texts(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=ROOT, check=True, capture_output=True)
    wheel = zipfile.ZipFile(next(tmp_path.glob("*.whl")))
    names = wheel.namelist()
    assert any(n.endswith(".dist-info/licenses/LICENSE") for n in names), names  # nanopynq's own MIT license
    metadata = wheel.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
    assert "License-Expression: MIT" in metadata
    for want in (
        "esp32-camera-LICENSE",
        "openmv-ov2640-LICENSE",
        "gowin-ddr3-LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "nanopynq/rtl/ddr3/ddr3_ctrl.sv",
        "nanopynq/rtl/ddr3/ddr3_phy_slow.sv",
    ):
        assert any(n.endswith(want) for n in names), (want, [n for n in names if "dist-info" in n])

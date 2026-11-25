import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from build_base import HPRAM_BELS, TOP_ROW_CAMERA, check_placement

OTHER = [
    "X0Y5/IOBA",
    "X0Y6/IOBA",
    "X0Y7/IOBA",
    "X0Y8/IOBA",
    "X0Y9/IOBA",
    "X0Y10/IOBA",
    "X0Y11/IOBA",
    "X0Y12/IOBA",
    "X0Y13/IOBA",
]  # 9 IOs off the top row (btn, xclk, cam_d[0..5] in the real design)


def pnr(tmp_path, bels):
    cells = {f"io{i}": {"type": "IBUF", "attributes": {"NEXTPNR_BEL": b}} for i, b in enumerate(bels)}
    cells["lut"] = {"type": "LUT4", "attributes": {"NEXTPNR_BEL": "X5Y5/LUT0"}}
    (tmp_path / "pnr.json").write_text(json.dumps({"modules": {"top": {"cells": cells}}}))
    return tmp_path / "pnr.json"


GOOD = sorted(HPRAM_BELS) + sorted(TOP_ROW_CAMERA) + OTHER


def test_camstream_placement_accepted(tmp_path):
    check_placement(pnr(tmp_path, GOOD), 31, TOP_ROW_CAMERA)


@pytest.mark.parametrize(
    "swap",
    [
        ("X22Y19/IOBA", "X1Y0/IOBA"),  # HyperRAM CK on the TDI pad
        ("X0Y13/IOBA", "X4Y0/IOBB"),  # something on DONE
        ("X0Y13/IOBA", "X30Y0/IOBA"),
    ],
)  # an unexpected top-row IO
def test_bad_placement_refused(tmp_path, swap):
    bels = [swap[1] if b == swap[0] else b for b in GOOD]
    with pytest.raises(SystemExit, match="refusing"):
        check_placement(pnr(tmp_path, bels), 31, TOP_ROW_CAMERA)


def test_io_count_checked(tmp_path):
    with pytest.raises(SystemExit, match="30 IOs"):
        check_placement(pnr(tmp_path, GOOD[:-1]), 31, TOP_ROW_CAMERA)

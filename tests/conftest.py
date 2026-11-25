import hashlib

import pytest

MANIFEST = """\
schema: fabricgate-platform/v1
runtime: nanopynq
board: {board}
device_family: {family}
design_ref: local/{board}-base:0.1.0
artifacts: {{bitstream: {{file: base.fs, sha256: {sha}}}}}
transport: {transport}
ips:
  sys:     {{base: "0x0000", type: "nanopynq:sysinfo:1.0", registers: {{id: {{offset: "0x0", width: 32, access: ro}}, version: {{offset: "0x4", width: 32, access: ro}}}}}}
  leds:    {{base: "0x1000", type: "nanopynq:gpio_out:1.0", parameters: {{width: {leds}}}, registers: {{data: {{offset: "0x0", width: {leds}, access: rw}}}}}}
  buttons: {{base: "0x2000", type: "nanopynq:gpio_in:1.0",  parameters: {{width: 2}}, registers: {{data: {{offset: "0x0", width: 2, access: ro}}}}}}
"""


def _design(path, **fields):
    bit = b"dummy bitstream"
    (path / "base.fs").write_bytes(bit)
    (path / "manifest.yaml").write_text(
        MANIFEST.format(sha=hashlib.sha256(bit).hexdigest(), **fields), encoding="utf-8"
    )
    return path


@pytest.fixture
def tmp_design(tmp_path):
    return _design(tmp_path, board="tangnano9k", family="gw1n-9c", transport="uart", leds=6)


@pytest.fixture
def tmp_design_4k(tmp_path):
    return _design(tmp_path, board="tangnano4k", family="gw1ns-4", transport="jtag", leds=1)

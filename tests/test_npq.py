import copy
import json
import re
from pathlib import Path

import pytest

from nanopynq.errors import ManifestError, NpqError
from nanopynq.manifest import load_manifest
from nanopynq.npq import Npq, design_id, load_npq, parse_npq, write_npq

SPEC = Path(__file__).resolve().parents[1] / "docs" / "spec_design_metadata.md"


def _spec_json(heading: str) -> dict:
    text = SPEC.read_text(encoding="utf-8")
    return json.loads(re.search(re.escape(heading) + r".*?```json\n(.*?)```", text, re.S).group(1))


NINE_K = _spec_json("### 6.1 `tangnano9k-base`")
CAMSTREAM = _spec_json("### 6.2 `tangnano4k-camstream`")
# conftest.MANIFEST's ips in the .npq form (sysinfo 1.0, no design_id register)
IPS = {
    "sys": {
        "base": "0x0000",
        "type": "nanopynq:sysinfo:1.0",
        "registers": {
            "id": {"offset": "0x0", "width": 32, "access": "ro"},
            "version": {"offset": "0x4", "width": 32, "access": "ro"},
        },
    },
    "leds": {
        "base": "0x1000",
        "type": "nanopynq:gpio_out:1.0",
        "parameters": {"width": 6},
        "registers": {"data": {"offset": "0x0", "width": 6, "access": "rw"}},
    },
    "buttons": {
        "base": "0x2000",
        "type": "nanopynq:gpio_in:1.0",
        "parameters": {"width": 2},
        "registers": {"data": {"offset": "0x0", "width": 2, "access": "ro"}},
    },
}
UART = {"kind": "uart", "baudrate": 115200}


def _write(folder: Path, ips=IPS, board="tangnano9k", link=UART) -> Path:
    fs = folder / "base.fs"
    fs.write_bytes(b"dummy bitstream")
    return write_npq(fs, board, link, ips)


# ---------------------------------------------------------------- design_id: the spec's own examples


def test_spec_example_values():
    assert design_id(NINE_K["ips"]) == int(NINE_K["design_id"], 16) == 0xABF78D8C
    assert design_id(CAMSTREAM["ips"]) == int(CAMSTREAM["design_id"], 16) == 0xCA950154
    four_k = copy.deepcopy(NINE_K["ips"])  # tangnano4k-base: 9K's ips with one LED (spec 5.4)
    four_k["leds"]["parameters"]["width"] = four_k["leds"]["registers"]["data"]["width"] = 1
    assert design_id(four_k) == 0x79D574B7


def test_spec_step3_bytes():
    from nanopynq.npq import _canonical

    step3 = re.search(r"手順 3 のバイト列.*?```\n(.*?)```", SPEC.read_text(encoding="utf-8"), re.S).group(1).strip()
    assert _canonical(NINE_K["ips"]).decode("utf-8") == step3


def test_design_id_ignores_doc_and_sees_base():
    ips = copy.deepcopy(NINE_K["ips"])
    ips["leds"]["doc"] = "six LEDs"
    ips["leds"]["registers"]["data"]["doc"] = "one bit per LED"
    assert design_id(ips) == 0xABF78D8C
    ips["buttons"]["base"] = "0x3000"  # spec 5.4's own example (leds at 0x1004) now overlaps buttons: V9
    assert design_id(ips) != 0xABF78D8C


@pytest.mark.parametrize(
    "ips, rule",
    [
        ({}, "V3"),
        ({"sys": {"base": "0x0", "type": "nanopynq:sysinfo:1.0", "parameters": {"w": 6.0}}}, "V4"),
        ({1: {}}, "V5"),
        ({"sys": {"base": 0, "type": "nanopynq:sysinfo:1.0"}}, "V7"),
    ],
)
def test_design_id_checks_the_ips_first(ips, rule):
    with pytest.raises(NpqError) as e:
        design_id(ips)
    assert e.value.rule == rule


def test_design_id_deep_or_cyclic_ips_is_v1():
    deep, cyclic = copy.deepcopy(IPS), copy.deepcopy(IPS)
    x = deep["leds"]["parameters"]["x"] = []
    for _ in range(5000):
        x.append([])
        x = x[0]
    loop = cyclic["leds"]["parameters"]["x"] = []
    loop.append(loop)
    for ips in (deep, cyclic):
        with pytest.raises(NpqError, match=r"^V1 at ips"):
            design_id(ips)


def test_text_nested_past_the_recursion_limit_is_v1():
    with pytest.raises(NpqError, match=r"^V1 at"):
        parse_npq(b'{"a":' + b"[" * 200000 + b"]" * 200000 + b"}")


def test_write_refuses_to_overwrite_its_input(tmp_path):
    fs = tmp_path / "x.npq"
    fs.write_bytes(b"dummy bitstream")
    with pytest.raises(ManifestError, match="overwrite"):
        write_npq(fs, "tangnano9k", UART, IPS)
    assert fs.read_bytes() == b"dummy bitstream"


# ---------------------------------------------------------------- load_npq


def test_load_has_the_manifest_fields_and_the_same_ips(tmp_design):
    npq = load_npq(_write(tmp_design))
    m = load_manifest(tmp_design)
    assert isinstance(npq, Npq)
    assert (npq.board, npq.bitstream, npq.sha256, npq.ips) == (m.board, m.bitstream, m.sha256, m.ips)
    assert npq.link == UART
    assert npq.design_id == design_id(IPS)


def test_load_from_folder_or_file(tmp_path):
    p = _write(tmp_path)
    assert load_npq(tmp_path) == load_npq(p)


def test_read_effect_kept_only_when_true(tmp_path):
    ips = copy.deepcopy(IPS)
    ips["leds"]["registers"]["data"]["read_effect"] = True
    ips["buttons"]["registers"]["data"]["read_effect"] = False
    regs = load_npq(_write(tmp_path, ips)).ips
    assert regs["leds"]["registers"]["data"]["read_effect"] is True
    assert "read_effect" not in regs["buttons"]["registers"]["data"]


@pytest.mark.parametrize("names", [[], ["a.npq", "b.npq"]])
def test_folder_needs_exactly_one_npq(tmp_path, names):
    for n in names:
        (tmp_path / n).write_text("{}")
    with pytest.raises(ManifestError, match=f"found {len(names)}"):
        load_npq(tmp_path)


def test_missing_path(tmp_path):
    with pytest.raises(ManifestError, match="cannot read"):
        load_npq(tmp_path / "none.npq")


def test_fs_changed_is_v12(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "base.fs").write_bytes(b"another bitstream")
    with pytest.raises(NpqError, match=r"^V12 at bitstream\.sha256") as e:
        load_npq(p)
    assert str(p) in e.value.__notes__[0]


def test_fs_missing_is_v12(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "base.fs").unlink()
    with pytest.raises(NpqError, match="not found") as e:
        load_npq(p)
    assert e.value.rule == "V12"


def test_v11_comes_before_v12(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "base.fs").write_bytes(b"another bitstream")
    p.write_text(p.read_text(encoding="utf-8").replace('"0x1000"', '"0x3000"'), encoding="utf-8")
    with pytest.raises(NpqError) as e:
        load_npq(p)
    assert e.value.rule == "V11"


def test_error_names_rule_and_place(tmp_path):
    p = _write(tmp_path)
    p.write_text(p.read_text(encoding="utf-8").replace('"width": 6,', '"width": 33,'), encoding="utf-8")
    with pytest.raises(NpqError, match=r"^V8 at ips\.leds\.registers\.data\.width: ") as e:
        load_npq(p)
    assert (e.value.rule, e.value.where) == ("V8", "ips.leds.registers.data.width")


def test_more_than_1_mib_is_v1(tmp_path):
    p = _write(tmp_path)
    p.write_bytes(p.read_bytes() + b" " * (1 << 20))
    with pytest.raises(NpqError, match=r"^V1 at"):
        load_npq(p)


# ---------------------------------------------------------------- write_npq


def test_write_is_checked_and_fixed_bytes(tmp_path):
    p = _write(tmp_path)
    first = p.read_bytes()
    assert p.name == "base.npq"
    assert parse_npq(first)["design_id"] == f"0x{design_id(IPS):08x}"
    assert first.endswith(b"}\n") and b"\r" not in first
    assert list(json.loads(first)) == ["format", "board", "bitstream", "link", "design_id", "ips"]
    assert _write(tmp_path).read_bytes() == first


def test_write_keeps_the_ips_order(tmp_path):
    # same dict by ==, other insertion order: other bytes, same design_id
    first = _write(tmp_path).read_bytes()
    second = _write(tmp_path, dict(reversed(IPS.items()))).read_bytes()
    assert first != second
    assert parse_npq(first)["design_id"] == parse_npq(second)["design_id"]


def test_write_jtag_has_no_baudrate(tmp_path):
    assert load_npq(_write(tmp_path, board="tangnano4k", link={"kind": "jtag"})).link == {"kind": "jtag"}


@pytest.mark.parametrize(
    "kw, rule",
    [
        ({"board": "Tang\ud800"}, "V3"),
        ({"link": {"kind": "uart", "baudrate": 115200.0}}, "V3"),
        ({"link": {"kind": "jtag", "baudrate": 115200}}, "V3"),
        ({"ips": {"leds": IPS["leds"]}}, "V10"),
    ],
)
def test_write_rejects_and_leaves_no_file(tmp_path, kw, rule):
    with pytest.raises(NpqError) as e:
        _write(tmp_path, **kw)
    assert e.value.rule == rule
    assert not (tmp_path / "base.npq").exists()

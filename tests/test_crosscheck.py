"""The check of the ips against the RTL (nanopynq.build.crosscheck) on the 9K designs and deliberate mismatches.

The mismatches use a small design (tests/data/crosscheck_small: one slave, a 4-clock reset, depth 20): on
two cores a check of the example takes about 14 s, one of the small design about 2 s. The bundled base and
the example (through nanopynq build in test_build_design.py) are checked as they are.
"""

import copy
import sys
from pathlib import Path

import pytest

import nanopynq.build.crosscheck as cc
from nanopynq.boards import get_board
from nanopynq.build.design import RTL_DIR, load_config

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_base as bb  # noqa: E402

pytestmark = pytest.mark.toolchain
BOARD = get_board("tangnano9k")

SMALL = load_config(ROOT / "tests" / "data" / "crosscheck_small")
TOP = SMALL.sources[-1][1].read_text()
IPS = SMALL.ips
BRIDGE = [p for _, p in SMALL.sources[:-1]]


def check(tmp_path, ips=IPS, top=TOP, sources=None, depth=SMALL.check_depth, **kw):
    (tmp_path / "top.v").write_text(top)
    return cc.crosscheck(ips, sources or [*BRIDGE, tmp_path / "top.v"], BOARD, tmp_path / "out", depth=depth, **kw)


def edited(f, ips=IPS):
    ips = copy.deepcopy(ips)
    f(ips)
    return ips


def top_with(old, new):
    assert old in TOP
    return TOP.replace(old, new)


def found(problems):
    return sorted((p.kind, p.where) for p in problems)


def test_the_bundled_9k_base_passes(tmp_path):  # the example passes in test_build_design.py
    res = cc.crosscheck(bb.ips("tangnano9k", "base"), bb.sources("tangnano9k", "base"), BOARD, tmp_path)
    assert res.ok and not res.warnings, res


def test_the_small_top_passes(tmp_path):
    res = check(tmp_path)
    assert res.ok and not res.warnings, res


def combined(ips):
    regs = ips["toy"]["registers"]
    ips["toy"]["addr_range"] = "0x1000"  # the default, written out: still an error
    del regs["spare"]  # register left out
    regs["extra"] = {"offset": "0x10", "width": 8, "access": "ro"}  # register not in the RTL
    regs["status"]["access"] = "rw"  # ro written as rw
    regs["mode"]["access"] = "ro"  # rw written as ro
    regs["data"]["width"] = 8  # rw too wide (the RTL has 4)
    ips["sys"]["registers"]["id"]["width"] = 16  # ro too narrow


def test_mismatches_that_share_a_run(tmp_path):
    res = check(tmp_path, edited(combined))
    assert found(res.errors) == [("no_slave", "ips.toy.registers.extra"), ("undeclared", "0x1008")], res
    assert found(res.warnings) == [
        ("not_ro", "ips.toy.registers.mode"),
        ("not_rw", "ips.toy.registers.data"),
        ("not_rw", "ips.toy.registers.status"),
        ("width", "ips.sys.registers.id"),
    ], res


def test_rw_too_narrow_is_found_and_ro_too_wide_is_missed(tmp_path):
    def f(ips):
        ips["toy"]["registers"]["spare"]["width"] = 16
        ips["toy"]["registers"]["status"]["width"] = 4  # high bits 0 are possible: not seen

    res = check(tmp_path, edited(f))
    assert res.ok and found(res.warnings) == [("not_rw", "ips.toy.registers.spare")], res


def test_shifted_base_in_the_ips(tmp_path):
    res = check(tmp_path, edited(lambda i: i["toy"].update(base="0x3000")))
    # outside: the address is the solver's pick
    assert sorted(k for k, _ in found(res.errors)) == ["no_slave"] * 4 + ["outside"], res
    assert not res.warnings, res  # a missing register is not warned about again


def test_shifted_base_in_the_rtl(tmp_path):
    top = TOP
    for w in ("400", "401", "402", "403"):
        top = top.replace(f"30'h{w}:", f"30'h{int(w, 16) + 0x40:x}:")  # 0x1000.. -> 0x1100..
    res = check(tmp_path, top=top)
    assert {k for k, _ in found(res.errors)} == {"no_slave", "undeclared"}, res
    assert all(0x1100 <= int(w, 16) < 0x1110 for k, w in found(res.errors) if k == "undeclared")


def test_ip_left_out(tmp_path):
    res = check(tmp_path, edited(lambda i: i.pop("toy")))
    assert [k for k, _ in found(res.errors)] == ["outside"] and not res.warnings, res


def test_a_narrow_addr_range_does_not_hide_a_missing_register(tmp_path):
    def f(ips):
        ips["toy"]["addr_range"] = "0x100"
        del ips["toy"]["registers"]["spare"]

    assert found(check(tmp_path, edited(f)).errors) == [("undeclared", "0x1008")]


def test_streams_make_undeclared_a_warning(tmp_path):  # a data window answers between the registers
    def f(ips):
        ips["toy"]["streams"] = {"rx": {"dir": "read", "mtu": 4, "register": "data", "framing": "raw"}}
        del ips["toy"]["registers"]["spare"]

    res = check(tmp_path, edited(f))
    assert res.ok and found(res.warnings) == [("undeclared", "0x1008")], res


@pytest.mark.parametrize("word, kind", [("405", "undeclared"), ("1400", "outside")])  # 0x1014, 0x5000
def test_an_address_that_answers_only_after_a_write(tmp_path, word, kind):
    top = top_with("LATE = 30'h3fff_ffff", f"LATE = 30'h{word}").replace("LATE: late <= 1'b0;", "LATE: late <= 1'b1;")
    res = check(tmp_path, top=top)
    assert found(res.errors) == [(kind, f"0x{int(word, 16) << 2:x}")], res
    assert "reads 0xdeadbeef, and 0x00000000 after writing 0x" in res.errors[0].message


def test_a_short_depth_cannot_check(tmp_path):
    res = check(tmp_path, depth=10)
    assert [p.kind for p in res.errors] == ["cannot_check"] and "within 10 clocks" in res.errors[0].message, res


def test_a_reset_from_an_input_needs_that_input_pinned(tmp_path):
    top = top_with("wire rst = !por[2];", "wire rst = !por[2] || btn[1];")
    assert [p.kind for p in check(tmp_path, top=top).errors] == ["cannot_check"]  # btn free: reset held
    assert check(tmp_path, top=top, inputs={"btn": 0}).ok


def test_only_input_ports_can_be_pinned(tmp_path):
    res = check(tmp_path, inputs={"por": 0})  # pinning an internal register could contradict the design
    assert found(res.errors) == [("cannot_check", "check.inputs.por")] and "btn, clk, uart_rx" in res.errors[0].message
    res = check(tmp_path, inputs={"btn": 4})  # sat would cut it to 2'b00
    assert found(res.errors) == [("cannot_check", "check.inputs.btn")] and "(2 bits)" in res.errors[0].message


def test_a_top_without_the_bridge_cannot_check(tmp_path):
    own = tmp_path / "my_bridge.v"
    own.write_text((RTL_DIR / "uartbone_bridge.v").read_text().replace("module uartbone_bridge", "module my_bridge"))
    res = check(
        tmp_path, top=top_with("uartbone_bridge #", "my_bridge #"), sources=[*BRIDGE[:2], own, tmp_path / "top.v"]
    )
    assert [p.kind for p in res.errors] == ["cannot_check"] and "holds 0" in res.errors[0].message, res


def test_an_address_that_cannot_be_pinned_is_not_a_pass(tmp_path, monkeypatch):
    # The spike's first master (report section 1): opt ties this register to 'x and every -set contradicts it.
    old = "(* anyconst *) reg [29:0] npqchk_adr;"
    assert old in cc.MASTER
    monkeypatch.setattr(
        cc, "MASTER", cc.MASTER.replace(old, "reg [29:0] npqchk_adr; always @(posedge clk) npqchk_adr <= npqchk_adr;")
    )
    res = check(tmp_path)
    assert [p.kind for p in res.errors] == ["cannot_check"] and "contradict" in res.errors[0].message, res


def test_the_check_elaborates_with_the_design_id_synthesis_will_set(tmp_path):
    # A slave that only exists for one DESIGN_ID: checked with the RTL default (0) it would look missing.
    top = top_with(
        "30'h400: dat_r <= {28'd0, data};",
        "30'h400: dat_r <= DESIGN_ID == 32'h1234_5678 ? {28'd0, data} : 32'hdead_beef;",
    )
    for d in ("set", "default"):
        (tmp_path / d).mkdir()
    assert check(tmp_path / "set", top=top, design_id=0x12345678).ok
    res = check(tmp_path / "default", top=top)
    assert [p.kind for p in res.errors] == ["no_slave"]

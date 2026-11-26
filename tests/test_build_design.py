import json
import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import nanopynq.build.design as bd
from nanopynq.__main__ import main
from nanopynq.build.crosscheck import Problem, Result, _yosys
from nanopynq.build.gowin import chparam_design_id
from nanopynq.errors import BuildError, NpqError
from nanopynq.npq import design_id, load_npq
from tests.fakes import own_netlist, pwm_netlist
from tests.test_npq import UART

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "tangnano9k_pwm"
DATA = Path(__file__).resolve().parent / "data"
SMALL = DATA / "crosscheck_small"


@pytest.fixture
def example(tmp_path):
    d = tmp_path / "pwm"
    shutil.copytree(EXAMPLE, d, ignore=shutil.ignore_patterns("build", "dist"))
    return d


@pytest.fixture
def design(example):  # the example with every ip written by hand, as before #44: such files keep working
    shutil.copyfile(DATA / "pwm_hand.toml", example / "nanopynq.toml")
    return example


def edit(d: Path, old: str, new: str) -> None:
    p = d / "nanopynq.toml"
    text = p.read_text()
    assert old in text
    p.write_text(text.replace(old, new, 1))


def fake_run(cmd, **kw):
    if cmd[0] == "gowin_pack":
        (Path(kw["cwd"]) / cmd[cmd.index("-o") + 1]).write_bytes(b"fake bitstream\n")
    return CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def tools_ok(monkeypatch):
    monkeypatch.setattr(bd, "check_yowasp", lambda: (True, "ok"))
    monkeypatch.setattr(bd, "elaborate", lambda *a, **kw: pwm_netlist())
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: Result([], [], 0, 0.0))


SHIFTED = [
    Problem("ips.pwm.registers.ctrl", "no_slave", "ips.pwm.registers.ctrl (0x7100): every read returns 0xdeadbeef"),
    Problem("0x7004", "outside", "0x7004: answers (reads 0x00000000)"),
]


def test_example_config_reads_in_order_and_differs_from_the_base(design):
    d = bd.load_config(design)
    assert (d.name, d.board, d.top, d.seed) == ("pwm", "tangnano9k", "top", 1)
    assert [s for s, _ in d.sources][-1] == "top.v" and d.sources[0][1] == bd.RTL_DIR / "base_regs.v"
    assert list(d.ips) == ["sys", "leds", "buttons", "pwm"]
    assert design_id(d.ips) not in (0xABF78D8C, 0)


@pytest.mark.parametrize(
    "old, new, match",
    [
        ('name = "pwm"\n', "", "name: missing"),
        ('constraints = "tangnano9k.cst"\n', "", "constraints: missing"),
        ('top = "top"\n', 'tpo = "top"\n', "tpo: unknown key"),
        ('board = "tangnano9k"', 'board = "tangnano99k"', "unknown board 'tangnano99k'"),
        ('board = "tangnano9k"', 'board = "tangnano4k"', "does not support tangnano4k yet"),
        ('"top.v",', '"missing.v",', r"sources\[7\]: .*missing.v not found"),
        ('"nanopynq:pwm_timer.v"', '"nanopynq:pwm.v"', r"sources\[1\]: 'nanopynq:pwm.v' is not a shared RTL file"),
        ('"nanopynq:pwm_timer.v"', '"nanopynq:../rtl/pwm_timer.v"', r"sources\[1\]: .* is not a shared RTL file"),
        ('"top.v",', '"to\\"p.v",', r"sources\[7\]: .* must not contain"),
        ('constraints = "tangnano9k.cst"', 'constraints = "tang\\"nano9k.cst"', r"constraints: .* must not contain"),
        ('name = "pwm"', 'name = "my design"', "name: 'my design'"),
        ('top = "top"', 'top = "top; shell"', "top: 'top; shell' is not a Verilog module name"),
        ('name = "pwm"', 'name = "pwm', "line 2"),  # not TOML
        ('top = "top"', 'top = "top"\ncheck = 1', "check: must be a table"),
        ("[ips.sys]", "[check]\ndepht = 40\n[ips.sys]", "check.depht: unknown key"),
        ("[ips.sys]", "[check]\ndepth = 0\n[ips.sys]", "check.depth: must be an integer 1 .. 1000"),
        ("[ips.sys]", "[check]\ninputs = { btn = -1 }\n[ips.sys]", "check.inputs.btn: must be an integer"),
        ("[ips.sys]", "[check]\ninputs = { btn = true }\n[ips.sys]", "check.inputs.btn: must be an integer"),
        ("[ips.sys]", '[check]\ninputs = { "btn x" = 0 }\n[ips.sys]', "check.inputs: 'btn x' is not a Verilog"),
    ],
)
def test_config_errors_name_the_key(design, old, new, match):
    edit(design, old, new)
    with pytest.raises(bd.ConfigError, match=match):
        bd.load_config(design)


def test_jtag_board_refusal_lists_every_board_with_a_uart(design):
    edit(design, 'board = "tangnano9k"', 'board = "tangnano4k"')
    with pytest.raises(bd.ConfigError, match="the supported boards are tangmega138kpro, tangnano20k, tangnano9k"):
        bd.load_config(design)


def test_a_20k_design_is_built_for_its_uart(design, tools_ok):
    """The 20K talks JTAG by default; nanopynq build uses its second link, the UART (boards.yaml uart_link)."""
    edit(design, 'board = "tangnano9k"', 'board = "tangnano20k"')
    npq = load_npq(bd.build_design(design, run=fake_run))
    assert (npq.board, npq.link) == ("tangnano20k", UART)


def test_tangmega138kpro_is_a_build_target(design):
    edit(design, 'board = "tangnano9k"', 'board = "tangmega138kpro"')
    assert bd.load_config(design).board == "tangmega138kpro"


def test_missing_config(tmp_path):
    with pytest.raises(bd.ConfigError, match=r"not found; a design folder needs a nanopynq.toml"):
        bd.load_config(tmp_path)


def test_overlapping_ips_stop_before_the_crosscheck(design, tools_ok, monkeypatch):
    # the ips are known only once collected from the RTL, which needs the tools (before #44: before the tools)
    edit(design, 'base = "0x7000"', 'base = "0x2100"')  # at 0x2000 it would take the collected buttons' place
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: pytest.fail("ran the crosscheck"))
    with pytest.raises(NpqError) as e:
        bd.build_design(design, run=fake_run)
    assert (e.value.rule, e.value.where) == ("V9", "ips.pwm.base")


def test_the_adder_example_reads_its_hand_written_ip(tmp_path, monkeypatch):
    adder = tmp_path / "adder"
    shutil.copytree(EXAMPLE.with_name("tangnano9k_adder"), adder, ignore=shutil.ignore_patterns("build", "dist"))
    n = pwm_netlist()  # the pwm example's netlist with the adder (no description: not collected) in place of the timer
    top = n["modules"]["top"]["cells"]
    top["add"] = {"type": "adder", "attributes": {}}
    del top["timer"]
    n["modules"]["adder"] = {
        "attributes": {"hdlname": "adder"},
        "cells": {},
        "parameter_default_values": {"BASE": f"{0x7000:032b}"},
    }
    n["modules"]["$paramod$6e\\regbus_gpio"]["parameter_default_values"]["WIDTH"] = f"{6:032b}"
    monkeypatch.setattr(bd, "check_yowasp", lambda: (True, "ok"))
    monkeypatch.setattr(bd, "elaborate", lambda *a, **kw: n)
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: Result([], [], 0, 0.0))
    d = bd.load_config(adder)
    assert next(s for s, _ in d.sources) == "adder.v"
    npq = load_npq(bd.build_design(adder, run=fake_run))
    assert list(npq.ips) == ["sys", "leds", "buttons", "adder"]
    ip = npq.ips["adder"]
    assert (ip["phys_addr"], ip["type"], ip["addr_range"]) == (0x7000, "fabricgate:adder:1.0", 0x10)
    assert {k: (r["offset"], r["width"], r["access"]) for k, r in ip["registers"].items()} == {
        "a": (0, 32, "rw"),
        "b": (4, 32, "rw"),
        "sum": (8, 32, "ro"),
        "carry": (0xC, 1, "ro"),
    }
    assert npq.ips["leds"]["registers"]["data"]["width"] == 6


def test_build_writes_a_loadable_pair_and_a_record(design, tools_ok):
    dist = bd.build_design(design, run=fake_run)
    assert sorted(p.name for p in dist.iterdir()) == ["build.json", "pwm.fs", "pwm.npq"]
    npq = load_npq(dist)
    assert npq.design_id == design_id(bd.load_config(design).ips) and npq.link == UART
    rec = json.loads((dist / "build.json").read_text())
    assert [s["file"] for s in rec["sources"]][-2:] == ["top.v", "tangnano9k.cst"]
    assert rec["design_id"] == f"0x{npq.design_id:08x}" and str(design) not in json.dumps(rec)
    assert rec["freq_mhz"] == 27.0
    assert json.loads((design / "build" / "ips.json").read_text()) == bd.load_config(design).ips


def test_the_example_builds_from_the_collected_ips(example, tools_ok, capsys):
    npq = load_npq(bd.build_design(example, run=fake_run))
    assert npq.design_id == 0x556FAE35 and list(npq.ips) == ["sys", "leds", "buttons", "pwm"]
    err = capsys.readouterr().err
    assert "  pwm      0x7000  nanopynq:pwm_timer:1.0  timer\n" in err, err
    assert json.loads((example / "build" / "ips.json").read_text())["pwm"]["parameters"] == {"clock_hz": 27000000}


def test_a_hand_written_ip_is_shown_as_such(design, tools_ok, capsys):
    bd.build_design(design, run=fake_run)
    assert "  pwm      0x7000  nanopynq:pwm_timer:1.0  nanopynq.toml\n" in capsys.readouterr().err


@pytest.mark.parametrize(
    "old, new, match",
    [
        ("[ips.pwm]", "[ips.pwm]\ninstance = 3", "ips.pwm.instance: must be a string"),
        ("[ips.pwm]", "[ips]\nleds = 1\n[ips.pwm]", "ips.leds: must be a table"),
        ("[ips.pwm]", '[ips.pwm]\ninstance = "tmr"', "ips.pwm.instance: no described instance 'tmr'"),
        ("[ips.pwm]", "[ips.x]\nbase = 1979-05-27\n[ips.pwm]", "V4 at ips.x.base"),  # a TOML date: spec 5.9, no crash
    ],
)
def test_ips_entry_errors(example, tools_ok, old, new, match):
    edit(example, old, new)
    with pytest.raises((bd.ConfigError, bd.CollectError, NpqError), match=match):
        bd.build_design(example, run=fake_run)


def test_cli_reports_collect_errors(example, tools_ok, capsys):
    edit(example, "parameters = { clock_hz = 27000000 }", "")
    assert main(["build", str(example)]) == 1
    assert "nanopynq.toml: ips.pwm (timer): give parameters ['clock_hz']" in capsys.readouterr().err


def test_a_failed_elaboration_is_a_build_error(design, monkeypatch):
    monkeypatch.setattr(bd, "check_yowasp", lambda: (True, "ok"))
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: pytest.fail("ran the crosscheck"))
    with pytest.raises(BuildError) as e:  # the CLI writes its log to build/ips.log
        bd.build_design(design, run=synth_fails)
    assert e.value.step == "ips"


def test_stale_npq_in_dist_is_an_error(design, tools_ok):
    (design / "dist").mkdir()
    (design / "dist" / "old.npq").write_text("{}")
    with pytest.raises(bd.ConfigError, match=r"old.npq"):
        bd.build_design(design, run=fake_run)


def test_check_table_reaches_the_crosscheck(design, tools_ok, monkeypatch):
    edit(design, "[ips.sys]", "[check]\ninputs = { btn = 0 }\ndepth = 40\n[ips.sys]")
    seen = {}
    monkeypatch.setattr(
        bd, "crosscheck", lambda ips, sources, board, out, **kw: seen.update(kw, out=out) or Result([], [], 0, 0.0)
    )
    bd.build_design(design, run=fake_run)
    assert (seen["inputs"], seen["depth"], seen["top"]) == ({"btn": 0}, 40, "top")
    assert seen["out"] == design / "build" / "crosscheck"


def test_order_tools_ips_crosscheck_synthesis(design, monkeypatch):
    calls = []
    monkeypatch.setattr(bd, "design_id", lambda ips: calls.append("ips") or 1)
    monkeypatch.setattr(bd, "check_yowasp", lambda: calls.append("tools") or (True, "ok"))
    monkeypatch.setattr(bd, "elaborate", lambda *a, **kw: calls.append("collect") or pwm_netlist())
    # the check gets the DESIGN_ID synthesis will set, so that both elaborate the same circuit
    monkeypatch.setattr(
        bd, "crosscheck", lambda *a, **kw: calls.append(("crosscheck", kw["design_id"])) or Result([], [], 0, 0.0)
    )
    monkeypatch.setattr(bd, "build_gowin", lambda *a, **kw: calls.append(("synth", kw["design_id"])) or fake_fs(design))
    bd.build_design(design)
    assert calls == ["tools", "collect", "ips", ("crosscheck", 1), ("synth", 1)]


def fake_fs(design):
    fs = design / "build" / "top.fs"
    fs.parent.mkdir(exist_ok=True)
    fs.write_bytes(b"fake bitstream\n")
    return fs


def test_missing_tools_stop_before_the_crosscheck(design, monkeypatch):
    monkeypatch.setattr(bd, "check_yowasp", lambda: (False, "install"))
    monkeypatch.setattr(bd, "elaborate", lambda *a, **kw: pytest.fail("elaborated"))
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: pytest.fail("ran the crosscheck"))
    with pytest.raises(bd.ToolsMissing):
        bd.build_design(design, run=fake_run)


def test_crosscheck_errors_stop_before_synthesis(design, tools_ok, monkeypatch, capsys):
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: Result(SHIFTED, [], 9, 1.0))
    monkeypatch.setattr(bd, "build_gowin", lambda *a, **kw: pytest.fail("synthesized"))
    assert main(["build", str(design)]) == 1
    err = capsys.readouterr().err
    assert "the ips do not match the RTL; nothing was built" in err and "Fix the ips in nanopynq.toml" in err
    assert all(f"  error: {p.message}" in err for p in SHIFTED)
    assert not (design / "dist").exists()


def old_build(design):
    dist = design / "dist"
    dist.mkdir()
    for f in ("pwm.fs", "pwm.npq", "build.json", "notes.txt"):
        (dist / f).write_text("from an earlier build")
    return dist


def synth_fails(cmd, **kw):
    return CompletedProcess(cmd, 1, "", "ERROR: syntax error") if cmd[0] == "yowasp-yosys" else fake_run(cmd, **kw)


@pytest.mark.parametrize("why", ["config", "ips", "crosscheck", "synthesis", "writing the .npq"])
def test_a_failed_build_leaves_none_of_its_outputs_in_dist(design, tools_ok, monkeypatch, why):
    dist = old_build(design)
    run = fake_run
    if why == "config":
        edit(design, 'board = "tangnano9k"', 'board = "tangnano99k"')
    elif why == "ips":
        edit(design, 'base = "0x7000"', 'base = "0x2000"')
    elif why == "crosscheck":
        monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: Result(SHIFTED, [], 9, 1.0))
    elif why == "synthesis":
        run = synth_fails
    else:
        monkeypatch.setattr(bd, "write_npq", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(Exception):  # noqa: B017 (each case fails with its own exception)
        bd.build_design(design, run=run)
    assert sorted(p.name for p in dist.iterdir()) == ["notes.txt"]


def test_an_unreadable_config_deletes_nothing(design):
    dist = old_build(design)
    edit(design, 'name = "pwm"', 'name = "pwm')
    with pytest.raises(bd.ConfigError):
        bd.build_design(design, run=fake_run)
    assert len(list(dist.iterdir())) == 4


def test_crosscheck_warnings_are_shown_and_counted(design, tools_ok, monkeypatch, capsys):
    warn = Problem("ips.pwm.registers.count", "not_rw", "ips.pwm.registers.count (0x700c): defined rw")
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: Result([], [warn], 9, 1.0))
    dist = bd.build_design(design, run=fake_run)
    assert f"warning: {warn.message}" in capsys.readouterr().err
    assert json.loads((dist / "build.json").read_text())["crosscheck"] == {"skipped": False, "warnings": 1}


def test_no_crosscheck_skips_it_and_says_so(design, tools_ok, monkeypatch, capsys):
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: pytest.fail("ran the crosscheck"))
    monkeypatch.setattr(bd, "build_gowin", lambda *a, **kw: fake_fs(design))
    assert main(["build", "--no-crosscheck", str(design)]) == 0
    assert "skipped the check of the ips against the RTL (--no-crosscheck)" in capsys.readouterr().err
    assert json.loads((design / "dist" / "build.json").read_text())["crosscheck"] == {"skipped": True}
    assert "crosscheck" not in (design / "dist" / "pwm.npq").read_text()


def test_an_instance_left_out_is_shown_also_without_the_check(design, tools_ok, monkeypatch, capsys):
    monkeypatch.setattr(bd, "elaborate", lambda *a, **kw: own_netlist("pwm_timer", ADDR=0x7000))
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: pytest.fail("ran the crosscheck"))
    monkeypatch.setattr(bd, "build_gowin", lambda *a, **kw: fake_fs(design))
    assert main(["build", "--no-crosscheck", str(design)]) == 0
    assert (
        "not an IP: timer does not fit nanopynq's pwm_timer (pwm_timer.toml: unknown name 'BASE' (known: ADDR))\n"
        in capsys.readouterr().err
    )


def test_cli_reports_config_errors(design, capsys):
    edit(design, 'board = "tangnano9k"', 'board = "tangnano4k"')
    assert main(["build", str(design)]) == 1
    assert "board: nanopynq build does not support tangnano4k" in capsys.readouterr().err


def test_cli_reports_ips_rule_and_place(design, tools_ok, capsys):
    edit(design, 'registers.wraps = { offset = "0x10"', 'registers.wraps = { offset = "0x2000"')
    assert main(["build", str(design)]) == 1
    assert "V7 at ips.pwm.registers.wraps.offset" in capsys.readouterr().err


def test_cli_without_build_tools_says_how_to_install(design, monkeypatch, capsys):
    monkeypatch.setattr(bd, "check_yowasp", lambda: (False, "run: pip install nanopynq[build]"))
    assert main(["build", str(design)]) == 2
    assert "pip install nanopynq[build]" in capsys.readouterr().err


@pytest.mark.toolchain
def test_example_builds_and_its_design_id_reaches_sysinfo(example, capsys):
    design = example
    dist = bd.build_design(design)
    assert "checked the ips against the RTL: 0 warnings" in capsys.readouterr().err
    npq = load_npq(dist)
    assert npq.design_id == 0x556FAE35  # the collected ips are the ones the example used to write by hand
    # a top that does not hand DESIGN_ID down still builds; only the elaborated sysinfo shows it.
    # The repository copy: yowasp hides the host /tmp, where `design` is.
    reads = " ".join(f'"{p.as_posix()}"' for _, p in bd.load_config(EXAMPLE).sources)
    script = f"read_verilog {reads}; {chparam_design_id(npq.design_id)}hierarchy -top top; ls"
    r = subprocess.run(["yowasp-yosys", "-p", script], capture_output=True, text=True, cwd=design)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert f"sysinfo\\DESIGN_ID=32'{npq.design_id:032b}" in r.stdout


@pytest.mark.toolchain
def test_ips_off_the_rtl_stop_the_build_unless_the_check_is_skipped(tmp_path, capsys):
    design = tmp_path / "small"  # small: a check of the example takes about 14 s on two cores
    shutil.copytree(SMALL, design)
    edit(design, 'base = "0x1000"', 'base = "0x1100"')
    assert main(["build", str(design)]) == 1
    err = capsys.readouterr().err
    assert "error: ips.toy.registers.data (0x1100): every read returns 0xdeadbeef" in err, err
    assert not (design / "dist").exists() and (design / "build" / "crosscheck" / "design.il").is_file()
    assert main(["build", "--no-crosscheck", str(design)]) == 0
    assert "skipped the check" in capsys.readouterr().err
    assert sorted(p.name for p in (design / "dist").iterdir()) == ["build.json", "small.fs", "small.npq"]


# The examples with an IP of their own besides the adder: (folder, cell in top.v, module, IP, type, addr_range,
# parameters, registers as {name: (offset, width, access)}), as written in each nanopynq.toml.
OWN_IP_EXAMPLES = [
    (
        "tangnano9k_chaser",
        "chase",
        "chaser",
        "chaser",
        "fabricgate:chaser:1.0",
        0x14,
        {"clock_hz": 27000000, "width": 6},
        {
            "ctrl": (0, 2, "rw"),
            "pattern": (4, 6, "rw"),
            "rate": (8, 16, "rw"),
            "current": (0xC, 6, "ro"),
            "steps": (0x10, 32, "ro"),
        },
    ),
    (
        "tangnano9k_button_counter",
        "counter",
        "button_counter",
        "counter",
        "fabricgate:button_counter:1.0",
        0x8,
        {"debounce_ms": 20},
        {"count0": (0, 32, "ro"), "count1": (4, 32, "ro")},
    ),
    (
        "tangnano9k_crc32",
        "crc",
        "crc32",
        "crc",
        "fabricgate:crc32:1.0",
        0x10,
        {"polynomial": "0xedb88320"},
        {"init": (0, 1, "wo"), "data": (4, 8, "wo"), "crc": (8, 32, "ro"), "length": (0xC, 32, "ro")},
    ),
]


def _fake_own_ip_netlist(monkeypatch, cell, module):
    n = (
        pwm_netlist()
    )  # the pwm example's netlist with the example's module (no description: not collected) for the timer
    top = n["modules"]["top"]["cells"]
    top[cell] = {"type": module, "attributes": {}}
    del top["timer"]
    n["modules"][module] = {
        "attributes": {"hdlname": module},
        "cells": {},
        "parameter_default_values": {"BASE": f"{0x7000:032b}"},
    }
    n["modules"]["$paramod$6e\\regbus_gpio"]["parameter_default_values"]["WIDTH"] = f"{6:032b}"
    monkeypatch.setattr(bd, "check_yowasp", lambda: (True, "ok"))
    monkeypatch.setattr(bd, "elaborate", lambda *a, **kw: n)
    monkeypatch.setattr(bd, "crosscheck", lambda *a, **kw: Result([], [], 0, 0.0))


def _copy_examples(tmp_path, *names):
    for n in names:
        shutil.copytree(EXAMPLE.with_name(n), tmp_path / n, ignore=shutil.ignore_patterns("build", "dist", "README.md"))
    return tmp_path / names[-1]


@pytest.mark.parametrize(
    ("example", "cell", "module", "name", "type_", "addr_range", "params", "regs"),
    OWN_IP_EXAMPLES,
    ids=[e[0] for e in OWN_IP_EXAMPLES],
)
def test_own_ip_examples_read_their_hand_written_ip(
    tmp_path, monkeypatch, example, cell, module, name, type_, addr_range, params, regs
):
    design = _copy_examples(tmp_path, example)
    _fake_own_ip_netlist(monkeypatch, cell, module)
    dist = bd.build_design(design, run=fake_run)
    npq = load_npq(dist)
    assert list(npq.ips) == ["sys", "leds", "buttons", name]
    ip = npq.ips[name]
    assert (ip["phys_addr"], ip["type"], ip["addr_range"], ip["parameters"]) == (0x7000, type_, addr_range, params)
    assert {k: (r["offset"], r["width"], r["access"]) for k, r in ip["registers"].items()} == regs
    written = json.loads((dist / f"{bd.load_config(design).name}.npq").read_text(encoding="utf-8"))
    assert all(r.get("doc") for r in written["ips"][name]["registers"].values())  # the panel shows each one's doc


@pytest.mark.parametrize(
    ("example", "cell", "module", "name", "type_", "addr_range", "params", "regs"),
    OWN_IP_EXAMPLES,
    ids=[e[0] for e in OWN_IP_EXAMPLES],
)
def test_the_20k_examples_build_the_9k_circuits_for_the_20k_uart(
    tmp_path, monkeypatch, example, cell, module, name, type_, addr_range, params, regs
):
    """examples/tangnano20k_<x> reads the 9K example's RTL (../tangnano9k_<x>/<x>.v) and is built for the 20K's UART."""
    design = _copy_examples(tmp_path, example, example.replace("tangnano9k_", "tangnano20k_"))
    _fake_own_ip_netlist(monkeypatch, cell, module)
    d = bd.load_config(design)
    assert (d.board, d.sources[0][1]) == ("tangnano20k", tmp_path / design.name / ".." / example / f"{module}.v")
    npq = load_npq(bd.build_design(design, run=fake_run))
    assert (npq.board, npq.link) == ("tangnano20k", UART)
    ip = npq.ips[name]
    assert (ip["phys_addr"], ip["type"], ip["addr_range"], ip["parameters"]) == (0x7000, type_, addr_range, params)
    assert {k: (r["offset"], r["width"], r["access"]) for k, r in ip["registers"].items()} == regs


def test_the_20k_pwm_example_is_the_9k_one_on_the_20k_uart(tmp_path, tools_ok):
    design = _copy_examples(tmp_path, "tangnano20k_pwm")
    npq = load_npq(bd.build_design(design, run=fake_run))
    assert (npq.board, npq.link) == ("tangnano20k", UART)
    assert list(npq.ips) == ["sys", "leds", "buttons", "pwm"] and npq.ips["pwm"]["type"] == "nanopynq:pwm_timer:1.0"


def test_a_yosys_timeout_shows_its_output_as_text(tmp_path):
    """TimeoutExpired keeps what was captured as bytes, even with text=True: the log must not read b'...'."""

    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"], output=b"ABC: step 3\n")

    with pytest.raises(BuildError) as e:
        _yosys("read_verilog top.v", tmp_path, run)
    assert e.value.log.endswith("\nABC: step 3\n"), e.value.log

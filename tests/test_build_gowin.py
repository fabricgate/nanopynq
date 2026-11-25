import subprocess
import sys
import tempfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from nanopynq.boards import get_board
from nanopynq.build.gowin import build_gowin, chparam_design_id
from nanopynq.errors import BuildError

BOARDS_DIR = Path(__file__).resolve().parent.parent / "gateware" / "boards"
sys.path.insert(0, str(BOARDS_DIR.parent.parent / "tools"))
import build_base  # noqa: E402


def recorder(fail_on=None, fs_bytes=b"\n"):
    calls, kws = [], []

    def run(cmd, **kw):
        calls.append(cmd)
        kws.append(kw)
        if cmd[0] == "gowin_pack":  # like the real tool: relative outputs land in the cwd it is given
            (Path(kw["cwd"]) / cmd[cmd.index("-o") + 1]).write_bytes(fs_bytes)
        if fail_on and cmd[0] == fail_on:
            return CompletedProcess(cmd, 1, "out", "nextpnr: ERROR boom")
        return CompletedProcess(cmd, 0, "", "")

    run.kws = kws
    return calls, run


def test_build_commands_for_9k(tmp_path):
    calls, run = recorder()
    fs = build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path, run=run)
    assert fs == tmp_path / "top.fs"
    assert calls[0][:2] == ["yowasp-yosys", "-p"] and 'synth_gowin -top top -json "synth.json"' in calls[0][2]
    assert calls[1] == [
        "yowasp-nextpnr-himbaechel-gowin",
        "--json",
        "synth.json",
        "--write",
        "pnr.json",
        "--device",
        "GW1NR-LV9QN88PC6/I5",
        "--vopt",
        "family=GW1N-9C",
        "--vopt",
        "cst=" + Path("t.cst").resolve().as_posix(),
        "--seed",
        "1",
    ]
    assert calls[2] == ["gowin_pack", "-d", "GW1N-9C", "-c", "-o", "top.fs", "pnr.json"]
    assert all(kw["cwd"] == tmp_path for kw in run.kws)  # yowasp hides the host /tmp: nothing is addressed through it


def test_design_id_is_set_with_chparam_before_synthesis(tmp_path):
    calls, run = recorder()
    build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path, run=run, design_id=0xABF78D8C)
    assert "; chparam -set DESIGN_ID 32'habf78d8c top; synth_gowin -top top " in calls[0][2]
    calls, run = recorder()
    build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path, run=run, design_id=0)
    assert "chparam -set DESIGN_ID 32'h00000000 top;" in calls[0][2]
    calls, run = recorder()
    build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path, run=run)
    assert "chparam" not in calls[0][2]


@pytest.mark.parametrize("bad", [-1, 1 << 32])
def test_design_id_out_of_range_is_an_error(tmp_path, bad):
    calls, run = recorder()
    with pytest.raises(ValueError, match="32-bit"):
        build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path, run=run, design_id=bad)
    assert not calls


def test_4k_has_no_family_vopt_and_synth_flags(tmp_path):
    calls, run = recorder()
    build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano4k"), tmp_path, run=run)
    assert not any(a.startswith("family=") for a in calls[1])
    assert "-nolutram -nowidelut" in calls[0][2]
    assert "--mspi_as_gpio" in calls[2] and calls[2][2] == "GW1NS-4"


@pytest.mark.parametrize("board", ["tangnano9k", "tangnano4k"])
def test_never_randomizes_seed(tmp_path, board):
    calls, run = recorder()
    build_gowin([Path("top.v")], Path("t.cst"), get_board(board), tmp_path, run=run)
    flat = [a for c in calls for a in c]
    assert "-r" not in flat and "--randomize-seed" not in flat
    assert calls[1][-2:] == ["--seed", "1"]


def test_failed_step_raises_build_error_with_log(tmp_path):
    calls, run = recorder(fail_on="yowasp-nextpnr-himbaechel-gowin")
    with pytest.raises(BuildError) as e:
        build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path, run=run)
    assert (e.value.step, e.value.returncode) == ("pnr", 1)
    assert "ERROR boom" in e.value.log
    assert len(calls) == 2  # pack never ran


def test_fs_is_normalised_to_lf(tmp_path):
    _, run = recorder(fs_bytes=b"a\r\nb\r\n\x00\rc\n")
    fs = build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path, run=run)
    assert fs.read_bytes() == b"a\nb\n\x00\rc\n"


@pytest.mark.toolchain
@pytest.mark.parametrize("board", ["tangnano4k", "tangnano9k"])
def test_real_blinky_build(tmp_path, board):
    d = BOARDS_DIR / board
    fs = build_gowin([d / "blinky.v"], d / "blinky.cst", get_board(board), tmp_path)
    assert fs.stat().st_size > 1000
    assert b"\r" not in fs.read_bytes()


@pytest.mark.toolchain
def test_real_9k_base_build_with_design_id(tmp_path):
    d = BOARDS_DIR / "tangnano9k"
    fs = build_gowin(
        build_base.sources("tangnano9k", "base"),
        d / "tangnano9k.cst",
        get_board("tangnano9k"),
        tmp_path,
        design_id=0xABF78D8C,
    )
    assert fs.stat().st_size > 1000


@pytest.mark.toolchain
@pytest.mark.parametrize("board, design", [(b, d) for d, spec in build_base.DESIGNS.items() for b in spec[2]])
def test_design_id_reaches_sysinfo_in_every_top(tmp_path, board, design):
    # A top that takes DESIGN_ID but does not hand it down still builds; only the elaborated sysinfo shows it.
    reads = build_base.yosys_reads(build_base.sources(board, design))  # the .sv of ddr3 need -sv and the include dir
    script = f"{reads}; {chparam_design_id(0xABF78D8C)}hierarchy -top top; ls"
    r = subprocess.run(["yowasp-yosys", "-p", script], capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert f"sysinfo\\DESIGN_ID=32'{0xABF78D8C:032b}" in r.stdout


def test_relative_inputs_resolve_against_the_callers_cwd(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "elsewhere"))  # keep these inputs "outside temp"
    calls, run = recorder()
    build_gowin([Path("top.v")], Path("t.cst"), get_board("tangnano9k"), tmp_path / "out", run=run)
    assert f'read_verilog "{(work / "top.v").resolve().as_posix()}"' in calls[0][2]
    assert "cst=" + (work / "t.cst").resolve().as_posix() in calls[1]


def test_inputs_under_the_temp_dir_are_copied_into_out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    src = tmp_path / "tmp" / "a"
    src.mkdir(parents=True)
    (src / "top.v").write_text("module top; endmodule")
    (src / "t.cst").write_text("cst")
    calls, run = recorder()
    build_gowin([src / "top.v"], src / "t.cst", get_board("tangnano9k"), tmp_path / "out", run=run)
    assert 'read_verilog "top.v"' in calls[0][2] and "cst=t.cst" in calls[1]
    assert (tmp_path / "out" / "top.v").read_text() == "module top; endmodule"
    assert (tmp_path / "out" / "t.cst").read_text() == "cst"


def test_inputs_outside_the_temp_dir_stay_absolute_and_are_not_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "top.v").write_text("x")
    calls, run = recorder()
    build_gowin(
        [tmp_path / "repo" / "top.v"], tmp_path / "repo" / "t.cst", get_board("tangnano9k"), tmp_path / "out", run=run
    )
    assert f'read_verilog "{(tmp_path / "repo" / "top.v").resolve().as_posix()}"' in calls[0][2]
    assert not (tmp_path / "out" / "top.v").exists()


def test_inputs_already_in_out_dir_are_passed_relative(tmp_path):
    (tmp_path / "top.v").write_text("x")
    calls, run = recorder()
    build_gowin([tmp_path / "top.v"], tmp_path / "t.cst", get_board("tangnano9k"), tmp_path, run=run)
    assert 'read_verilog "top.v"' in calls[0][2] and "cst=t.cst" in calls[1]


def test_same_named_temp_inputs_are_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    for d in ("a", "b"):
        (tmp_path / "tmp" / d).mkdir(parents=True)
        (tmp_path / "tmp" / d / "top.v").write_text(d)
    calls, run = recorder()
    with pytest.raises(ValueError, match=r"two inputs named 'top.v'"):
        build_gowin(
            [tmp_path / "tmp" / "a" / "top.v", tmp_path / "tmp" / "b" / "top.v"],
            Path("t.cst"),
            get_board("tangnano9k"),
            tmp_path / "out",
            run=run,
        )
    assert not calls

import subprocess
import sys
from pathlib import Path

import pytest

from nanopynq.boards import get_board, npq_family, npq_link
from nanopynq.npq import design_id, load_npq, write_npq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_base as bb  # noqa: E402

ALL = [(board, d) for d, spec in bb.DESIGNS.items() for board in spec[2]]


@pytest.mark.parametrize(
    "board, design, want",
    [
        ("tangnano9k", "base", 0xABF78D8C),
        ("tangnano20k", "base", 0xABF78D8C),
        ("tangnano4k", "base", 0x79D574B7),
        ("tangnano4k", "camstream", 0xCA950154),
        ("tangnano20k", "sdram", 0x1EF753EF),
        ("tangmega138kpro", "base", 0xABF78D8C),
    ],
)
def test_bundled_ips_give_the_spec_design_ids(board, design, want):  # spec 5.4 and 6
    assert design_id(bb.ips(board, design)) == want


@pytest.mark.parametrize("board, design", ALL)
def test_every_designs_ips_can_be_written_to_a_npq(tmp_path, board, design):  # list parameters (pllcheck, pwm)
    fs = tmp_path / "base.fs"
    fs.write_bytes(b"dummy bitstream")
    b = get_board(board)
    npq = write_npq(fs, board, npq_family(b), npq_link(b, b.host_link["kind"]), bb.ips(board, design))
    assert load_npq(npq).design_id == design_id(bb.ips(board, design))


@pytest.mark.parametrize("board, design", ALL)
def test_listed_sources_exist(board, design):
    assert all(p.is_file() for p in bb.sources(board, design))


def test_build_record_has_no_absolute_paths():
    srcs = bb.sources("tangnano9k", "base")
    rec = bb.build_record("tangnano9k", "base", 1, srcs, bb.GATEWARE / "boards/tangnano9k/tangnano9k.cst", "0" * 64, {})
    assert [s["file"] for s in rec["sources"]][-2:] == [
        "gateware/boards/tangnano9k/top.v",
        "gateware/boards/tangnano9k/tangnano9k.cst",
    ]
    assert str(ROOT) not in repr(rec) and isinstance(rec["dirty"], bool) and len(rec["commit"]) == 40


def test_tool_versions_are_read_with_the_oss_lib_on_path(tmp_path, monkeypatch):
    # Windows: the oss-cad-suite exes need their DLLs in OSS/lib, or -V exits 0xC0000135 and records null
    oss, ovl, chipdb = tmp_path / "oss", tmp_path / "ovl", tmp_path / "chipdb.bin"
    (ovl / "apycula").mkdir(parents=True)
    chipdb.write_bytes(b"db")
    for k, v in {"OSS": oss, "OVL": ovl, "CHIPDB": chipdb}.items():
        monkeypatch.setenv(k, str(v))
    oss.mkdir()
    paths = []
    monkeypatch.setattr(bb.shutil, "which", lambda name, path: name)
    monkeypatch.setattr(
        bb.subprocess,
        "run",
        lambda cmd, **kw: paths.append(kw["env"]["PATH"]) or subprocess.CompletedProcess(cmd, 0, f"{cmd[0]} 1.0\n", ""),
    )
    rec = bb.tools_record(jtag=True)
    assert (rec["yosys"], rec["nextpnr"]) == ("yosys 1.0", "nextpnr-himbaechel 1.0")
    assert all(p.split(bb.os.pathsep)[:2] == [str(oss / "bin"), str(oss / "lib")] for p in paths) and len(paths) == 2


@pytest.mark.toolchain
@pytest.mark.parametrize("board, design", ALL)
def test_listed_sources_elaborate(tmp_path, board, design):
    # synth_gowin's begin step: the vendor cell libraries, then hierarchy -check -top top
    synth_args = " ".join(get_board(board).synth_args)
    script = f"{bb.yosys_reads(bb.sources(board, design))}; synth_gowin -top top {synth_args} -run :coarse"
    r = subprocess.run(["yowasp-yosys", "-q", "-p", script], capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


@pytest.mark.parametrize("design,compressed", [("base", True), ("sdram", False)])
def test_sdram_packs_without_compression(tmp_path, monkeypatch, design, compressed):
    monkeypatch.setenv("OSS", str(tmp_path))
    monkeypatch.setenv("OVL", str(tmp_path))
    monkeypatch.setenv("CHIPDB", str(tmp_path))
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "apycula.gowin_pack" in cmd:
            (tmp_path / "top.fs").write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bb.subprocess, "run", fake_run)
    bb.build_jtag_local([], tmp_path / "x.cst", get_board("tangnano20k"), tmp_path, 1, design=design)
    pack = next(c for c in calls if "apycula.gowin_pack" in c)
    assert ("-c" in pack) is compressed


def test_yosys_reads_keep_the_plain_form_without_sv(tmp_path):
    srcs = [tmp_path / "a.v", tmp_path / "b.v"]
    assert bb.yosys_reads(srcs) == f'read_verilog "{srcs[0].as_posix()}" "{srcs[1].as_posix()}"'


def test_ddr3_reads_sv_with_the_rtl_incdir():
    reads = bb.yosys_reads(bb.sources("tangmega138kpro", "ddr3"))
    assert f'read_verilog -defer -sv -I {bb.RTL.as_posix()} "{(bb.RTL / "ddr3" / "ddr3_ctrl.sv").as_posix()}"' in reads
    assert reads.index("ddr3_ctrl.sv") < reads.index("ddr3_top.v")  # the top comes last


def test_ddr3_builds_with_the_fork_tools(tmp_path, monkeypatch):
    for k in ("OSS", "DDR3_OVL", "DDR3_CHIPDB"):
        monkeypatch.setenv(k, str(tmp_path))
    (tmp_path / "nextpnr.sh").write_text("")
    monkeypatch.setenv("DDR3_NEXTPNR", str(tmp_path / "nextpnr.sh"))
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("env", {}).get("PYTHONPATH")))
        if "apycula.gowin_pack" in cmd:
            (tmp_path / "top.fs").write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bb.subprocess, "run", fake_run)
    bb.build_jtag_local(
        [], tmp_path / "x.cst", get_board("tangmega138kpro"), tmp_path, 1, design="ddr3", env_prefix="DDR3_"
    )
    pnr = next(c for c, _ in calls if "--chipdb" in c)
    assert pnr[:2] == [bb.shutil.which("bash") or "bash", str(tmp_path / "nextpnr.sh")]  # a .sh goes through bash
    pack, pythonpath = next((c, pp) for c, pp in calls if "apycula.gowin_pack" in c)
    assert pythonpath == str(tmp_path) and "--cpu_as_gpio" in pack


def test_fork_tools_are_recorded(tmp_path, monkeypatch):
    oss, ovl, chipdb, nextpnr = tmp_path / "oss", tmp_path / "ovl", tmp_path / "chipdb.bin", tmp_path / "nextpnr.sh"
    (ovl / "apycula").mkdir(parents=True)
    (ovl / "apycula" / "GW5AST-138C.msgpack.xz").write_bytes(b"db")
    oss.mkdir()
    chipdb.write_bytes(b"chip")
    nextpnr.write_text("")
    for k, v in {"OSS": oss, "DDR3_OVL": ovl, "DDR3_CHIPDB": chipdb, "DDR3_NEXTPNR": nextpnr}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(bb.shutil, "which", lambda name, path: name)

    def fake_run(cmd, **kw):
        if str(nextpnr) in cmd:
            assert cmd[-1] == "--source-commit"
            return subprocess.CompletedProcess(cmd, 0, "nextpnr 7b1ae4cd image sha256:abc\n", "")
        out = {"yosys": "yosys 1.0\n", "git": "fd1b65b\n"}
        return subprocess.CompletedProcess(cmd, 0, out.get(cmd[0], ""), "")

    monkeypatch.setattr(bb.subprocess, "run", fake_run)
    rec = bb.tools_record(jtag=False, env_prefix="DDR3_")
    assert rec["yosys"] == "yosys 1.0" and rec["nextpnr"] == "nextpnr 7b1ae4cd image sha256:abc"
    assert rec["apicula"]["commit"] == "fd1b65b" and rec["apicula"]["db_image"] == "pepijndevos/apicula:1.9.10.03"
    assert rec["apicula"]["db"] == {"GW5AST-138C.msgpack.xz": bb._sha256(ovl / "apycula" / "GW5AST-138C.msgpack.xz")}
    assert rec["chipdb"] == {"file": "chipdb.bin", "sha256": bb._sha256(chipdb)}
    assert str(tmp_path) not in repr(rec)

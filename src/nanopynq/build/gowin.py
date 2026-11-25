import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from nanopynq.boards import BoardInfo
from nanopynq.errors import BuildError


def tool_path(p: Path, out_dir: Path, copied: dict[str, Path]) -> str:
    """Path of an input as the tools (run with cwd=out_dir) must be given it.

    yowasp-runtime maps its own temp dir over the WASM-side /tmp, hiding the host temp dir, so an input
    under it is copied into out_dir; one already in out_dir is passed relative; any other is absolute.
    """
    p = Path(p).resolve()
    if p.is_relative_to(out_dir):
        return p.relative_to(out_dir).as_posix()
    if not p.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        return p.as_posix()
    if copied.get(p.name, p) != p:
        raise ValueError(f"two inputs named {p.name!r} under the temp dir ({copied[p.name]} and {p}); rename one")
    copied[p.name] = p
    shutil.copyfile(p, out_dir / p.name)
    return p.name


def chparam_design_id(design_id: int | None, top: str = "top") -> str:
    """yosys command that sets top's DESIGN_ID (sysinfo +0xc), or "" for None (the RTL default, 0)."""
    if design_id is None:
        return ""
    if not 0 <= design_id <= 0xFFFF_FFFF:
        raise ValueError(f"design_id {design_id!r} is not a 32-bit unsigned value")
    return f"chparam -set DESIGN_ID 32'h{design_id:08x} {top}; "


def build_gowin(
    sources: list[Path],
    cst: Path,
    board: BoardInfo,
    out_dir: Path,
    top: str = "top",
    seed: int = 1,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    design_id: int | None = None,
) -> Path:
    """Verilog -> .fs via YoWASP yosys / nextpnr-himbaechel-gowin / Apicula gowin_pack.

    design_id: sets the top module's DESIGN_ID parameter; a top without one makes yosys stop with an error.

    All paths go to the tools as forward-slash strings (YoWASP's WASI runtime needs that on Windows).
    """
    chparam = chparam_design_id(design_id, top)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # The tools run with cwd=out_dir and write their outputs by relative name (see tool_path for inputs).
    abs_out, copied = out_dir.resolve(), dict[str, Path]()
    synth_json, pnr_json, fs_name = "synth.json", "pnr.json", f"{top}.fs"
    fs = out_dir / fs_name

    reads = " ".join(f'"{tool_path(s, abs_out, copied)}"' for s in sources)
    synth = (
        f'read_verilog {reads}; {chparam}synth_gowin -top {top} -json "{synth_json}" {" ".join(board.synth_args)}'
    ).rstrip()
    pnr = ["yowasp-nextpnr-himbaechel-gowin", "--json", synth_json, "--write", pnr_json, "--device", board.device]
    if board.family:
        pnr += ["--vopt", f"family={board.family}"]
    pnr += ["--vopt", "cst=" + tool_path(cst, abs_out, copied), "--seed", str(seed)]
    pack = ["gowin_pack", "-d", board.pack_device, *board.pack_args, "-o", fs_name, pnr_json]

    for step, cmd in (("synth", ["yowasp-yosys", "-p", synth]), ("pnr", pnr), ("pack", pack)):
        r = run(cmd, capture_output=True, text=True, cwd=out_dir)
        if r.returncode != 0:
            raise BuildError(step, r.returncode, (r.stdout or "") + (r.stderr or ""))
    # Apycula writes the .fs in text mode (CRLF on Windows); LF is the canonical form so the hash is OS-independent.
    fs.write_bytes(fs.read_bytes().replace(b"\r\n", b"\n"))
    return fs

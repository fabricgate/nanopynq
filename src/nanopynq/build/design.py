"""`nanopynq build`: a design folder with nanopynq.toml -> dist/<name>.fs + <name>.npq + build.json (spec 5.6).

nanopynq.toml (unknown keys are errors, so a misspelt optional key cannot silently change the .fs):

    name = "pwm"                  # dist/pwm.fs, dist/pwm.npq
    board = "tangnano9k"
    top = "top"                   # optional, default "top"; must take a DESIGN_ID parameter
    seed = 1                      # optional, default 1
    sources = ["nanopynq:base_regs.v", ..., "top.v"]   # read in this order; nanopynq:<file> is the shared RTL
    constraints = "pwm.cst"
    [ips.pwm]                     # optional: the ips are collected from the RTL (collect.py); here only what it
    parameters = { clock_hz = 27000000 }   # does not hold, instance = "<path>" to name an instance, or a whole
                                  # IP (spec 5.3, with base) that the RTL does not describe or that replaces one
    [check]                       # optional: the check of the ips against the RTL (crosscheck.py)
    inputs = { btn = 0 }          # top inputs held at a value during the check
    depth = 32                    # clocks from configuration the check unrolls

The link (uart, baudrate) comes from the board: boards.yaml host_link, or uart_link where host_link is JTAG.
Intermediate files go to build/, the ips the build used to build/ips.json.
"""

import hashlib
import importlib.metadata as md
import json
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from nanopynq.boards import BoardInfo, get_board, list_boards, uart_link
from nanopynq.build.collect import CollectError as CollectError  # re-exported: __main__ catches it from here
from nanopynq.build.collect import collect, elaborate, load_descriptions, merge
from nanopynq.build.crosscheck import Result, _family, crosscheck
from nanopynq.build.gowin import build_gowin
from nanopynq.doctor import check_yowasp
from nanopynq.npq import FILE, design_id, write_npq

CONFIG = "nanopynq.toml"
RTL_DIR = Path(str(files("nanopynq").joinpath("rtl")))
RTL_PREFIX = "nanopynq:"
REQUIRED = ("name", "board", "sources", "constraints")
OPTIONAL = {"top": "top", "seed": 1, "check": {}, "ips": {}}
CHECK = {"inputs": {}, "depth": 32}
VERILOG_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
TOOLS = ("yowasp-yosys", "yowasp-nextpnr-himbaechel-gowin", "Apycula", "yowasp-runtime", "wasmtime")


class ConfigError(ValueError):
    """nanopynq.toml is missing, unreadable or wrong; the message names the key."""


class ToolsMissing(RuntimeError):
    """The [build] extra (YoWASP yosys, nextpnr, Apicula) is not installed or not on PATH."""


class CrosscheckFailed(Exception):
    """The ips do not match the RTL, or the design cannot be checked; `result` lists every problem."""

    def __init__(self, result: Result):
        super().__init__(f"the ips do not match the RTL ({len(result.errors)} errors)")
        self.result = result


@dataclass(frozen=True)
class Design:
    folder: Path
    name: str
    board: str
    top: str
    seed: int
    sources: list[tuple[str, Path]]  # (as written in nanopynq.toml, resolved path), in reading order
    constraints: tuple[str, Path]
    ips: dict[str, dict[str, Any]]  # nanopynq.toml's [ips]: laid over the ips collected from the RTL (collect.merge)
    check_inputs: dict[str, int]
    check_depth: int


def _resolve(folder: Path, entry: Any, key: str) -> tuple[str, Path]:
    if type(entry) is not str or not entry:
        raise ConfigError(f"{key}: must be a file name, got {entry!r}")
    if '"' in entry:  # the tools get the names in double quotes
        raise ConfigError(f"{key}: {entry!r} must not contain '\"'")
    if entry.startswith(RTL_PREFIX):
        name = entry[len(RTL_PREFIX) :]
        p = RTL_DIR / name
        if "/" in name or "\\" in name or not p.is_file():
            known = ", ".join(sorted(f.name for f in RTL_DIR.glob("*.v")))
            raise ConfigError(f"{key}: {entry!r} is not a shared RTL file; there are: {known}")
        return entry, p
    p = folder / entry
    if not p.is_file():
        raise ConfigError(f"{key}: {p} not found")
    return entry, p


def _check_table(check: Any) -> dict[str, Any]:
    if type(check) is not dict:
        raise ConfigError("check: must be a table ([check])")
    for k in check:
        if k not in CHECK:
            raise ConfigError(f"check.{k}: unknown key (known: {', '.join(CHECK)})")
    check = CHECK | check
    if type(check["inputs"]) is not dict:
        raise ConfigError("check.inputs: must be a table of top input names and integers, e.g. { btn = 0 }")
    for name, v in check["inputs"].items():
        if not VERILOG_ID.fullmatch(name):
            raise ConfigError(f"check.inputs: {name!r} is not a Verilog port name")
        if type(v) is not int or not 0 <= v < 2**32:
            raise ConfigError(f"check.inputs.{name}: must be an integer 0 .. 2^32 - 1, got {v!r}")
    if type(check["depth"]) is not int or not 1 <= check["depth"] <= 1000:
        raise ConfigError(f"check.depth: must be an integer 1 .. 1000, got {check['depth']!r}")
    return cast(dict[str, Any], check)


def load_config(folder: Path) -> Design:
    """Read and check nanopynq.toml in `folder` (all but the ips' contents: collect.merge and then design_id check
    them, against spec 5.9)."""
    folder = Path(folder)
    path = folder / CONFIG
    try:
        cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"not found; a design folder needs a {CONFIG}") from None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(str(e)) from None
    for k in cfg:
        if k not in REQUIRED and k not in OPTIONAL:
            raise ConfigError(f"{k}: unknown key (known: {', '.join([*REQUIRED, *OPTIONAL])})")
    for k in REQUIRED:
        if k not in cfg:
            raise ConfigError(f"{k}: missing")
    cfg = OPTIONAL | cfg
    if type(cfg["name"]) is not str or not FILE.fullmatch(cfg["name"]) or len(cfg["name"]) > 250:
        raise ConfigError(f"name: {cfg['name']!r} must be letters, digits, '.', '_' or '-' (it names the files)")
    if type(cfg["top"]) is not str or not VERILOG_ID.fullmatch(cfg["top"]):
        raise ConfigError(f"top: {cfg['top']!r} is not a Verilog module name")
    if type(cfg["seed"]) is not int or not 0 <= cfg["seed"] < 2**31:
        raise ConfigError(f"seed: must be an integer 0 .. 2^31 - 1, got {cfg['seed']!r}")
    board = cfg["board"]
    if board not in list_boards():
        raise ConfigError(f"board: unknown board {board!r} (known: {', '.join(list_boards())})")
    if uart_link(get_board(board)) is None:
        uart = ", ".join(b for b in list_boards() if uart_link(get_board(b)) is not None)
        raise ConfigError(
            f"board: nanopynq build does not support {board} yet (its JTAG link needs tools that pip "
            f"does not install); the supported boards are {uart}"
        )
    if type(cfg["sources"]) is not list or not cfg["sources"]:
        raise ConfigError("sources: must be a non-empty list of files, in the order yosys reads them")
    if type(cfg["ips"]) is not dict:
        raise ConfigError("ips: must be a table of IPs ([ips.pwm], ...)")
    for name, ip in cfg["ips"].items():
        if type(ip) is not dict:
            raise ConfigError(f"ips.{name}: must be a table ([ips.{name}])")
        if "instance" in ip and type(ip["instance"]) is not str:
            raise ConfigError(f'ips.{name}.instance: must be a string, the instance\'s path (e.g. "regs.gpio_leds")')
    check = _check_table(cfg["check"])
    return Design(
        folder=folder,
        name=cfg["name"],
        board=board,
        top=cfg["top"],
        seed=cfg["seed"],
        sources=[_resolve(folder, s, f"sources[{i}]") for i, s in enumerate(cfg["sources"])],
        constraints=_resolve(folder, cfg["constraints"], "constraints"),
        ips=cfg["ips"],
        check_inputs=check["inputs"],
        check_depth=check["depth"],
    )


def _version(dist: str) -> str | None:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:  # tools on PATH but not from pip, or nanopynq run from a source tree
        return None


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _outputs(folder: Path, name: str) -> list[Path]:
    dist = Path(folder) / "dist"
    return [dist / f"{name}.fs", dist / f"{name}.npq", dist / "build.json"]


def _clear_outputs(folder: Path) -> None:
    """Delete what this build writes to dist/, so that a failed build leaves no older or partial design there.
    Without a readable name in nanopynq.toml there is nothing to tell which files those are."""
    try:
        name = tomllib.loads((Path(folder) / CONFIG).read_text(encoding="utf-8")).get("name")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return
    if type(name) is str and FILE.fullmatch(name) and len(name) <= 250:
        for p in _outputs(folder, name):
            p.unlink(missing_ok=True)


def _ips(
    d: Design, board: BoardInfo, work: Path, run: Callable[..., subprocess.CompletedProcess[str]]
) -> dict[str, dict[str, Any]]:
    """The ips: collected from the RTL, nanopynq.toml's [ips] over them; shown on stderr, written to build/ips.json."""
    netlist = elaborate([p for _, p in d.sources], work / "elaborate", top=d.top, family=_family(board), run=run)
    ips, origin, left_out = merge(collect(netlist, load_descriptions(), d.top), d.ips)
    print(f"the ips (from the RTL, or from {CONFIG}):", file=sys.stderr)
    for name, ip in ips.items():
        print(f"  {name:<8} {ip.get('base')!s:<7} {ip.get('type')!s:<23} {origin[name] or CONFIG}", file=sys.stderr)
    for why in left_out:
        print(f"not an IP: {why}", file=sys.stderr)
    work.mkdir(parents=True, exist_ok=True)
    # before design_id checks them, to show what failed; default=str: a TOML date breaks a rule there, not here
    (work / "ips.json").write_bytes((json.dumps(ips, indent=2, default=str) + "\n").encode("utf-8"))
    return ips


def build_design(
    folder: Path, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run, check: bool = True
) -> Path:
    """Spec 5.6 for the design in `folder`; returns the dist folder. Raises ConfigError, ToolsMissing, CollectError
    (the ips cannot be collected from the RTL as nanopynq.toml says), NpqError (the ips break a rule of spec 5.9),
    ManifestError (reserved design_id), CrosscheckFailed (the ips do not match the RTL) or BuildError (a tool
    failed; work files in build/). check=False skips the check against the RTL. The check's warnings go to
    stderr."""
    _clear_outputs(folder)
    d = load_config(folder)
    ok, msg = check_yowasp()
    if not ok:
        raise ToolsMissing(msg)
    board = get_board(d.board)
    work, dist = d.folder / "build", d.folder / "dist"
    stale = [p.name for p in dist.glob("*.npq") if p.name != f"{d.name}.npq"]
    if stale:  # Overlay(dist) needs exactly one .npq
        raise ConfigError(f"{dist} holds {', '.join(stale)} from an earlier name; delete it and build again")
    ips = _ips(d, board, work, run)
    did = design_id(ips)  # also checks the ips (spec 5.4 step 0)
    if check:
        res = crosscheck(
            ips,
            [p for _, p in d.sources],
            board,
            work / "crosscheck",
            top=d.top,
            depth=d.check_depth,
            inputs=d.check_inputs,
            design_id=did,
            run=run,
        )
        if not res.ok:
            raise CrosscheckFailed(res)
        for w in res.warnings:
            print(f"warning: {w.message}", file=sys.stderr)
        print(
            f"checked the ips against the RTL: {len(res.warnings)} warnings ({res.queries} queries, "
            f"{res.seconds:.1f} s)",
            file=sys.stderr,
        )
    else:
        print("skipped the check of the ips against the RTL (--no-crosscheck)", file=sys.stderr)
    fs = build_gowin(
        [p for _, p in d.sources], d.constraints[1], board, work, top=d.top, seed=d.seed, design_id=did, run=run
    )
    dist.mkdir(exist_ok=True)
    out = dist / f"{d.name}.fs"
    link = uart_link(board)
    assert link is not None  # load_config refused a board without a UART link
    try:
        shutil.copyfile(fs, out)
        write_npq(out, d.board, link, ips)
        record = {
            "design": d.name,
            "board": d.board,
            "command": "nanopynq build",
            "nanopynq": _version("nanopynq"),
            "top": d.top,
            "seed": d.seed,
            "freq_mhz": board.clock_hz / 1e6,  # the clock timing was checked at (nextpnr --freq)
            "sources": [{"file": s, "sha256": _sha256(p)} for s, p in [*d.sources, d.constraints]],
            "tools": {t: _version(t) for t in TOOLS},
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.machine()}",
            "design_id": f"0x{did:08x}",
            "crosscheck": {"skipped": False, "warnings": len(res.warnings)} if check else {"skipped": True},
            "bitstream_sha256": _sha256(out),
        }
        (dist / "build.json").write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))
    except BaseException:  # no .fs without its .npq and build.json
        for p in _outputs(d.folder, d.name):
            p.unlink(missing_ok=True)
        raise
    return dist

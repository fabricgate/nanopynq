"""Check a design's ips against its RTL before synthesis (issue #27), with YoWASP yosys only.

The host bridge is replaced by a bus master that does "read A, write W to A, read A" after reset, and yosys'
`sat` (bounded model check over `depth` clocks) proves properties of that sequence on the flattened design:

  done       for every address, the three bus cycles finish in time              else error: cannot check
  canary     with the address pinned, some trace reaches done                    else error: cannot check
  no_slave   per register: some trace reads a value other than 0xdeadbeef        else error
  undeclared per IP range: every address that is not a register reads 0xdeadbeef, else error (warning for an
             before and after the write                                            IP with streams)
  outside    every address in no IP's range reads 0xdeadbeef, before and after   else error
             the write
  not_rw     rw: the read after the write gives W & mask(width)                  else warning
  not_ro     ro: that does not hold                                              else warning
  width      ro: the bits above the width read 0                                 else warning

Why the canary and one no_slave query per register: when the assumptions contradict each other, every `sat
-prove` passes (reports/report_crosscheck_spike.md section 1); then the canary fails and every register is
reported. The design must hold exactly one uartbone_bridge, and unmapped addresses must read 0xdeadbeef.
"""

import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from nanopynq.boards import BoardInfo
from nanopynq.build.gowin import chparam_design_id, tool_path
from nanopynq.errors import BuildError
from nanopynq.manifest import DEFAULT_ADDR_RANGE

MAX_WORKERS = 8
TIMEOUT = 600

# adr / wdat / mask are $anyconst: one value for the whole trace, free or pinned by sat -set. A register without
# init that holds itself does not work: opt_dff ties it to 'x, which sat reads as 0 (report section 1).
MASTER = """
module npqchk_master (
    input clk, input rst,
    output [29:0] bus_adr, output [31:0] bus_dat_w, input [31:0] bus_dat_r,
    output bus_we, output bus_stb, input bus_ack);
    (* anyconst *) reg [29:0] npqchk_adr;
    (* anyconst *) reg [31:0] npqchk_wdat, npqchk_mask;
    reg [1:0] op = 2'd0;  // 0 read r1, 1 write wdat, 2 read r2, 3 done
    reg stb = 1'b0;
    reg [31:0] r1 = 32'd0, r2 = 32'd0;
    assign bus_adr = npqchk_adr;
    assign bus_dat_w = npqchk_wdat;
    assign bus_we = (op == 2'd1);
    assign bus_stb = stb;
    always @(posedge clk) begin
        if (rst) begin
            op <= 2'd0; stb <= 1'b0;
        end else if (op != 2'd3) begin
            if (!stb) stb <= 1'b1;
            else if (bus_ack) begin  // the bridges' protocol: stb held until ack
                stb <= 1'b0;
                if (op == 2'd0) r1 <= bus_dat_r;
                if (op == 2'd2) r2 <= bus_dat_r;
                op <= op + 2'd1;
            end
        end
    end
    wire done = (op == 2'd3);
    wire defined = @DEFINED@;
    (* keep *) wire [31:0] npqchk_r1 = r1;
    (* keep *) wire [31:0] npqchk_r2 = r2;
    (* keep *) wire npqchk_done = done;
    (* keep *) wire npqchk_r1_unmapped = !done || r1 == 32'hDEAD_BEEF;
    (* keep *) wire npqchk_rw = !done || r2 == (npqchk_wdat & npqchk_mask);
    (* keep *) wire npqchk_hi_zero = !done || (r1 & ~npqchk_mask) == 32'd0;
    wire unmapped = r1 == 32'hDEAD_BEEF && r2 == 32'hDEAD_BEEF;
    (* keep *) wire npqchk_out_unmapped = @INSIDE_ANY@ || !done || unmapped;
@RANGES@
endmodule
"""
# jtag_bridge (4K / 20K) gets the same kind of override when nanopynq build takes JTAG boards.
BRIDGE = """
module uartbone_bridge #(parameter CLK_HZ = 0, parameter BAUD = 0, parameter TIMEOUT_CYCLES = 0) (
    input clk, input rst, input uart_rx, output uart_tx,
    output [29:0] bus_adr, output [31:0] bus_dat_w, input [31:0] bus_dat_r,
    output bus_we, output bus_stb, input bus_ack);
    assign uart_tx = 1'b1;
    npqchk_master npqchk (.clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w),
        .bus_dat_r(bus_dat_r), .bus_we(bus_we), .bus_stb(bus_stb), .bus_ack(bus_ack));
endmodule
"""


@dataclass(frozen=True)
class Problem:
    where: str  # ips.<ip>.registers.<reg>, an address (0x7010), check.inputs.<name> or the top
    kind: str  # cannot_check, no_slave, undeclared, outside, not_rw, not_ro, width
    message: str


@dataclass(frozen=True)
class Result:
    errors: list[Problem]
    warnings: list[Problem]
    queries: int
    seconds: float

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class _Query:
    kind: str
    args: str
    ip: str | None = None
    reg: str | None = None
    addr: int | None = None


def _registers(ips: dict):
    for ip_name, ip in ips.items():
        for reg_name, r in (ip.get("registers") or {}).items():
            yield ip_name, reg_name, int(ip["base"], 16) + int(r["offset"], 16), r


def _range(ip: dict) -> tuple[int, int]:
    base = int(ip["base"], 16)
    return base, base + int(ip.get("addr_range", hex(DEFAULT_ADDR_RANGE)), 16)


def master_verilog(ips: dict) -> str:
    words = sorted({a >> 2 for *_, a, _ in _registers(ips)})
    defined = " || ".join(f"npqchk_adr == 30'h{w:x}" for w in words) or "1'b0"
    inside, ranges = [], []
    for i, ip in enumerate(ips.values()):
        lo, hi = _range(ip)
        cond = f"({{1'b0, npqchk_adr}} >= 31'h{lo >> 2:x} && {{1'b0, npqchk_adr}} < 31'h{hi >> 2:x})"
        inside.append(cond)
        ranges.append(f"    (* keep *) wire npqchk_in{i}_unmapped = !{cond} || defined || !done || unmapped;")
    return (
        MASTER.replace("@DEFINED@", defined)
        .replace("@INSIDE_ANY@", "(" + " || ".join(inside) + ")")
        .replace("@RANGES@", "\n".join(ranges))
        + BRIDGE
    )


def _family(board: BoardInfo) -> str:
    """The cell library family: synth_gowin's -family from boards.yaml, else its default."""
    args = board.synth_args
    return args[args.index("-family") + 1] if "-family" in args else "gw1n"


def _yosys(script: str, out: Path, run) -> str:
    try:
        r = run(["yowasp-yosys", "-q", "-p", script], capture_output=True, text=True, cwd=out, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:
        # TimeoutExpired keeps what was captured as bytes, even with text=True.
        captured = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        raise BuildError("crosscheck", -1, f"yosys took more than {TIMEOUT} s\n{captured}") from None
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise BuildError("crosscheck", r.returncode, log)
    return log


def _holds(log: str) -> bool:
    if "SAT proof finished - no model found: SUCCESS!" in log:
        return True
    if "SAT proof finished - model found: FAIL!" in log:
        return False
    raise BuildError("crosscheck", 0, "yosys sat printed neither SUCCESS! nor FAIL!\n" + log)


def _value(log: str, sig: str) -> int:
    """sig's value at the last step shown in the counterexample table of `sat -show` (undefined bits as 0)."""
    rows = re.findall(rf"^\s*(\d+)\s+\\{re.escape(sig)}\s+\S+\s+([0-9a-fA-Fx-]+)\s+[01x-]+\s*$", log, re.M)
    if not rows:
        raise BuildError("crosscheck", 0, f"no value of {sig} in the sat output\n" + log)
    return int(max(rows, key=lambda r: int(r[0]))[1].replace("-", "0").replace("x", "0"), 16)


def _input_widths(design_il: Path, top: str) -> dict[str, int]:
    body = design_il.read_text(encoding="utf-8").split(f"\nmodule \\{top}\n", 1)[1].split("\nend\n", 1)[0]
    return {
        m[2]: int(m[1] or 1)
        for m in re.finditer(r"^  wire (?:width (\d+) )?(?:\S+ )*?input \d+ (?:\S+ )*?\\(\S+)$", body, re.M)
    }


def _cannot_check(where: str, message: str, queries: int, t0: float) -> Result:
    return Result([Problem(where, "cannot_check", "cannot check: " + message)], [], queries, time.monotonic() - t0)


def crosscheck(
    ips: dict,
    sources: list[Path],
    board: BoardInfo,
    out_dir: Path,
    *,
    top: str = "top",
    depth: int = 32,
    inputs: dict[str, int] | None = None,
    workers: int | None = None,
    design_id: int | None = None,
    run=subprocess.run,
) -> Result:
    """Check `ips` (spec 5.3, already valid) against the design; design.il and one log per query go to out_dir.

    depth: clocks from configuration; must cover the reset plus the three bus cycles (the 9K top: 16 + 10).
    inputs: top input ports held at a value (a free reset button would hold the design in reset).
    design_id: the DESIGN_ID synthesis will set on the top, so that the check elaborates the same circuit.
    Raises BuildError when yosys fails or prints something unexpected.
    """
    t0 = time.monotonic()
    inputs = inputs or {}
    # the CPUs this process may use (os.cpu_count() counts all of them, also under taskset or a container limit)
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    workers = workers or min(MAX_WORKERS, cpus)
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("q*.log"):
        old.unlink()
    (out / "npqchk.v").write_text(master_verilog(ips), encoding="utf-8")
    copied: dict[str, Path] = {}
    reads = " ".join(f'"{tool_path(s, out, copied)}"' for s in sources)
    family = _family(board)
    _yosys(
        f"read_verilog -specify -lib +/gowin/cells_sim.v +/gowin/cells_xtra_{family}.v; "
        f"read_verilog {reads}; read_verilog -overwrite npqchk.v; {chparam_design_id(design_id, top)}"
        f"hierarchy -check -top {top}; proc; flatten; cutpoint -blackbox; async2sync; "
        # memory read data becomes free: mapping a 20 KiB buffer to FFs ran yosys out of memory
        f"memory -nomap; cutpoint t:$mem_v2; opt -full; opt_clean; "
        f"tee -q -o masters.txt select -list w:*npqchk_done; "
        f"write_rtlil design.il",
        out,
        run,
    )

    widths = _input_widths(out / "design.il", top)
    for name, value in inputs.items():
        width = widths.get(name)
        if width is None:
            return _cannot_check(
                f"check.inputs.{name}",
                f"[check] inputs: {name} is not an input port of {top} (its inputs: {', '.join(sorted(widths))})",
                0,
                t0,
            )
        if value >= 1 << width:  # sat -set would silently cut it to the port's width
            return _cannot_check(
                f"check.inputs.{name}", f"[check] inputs: {value} does not fit in {name} ({width} bits)", 0, t0
            )
    masters = (out / "masters.txt").read_text().split()
    if len(masters) != 1:
        return _cannot_check(
            top,
            f"the design must hold exactly one instance of nanopynq's uartbone_bridge "
            f"(the check puts a test bus master in its place); it holds {len(masters)}",
            0,
            t0,
        )
    p = masters[0].split("/", 1)[1][: -len("npqchk_done")]  # e.g. "bridge.npqchk."

    base = f"-seq {depth}" + "".join(f" -set {name} {value}" for name, value in inputs.items())
    regs = list(_registers(ips))
    pinned = max(a for *_, a, _ in regs) >> 2  # not 0: an address stuck at 'x reads as 0 (sys.version is at 4)
    queries = [
        _Query("done", f"{base} -prove {p}npqchk_done 1 -prove-skip {depth - 1} -show {p}npqchk_adr"),
        _Query("canary", f"{base} -set {p}npqchk_adr 30'h{pinned:x} -prove {p}npqchk_done 0"),
    ]
    for ip_name, reg_name, a, r in regs:
        pin = f"{base} -set {p}npqchk_adr 30'h{a >> 2:x}"
        mask = f"-set {p}npqchk_mask 32'h{(1 << r['width']) - 1:x}"
        queries.append(_Query("no_slave", f"{pin} -prove {p}npqchk_r1_unmapped 1", ip_name, reg_name, a))
        if r["access"] in ("rw", "ro"):
            queries.append(
                _Query(
                    "rw", f"{pin} {mask} -prove {p}npqchk_rw 1 -show {p}npqchk_wdat,{p}npqchk_r2", ip_name, reg_name, a
                )
            )
        if r["access"] == "ro":
            queries.append(
                _Query("width", f"{pin} {mask} -prove {p}npqchk_hi_zero 1 -show {p}npqchk_r1", ip_name, reg_name, a)
            )
    for i, ip_name in enumerate(ips):
        queries.append(
            _Query(
                "undeclared",
                f"{base} -prove {p}npqchk_in{i}_unmapped 1 "
                f"-show {p}npqchk_adr,{p}npqchk_r1,{p}npqchk_wdat,{p}npqchk_r2",
                ip_name,
            )
        )
    queries.append(
        _Query(
            "outside",
            f"{base} -prove {p}npqchk_out_unmapped 1 -show {p}npqchk_adr,{p}npqchk_r1,{p}npqchk_wdat,{p}npqchk_r2",
        )
    )

    scripts = [
        "read_rtlil design.il; "
        + "; ".join(f"tee -q -o q{k}.log sat {queries[k].args}" for k in range(w, len(queries), workers))
        for w in range(min(workers, len(queries)))
    ]
    with ThreadPoolExecutor(len(scripts)) as pool:
        list(pool.map(lambda s: _yosys(s, out, run), scripts))
    logs = [(out / f"q{k}.log").read_text(encoding="utf-8") for k in range(len(queries))]

    if not _holds(logs[0]):
        adr = _value(logs[0], f"{p}npqchk_adr") << 2
        return _cannot_check(
            top,
            f"within {depth} clocks of configuration, the read-write-read at 0x{adr:x} "
            f"does not finish. The reset may last longer than about {depth - 10} clocks, a slave "
            "may not ack, or a free input may hold the design in reset (pin it with [check] "
            "inputs); [check] depth sets the clocks",
            len(queries),
            t0,
        )
    if _holds(logs[1]):
        return _cannot_check(
            top,
            "the check's assumptions contradict each other, so every proof would pass (look at [check] inputs)",
            len(queries),
            t0,
        )
    errors, warnings, missing = [], [], set()  # missing: no_slave registers, not warned about again
    for q, log in zip(queries[2:], logs[2:], strict=False):
        holds = _holds(log)
        where = f"ips.{q.ip}.registers.{q.reg}"
        if q.kind == "no_slave" and holds:
            missing.add(where)
            errors.append(
                Problem(
                    where,
                    q.kind,
                    f"{where} (0x{q.addr:x}): every read returns 0xdeadbeef, so no "
                    "slave answers there. The base or offset differs from the address decoding in "
                    "the RTL, or the register is not in the RTL",
                )
            )
        elif where in missing:
            pass
        elif q.kind == "rw" and holds and ips[q.ip]["registers"][q.reg]["access"] == "ro":
            warnings.append(
                Problem(
                    where, "not_ro", f"{where} (0x{q.addr:x}): defined ro, but what is written reads back. Is it rw?"
                )
            )
        elif q.kind == "rw" and not holds and ips[q.ip]["registers"][q.reg]["access"] == "rw":
            width = ips[q.ip]["registers"][q.reg]["width"]
            wdat, r2 = _value(log, f"{p}npqchk_wdat"), _value(log, f"{p}npqchk_r2")
            warnings.append(
                Problem(
                    where,
                    "not_rw",
                    f"{where} (0x{q.addr:x}): defined rw and {width} bits wide, "
                    f"but writing 0x{wdat:08x} reads back 0x{r2:08x} (expected "
                    f"0x{wdat & ((1 << width) - 1):08x}). Check access and width (a register "
                    "that reads something else than what was written is rw too)",
                )
            )
        elif q.kind == "width" and not holds:
            width = ips[q.ip]["registers"][q.reg]["width"]
            warnings.append(
                Problem(
                    where,
                    q.kind,
                    f"{where} (0x{q.addr:x}): defined {width} bits wide, but it "
                    f"reads 0x{_value(log, f'{p}npqchk_r1'):08x}, with bits above bit {width - 1} "
                    "set. Is the width wrong?",
                )
            )
        elif q.kind in ("undeclared", "outside") and not holds:
            adr = _value(log, f"{p}npqchk_adr") << 2
            r1, wdat, r2 = (_value(log, f"{p}npqchk_{sig}") for sig in ("r1", "wdat", "r2"))
            reads = f"reads 0x{r1:08x}, and 0x{r2:08x} after writing 0x{wdat:08x}"
            if q.kind == "outside":
                errors.append(
                    Problem(
                        f"0x{adr:x}",
                        q.kind,
                        f"0x{adr:x}: answers ({reads}) but is in no IP's range. "
                        "Is an IP missing from ips, or is a base wrong?",
                    )
                )
            else:
                # only streams mark a data window: a narrow addr_range must not hide a missing register
                (warnings if ips[q.ip].get("streams") else errors).append(
                    Problem(
                        f"0x{adr:x}",
                        q.kind,
                        f"0x{adr:x}: answers inside ips.{q.ip} ({reads}) but is not one of its "
                        f"registers. Is a register missing from ips.{q.ip}.registers, or is an offset wrong?",
                    )
                )
    return Result(errors, warnings, len(queries), time.monotonic() - t0)

"""User flash pin polarity check (reports/report_4k_peripherals.md 3.8): build a top whose flash inputs are
all tied to V with the Gowin IDE, unpack the bitstream with Apicula, and print the physical value on each
flash input wire (constant VSS / VCC, or a constant LUT; "None" = driven by logic).

Env: OVL = Apicula with the device's chipdb (as for tools/build_base.py), GW_SH = the IDE's gw_sh.exe.
Run (Git Bash): uv run python tools/p0/uflash4k/flash_polarity.py GW1N-9C GW1NR-LV9QN88PC6/I5 FLASH608K 0 DIR
             or: uv run python tools/p0/uflash4k/flash_polarity.py --fs GW1NS-4 some.fs
gowin_unpack emits no LUT cell when none of its fuses is set; such a LUT is INIT 0xFFFF (constant 1). The flash's
DOUT tiles (on GW1NS-4 the corner R1C1, which has no LUTs) have no LUT outputs: a default route from their F
wires is reported as unknown.
"""
import re
import subprocess
import tempfile
import sys
from pathlib import Path

import os

OVL = os.environ.get("OVL", "")
GW_SH = os.environ.get("GW_SH", "gw_sh")
PORTS = {  # inputs per UG295
    "FLASH64KZ": dict(XADR=5, YADR=6, XE=1, YE=1, SE=1, ERASE=1, PROG=1, NVSTR=1, DIN=32),
    "FLASH608K": dict(XADR=9, YADR=6, XE=1, YE=1, SE=1, ERASE=1, PROG=1, NVSTR=1, DIN=32),
}


def build(dev, part, ftype, v, wd: Path) -> Path:
    wd.mkdir(parents=True, exist_ok=True)
    conns = ", ".join(f".{p}({{{w}{{1'b{v}}}}})" if w > 1 else f".{p}(1'b{v})" for p, w in PORTS[ftype].items())
    (wd / "top.v").write_text(f"""module top(output led);
    wire [31:0] d;
    {ftype} f({conns}, .DOUT(d));
    assign led = d[0];
endmodule
""")
    (wd / "ide.tcl").write_text(f"""set_device {part}
add_file top.v
set_option -top_module top
set_option -output_base_name top
run all
""")
    r = subprocess.run([GW_SH, "ide.tcl"], cwd=wd, capture_output=True, text=True, errors="replace")
    (wd / "ide.log").write_text(r.stdout + r.stderr)
    fs = wd / "impl" / "pnr" / "top.fs"
    if not fs.exists():
        sys.exit("IDE failed:\n" + "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "ERROR" in l))
    return fs


def unpack(dev, fs: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:  # not next to the .fs (it may be a bundled design)
        out = Path(tmp) / "unpacked.v"
        subprocess.run(["uv", "run", "-q", "--no-project", "--with", "msgspec", "--with", "apycula==0.35", "python",
                        "-m", "apycula.gowin_unpack", "-d", dev, "-o", str(out), str(fs)], check=True,
                       env={**os.environ, "PYTHONPATH": OVL})
        return out.read_text()


def port_wires(dev):
    """port -> tile wire name R{r}C{c}_{wire} (Apicula chipdb)."""
    code = f"""
import sys; sys.path.insert(0, r"{OVL}")
from apycula import chipdb
db = chipdb.load_chipdb(r"{OVL}/apycula/{dev}.msgpack.xz")
uf = db.extra_func[(0, 0)]['userflash']
for k, w in {{**uf['ins'], **uf['outs']}}.items():
    node = db.nodes.get(f'X0Y0/{{w}}')
    if node:
        r, c, ww = [m for m in node[1] if m[2] != w][0]
    else:
        r, c, ww = 0, 0, w
    print(k, f'R{{r+1}}C{{c+1}}_{{ww}}')
"""
    r = subprocess.run(["uv", "run", "-q", "--no-project", "--with", "msgspec", "python", "-c", code],
                       capture_output=True, text=True, check=True)
    return dict(l.split() for l in r.stdout.splitlines())


def evaluator(txt, not_luts=frozenset()):
    asg = {}
    for m in re.finditer(r"assign `?(\S+?) = `?(\S+);", txt):
        asg.setdefault(m.group(1), m.group(2))
    for m in re.finditer(r"`define (\S+) (\S+)", txt):
        asg.setdefault(m.group(1), m.group(2))
    init = {m.group(1): int(m.group(2).split("'h")[1], 16) for m in re.finditer(r"defparam (\S+)\.INIT = (\S+);", txt)}

    def val(w, depth=0):
        if depth > 30:
            return None, ["..."]
        if w in ("VSS", "1'b0"):
            return 0, [w]
        if w in ("VCC", "1'b1"):
            return 1, [w]
        if w in asg:
            v, p = val(asg[w], depth + 1)
            return v, [w] + p
        m = re.fullmatch(r"R(\d+)C(\d+)_F(\d)", w)
        if m:
            lut = f"R{m[1]}C{m[2]}_LUT4_{m[3]}"
            if f"R{m[1]}C{m[2]}" in not_luts:  # tiles of the flash's DOUT (no LUTs there, e.g. the corner R1C1)
                return None, [w + " (not a LUT: default route, value unknown)"]
            if lut not in init:  # gowin_unpack emits no LUT when none of its fuses is set: INIT 0xFFFF
                return 1, [w + " (LUT, no fuses = 0xFFFF)"]
            idx, path = 0, [f"{lut}(INIT={init[lut]:04x})"]
            for bit, pin in enumerate("ABCD"):
                v, _ = val(f"R{m[1]}C{m[2]}_{pin}{m[3]}", depth + 1)
                idx |= (v or 0) << bit  # a non-constant input counts as 0
            return init[lut] >> idx & 1, path
        return None, [w + " (undriven)"]
    return val


def report(dev, txt):
    pw = port_wires(dev)
    val = evaluator(txt, frozenset(w.split("_")[0] for p, w in pw.items() if p.startswith("DOUT")))
    for port in sorted(pw, key=lambda p: (re.sub(r"\d+$", "", p), int(re.search(r"\d*$", p).group() or 0))):
        if port.startswith("DOUT"):
            continue
        v, path = val(pw[port])
        print(f"{port:10} {pw[port]:22} phys={v}  {' <- '.join(path[:6])}")


if __name__ == "__main__":
    if sys.argv[1] == "--fs":
        report(sys.argv[2], unpack(sys.argv[2], Path(sys.argv[3])))
    else:
        dev, part, ftype, v, wd = sys.argv[1:6]
        report(dev, unpack(dev, build(dev, part, ftype, v, Path(wd))))

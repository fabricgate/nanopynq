"""The ips (spec 5.3) collected from the RTL and nanopynq's IP descriptions (issue #44, docs/design_ips_from_rtl.md).

- elaborate(): yosys `hierarchy -top; proc; write_json -selected`. The Verilog parameters are read from the derived
  modules (`parameter_default_values`): flatten would drop them.
- A description (nanopynq/ipdesc/*.toml) is one IP type: the spec 5.3 item (type, base, parameters, registers) plus
  `module` (the Verilog module), `when` (a condition on its parameters: regbus_gpio is gpio_out or gpio_in by
  IS_INPUT) and `user_parameters` (IP parameters the RTL does not hold, like pwm_timer's clock_hz: nanopynq.toml
  gives them). A string that starts with "=" is an expression: integers, strings, + - * // %, comparisons,
  `a if c else b`, len(). base and parameters see the instance's Verilog parameters (BASE, WIDTH); registers see
  the IP's parameters (width).
- collect(): every instance whose module has a description is an IP, named by (* npq_name = "..." *) or else by the
  instance name. Its base is the description's (the parameter the IP decodes with), else (* npq_base = ... *).
  Repeated names and modules that only share a described name are left to merge(): nanopynq.toml may settle them.
- merge(): nanopynq.toml's [ips.<name>] over the collected ips (see merge()).
"""

import ast
import json
import operator
import re
import subprocess
import tomllib
from importlib.resources import files
from pathlib import Path

from nanopynq.build.gowin import tool_path
from nanopynq.errors import BuildError
from nanopynq.manifest import DEFAULT_ADDR_RANGE

DESC_DIR = Path(str(files("nanopynq").joinpath("ipdesc")))
DESC_KEYS = ("type", "module", "when", "base", "parameters", "user_parameters", "registers")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")  # spec 5.3
HEX = re.compile(r"^0x[0-9a-f]+$")  # spec 5.3
# shortcut: * on strings and big integers is not bounded; fine for nanopynq's own descriptions, bound it before a
# design folder may bring its own (stage 2)
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class CollectError(ValueError):
    """The ips cannot be collected: a description or nanopynq.toml's [ips] does not fit the RTL; the message says
    where."""


def _eval(node, env: dict):
    if isinstance(node, ast.Constant) and type(node.value) in (int, str, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise CollectError(f"unknown name {node.id!r} (known: {', '.join(sorted(env))})")
        return env[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _OPS:
        return _OPS[type(node.ops[0])](_eval(node.left, env), _eval(node.comparators[0], env))
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, env)
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "len" and len(node.args) == 1:
        return len(_eval(node.args[0], env))
    raise CollectError(f"not allowed in a description expression: {ast.unparse(node)}")


def value(v, env: dict):
    """A description value: "=expr" is evaluated in env, tables element-wise, the rest as is."""
    if isinstance(v, str) and v.startswith("="):
        try:
            tree = ast.parse(v[1:], mode="eval")
        except SyntaxError as e:
            raise CollectError(f"{v!r}: {e.msg}") from None
        return _eval(tree.body, env)
    if isinstance(v, dict):
        return {k: value(x, env) for k, x in v.items()}
    return v


def load_descriptions(folder: Path = DESC_DIR) -> list[dict]:
    """Every *.toml in folder, with its file name as "_file"."""
    descs = []
    for p in sorted(Path(folder).glob("*.toml")):
        desc = tomllib.loads(p.read_text(encoding="utf-8"))
        for k in desc:
            if k not in DESC_KEYS:
                raise CollectError(f"{p.name}: unknown key {k} (known: {', '.join(DESC_KEYS)})")
        for k in ("type", "module"):
            if k not in desc:
                raise CollectError(f"{p.name}: {k} missing")
        descs.append(desc | {"_file": p.name})
    return descs


def elaborate(sources: list[Path], out_dir: Path, top: str = "top", family: str = "gw1n", run=subprocess.run) -> dict:
    """The design after hierarchy (+ proc, which write_json needs) as yosys' JSON, in out_dir/elab.json. The Gowin
    primitives are read as a library, as the crosscheck does; -selected leaves out the library's own modules,
    which write_json cannot write."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    abs_out, copied = out_dir.resolve(), dict[str, Path]()
    reads = " ".join(f'"{tool_path(s, abs_out, copied)}"' for s in sources)
    script = (
        f"read_verilog -specify -lib +/gowin/cells_sim.v +/gowin/cells_xtra_{family}.v; "
        f'read_verilog {reads}; hierarchy -check -top {top}; proc; write_json -selected "elab.json"'
    )
    r = run(["yowasp-yosys", "-q", "-p", script], capture_output=True, text=True, cwd=out_dir)
    if r.returncode != 0:
        raise BuildError("ips", r.returncode, (r.stdout or "") + (r.stderr or ""))
    return json.loads((out_dir / "elab.json").read_text(encoding="utf-8"))


def _const(v):
    """A parameter or attribute value from yosys' JSON: bit strings -> int, other strings as written."""
    if isinstance(v, str) and v and set(v) <= set("01"):
        return int(v, 2)  # shortcut: no signed parameters and no x/z bits; none of nanopynq's IPs has them
    if isinstance(v, str) and v.endswith(" ") and set(v.rstrip(" ")) <= set("01xz"):
        return v[:-1]  # write_json appends a blank to strings that look like bits
    return v


def _instances(netlist: dict, top: str):
    """(path, module name as written, Verilog parameters, instance attributes) for every instance under top."""
    mods = netlist["modules"]

    def walk(mod, prefix):
        for cname, cell in mods[mod]["cells"].items():
            sub = mods.get(cell["type"])
            if sub is None:  # a yosys cell ($add, ...)
                continue
            path = prefix + cname.lstrip("\\")
            params = {k: _const(v) for k, v in sub.get("parameter_default_values", {}).items()}
            attrs = {k: _const(v) for k, v in cell.get("attributes", {}).items() if k != "src"}
            yield path, sub["attributes"].get("hdlname", cell["type"]), params, attrs
            yield from walk(cell["type"], path + ".")

    yield from walk(top, "")


def _base(b) -> int:
    return int(b, 16) if isinstance(b, str) else b


def _npq_base(path: str, b) -> int:
    try:
        return _base(b)
    except ValueError:
        raise CollectError(
            f'{path}: npq_base {b!r} is not an address; write (* npq_base = 32\'h9000 *) or (* npq_base = "0x9000" *)'
        ) from None


def _span(ip: dict) -> tuple[int, int] | None:
    """[base, base + addr_range) of a hand-written IP; None when they are not hex strings (design_id says why)."""
    b, r = ip["base"], ip.get("addr_range", hex(DEFAULT_ADDR_RANGE))
    if not all(isinstance(v, str) and HEX.fullmatch(v) for v in (b, r)):
        return None
    return int(b, 16), int(b, 16) + int(r, 16)


def collect(netlist: dict, descs: list[dict], top: str = "top") -> dict[str, dict]:
    """{instance path: {"name", "desc", "base": int, "params": the IP's parameters from the RTL}}. Names may repeat
    (a generate loop): merge() checks them once nanopynq.toml has had its say. An instance whose module has a
    described name but not the parameters the description reads (a module of the user's own) is {"name", "error"}."""
    found: dict[str, dict] = {}
    for path, module, vparams, attrs in _instances(netlist, top):
        cands = [d for d in descs if d["module"] == module]
        if not cands:
            continue
        name = attrs.get("npq_name", path.rsplit(".", 1)[-1])
        if not isinstance(name, str):
            raise CollectError(f'{path}: npq_name must be a string, like (* npq_name = "pwm" *)')
        fits, errors = [], []
        for d in cands:
            try:
                if value(d.get("when", True), vparams):
                    fits.append((d, value(d.get("base"), vparams), value(d.get("parameters", {}), vparams)))
            except CollectError as e:
                errors.append(f"{d['_file']}: {e}")
        if errors:
            found[path] = {"name": name, "error": f"{path} does not fit nanopynq's {module} ({'; '.join(errors)})"}
            continue
        if not fits:
            continue
        if len(fits) > 1:
            raise CollectError(f"{path}: several descriptions fit {module}: {[d['_file'] for d, _, _ in fits]}")
        desc, base, params = fits[0]
        if base is not None:
            base = _base(base)
            if "npq_base" in attrs and _npq_base(path, attrs["npq_base"]) != base:
                raise CollectError(
                    f"{path}: npq_base is 0x{_npq_base(path, attrs['npq_base']):x}, but the IP decodes 0x{base:x}"
                )
        elif "npq_base" in attrs:
            base = _npq_base(path, attrs["npq_base"])
        else:
            raise CollectError(
                f"{path}: the description of {module} has no base; add (* npq_base = ... *) to the instance"
            )
        found[path] = {"name": name, "desc": desc, "base": base, "params": params}
    return found


def merge(found: dict, overrides: dict) -> tuple[dict, dict, list[str]]:
    """nanopynq.toml's [ips.*] (tables, checked by load_config) over the collected ips -> (ips, {ip name: instance
    path, or None for a hand-written IP}, why each instance left out is not an IP).

    - `instance = "regs.gpio_leds"` gives that instance's IP this name.
    - An entry with a base is written whole, as before #44: it is the IP, in place of the collected IP of the same
      name and of every other collected IP its address range overlaps (so a nanopynq.toml with every IP by hand
      gives exactly those, whether or not the RTL names them).
    - An entry without a base adds to the collected IP of its name: parameters key by key, the other keys replace.
    - Then the collected IPs left must have names of their own (two instances in a generate loop need instance =).
      An instance whose module only shares the name of a described one is an error where nanopynq.toml names it,
      else left out: not an IP.
    """
    found = {path: dict(f) for path, f in found.items()}
    overrides = {name: dict(ov) for name, ov in overrides.items()}
    bound: dict[str, str] = {}  # instance path: the name instance = gives it
    for name, ov in overrides.items():
        if "instance" not in ov:
            continue
        path = ov.pop("instance")
        if path not in found:
            raise CollectError(
                f"ips.{name}.instance: no described instance {path!r} (there are: {', '.join(sorted(found))})"
            )
        if path in bound:
            raise CollectError(f"ips.{name}.instance: {path!r} is already ips.{bound[path]}")
        found[path]["name"] = bound[path] = name
    adds = [n for n, ov in overrides.items() if "base" not in ov and n not in bound.values()]
    named = set(bound) | {p for p, f in found.items() if f["name"] in adds}  # no base drops these
    for name, ov in overrides.items():
        if "base" in ov:
            # the collected ranges are 0x1000: no description has an addr_range yet
            lo, hi = _span(ov) or (0, 0)
            for p in [
                p
                for p, f in found.items()
                if f["name"] == name
                or (p not in named and "base" in f and f["base"] < hi and lo < f["base"] + DEFAULT_ADDR_RANGE)
            ]:
                del found[p]
    left_out = []
    for p, f in list(found.items()):
        if "error" in f:
            if p in named:
                raise CollectError(f"ips.{f['name']}: {f['error']}; write the IP whole, with base and type")
            left_out.append(f["error"])  # the build shows it: a slip in a description must not drop an IP unseen
            del found[p]
    by_name: dict[str, list] = {}
    for p, f in found.items():
        if f["name"] in by_name:
            raise CollectError(
                f"{p} and {by_name[f['name']]} are both named {f['name']!r}; give one of them "
                "another name with (* npq_name *) or with instance = in nanopynq.toml"
            )
        by_name[f["name"]] = p
    for name in adds:
        if name not in by_name:
            raise CollectError(
                f"ips.{name}: no IP is named {name} (the collected ones: {', '.join(by_name)}); "
                'name an instance with (* npq_name *) or instance = "...", or write the IP whole, '
                "with base and type"
            )
    ips, origin = {}, {}
    for path, f in found.items():
        name = f["name"]
        if not NAME.fullmatch(name):
            raise CollectError(
                f"{name!r} ({path}) is not an IP name (spec 5.3); set (* npq_name = ... *) or instance ="
            )
        ov = dict(overrides.get(name, {}))
        if type(ov.get("parameters", {})) is not dict:
            raise CollectError(f"ips.{name}.parameters: must be a table")
        params = f["params"] | ov.pop("parameters", {})
        missing = [p for p in f["desc"].get("user_parameters", []) if p not in params]
        if missing:
            raise CollectError(
                f"ips.{name} ({path}): give parameters {missing} in nanopynq.toml (they are not in the RTL)"
            )
        ip = {"base": f"0x{f['base']:x}", "type": f["desc"]["type"]}
        if params:
            ip["parameters"] = params
        try:
            ip["registers"] = value(f["desc"].get("registers", {}), params)
        except CollectError as e:
            raise CollectError(f"ips.{name} ({path}, {f['desc']['_file']}): {e}") from None
        ips[name], origin[name] = ip | ov, path
    for name, ov in overrides.items():
        if "base" in ov:
            ips[name], origin[name] = ov, None
    return ips, origin, left_out

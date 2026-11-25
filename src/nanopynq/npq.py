"""Design metadata files (`<name>.npq`, docs/spec_design_metadata.md): the checks V1-V12, the design_id, read, write.

Rules are checked one at a time over the whole document in the order of spec 5.9, so an input that breaks several
rules reports the lowest number. Nothing is repaired: a broken file raises NpqError with the rule and the place.
"""

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from nanopynq.errors import ManifestError, NpqError
from nanopynq.manifest import DEFAULT_ADDR_RANGE, Manifest, load_manifest

FORMAT = "nanopynq-design/1"
MAX_BYTES = 1 << 20
MAX_DEPTH = 64  # objects and lists; the top object is 1
MAX_SAFE = 2**53 - 1
MAX_FILE = 255
RESERVED_IDS = ("0x00000000", "0xdeadbeef")

# every pattern is used with fullmatch: "$" would also accept a trailing "\n"
INT_LITERAL = re.compile(r"-?(0|[1-9][0-9]{0,15})")
BOARD = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?")
FILE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
DESIGN_ID = re.compile(r"0x[0-9a-f]{8}")
NAME = re.compile(r"[a-z][a-z0-9_]*")
HEX = re.compile(r"0x[0-9a-f]+")
VERSION = r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})"
TYPE = re.compile(r"[a-z0-9_]+:[a-z0-9_]+:" + VERSION)
SYSINFO = re.compile(r"nanopynq:sysinfo:" + VERSION)
BAD_CHAR = re.compile(r"[\x00-\x1f\x7f\ud800-\udfff]")  # control characters and unpaired surrogates

IP_FIELDS = ("base", "addr_range", "type", "parameters", "registers", "streams", "doc")
REG_FIELDS = ("offset", "width", "access", "read_effect", "doc")
SECTIONS = ("parameters", "registers", "streams")


@dataclass(frozen=True)
class Npq(Manifest):
    """A checked .npq: the Manifest fields (ips in the same DefaultIP description shape) plus the link and design_id."""

    link: dict[str, Any]
    design_id: int


def _fail(rule: str, where: str, detail: str) -> NoReturn:
    raise NpqError(rule, where, detail)


def _is_int(v: Any) -> bool:
    return type(v) is int  # bool is not an integer here


def _matches(pattern: re.Pattern[str], v: Any) -> bool:
    return type(v) is str and pattern.fullmatch(v) is not None


def _items(v: Any) -> Iterable[tuple[Any, Any]]:
    return v.items() if type(v) is dict else ()


# ---------------------------------------------------------------- V1: the bytes and the text


def _not_json(token: str) -> NoReturn:
    _fail("V1", "", f"{token} is not JSON")


def _int_literal(s: str) -> int:
    if not INT_LITERAL.fullmatch(s):
        _fail("V1", "", f"integer with more than 16 digits ({s[:20]}...)")
    return int(s)


def _float_literal(s: str) -> NoReturn:
    _fail("V1", "", f"number with a fraction or exponent ({s[:20]})")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # json hands over every pair, including the ones a duplicate would hide, with escapes already decoded
    d: dict[str, Any] = {}
    for k, v in pairs:
        if k in d:
            _fail("V1", "", f"two items named {k!r} in one object")
        d[k] = v
    return d


def _depth(v: Any, d: int) -> int:
    if type(v) not in (dict, list):
        return d - 1
    if d > MAX_DEPTH:
        return d
    return max((_depth(x, d + 1) for x in (v.values() if type(v) is dict else v)), default=d)


def _parse(data: bytes) -> dict[str, Any]:
    """V1 up to a JSON value. json.loads passes every number token and every object's pairs to the hooks, so the hooks
    see the whole text; with duplicates rejected, the value holds all of the text, so the depth is checked on it."""
    if len(data) > MAX_BYTES:
        _fail("V1", "", f"more than {MAX_BYTES} bytes")
    if data.startswith(b"\xef\xbb\xbf"):
        _fail("V1", "", "starts with a BOM")
    try:
        text = data.decode("utf-8")  # a str, so json cannot guess UTF-16 / UTF-32
    except UnicodeDecodeError as e:
        _fail("V1", "", f"not UTF-8 ({e})")
    try:
        doc = json.loads(
            text,
            parse_constant=_not_json,
            parse_int=_int_literal,
            parse_float=_float_literal,
            object_pairs_hook=_no_duplicates,
        )
    except json.JSONDecodeError as e:
        _fail("V1", "", f"not JSON ({e})")
    except RecursionError:
        _fail("V1", "", f"nested deeper than {MAX_DEPTH}")
    if type(doc) is not dict:
        _fail("V1", "", "the top level must be an object")
    if _depth(doc, 1) > MAX_DEPTH:
        _fail("V1", "", f"nested deeper than {MAX_DEPTH}")
    return doc


# ---------------------------------------------------------------- V2, V3: the top level


def _v2(doc: dict[str, Any]) -> None:
    if type(doc.get("format")) is not str or doc["format"] != FORMAT:
        _fail("V2", "format", f"must be {FORMAT!r}, got {doc.get('format')!r}")


def _v3(doc: dict[str, Any]) -> None:
    for k in ("board", "bitstream", "link", "design_id", "ips"):
        if k not in doc:
            _fail("V3", k, "missing")
    if not _matches(BOARD, doc["board"]):
        _fail("V3", "board", f"bad board name {doc['board']!r}")
    for k, fields in (("bitstream", ("file", "sha256")), ("link", ("kind", "baudrate"))):
        if type(doc[k]) is not dict:
            _fail("V3", k, "must be an object")
        for f in doc[k]:
            if f not in fields:
                _fail("V3", f"{k}.{f}", "unknown field")
    bit = doc["bitstream"]
    for f, pattern in (("file", FILE), ("sha256", SHA256)):
        if f not in bit:
            _fail("V3", f"bitstream.{f}", "missing")
        if not _matches(pattern, bit[f]):
            _fail("V3", f"bitstream.{f}", f"bad value {bit[f]!r}")
    if len(bit["file"]) > MAX_FILE:
        _fail("V3", "bitstream.file", f"more than {MAX_FILE} characters")
    link = doc["link"]
    if "kind" not in link:
        _fail("V3", "link.kind", "missing")
    if type(link["kind"]) is not str or link["kind"] not in ("uart", "jtag"):
        _fail("V3", "link.kind", f"must be 'uart' or 'jtag', got {link['kind']!r}")
    if link["kind"] == "uart":
        b = link.get("baudrate")
        if not _is_int(b) or not 1 <= b <= MAX_SAFE:
            _fail("V3", "link.baudrate", f"uart needs an integer 1 .. 2^53 - 1, got {b!r}")
    elif "baudrate" in link:
        _fail("V3", "link.baudrate", "not allowed with jtag")
    if not _matches(DESIGN_ID, doc["design_id"]):
        _fail("V3", "design_id", f"must be 0x and 8 lowercase hex digits, got {doc['design_id']!r}")
    if doc["design_id"] in RESERVED_IDS:
        _fail("V3", "design_id", f"{doc['design_id']} is reserved")
    _v3_ips(doc["ips"])
    for k in ("name", "doc"):
        if k in doc and type(doc[k]) is not str:
            _fail("V3", k, "must be a string")


def _v3_ips(ips: Any) -> None:
    if type(ips) is not dict or not ips:
        _fail("V3", "ips", "must be an object with at least one IP")


# ---------------------------------------------------------------- V4 to V10: ips


def _v4(v: Any, where: str) -> None:
    t = type(v)
    if t is dict:
        for k, x in v.items():
            _v4(x, f"{where}.{k}")
    elif t is list:
        for i, x in enumerate(v):
            _v4(x, f"{where}.{i}")
    elif t is int:
        if not -MAX_SAFE <= v <= MAX_SAFE:
            _fail("V4", where, "integer outside -(2^53 - 1) .. 2^53 - 1")
    elif t is str:
        if BAD_CHAR.search(v):
            _fail("V4", where, "control character or unpaired surrogate")
    elif t is not bool:  # null from a file; also floats and other types in ips handed over from Python
        _fail("V4", where, f"{v!r} is not an integer, string, boolean, list or object")


def _name(n: Any, where: str) -> None:
    if type(n) is not str or n == "doc" or not NAME.fullmatch(n):
        _fail("V5", where, f"bad name {n!r}")


def _v5(ips: dict[str, Any]) -> None:
    for ipn, ip in ips.items():
        _name(ipn, f"ips.{ipn}")
        for sec in SECTIONS:
            for n, x in _items(ip.get(sec) if type(ip) is dict else None):
                _name(n, f"ips.{ipn}.{sec}.{n}")
                if sec == "streams":
                    for f, _ in _items(x):
                        if f != "doc":  # doc is a stream field, not a name
                            _name(f, f"ips.{ipn}.streams.{n}.{f}")


def _v6(ips: dict[str, Any]) -> None:
    for ipn, ip in ips.items():
        p = f"ips.{ipn}"
        if type(ip) is not dict:
            _fail("V6", p, "an IP must be an object")
        for k in ip:
            if k not in IP_FIELDS:
                _fail("V6", f"{p}.{k}", "unknown field")
        for k in ("base", "type"):
            if k not in ip:
                _fail("V6", f"{p}.{k}", "missing")
        for sec in SECTIONS:
            if sec in ip and type(ip[sec]) is not dict:
                _fail("V6", f"{p}.{sec}", "must be an object")
        for rn, r in ip.get("registers", {}).items():
            rp = f"{p}.registers.{rn}"
            if type(r) is not dict:
                _fail("V6", rp, "a register must be an object")
            for k in r:
                if k not in REG_FIELDS:
                    _fail("V6", f"{rp}.{k}", "unknown field")
            for k in ("offset", "width", "access"):
                if k not in r:
                    _fail("V6", f"{rp}.{k}", "missing")


def _hex(v: Any, where: str) -> int:
    if not _matches(HEX, v):
        _fail("V7", where, f"must be a lowercase 0x hex string, got {v!r}")
    n = int(v, 16)
    if n >= 2**32:
        _fail("V7", where, "2^32 or more")
    if n % 4:
        _fail("V7", where, "not a multiple of 4")
    return n


def _v7(ips: dict[str, Any]) -> None:
    for ipn, ip in ips.items():
        p = f"ips.{ipn}"
        base = _hex(ip["base"], f"{p}.base")
        size = _hex(ip["addr_range"], f"{p}.addr_range") if "addr_range" in ip else DEFAULT_ADDR_RANGE
        if size < 4:
            _fail("V7", f"{p}.addr_range", "less than 4")
        if base + size > 2**32:
            _fail("V7", f"{p}.base", "base + addr_range is more than 2^32")
        for rn, r in ip.get("registers", {}).items():
            if _hex(r["offset"], f"{p}.registers.{rn}.offset") + 4 > size:
                _fail("V7", f"{p}.registers.{rn}.offset", "offset + 4 is more than addr_range")


def _scalar(v: Any) -> bool:
    return type(v) in (int, str, bool)


def _v8(ips: dict[str, Any]) -> None:
    for ipn, ip in ips.items():
        p = f"ips.{ipn}"
        if not _matches(TYPE, ip["type"]):
            _fail("V8", f"{p}.type", f"bad type {ip['type']!r}")
        if "doc" in ip and type(ip["doc"]) is not str:
            _fail("V8", f"{p}.doc", "must be a string")
        for n, v in ip.get("parameters", {}).items():
            if type(v) is list:
                for i, x in enumerate(v):
                    if not _scalar(x):
                        _fail("V8", f"{p}.parameters.{n}.{i}", "list items must be integers, strings or booleans")
            elif not _scalar(v):
                _fail("V8", f"{p}.parameters.{n}", "must be an integer, string, boolean or a list of them")
        for rn, r in ip.get("registers", {}).items():
            rp = f"{p}.registers.{rn}"
            if not _is_int(r["width"]) or not 1 <= r["width"] <= 32:
                _fail("V8", f"{rp}.width", f"must be an integer 1 .. 32, got {r['width']!r}")
            if type(r["access"]) is not str or r["access"] not in ("ro", "rw", "wo"):
                _fail("V8", f"{rp}.access", f"must be ro, rw or wo, got {r['access']!r}")
            if "read_effect" in r and type(r["read_effect"]) is not bool:
                _fail("V8", f"{rp}.read_effect", "must be a boolean")
            if "doc" in r and type(r["doc"]) is not str:
                _fail("V8", f"{rp}.doc", "must be a string")
        for sn, s in ip.get("streams", {}).items():
            sp = f"{p}.streams.{sn}"
            if type(s) is not dict:
                _fail("V8", sp, "a stream must be an object")
            if type(s.get("dir")) is not str or s["dir"] not in ("read", "write"):
                _fail("V8", f"{sp}.dir", "must be read or write")
            if not _is_int(s.get("mtu")) or s["mtu"] < 1:
                _fail("V8", f"{sp}.mtu", "must be an integer >= 1")
            for f, v in s.items():
                if f == "doc" and type(v) is not str:
                    _fail("V8", f"{sp}.doc", "must be a string")
                if not _scalar(v):
                    _fail("V8", f"{sp}.{f}", "must be an integer, string or boolean")


def _span(ip: dict[str, Any]) -> tuple[int, int]:
    base = int(ip["base"], 16)
    return base, base + int(ip.get("addr_range", "0x1000"), 16)


def _v9(ips: dict[str, Any]) -> None:
    seen: list[tuple[str, int, int]] = []
    for ipn, ip in ips.items():
        b, e = _span(ip)
        for other, ob, oe in seen:
            if b < oe and ob < e:
                _fail("V9", f"ips.{ipn}.base", f"address range overlaps ips.{other}")
        seen.append((ipn, b, e))
    for ipn, ip in ips.items():
        offsets: set[int] = set()
        for rn, r in ip.get("registers", {}).items():
            off = int(r["offset"], 16)  # by value: "0x4" and "0x04" are the same offset
            if off in offsets:
                _fail("V9", f"ips.{ipn}.registers.{rn}.offset", "same offset as another register")
            offsets.add(off)


def _v10(ips: dict[str, Any]) -> None:
    if "sys" not in ips:
        _fail("V10", "ips.sys", "missing")
    sys_ = ips["sys"]
    if int(sys_["base"], 16) != 0:
        _fail("V10", "ips.sys.base", "must be 0x0")
    m = SYSINFO.fullmatch(sys_["type"])
    if not m:
        _fail("V10", "ips.sys.type", "must be nanopynq:sysinfo:<version>")
    regs = sys_.get("registers", {})
    need = [("id", 0x0), ("version", 0x4)] + ([("design_id", 0xC)] if (int(m[1]), int(m[2])) >= (1, 1) else [])
    for rn, off in need:
        r = regs.get(rn)
        if r is None:
            _fail("V10", f"ips.sys.registers.{rn}", "missing")
        if int(r["offset"], 16) != off or r["width"] != 32 or r["access"] != "ro":
            _fail("V10", f"ips.sys.registers.{rn}", f"must be offset 0x{off:x}, 32 bits, ro")
        if r.get("read_effect") is True:  # the host reads these to check the design
            _fail("V10", f"ips.sys.registers.{rn}.read_effect", "must not be true")


def _check_ips(ips: dict[str, Any]) -> None:
    _v4(ips, "ips")
    for rule in (_v5, _v6, _v7, _v8, _v9, _v10):
        rule(ips)


# ---------------------------------------------------------------- design_id (spec 5.4)


def _canonical(ips: dict[str, Any]) -> bytes:
    """Spec 5.4 steps 1-3, on ips that pass V4-V10."""
    norm = {
        n: {
            "addr_range": int(ip.get("addr_range", "0x1000"), 16),
            "base": int(ip["base"], 16),
            "parameters": ip.get("parameters", {}),
            "registers": {
                rn: {
                    "access": r["access"],
                    "offset": int(r["offset"], 16),
                    "read_effect": r.get("read_effect", False),
                    "width": r["width"],
                }
                for rn, r in ip.get("registers", {}).items()
            },
            "streams": {sn: {f: v for f, v in s.items() if f != "doc"} for sn, s in ip.get("streams", {}).items()},
            "type": ip["type"],
        }
        for n, ip in ips.items()
    }
    return json.dumps(norm, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _compute_id(ips: dict[str, Any]) -> int:
    return int.from_bytes(hashlib.sha256(_canonical(ips)).digest()[:4], "big")


def design_id(ips: dict[str, Any]) -> int:
    """The design_id of `ips` as written in a .npq (hex strings for addresses). Checks V4-V10 first (spec 5.4 step 0);
    raises ManifestError when the value is reserved (step 5: change the ips, e.g. add a parameter)."""
    _v3_ips(ips)
    if _depth(ips, 2) > MAX_DEPTH:  # as in a file (ips sits at depth 2); also ends cycles before a RecursionError
        _fail("V1", "ips", f"nested deeper than {MAX_DEPTH}")
    _check_ips(ips)
    did = _compute_id(ips)
    if f"0x{did:08x}" in RESERVED_IDS:
        raise ManifestError(f"the ips give the reserved design_id 0x{did:08x}; change the ips (spec 5.4 step 5)")
    return did


# ---------------------------------------------------------------- reading and writing


def _check(doc: dict[str, Any]) -> None:
    _v2(doc)
    _v3(doc)
    _check_ips(doc["ips"])


def parse_npq(data: bytes) -> dict[str, Any]:
    """V1-V11 on the contents of a .npq; returns the JSON document as written (spec 5.7 steps 1-2)."""
    doc = _parse(data)
    _check(doc)
    did = _compute_id(doc["ips"])
    if did != int(doc["design_id"], 16):
        _fail("V11", "design_id", f"the file has {doc['design_id']}, its ips give 0x{did:08x}")
    return doc


def _description(name: str, ip: dict[str, Any]) -> dict[str, Any]:
    """The DefaultIP description, as nanopynq.manifest builds it; read_effect only when true, docs dropped."""
    return {
        "name": name,
        "type": ip["type"],
        "phys_addr": int(ip["base"], 16),
        "addr_range": int(ip.get("addr_range", "0x1000"), 16),
        "parameters": dict(ip.get("parameters", {})),
        "registers": {
            rn: {"offset": int(r["offset"], 16), "width": r["width"], "access": r["access"]}
            | ({"read_effect": True} if r.get("read_effect") else {})
            for rn, r in ip.get("registers", {}).items()
        },
        "streams": {sn: {f: v for f, v in s.items() if f != "doc"} for sn, s in ip.get("streams", {}).items()},
    }


def load_npq(path: Path, check_bitstream: bool = True) -> Npq:
    """Read a .npq: `path` is the file, or a folder holding exactly one *.npq (spec 5.1). Checks V1-V11, then the .fs
    named by bitstream.file (V12), in the order of spec 5.7 steps 1-3. With check_bitstream=False V12 is skipped: the
    .fs is not read (it may be absent) and `sha256` is None."""
    path = Path(path)
    if path.is_dir():
        found = sorted(path.glob("*.npq"))
        if len(found) != 1:
            names = ", ".join(p.name for p in found) or "none"
            raise ManifestError(f"{path}: expected exactly one *.npq, found {len(found)} ({names}); pass the file")
        path = found[0]
    try:
        with path.open("rb") as f:
            data = f.read(MAX_BYTES + 1)  # one byte more is enough to fail V1 without reading a huge file
    except OSError as e:
        raise ManifestError(f"cannot read {path}: {e}") from e
    try:
        doc = parse_npq(data)
        bit = path.parent / doc["bitstream"]["file"]  # V3 allows no folder separators
        actual = None
        if check_bitstream:
            actual = hashlib.sha256(bit.read_bytes()).hexdigest() if bit.is_file() else None
        if check_bitstream and actual != doc["bitstream"]["sha256"]:
            _fail("V12", "bitstream.sha256", f"{bit.name}: " + (f"sha256 is {actual}" if actual else "not found"))
    except NpqError as e:
        e.add_note(f"in {path}")
        raise
    return Npq(
        board=doc["board"],
        bitstream=bit.resolve(),
        sha256=actual,
        ips={n: _description(n, ip) for n, ip in doc["ips"].items()},
        link=dict(doc["link"]),
        design_id=int(doc["design_id"], 16),
    )


def load_design(path: Path, check_bitstream: bool = True) -> Manifest:
    """The .npq at `path` (the file, or the one in the folder); a folder without a *.npq falls back to its
    manifest.yaml (spec 5.8, for designs not rebuilt yet). Decided up front: load_npq raises ManifestError for both a
    missing and a broken .npq, and a broken one must not fall back."""
    path = Path(path)
    if path.suffix == ".npq" or any(path.glob("*.npq")):
        return load_npq(path, check_bitstream)
    return load_manifest(path)


def write_npq(bitstream: Path, board: str, link: dict[str, Any], ips: dict[str, Any]) -> Path:
    """Spec 5.6 step 5: write `<stem>.npq` next to the built .fs and return its path.

    The output is JSON with a 2-space indent, LF and a final newline, UTF-8 without escapes; the top-level keys are in
    the order of spec 5.6, and `ips` keeps the caller's order, so the same arguments always give the same bytes. The
    bytes are checked with parse_npq before anything is written."""
    bitstream = Path(bitstream)
    out = bitstream.with_suffix(".npq")
    if out == bitstream:
        raise ManifestError(f"{bitstream}: the bitstream already has the .npq suffix; writing would overwrite it")
    doc = {
        "format": FORMAT,
        "board": board,
        "bitstream": {"file": bitstream.name, "sha256": hashlib.sha256(bitstream.read_bytes()).hexdigest()},
        "link": link,
        "design_id": f"0x{design_id(ips):08x}",
        "ips": ips,
    }
    _check(doc)  # V2-V10 on the value first, so json.dumps and encode get only what a .npq can hold
    data = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    parse_npq(data)
    out.write_bytes(data)
    return out

"""Conformance of nanopynq.npq against the shared .npq inputs (spec 5.9), and inputs nobody wrote by hand.

tests/data/npq_vectors.json is the input file of experiment A6 (issue #24), copied byte for byte from
experiments/a6_conformance/vectors.json at commit d538695. Its expectations were written by hand from the spec, so it
is kept as the reference and is not regenerated here; change it only together with the spec (#24).
Each case holds the file contents ("text" as UTF-8, or "base64"; "pad_to" N: spaces appended up to N bytes) and
"expect": {"design_id": "0x..."} (accepted) or {"rule": "Vn"} (rejected). The place is not compared (spec 5.9).
"""

import base64
import json
import random
import re
from collections import Counter
from pathlib import Path

import pytest

from nanopynq.errors import NpqError
from nanopynq.npq import _compute_id, parse_npq

VECTORS = json.loads((Path(__file__).parent / "data" / "npq_vectors.json").read_text(encoding="utf-8"))
CASES = {c["name"]: c for c in VECTORS["cases"]}


def _contents(c: dict) -> bytes:
    b = base64.b64decode(c["base64"]) if "base64" in c else c["text"].encode("utf-8")
    return b.ljust(c["pad_to"], b" ") if "pad_to" in c else b


def _result(data: bytes) -> dict:
    try:
        doc = parse_npq(data)
    except NpqError as e:
        return {"rule": e.rule}
    return {"design_id": f"0x{_compute_id(doc['ips']):08x}"}  # the computed value, not the field echoed back


def test_vectors_file():
    expects = [c["expect"] for c in VECTORS["cases"]]
    assert len(expects) == 286 and VECTORS["undecided"] == []
    assert sum("design_id" in e for e in expects) == 74
    assert {e["rule"] for e in expects if "rule" in e} == {f"V{i}" for i in range(1, 12)}


@pytest.mark.parametrize("name", list(CASES))
def test_conformance(name):
    c = CASES[name]
    assert _result(_contents(c)) == c["expect"], c["what"]


# ---------------------------------------------------------------- broken inputs: never a crash

POOL = [
    None,
    True,
    False,
    0,
    1,
    -1,
    4,
    32,
    33,
    2**53 - 1,
    2**53,
    -(2**53),
    "",
    "0x0",
    "0x4",
    "0x04",
    "0xc",
    "0x10",
    "0x1000",
    "0x1002",
    "0X10",
    "ro",
    "rw",
    "wo",
    "read",
    "write",
    "uart",
    "jtag",
    "a\n",
    "a\ud800",
    "\x7f",
    "nanopynq:sysinfo:1.0",
    "nanopynq:sysinfo:1.1",
    "nanopynq:x:01.1",
    "nanopynq-design/1",
    "a" * 256,
    [],
    [1, "a", True],
    [1, [2]],
    [None],
    {},
    {"offset": "0x10", "width": 32, "access": "ro"},
    {"dir": "read", "mtu": 1},
]
NAMES = [
    "LEDs",
    "doc",
    "x",
    "7",
    "sys",
    "leds",
    "offset",
    "width",
    "access",
    "read_effect",
    "dir",
    "mtu",
    "type",
    "base",
    "addr_range",
    "registers",
    "parameters",
    "streams",
    "design_id",
    "format",
    "board",
    "kind",
    "baudrate",
    "file",
    "sha256",
    "name",
    "__proto__",
]
TOKENS = ["6.0", "-0.0", "1E2", "NaN", "10000000000000000", "9999999999999999", "null", '"x"']
BYTES = list(b'0123456789.eE-+"\\{}[],: a\x00\x1f\x7f\xc3\xff')


def _mutate(rng: random.Random, doc: dict) -> None:
    node = doc.get("ips") if rng.random() < 0.7 and type(doc.get("ips")) is dict else doc
    while True:  # down to a random object or list, mostly inside ips where most rules look
        kids = [x for x in (node.values() if type(node) is dict else node) if type(x) in (dict, list)]
        if not kids or rng.random() < 0.25:
            break
        node = rng.choice(kids)
    value = json.loads(json.dumps(rng.choice(POOL)))
    if type(node) is list:
        if node and rng.random() < 0.5:
            node[rng.randrange(len(node))] = value
        else:
            node.append(value)
        return
    keys = list(node)
    op = rng.randrange(4) if keys else 2
    if op == 0:
        node[rng.choice(keys)] = value
    elif op == 1:
        del node[rng.choice(keys)]
    elif op == 2:
        node[rng.choice(NAMES)] = value
    else:
        node[rng.choice(NAMES)] = node.pop(rng.choice(keys))


def _mutant(rng: random.Random, text: str) -> bytes:
    doc = json.loads(text)
    for _ in range(rng.randint(1, 3)):
        _mutate(rng, doc)
    if rng.random() < 0.5:
        try:  # recompute design_id so that V11 does not stop every mutant; may fail on broken ips
            doc["design_id"] = f"0x{_compute_id(doc['ips']):08x}"
        except Exception:
            pass
    b = bytearray(json.dumps(doc).encode("utf-8"))
    r = rng.random()
    if r < 0.15:  # a duplicate name or a token json.dumps never writes, right after an opening brace
        i = rng.choice([i for i, x in enumerate(b) if x == ord("{")]) + 1
        b[i:i] = f'"{rng.choice(NAMES)}": {rng.choice(TOKENS)}, '.encode()
    elif r < 0.3:
        i = rng.randrange(len(b))
        b[i : i + rng.randrange(2)] = bytes([rng.choice(BYTES)]) if rng.random() < 0.7 else b""
    return bytes(b)


def test_broken_inputs_are_accepted_or_rejected_with_a_rule():
    rng = random.Random(24)
    seeds = [
        c["text"]
        for c in VECTORS["cases"]
        if "design_id" in c["expect"] and "text" in c and "pad_to" not in c and len(c["text"]) < 20000
    ]
    hist = Counter()
    for _ in range(3000):
        data = _mutant(rng, rng.choice(seeds))
        try:
            parse_npq(data)
            hist["ok"] += 1
        except NpqError as e:
            assert re.fullmatch(r"V([1-9]|1[01])", e.rule), data
            hist[e.rule] += 1
    # the mutants reach past V1: most rules are hit, and some still pass
    assert hist["ok"] > 50 and sum(hist[f"V{i}"] > 0 for i in range(1, 12)) >= 9, hist

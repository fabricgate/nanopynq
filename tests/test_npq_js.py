"""Conformance of the browser .npq reader (sdk/js/npq.js) against the shared inputs of
tests/test_npq_conformance.py, in Node and in headless Chrome (file:// page, so crypto.subtle and TextDecoder are the
browser's). The place is not compared (spec 5.9)."""

import base64
import json
import random
from pathlib import Path

from tests.jsrun import ROOT, SDK, chrome_dump, node, pre
from tests.test_npq_conformance import _mutant, _result

VECTORS_FILE = Path(__file__).parent / "data" / "npq_vectors.json"
RUNNER = Path(__file__).parent / "js" / "run_npq_vectors.js"
VECTORS = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))

_NODE = """
const reader = require(process.argv[1]);
const { runNpqVectors } = require(process.argv[2]);
const vectors = JSON.parse(require("fs").readFileSync(process.argv[3], "utf8"));
runNpqVectors(reader, vectors).then((out) => console.log(JSON.stringify(out)));
"""

_PAGE = """<!doctype html>
<meta charset="utf-8">
<pre id="out">pending</pre>
<script src="{npq}"></script>
<script src="{runner}"></script>
<script>
const VECTORS = {vectors};
runNpqVectors(npq, VECTORS).then(
  (out) => {{ document.getElementById("out").textContent = JSON.stringify(out); }},
  (e) => {{ document.getElementById("out").textContent = "crash " + e; }});
</script>
"""


def _compare(results: dict) -> None:
    assert len(results) == len(VECTORS["cases"]) == 318
    wrong = {
        c["name"]: (results[c["name"]], c["expect"]) for c in VECTORS["cases"] if results[c["name"]] != c["expect"]
    }
    assert not wrong


def test_js_reader_conformance_in_node():
    _compare(json.loads(node(_NODE, str(SDK / "npq.js"), str(RUNNER), str(VECTORS_FILE))))


def test_js_reader_conformance_in_chrome(tmp_path):
    page = tmp_path / "vectors.html"
    # "<" escaped so that no input text can end the inline script
    vectors = json.dumps(VECTORS).replace("<", "\\u003c")
    page.write_text(
        _PAGE.format(npq=(SDK / "npq.js").as_uri(), runner=RUNNER.as_uri(), vectors=vectors), encoding="utf-8"
    )
    out = pre(chrome_dump(page, tmp_path / "profile"), "out")
    assert out.startswith("{"), out[:500]
    _compare(json.loads(out))


def test_js_reader_agrees_with_python_on_broken_inputs(tmp_path):
    """The mutants of test_npq_conformance, from the accepted cases of both formats: whatever Python says of each
    (accepted with a design_id, or the rule) the JavaScript reader says too."""
    rng = random.Random(2)
    seeds = [c["text"] for c in VECTORS["cases"] if "design_id" in c["expect"] and "text" in c and "pad_to" not in c]
    seeds = [s for s in seeds if len(s) < 20000]
    cases = []
    for i in range(1500):
        data = _mutant(rng, rng.choice(seeds))
        cases.append({"name": str(i), "base64": base64.b64encode(data).decode(), "expect": _result(data)})
    file = tmp_path / "mutants.json"
    file.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    results = json.loads(node(_NODE, str(SDK / "npq.js"), str(RUNNER), str(file)))
    wrong = [
        (base64.b64decode(c["base64"]), results[c["name"]], c["expect"])
        for c in cases
        if results[c["name"]] != c["expect"]
    ]
    assert not wrong, wrong[:3]
    assert sum("design_id" in c["expect"] for c in cases) > 20  # some mutants are still read, in both formats


def test_bundled_base_npq_in_node():
    bundled = ROOT / "src" / "nanopynq" / "data" / "designs" / "tangnano9k-base" / "base.npq"
    out = node(
        "require(process.argv[1]).readNpq(require('fs').readFileSync(process.argv[2]))"
        ".then((d) => console.log(d.design_id, d.link.baudrate))",
        str(SDK / "npq.js"),
        str(bundled),
    )
    assert out.split() == ["0xabf78d8c", "115200"]

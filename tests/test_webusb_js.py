"""The browser JTAG code (sdk/js/transport/jtag.js) builds the same MPSSE bytes as src/nanopynq/transport/mpsse.py."""

import json
import random
from pathlib import Path

from nanopynq.transport.jtagbridge import _command
from nanopynq.transport.mpsse import _resp_len, decode_shift, encode_shift
from tests.jsrun import node

JS = Path(__file__).parents[1] / "sdk" / "js" / "transport" / "jtag.js"

_DRIVER = """
const j = require(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  enc: cases.enc.map(([v, n]) => j.encodeShift(BigInt(v), n)),
  dec: cases.dec.map(([r, n]) => j.decodeShift(r, n).toString()),
  tms: cases.tms.map((b) => j.tmsCmd(b)),
  cmd: cases.cmd.map(([a, w, d]) => j.command(a, w, d).toString()),
}));
"""


def test_js_shift_encoding_matches_python():
    rnd = random.Random(1)
    widths = [1, 2, 7, 8, 9, 16, 32, 33, 63, 64, 65, 200]
    enc = [(rnd.getrandbits(n), n) for n in widths for _ in range(3)]
    dec = [(list(rnd.randbytes(_resp_len(n))), n) for n in widths for _ in range(3)]
    tms = ["1", "10", "100", "01100", "11111"]
    cmd = [(0x0, False, 0), (0x1000, True, 0xDEADBEEF), (0xFFFFFFFC, False, 0), (0x800000, True, 1)]
    cases = {"enc": [[str(v), n] for v, n in enc], "dec": dec, "tms": tms, "cmd": cmd}
    out = json.loads(node(_DRIVER, str(JS), json.dumps(cases)))
    assert [bytes(b) for b in out["enc"]] == [encode_shift(v, n) for v, n in enc]
    assert [int(x) for x in out["dec"]] == [decode_shift(bytes(r), n) for r, n in dec]
    # mpsse.Mpsse.tms: [0x4B, len - 1, bits LSB first]
    assert out["tms"] == [[0x4B, len(b) - 1, sum(int(c) << i for i, c in enumerate(b))] for b in tms]
    assert [int(x) for x in out["cmd"]] == [_command(a, w, d) for a, w, d in cmd]


_PARSE = """
const j = require(process.argv[1]);
const fs = require("fs"), crypto = require("crypto");
const { data, idcode } = j.parseFs(fs.readFileSync(process.argv[2], "latin1"));
console.log(JSON.stringify({ sha: crypto.createHash("sha256").update(data).digest("hex"), n: data.length, idcode,
                             rev: [0x01, 0x80, 0x0f, 0xa5].map((b) => j.REV[b]) }));
"""


def test_js_reads_a_fs_like_the_fpga_wants_it():
    # The bytes sent to XFER_WRITE: every non-comment line, 8 characters per byte, first character = MSB
    # (openFPGALoader's FsParser up to its first empty line). Checked on the 20K (reports/report_webusb.md).
    import hashlib

    fs = Path(__file__).parents[1] / "src" / "nanopynq" / "data" / "designs" / "tangnano20k-base" / "base.fs"
    lines = [ln.strip() for ln in fs.read_text(encoding="ascii").splitlines()]
    want = b"".join(int(ln, 2).to_bytes(len(ln) // 8, "big") for ln in lines if ln and not ln.startswith("//"))
    out = json.loads(node(_PARSE, str(JS), str(fs)))
    assert (out["sha"], out["n"]) == (hashlib.sha256(want).hexdigest(), len(want))
    assert out["idcode"] == 0x0000081B
    assert out["rev"] == [0x80, 0x01, 0xF0, 0xA5]


# A fake debugger: runs the MPSSE opcodes jtag.js sends through a TAP state machine and records the TDI bits
# clocked while in Shift-DR (and any data bits clocked outside a shift state).
_TAP = """
const j = require(process.argv[1]);
const NEXT = { TLR: ["RTI", "TLR"], RTI: ["RTI", "SDS"], SDS: ["CDR", "SIS"], CDR: ["SDR", "E1D"], SDR: ["SDR", "E1D"],
  E1D: ["PDR", "UDR"], PDR: ["PDR", "E2D"], E2D: ["SDR", "UDR"], UDR: ["RTI", "SDS"], SIS: ["CIR", "TLR"],
  CIR: ["SIR", "E1I"], SIR: ["SIR", "E1I"], E1I: ["PIR", "UIR"], PIR: ["PIR", "E2I"], E2I: ["SIR", "UIR"], UIR: ["RTI", "SDS"] };
function fakeUsb(pkt, failReads = 0) {
  const t = { state: "RTI", dr: [], stray: 0, purges: 0, answer: [], failReads };
  const clk = (tms, tdi) => {
    if (t.state === "SDR") t.dr.push(tdi); else if (tdi !== undefined && t.state !== "SIR") t.stray++;
    t.state = NEXT[t.state][tms];
  };
  t.usb = {
    async controlTransferOut(setup) { if (setup.request === 0 && setup.value === 1) { t.purges++; t.answer = []; } },
    async transferOut(ep, b) {
      for (let i = 0; i < b.length;) {
        const op = b[i];
        if (op === 0x39) { const n = b[i + 1] | (b[i + 2] << 8); for (let k = 0; k <= n; k++) { for (let q = 0; q < 8; q++) clk(0, (b[i + 3 + k] >> q) & 1); t.answer.push(0); } i += 4 + n; }
        else if (op === 0x3b) { for (let q = 0; q <= b[i + 1]; q++) clk(0, (b[i + 2] >> q) & 1); t.answer.push(0); i += 3; }
        else if (op === 0x4b || op === 0x6b) { for (let q = 0; q <= b[i + 1]; q++) clk((b[i + 2] >> q) & 1, op === 0x6b ? (b[i + 2] >> 7) & 1 : undefined); if (op === 0x6b) t.answer.push(0); i += 3; }
        else if (op === 0x87) i++;
        else throw new Error("unexpected opcode 0x" + op.toString(16));
      }
      return { status: "ok", bytesWritten: b.length };
    },
    async transferIn(ep, n) {
      if (t.failReads > 0) { t.failReads--; throw new Error("stall"); }
      const out = [];
      while (t.answer.length && out.length + 2 < n) { out.push(1, 0x60); out.push(...t.answer.splice(0, pkt - 2)); }
      if (!out.length) out.push(1, 0x60);
      const u = Uint8Array.from(out);
      return { status: "ok", data: new DataView(u.buffer) };
    },
  };
  return t;
}
(async () => {
  const out = { dr: [], stale: null };
  for (const pkt of [64, 512]) for (const len of [1, 2, 4095, 4096, 4097, 8193]) {
    const t = fakeUsb(pkt);
    const data = Uint8Array.from({ length: len }, (_, i) => (i * 37 + 11) & 0xff);
    await new j.GowinSram(new j.Mpsse(t.usb, pkt))._dr(data);
    const want = [];
    for (const b of data) for (let q = 7; q >= 0; q--) want.push((b >> q) & 1);
    out.dr.push({ pkt, len, same: t.dr.length === want.length && t.dr.every((x, i) => x === want[i]), state: t.state, stray: t.stray });
  }
  const t = fakeUsb(512, 1);
  const m = new j.Mpsse(t.usb, 512);
  m.shift(0x42, 8);
  let failed = false;
  try { await m.flush(); } catch (e) { failed = true; }
  m.shift(0x42, 8);
  const [v] = await m.flush();
  out.stale = { failed, purges: t.purges, value: Number(v) };
  console.log(JSON.stringify(out));
})();
"""


def test_js_sends_the_whole_bitstream_inside_shift_dr():
    # The prototype once wrote the data while the move to Shift-DR was still queued (reports/report_webusb.md 3).
    out = json.loads(node(_TAP, str(JS)))
    assert out["dr"] and all(r["same"] and r["state"] == "RTI" and r["stray"] == 0 for r in out["dr"]), out["dr"]
    # a failed flush leaves its answer behind: the next flush purges the receive buffer first (as mpsse.py)
    assert out["stale"] == {"failed": True, "purges": 1, "value": 0}

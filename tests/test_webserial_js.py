"""The browser UARTBone client (sdk/js/transport/uartbone.js) puts the same bytes on the wire as the Python one."""

import json
from pathlib import Path

import pytest

from nanopynq.npq import design_id
from nanopynq.transport.uartbone import UARTBone
from tests import jsrun
from tests.fakes import FakeUARTBoneDevice
from tests.jsrun import ROOT, node

JS = Path(__file__).parents[1] / "sdk" / "js" / "transport" / "uartbone.js"

_DRIVER = """
const { UARTBone } = require(process.argv[1]);
const sent = [];
const port = {
  resetInput() {},
  async write(b) { sent.push(...b); },
  async readExactly(n, timeoutMs) {
    if (process.argv[2] === "silent") throw new Error("timeout");
    return Uint8Array.from([0x4e, 0x50, 0x51, 0x31]);
  },
};
(async () => {
  const bone = new UARTBone(port);
  const out = {};
  // Not awaited one by one: the client itself must keep the transactions in order.
  const pending = [bone.read(0x1000), bone.write(0x2000, 0xdeadbeef), bone.read(0x0008)];
  out.results = (await Promise.allSettled(pending)).map((r) => (r.status === "fulfilled" ? r.value ?? null : "error"));
  out.sent = sent;
  try { await bone.read(0x1002); } catch (e) { out.unaligned = e.name; }
  console.log(JSON.stringify(out));
})();
"""


def _run(mode: str) -> dict:
    return json.loads(node(_DRIVER, str(JS), mode))


def test_js_client_matches_python_frames():
    dev = FakeUARTBoneDevice()
    ub = UARTBone(dev, 115200)
    ub.read(0x1000)
    ub.write(0x2000, 0xDEADBEEF)
    ub.read(0x0008)

    out = _run("answer")
    assert bytes(out["sent"]) == dev.received
    assert out["results"] == [0x4E505131, None, 0x4E505131]
    assert out["unaligned"] == "RangeError"


def test_js_client_keeps_going_after_a_timeout():
    out = _run("silent")
    assert out["results"] == ["error", None, "error"]
    assert len(out["sent"]) == 6 + 10 + 6


# ---------------------------------------------------------------- transport/webserial.js: SerialLink

_LINK = """
const { SerialLink } = require("./sdk/js/transport/webserial.js");
// A Web Serial port with the real port's streams; rx feeds what the board answers, rx.error() is the port failing.
function fakePort() {
  const port = { rx: null, sent: [], closed: 0 };
  port.open = async (options) => {
    port.options = options;
    port.readable = new ReadableStream({ start(c) { port.rx = c; } });
    port.writable = new WritableStream({ write(b) { port.sent.push(...b); } });
  };
  port.close = async () => {
    if (port.readable.locked || port.writable.locked) throw new TypeError("close() while the streams are locked");
    port.closed++;
  };
  return port;
}
const tick = () => new Promise((r) => setTimeout(r, 0));
(async () => {
  const out = {};
  let port = fakePort();
  const errors = [];
  let link = new SerialLink(port, (e) => errors.push(e.message));
  await link.open({ baudRate: 115200 });
  await link.write(Uint8Array.of(1, 2));
  out.options = port.options;
  out.sent = port.sent;
  // an answer in pieces, as USB delivers it; a byte past the four stays for the next read
  const answer = link.readExactly(4, 1000);
  for (const piece of [[0x4e, 0x50], [0x51], [0x31, 0x99]]) { port.rx.enqueue(Uint8Array.from(piece)); await tick(); }
  out.answer = [...await answer];
  out.left = [...link.buf];
  link.resetInput();
  out.afterReset = link.buf.length;
  out.timeout = await link.readExactly(4, 20).catch((e) => e.message);
  // pyserial's read: what came within the time, at most n; at once when n are in
  const some = link.readAtMost(4, 50);
  port.rx.enqueue(Uint8Array.of(1, 2));
  out.atMostShort = [...await some];
  port.rx.enqueue(Uint8Array.of(3, 4, 5, 6, 7));
  await tick();
  const t1 = performance.now();
  out.atMostFull = [...await link.readAtMost(4, 5000)];
  out.atMostFast = performance.now() - t1 < 1000;
  out.atMostLeft = [...link.buf];
  link.resetInput();
  out.atMostNone = [...await link.readAtMost(4, 20)];
  // close() ends a waiting read at once, and closing is not a read error
  const t0 = performance.now();
  const waiting = link.readExactly(4, 5000).catch((e) => e.message);
  await tick();
  await link.close();
  out.waiting = await waiting;
  out.closedFast = performance.now() - t0 < 1000;
  out.closed = port.closed;
  out.writeAfterClose = await link.write(Uint8Array.of(1)).catch((e) => e.message);
  out.errorsAfterClose = [...errors];
  // the port fails while open (unplugged): onReadError once, and reads time out from then on
  port = fakePort();
  link = new SerialLink(port, (e) => errors.push(e.message));
  await link.open({ baudRate: 115200 });
  port.rx.error(new Error("device lost"));
  await tick();
  out.readErrors = [...errors];
  out.afterError = await link.readExactly(1, 20).catch((e) => e.message);
  // the port fails while it is being closed (unplugged during Disconnect): nothing to report
  port = fakePort();
  const closing = [];
  link = new SerialLink(port, (e) => closing.push(e.message));
  await link.open({ baudRate: 115200 });
  port.rx.error(new Error("device lost"));
  await link.close();
  out.failedWhileClosing = closing;
  out.closedAfterFailure = port.closed;
  // close() ends a waiting readAtMost at once too
  port = fakePort();
  link = new SerialLink(port);
  await link.open({ baudRate: 115200 });
  const t2 = performance.now();
  const waitingAtMost = link.readAtMost(4, 5000).catch((e) => e.message);
  await tick();
  await link.close();
  out.waitingAtMost = await waitingAtMost;
  out.atMostClosedFast = performance.now() - t2 < 1000;
  // a closed link does not read, even with bytes left in its buffer: pyserial raises on a closed port
  port = fakePort();
  link = new SerialLink(port);
  await link.open({ baudRate: 115200 });
  port.rx.enqueue(Uint8Array.of(9, 9));
  await tick();
  await link.close();
  out.atMostAfterClose = await link.readAtMost(1, 20).then((b) => [...b], (e) => e.message);
  // open() drops what the debugger kept from before, in pieces, and returns once the line is quiet
  port = fakePort();
  link = new SerialLink(port);
  const stale = () => port.rx.enqueue(Uint8Array.from("15 M: 0x", (c) => c.charCodeAt(0)));
  const t4 = performance.now();
  const opening = link.open({ baudRate: 115200 });
  stale();
  for (const delay of [80, 160]) setTimeout(stale, delay); // each piece restarts the quiet time
  await opening;
  out.staleOpenMs = performance.now() - t4;
  await tick();
  out.staleLeft = link.buf.length;
  const clean = link.readExactly(4, 1000);
  port.rx.enqueue(Uint8Array.of(0x4e, 0x50, 0x51, 0x31));
  out.afterStale = [...await clean];
  await link.close();
  // a board that never stops sending does not hold open() forever
  port = fakePort();
  link = new SerialLink(port);
  const noisy = link.open({ baudRate: 115200 });
  await tick();
  const chatter = setInterval(() => port.rx.enqueue(Uint8Array.of(0x55)), 20);
  const t3 = performance.now();
  await noisy;
  out.noisyOpenMs = performance.now() - t3;
  clearInterval(chatter);
  await link.close();
  // sendBreak holds the break signal for the time asked
  port = fakePort();
  port.signals = [];
  port.setSignals = async (s) => { port.signals.push([s, Math.round(performance.now())]); };
  link = new SerialLink(port);
  await link.open({ baudRate: 115200 });
  await link.sendBreak(60);
  out.breakSignals = port.signals.map(([s]) => s);
  out.breakMs = port.signals[1][1] - port.signals[0][1];
  // closing during a break ends the break first
  port.signals = [];
  const held = link.sendBreak(5000).catch(() => {});
  await tick();
  port.close = ((close) => async () => { port.signals.push("close"); return close(); })(port.close);
  await link.close();
  out.breakAtClose = port.signals.map((s) => (Array.isArray(s) ? s[0] : s));
  // without a callback the failure is dropped, not thrown
  port = fakePort();
  link = new SerialLink(port);
  await link.open({ baudRate: 115200 });
  port.rx.error(new Error("device lost"));
  await tick();
  out.noCallback = "ok";
  console.log(JSON.stringify(out));
})();
"""


def test_serial_link_assembles_answers_times_out_closes_and_reports_read_errors():
    out = json.loads(node(_LINK))
    assert out["options"] == {"baudRate": 115200} and out["sent"] == [1, 2]
    assert out["answer"] == [0x4E, 0x50, 0x51, 0x31] and out["left"] == [0x99] and out["afterReset"] == 0
    assert out["timeout"] == "timeout: expected 4 bytes, got 0"
    assert out["atMostShort"] == [1, 2] and out["atMostFull"] == [3, 4, 5, 6] and out["atMostFast"]
    assert out["atMostLeft"] == [7] and out["atMostNone"] == []
    assert out["atMostAfterClose"] == "port closed"
    assert out["waitingAtMost"] == "port closed" and out["atMostClosedFast"]
    assert out["waiting"] == "port closed" and out["closedFast"] and out["closed"] == 1
    assert out["writeAfterClose"] == "port closed" and out["errorsAfterClose"] == []
    assert out["readErrors"] == ["device lost"]
    assert out["afterError"] == "timeout: expected 1 bytes, got 0"
    assert out["failedWhileClosing"] == [] and out["closedAfterFailure"] == 1
    assert 250 < out["staleOpenMs"] < 900 and out["staleLeft"] == 0 and out["afterStale"] == [0x4E, 0x50, 0x51, 0x31]
    assert 900 < out["noisyOpenMs"] < 2000
    assert out["breakSignals"] == [{"break": True}, {"break": False}] and 50 <= out["breakMs"] < 500
    assert out["breakAtClose"] == [{"break": True}, {"break": False}, "close"]
    assert out["noCallback"] == "ok"


# ---------------------------------------------------------------- connect.js, controls.js: board check, widgets

BASE_NPQ = json.loads(
    (ROOT / "src" / "nanopynq" / "data" / "designs" / "tangnano9k-base" / "base.npq").read_text(encoding="utf-8")
)
V10, V11 = 0x00010000, 0x00010001

_CHECK = """
const { UARTBone } = require("./sdk/js/transport/uartbone.js");
const npqConnect = require("./sdk/js/connect.js");
(async () => {
  const out = [];
  for (const { doc, regs, silent: quiet, wakes, noAnswer, fails } of JSON.parse(process.argv[1])) {
    let silent = quiet;
    const breaks = [];
    const sent = [];
    let rx = [];
    const port = {  // answers every read from regs (byte address -> value); unmapped reads give 0xdeadbeef
      resetInput() { rx = []; },
      async write(b) {
        sent.push(...b);
        if (b[0] !== 0x02 || silent) return;
        const v = regs[new DataView(b.buffer).getUint32(2) * 4] ?? 0xdeadbeef;
        rx = [v >>> 24, (v >>> 16) & 255, (v >>> 8) & 255, v & 255];
      },
      async readExactly(n) {
        if (rx.length < n) throw new Error(fails ?? "timeout");
        return Uint8Array.from(rx.splice(0, n));
      },
    };
    if (wakes !== undefined) port.sendBreak = async (ms) => { breaks.push(ms); silent = !wakes; };
    try {
      const t = performance.now();
      const ok = await npqConnect.checkBoard(doc, new UARTBone(port, 10), noAnswer);
      out.push({ ok, sent, breaks, ms: performance.now() - t });
    } catch (e) {
      out.push({ error: e.message, sent, breaks });
    }
  }
  console.log(JSON.stringify(out));
})();
"""


def _doc(sysinfo: str, did: str = "0xabf78d8c") -> dict:
    doc = json.loads(json.dumps(BASE_NPQ))
    doc["ips"]["sys"]["type"] = f"nanopynq:sysinfo:{sysinfo}"
    doc["design_id"] = did
    return doc


def _check(*scenarios: dict) -> list[dict]:
    out = json.loads(node(_CHECK, json.dumps(list(scenarios))))
    for r in out:  # what went on the wire, decoded by the Python fake device
        dev = FakeUARTBoneDevice()
        dev.write(bytes(r.pop("sent")))
        r["accesses"] = [(rw, a * 4) for rw, a in dev.accesses]
    return out


def _board(version: int, did: int | None = None) -> dict:
    regs = {0x0: 0x4E505131, 0x4: version}
    if did is not None:
        regs[0xC] = did
    return {str(k): v for k, v in regs.items()}


# (file sysinfo, board sys.version, board sys.design_id) -> connects, or the words the reason must contain
MATRIX = [
    ("1.1", V11, 0xABF78D8C, None),
    ("1.1", V11, 0x12345678, "another design: sys.design_id is 0x12345678"),
    ("1.1", V11, 0x0, "0x00000000 (built without a design ID)"),
    ("1.1", V10, None, "has no design ID, but the file declares nanopynq:sysinfo:1.1"),
    ("1.0", V10, None, "Rebuild the design, or use it from Python"),
    # spec 5.8: a 1.0 file is checked by the board's version alone
    ("1.0", V11, 0xABF78D8C, None),
    ("1.0", V11, 0x12345678, "another design"),
    ("1.0", V11, 0x0, "built without a design ID"),
]


@pytest.mark.parametrize(("file_v", "board_v", "board_id", "reason"), MATRIX)
def test_check_board_follows_spec_5_8_and_reads_only_sys(file_v, board_v, board_id, reason):
    (r,) = _check({"doc": _doc(file_v), "regs": _board(board_v, board_id)})
    if reason is None:
        assert r["ok"] == {"id": 0x4E505131, "version": board_v, "designId": board_id}
    else:
        assert reason in r["error"]
    reads = [0x0, 0x4] + ([0xC] if board_v >= V11 else [])
    assert r["accesses"] == [("r", a) for a in reads]  # sys only, and no write


def test_check_board_stops_after_sys_id():
    wrong, silent = _check(
        {"doc": _doc("1.1"), "regs": {"0": 0x12345678}}, {"doc": _doc("1.1"), "regs": {}, "silent": True}
    )
    assert "not a nanopynq design" in wrong["error"] and wrong["accesses"] == [("r", 0x0)]
    assert "No answer" in silent["error"] and silent["accesses"] == [("r", 0x0)]


def test_check_board_wakes_a_silent_port_with_one_break():
    board = _board(V11, 0xABF78D8C)
    woke, still, answering = _check(
        {"doc": _doc("1.1"), "regs": board, "silent": True, "wakes": True},
        {"doc": _doc("1.1"), "regs": board, "silent": True, "wakes": False},
        {"doc": _doc("1.1"), "regs": board, "wakes": True},
    )
    assert woke["ok"]["designId"] == 0xABF78D8C and woke["breaks"] == [250]
    assert woke["accesses"] == [("r", 0x0), ("r", 0x0), ("r", 0x4), ("r", 0xC)]
    assert "No answer" in still["error"] and still["breaks"] == [250] and still["accesses"] == [("r", 0x0)] * 2
    assert answering["breaks"] == []  # a port that answers gets none
    # the bridge gets its time to drop what the break left before the second request (timers may fire a little early)
    assert woke["ms"] >= 190


def test_check_board_sends_no_break_after_connect_time_or_for_another_failure():
    board = _board(V11, 0xABF78D8C)
    later, closed = _check(
        {"doc": _doc("1.1"), "regs": board, "silent": True, "wakes": True, "noAnswer": "the board stopped answering"},
        {"doc": _doc("1.1"), "regs": board, "silent": True, "wakes": True, "fails": "port closed"},
    )
    # a page's poll: other requests share the link, and one sent under a break would be lost
    assert later["error"] == "timeout. No answer: the board stopped answering." and later["breaks"] == []
    assert closed["error"].startswith("port closed.") and closed["breaks"] == []
    assert later["accesses"] == closed["accesses"] == [("r", 0x0)]


_PLAN = """
const npqConnect = require("./sdk/js/connect.js");
const npqControls = require("./sdk/js/controls.js");
const out = { plans: JSON.parse(process.argv[1]).map(npqControls.plan) };
out.values = [["0x3f", 6], ["63", 6], ["64", 6], ["0X3F", 6], ["", 6], ["abc", 6], ["-1", 6], ["0xffffffff", 32],
              ["0x100000000", 32]].map(([t, w]) => npqControls.parseValue(t, w));
out.uart = npqConnect.serialOptions({ link: { kind: "uart", baudrate: 115200 } });
try { npqConnect.serialOptions({ link: { kind: "jtag" } }); } catch (e) { out.jtag = e.message; }
out.ids = [{ kind: "jtag", usb_vid: "0x0403", usb_pid: "0x6010" }, { kind: "jtag" }].map((link) => npqConnect.usbIds({ link }));
console.log(JSON.stringify(out));
"""


def test_widgets_come_from_ips():
    odd = json.loads(json.dumps(BASE_NPQ))
    reg = {"offset": "0x0", "width": 8, "access": "rw"}
    odd["ips"] = {
        "sys": BASE_NPQ["ips"]["sys"],
        "huge": {
            "base": "0x1000",
            "type": "nanopynq:gpio_out:1.0",
            "parameters": {"width": 2**53 - 1},
            "registers": {"data": reg},
        },
        "nowidth": {"base": "0x2000", "type": "nanopynq:gpio_out:2.0", "registers": {"data": reg}},
        "textwidth": {
            "base": "0x3000",
            "type": "nanopynq:gpio_in:1.0",
            "parameters": {"width": "2"},
            "registers": {"data": reg},
        },
        "effect": {
            "base": "0x4000",
            "type": "nanopynq:gpio_in:1.0",
            "parameters": {"width": 2},
            "registers": {"data": reg | {"read_effect": True}},
        },
        "wo_in": {
            "base": "0x5000",
            "type": "nanopynq:gpio_in:1.0",
            "parameters": {"width": 2},
            "registers": {"data": reg | {"access": "wo"}},
        },
        "ro_out": {
            "base": "0x6000",
            "type": "nanopynq:gpio_out:1.0",
            "parameters": {"width": 2},
            "registers": {"data": reg | {"access": "ro"}},
        },
        "wo_out": {
            "base": "0x7000",
            "type": "nanopynq:gpio_out:1.0",
            "parameters": {"width": 3},
            "registers": {"data": reg | {"access": "wo"}},
        },
        "fifo": {
            "base": "0x8000",
            "type": "acme:fifo:1.0",
            "doc": "<b>not html</b>",
            "registers": {
                "pop": {"offset": "0x0", "width": 8, "access": "ro", "read_effect": True},
                "push": {"offset": "0x4", "width": 8, "access": "wo"},
                "level": {"offset": "0x8", "width": 8, "access": "ro", "doc": "entries"},
            },
        },
        "empty": {"base": "0x9000", "type": "acme:empty:1.0"},
        "narrow": {
            "base": "0xa000",
            "type": "nanopynq:gpio_out:1.0",
            "parameters": {"width": 6},
            "registers": {"data": reg | {"width": 4}},
        },
    }
    out = json.loads(node(_PLAN, json.dumps([BASE_NPQ, odd])))
    base, odd_plan = out["plans"]

    assert [(w["name"], w["kind"]) for w in base] == [("sys", "table"), ("leds", "toggles"), ("buttons", "lamps")]
    assert base[1] | {"doc": ""} == {
        "kind": "toggles",
        "name": "leds",
        "type": "nanopynq:gpio_out:1.0",
        "doc": "",
        "addr": 0x1000,
        "count": 6,
        "autoRead": True,
    }
    assert (base[2]["addr"], base[2]["count"]) == (0x2000, 2)
    assert [(r["name"], r["addr"], r["read"], r["write"], r["autoRead"]) for r in base[0]["registers"]] == [
        ("id", 0x0, True, False, True),
        ("version", 0x4, True, False, True),
        ("scratch", 0x8, True, True, True),
        ("design_id", 0xC, True, False, True),
    ]

    kinds = {w["name"]: w["kind"] for w in odd_plan}
    assert kinds == {
        "sys": "table",
        "huge": "table",
        "nowidth": "table",
        "textwidth": "table",
        "effect": "table",
        "wo_in": "table",
        "ro_out": "table",
        "wo_out": "toggles",
        "fifo": "table",
        "empty": "table",
        "narrow": "toggles",
    }
    # #42: no toggle for a bit the data register does not have
    assert next(w for w in odd_plan if w["name"] == "narrow")["count"] == 4
    wo_out = next(w for w in odd_plan if w["name"] == "wo_out")
    assert (wo_out["count"], wo_out["autoRead"]) == (3, False)  # written blind, never read
    fifo = next(w for w in odd_plan if w["name"] == "fifo")
    assert fifo["doc"] == "<b>not html</b>"
    assert [(r["name"], r["read"], r["write"], r["autoRead"]) for r in fifo["registers"]] == [
        ("pop", True, False, False),
        ("push", False, True, False),
        ("level", True, False, True),
    ]
    effect = next(w for w in odd_plan if w["name"] == "effect")
    assert [r["autoRead"] for r in effect["registers"]] == [False]

    assert out["values"] == [63, 63, None, 63, None, None, None, 0xFFFFFFFF, None]
    assert out["uart"] == {"baudRate": 115200}
    assert "only designs reached over UART" in out["jtag"]
    assert out["ids"] == [{"vid": 0x0403, "pid": 0x6010}, None]  # None: a nanopynq-design/1 file


# ---------------------------------------------------------------- the page in headless Chrome, with a fake port

# Before the page's scripts: record errors, and replace Web Serial with a fake UARTBone device (registers by byte
# address) so that no real port can be asked for or opened.
_HEAD = """<base href="{web}">
<script>
"use strict";
window.errors = [];
addEventListener("error", (e) => errors.push(String(e.message)));
addEventListener("unhandledrejection", (e) => errors.push(`unhandled: ${e.reason}`));
window.fake = { regs: {}, wire: [], opened: [], closed: 0, delay: 0, closeDelay: 0, cancel: false, ports: [], listeners: [] };
class FakePort {
  async setSignals(s) { (fake.signals ??= []).push(s); } // so that a break really runs, as on a real port
  async open(options) {
    fake.opened.push(options);
    let rx;
    this.readable = new ReadableStream({ start(c) { rx = c; } });
    this.writable = new WritableStream({ write(b) {
      const addr = new DataView(b.buffer, b.byteOffset).getUint32(2) * 4;
      fake.wire.push([b[0] === 0x02 ? "r" : "w", addr]);
      if (b[0] === 0x02) {
        if (fake.mute) return;
        const v = fake.regs[addr] ?? 0xdeadbeef;
        const send = () => { try { rx.enqueue(Uint8Array.of(v >>> 24, (v >>> 16) & 255, (v >>> 8) & 255, v & 255)); } catch {} };
        if (fake.delay) setTimeout(send, fake.delay); else send();
      } else fake.regs[addr] = new DataView(b.buffer, b.byteOffset).getUint32(6);
    } });
  }
  async close() {
    if (this.readable.locked || this.writable.locked) throw new TypeError("close() while the streams are locked");
    if (fake.closeDelay) await new Promise((r) => setTimeout(r, fake.closeDelay));
    fake.closed++;
  }
  getInfo() { return {}; }
}
Object.defineProperty(navigator, "serial", { configurable: true,
  value: { fake: true,
    async requestPort(options) {
      fake.filters = options && options.filters;
      if (fake.cancel) throw new DOMException("No port selected by the user.", "NotFoundError");
      const p = new FakePort();
      fake.ports.push(p);
      return p;
    },
    addEventListener(type, f) { if (type === "disconnect") fake.listeners.push(f); } } });
</script>
"""

_PAGE_DRIVER = """<script>
const out = {};
const done = () => { document.getElementById("result").textContent = JSON.stringify(out); };
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  Object.assign(out, { ready: document.body.dataset.ready, accept: $("file").accept });
  if (navigator.serial.fake !== true) { out.abort = "Web Serial was not replaced"; return done(); }
  const files = JSON.parse(document.getElementById("files").textContent);
  async function choose(name) {
    const dt = new DataTransfer();
    dt.items.add(new File([files[name]], name));
    $("file").files = dt.files;
    $("status").textContent = "";
    $("file").dispatchEvent(new Event("change"));
    // the check runs outside virtual time (Blob, crypto.subtle): wait on messages, which keep virtual time still
    const tick = () => new Promise((r) => { const ch = new MessageChannel(); ch.port1.onmessage = r; ch.port2.postMessage(0); });
    for (let i = 0; i < 1e6 && !$("status").textContent; i++) await tick();
    return { status: $("status").textContent, connect: !$("connect").disabled, summary: $("summary").textContent };
  }
  async function connect(regs) {
    fake.regs = { ...regs };
    fake.wire = [];
    $("connect").click();
    await sleep(500);
    return { status: $("status").textContent, wire: fake.wire.slice(0, 12), closed: fake.closed,
             fieldsets: document.querySelectorAll("#ips fieldset").length };
  }
  const board = { 0: 0x4e505131, 4: 0x00010001, 12: 0xabf78d8c, 8: 0x11, 0x1000: 0x5, 0x2000: 0x2 };
  out.broken = await choose("broken.npq");
  out.jtag = await choose("jtag.npq");
  out.good = await choose("base.npq");
  out.summaryHasImg = !!$("summary").querySelector("img");
  out.connected = await connect(board);
  out.opened = fake.opened;
  out.filters = fake.filters;
  out.toggles = [...document.querySelectorAll("#ips input[type=checkbox]")].map((b) => b.checked);
  out.lamps = [...document.querySelectorAll(".lamp")].map((s) => s.textContent);
  out.legends = [...document.querySelectorAll("legend")].map((l) => l.textContent);
  out.docs = [...document.querySelectorAll("#ips p.doc")].map((p) => p.textContent);
  out.docHasElement = !!document.querySelector("#ips p.doc > i");
  out.sysValues = [...document.querySelectorAll("#ips table code")].map((c) => c.textContent);
  fake.wire = [];
  document.querySelector("#ips input[type=checkbox]").click();
  await sleep(100);
  out.toggleWrites = fake.wire.filter(([rw]) => rw === "w");
  fake.mute = true;  // a poll read is left waiting when Disconnect is pressed
  await sleep(60);
  $("disconnect").click();
  await sleep(1500);
  fake.mute = false;
  out.afterDisconnect = { status: $("status").textContent, closed: fake.closed, fieldsets: document.querySelectorAll("#ips fieldset").length };
  out.mismatch = await connect({ ...board, 12: 0x12345678 });
  out.old = await connect({ ...board, 4: 0x00010000 });
  out.errors = errors;
  done();
})().catch((e) => { out.errors = [...errors, `driver: ${e}`]; done(); });
</script>
<pre id="result">pending</pre>
"""


def _run_page(tmp_path, files: dict, driver: str) -> dict:
    page = (jsrun.WEB / "index.html").read_text(encoding="utf-8")
    page = page.replace("<head>", "<head>" + _HEAD.replace("{web}", jsrun.WEB.as_uri() + "/"), 1)
    files_json = json.dumps(files).replace("<", "\\u003c")
    page = page.replace(
        "</body>", f'<script type="application/json" id="files">{files_json}</script>{driver}</body>', 1
    )
    (tmp_path / "page.html").write_text(page, encoding="utf-8")
    return json.loads(jsrun.pre(jsrun.chrome_dump(tmp_path / "page.html", tmp_path / "profile"), "result"))


def test_page_flow_in_chrome(tmp_path):
    base_text = (ROOT / "src" / "nanopynq" / "data" / "designs" / "tangnano9k-base" / "base.npq").read_text(
        encoding="utf-8"
    )
    good = json.loads(base_text)
    good["name"] = "<img src=x onerror=errors.push('name')>"  # top-level strings are not checked (spec 5.2)
    good["ips"]["leds"]["doc"] = "<i>six</i> LEDs"  # doc is not part of the design_id
    good["link"]["usb_vid"] = "0x1a86"  # not the page's own default: the chooser must be asked for the file's
    jtag = json.loads(base_text)
    jtag["link"] = {"kind": "jtag", "usb_vid": jtag["link"]["usb_vid"], "usb_pid": jtag["link"]["usb_pid"]}
    files = {
        "broken.npq": '{"format": "nanopynq-design/1", "board": 6.0}',
        "base.npq": json.dumps(good),
        "jtag.npq": json.dumps(jtag),
    }
    out = _run_page(tmp_path, files, _PAGE_DRIVER)

    assert "abort" not in out and out["errors"] == [] and out["ready"] == "1"
    assert out["accept"] == ".npq"
    assert "rule V1 at (file)" in out["broken"]["status"] and not out["broken"]["connect"]
    assert "only designs reached over UART" in out["jtag"]["status"] and not out["jtag"]["connect"]
    assert out["good"]["connect"] and "design_id 0xabf78d8c" in out["good"]["summary"]
    assert "<img src=x" in out["good"]["summary"] and not out["summaryHasImg"]

    c = out["connected"]
    assert c["status"] == "Connected: the board runs design 0xabf78d8c" and c["fieldsets"] == 3
    assert out["opened"][0] == {"baudRate": 115200}
    assert out["filters"] == [{"usbVendorId": 0x1A86, "usbProductId": 0x6010}]  # link.usb_vid / usb_pid of the file
    assert c["wire"][:3] == [["r", 0x0], ["r", 0x4], ["r", 0xC]]  # the check comes before anything else
    assert ["r", 0x2000] in c["wire"] and all(rw == "r" for rw, _ in c["wire"])
    assert out["toggles"] == [True, False, True, False, False, False]
    assert out["lamps"] == ["0: off", "1: on"]
    assert out["legends"] == [
        "sys (nanopynq:sysinfo:1.1)",
        "leds (nanopynq:gpio_out:1.0)",
        "buttons (nanopynq:gpio_in:1.0)",
    ]
    assert out["docs"] == ["<i>six</i> LEDs"] and not out["docHasElement"]
    assert out["sysValues"] == ["0x4e505131", "0x00010001", "0x00000011", "0xabf78d8c"]
    assert out["toggleWrites"] == [["w", 0x1000]]
    assert out["afterDisconnect"] == {"status": "Disconnected", "closed": 1, "fieldsets": 0}

    for key, reason, reads in (
        ("mismatch", "another design: sys.design_id is 0x12345678", [0x0, 0x4, 0xC]),
        ("old", "has no design ID, but the file declares", [0x0, 0x4]),
    ):
        stop = out[key]
        assert reason in stop["status"] and stop["fieldsets"] == 0
        assert stop["wire"] == [["r", a] for a in reads]  # sys only, then the port is closed
    assert (out["mismatch"]["closed"], out["old"]["closed"]) == (2, 3)


# ---------------------------------------------------------------- the page with other designs, and a connection that ends

_SYS = BASE_NPQ["ips"]["sys"]
_REG = {"offset": "0x0", "width": 8}
_IPS = {
    # gpio_in only: lamps polled at 0x2000
    "a": {
        "sys": _SYS,
        "buttons": {
            "base": "0x2000",
            "type": "nanopynq:gpio_in:1.0",
            "parameters": {"width": 2},
            "registers": {"data": {"offset": "0x0", "width": 2, "access": "ro"}},
        },
    },
    # a write-only gpio_out, and at 0x2000 an IP of an unknown type whose read pops
    "b": {
        "sys": _SYS,
        "leds": {
            "base": "0x1000",
            "type": "nanopynq:gpio_out:1.0",
            "parameters": {"width": 3},
            "registers": {"data": {"offset": "0x0", "width": 3, "access": "wo"}},
        },
        "fifo": {
            "base": "0x2000",
            "type": "acme:fifo:1.0",
            "registers": {
                "pop": _REG | {"access": "ro", "read_effect": True},
                "push": _REG | {"offset": "0x4", "access": "wo"},
                "level": _REG | {"offset": "0x8", "access": "ro"},
            },
        },
    },
}


def _npq(ips: dict) -> dict:
    return {
        "format": "nanopynq-design/1",
        "board": "tangnano9k",
        "bitstream": {"file": "x.fs", "sha256": "0" * 64},
        "link": {"kind": "uart", "baudrate": 115200},
        "design_id": f"0x{design_id(ips):08x}",
        "ips": ips,
    }


# Each scenario ends disconnected. A negative check ("nothing more happens") waits 1500 ms first: longer than the
# 1000 ms read timeout after which a stale read used to act. The page runs in virtual time, so the waits are exact.
_ENDS_DRIVER = """<pre id="result">pending</pre>
<script>
const out = {};
const done = () => { document.getElementById("result").textContent = JSON.stringify(out); };
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const until = async (what, cond) => {
    for (let t = 0; !cond(); t += 10) { if (t > 10000) throw new Error(`waited for ${what}`); await sleep(10); }
  };
  const files = JSON.parse(document.getElementById("files").textContent);
  const bytes = (name) => new TextEncoder().encode(files[name]);
  const ids = Object.fromEntries(Object.entries(files).map(([n, t]) => [n, JSON.parse(t).design_id]));
  const pick = (name) => {
    const dt = new DataTransfer();
    dt.items.add(new File([files[name]], name));
    $("file").files = dt.files;
    $("file").dispatchEvent(new Event("change"));
  };
  // The check reads a Blob and hashes with crypto.subtle outside virtual time, so a timer wait could run out before it
  // ends; waiting on messages keeps virtual time still.
  const tick = () => new Promise((r) => { const ch = new MessageChannel(); ch.port1.onmessage = r; ch.port2.postMessage(0); });
  async function choose(name) {
    $("status").textContent = "";
    pick(name);
    for (let i = 0; !$("status").textContent; i++) { if (i > 1e6) throw new Error(`waited for the check of ${name}`); await tick(); }
    return $("status").textContent;
  }
  const board = (name) => ({ 0: 0x4e505131, 4: 0x00010001, 12: parseInt(ids[name]), 8: 0x11, 0x2000: 0x2 });
  const connected = () => $("status").textContent.startsWith("Connected");
  async function connect(name) {
    fake.regs = board(name);
    fake.wire = [];
    $("connect").click();
    await until("Connected", connected);
  }
  async function disconnect() {
    $("disconnect").click();
    await until("Disconnected", () => $("status").textContent === "Disconnected");
  }
  const reads = (from = 0) => fake.wire.slice(from).filter(([rw]) => rw === "r").map(([, a]) => a);
  const view = () => ({ status: $("status").textContent, fieldsets: document.querySelectorAll("#ips fieldset").length,
                        lamps: document.querySelectorAll(".lamp").length });
  const button = (label) => document.querySelector(`#ips button[aria-label="${label}"]`);

  // without crypto.subtle (an insecure context) the reason is said
  Object.defineProperty(crypto, "subtle", { value: undefined, configurable: true });
  out.noSubtle = await choose("base.npq");
  delete crypto.subtle;

  // a check that ends after a later choice does not replace it; Connect waits for the check
  await choose("base.npq");
  const real = npq.readNpq;
  let release;
  const gate = new Promise((r) => { release = r; });
  npq.readNpq = async (b) => { const d = await real(b); if (d.design_id === ids["a.npq"]) await gate; return d; };
  pick("a.npq");
  out.connectDuringCheck = !$("connect").disabled;
  $("connect").click();
  out.choice = { later: await choose("b.npq") };
  release();
  await npq.readNpq(bytes("a.npq"));  // after the held check has gone on
  npq.readNpq = real;
  Object.assign(out.choice, { status: $("status").textContent, summary: $("summary").textContent,
                              opened: fake.opened.length });

  // b: only safe reads, a write-only toggle written blind, and the file kept while connected
  await connect("b.npq");
  out.b = { connectReads: reads(), fileDisabled: $("file").disabled };
  let from = fake.wire.length;
  button("Read all registers of fifo that are safe to read").click();
  await until("Read all", () => reads(from).length);
  out.b.readAll = reads(from);
  from = fake.wire.length;
  document.querySelector("#ips input[type=checkbox]").click();
  await until("the toggle write", () => fake.wire.length > from);
  out.b.toggle = fake.wire.slice(from);
  const summary = $("summary").textContent;
  pick("a.npq");
  await npq.readNpq(bytes("a.npq"));
  out.b.afterChange = { summaryKept: $("summary").textContent === summary, ...view() };
  await disconnect();

  // B1: Disconnect while the build reads sys.scratch; then another design at the same addresses
  await choose("a.npq");
  fake.delay = 100;
  fake.regs = board("a.npq");
  fake.wire = [];
  $("connect").click();
  await until("the scratch read", () => reads().includes(0x8));
  await disconnect();
  from = fake.wire.length;
  await sleep(1500);
  out.b1 = { later: view(), wireAfter: fake.wire.slice(from) };
  fake.delay = 0;
  await choose("b.npq");
  await connect("b.npq");
  await sleep(500);
  Object.assign(out.b1, { next: view(), legends: [...document.querySelectorAll("legend")].map((l) => l.textContent),
                          popReads: reads().filter((a) => a === 0x2000).length });
  await disconnect();

  // a table read unanswered at Disconnect does not stop the next connection
  await connect("b.npq");
  fake.mute = true;
  from = fake.wire.length;
  button("Read sys.scratch").click();
  await until("the scratch read", () => reads(from).includes(0x8));
  await disconnect();
  fake.mute = false;
  await connect("b.npq");
  const closed = fake.closed;
  await sleep(1500);
  out.tableRead = { ...view(), closedSince: fake.closed - closed };
  await disconnect();

  // Disconnect during the check of the board
  await choose("a.npq");
  fake.delay = 100;
  fake.regs = board("a.npq");
  fake.wire = [];
  $("connect").click();
  await until("the version read", () => reads().includes(0x4));
  await disconnect();
  await sleep(1500);
  out.duringCheck = view();
  fake.delay = 0;

  // two clicks on Connect
  const opened = fake.opened.length;
  fake.regs = board("a.npq");
  $("connect").click();
  $("connect").click();
  await until("Connected", connected);
  await sleep(500);
  out.double = { opened: fake.opened.length - opened, ...view() };
  await disconnect();
  out.ports = { opened: fake.opened.length, closed: fake.closed };
  out.errors = errors;
  done();
})().catch((e) => { out.errors = [...errors, `driver: ${e}`]; done(); });
</script>
"""


def test_page_ends_connections_cleanly_and_reads_only_what_is_safe(tmp_path):
    files = {f"{n}.npq": json.dumps(_npq(ips)) for n, ips in _IPS.items()}
    files["base.npq"] = json.dumps(BASE_NPQ)
    out = _run_page(tmp_path, files, _ENDS_DRIVER)
    assert out["errors"] == []
    assert "needs crypto.subtle" in out["noSubtle"]

    assert not out["connectDuringCheck"]
    b_id = json.loads(files["b.npq"])["design_id"]
    assert out["choice"] == {
        "later": "File checked. Connect to the board.",
        "status": "File checked. Connect to the board.",
        "summary": out["choice"]["summary"],
        "opened": 0,
    }
    assert out["choice"]["summary"].startswith("b.npq:") and b_id in out["choice"]["summary"]

    b = out["b"]
    assert b["connectReads"] == [
        0x0,
        0x4,
        0xC,
        0x8,
        0x2008,
    ]  # not leds.data (wo), fifo.pop (read_effect), fifo.push (wo)
    assert b["readAll"] == [0x2008]
    assert b["toggle"] == [["w", 0x1000]]
    assert b["fileDisabled"]
    assert b["afterChange"] == {
        "summaryKept": True,
        "status": f"Connected: the board runs design {b_id}",
        "fieldsets": 3,
        "lamps": 0,
    }

    b1 = out["b1"]
    assert b1["later"] == {"status": "Disconnected", "fieldsets": 0, "lamps": 0}
    assert b1["wireAfter"] == []
    assert b1["next"] == {"status": f"Connected: the board runs design {b_id}", "fieldsets": 3, "lamps": 0}
    assert b1["legends"] == ["sys (nanopynq:sysinfo:1.1)", "leds (nanopynq:gpio_out:1.0)", "fifo (acme:fifo:1.0)"]
    assert b1["popReads"] == 0

    assert out["tableRead"] == {
        "status": f"Connected: the board runs design {b_id}",
        "fieldsets": 3,
        "lamps": 0,
        "closedSince": 0,
    }
    assert out["duringCheck"] == {"status": "Disconnected", "fieldsets": 0, "lamps": 0}
    a_id = json.loads(files["a.npq"])["design_id"]
    assert out["ports"]["opened"] == out["ports"]["closed"]  # every port opened was closed
    assert out["double"] == {
        "opened": 1,
        "status": f"Connected: the board runs design {a_id}",
        "fieldsets": 2,
        "lamps": 2,
    }


_FOLLOW_DRIVER = """<script>
const out = {};
const done = () => { document.getElementById("result").textContent = JSON.stringify(out); };
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const files = JSON.parse(document.getElementById("files").textContent);
  const tick = () => new Promise((r) => { const ch = new MessageChannel(); ch.port1.onmessage = r; ch.port2.postMessage(0); });
  function pick(name) {
    const dt = new DataTransfer();
    dt.items.add(new File([files[name]], name));
    $("file").files = dt.files;
    $("file").dispatchEvent(new Event("change"));
  }
  async function choose(name) {
    $("status").textContent = "";
    pick(name);
    for (let i = 0; i < 1e6 && !$("status").textContent; i++) await tick();
  }
  const state = () => ({ status: $("status").textContent, closed: fake.closed, fieldsets: document.querySelectorAll("#ips fieldset").length });
  const board = { 0: 0x4e505131, 4: 0x00010001, 12: 0xabf78d8c, 8: 0x11, 0x1000: 0x5, 0x2000: 0x2 };
  await choose("base.npq");

  // the chooser is cancelled: say so
  fake.cancel = true;
  $("connect").click();
  await sleep(100);
  fake.cancel = false;
  out.cancelled = { status: $("status").textContent, connect: !$("connect").disabled };

  // the FPGA is reprogrammed while connected: the next poll stops
  fake.regs = { ...board };
  $("connect").click();
  await sleep(300);
  out.connected = state();
  fake.wire = [];
  fake.regs[12] = 0x12345678;
  await sleep(300);
  out.reprogrammed = { ...state(), writes: fake.wire.filter(([rw]) => rw === "w").length };

  // the board stops answering while connected (being reprogrammed): no "wrong port" hint
  fake.regs = { ...board };
  $("connect").click();
  await sleep(300);
  fake.mute = true;
  await sleep(1500);
  fake.mute = false;
  out.silent = state();

  // another serial device goes away: the connection stays; this board's port goes away: it ends
  fake.regs = { ...board };
  $("connect").click();
  await sleep(300);
  fake.listeners.forEach((f) => f({ target: {} }));
  await sleep(100);
  out.otherUnplugged = state();
  // a file chosen while connected is not taken, and the input does not keep showing it
  pick("other.npq");
  await sleep(50);
  out.fileWhileConnected = { files: $("file").files.length, summary: $("summary").textContent };
  fake.listeners.forEach((f) => f({ target: fake.ports.at(-1) }));
  await sleep(300);
  out.unplugged = state();

  // a slow close: a file chosen meanwhile and a new connection must keep the new connection's status
  fake.regs = { ...board };
  $("connect").click();
  await sleep(300);
  fake.closeDelay = 400;
  $("disconnect").click();
  await sleep(50);
  await choose("base.npq");
  fake.closeDelay = 0;
  $("connect").click();
  await sleep(800);
  out.reconnectWhileClosing = state();
  out.errors = errors;
  done();
})().catch((e) => { out.errors = [...errors, `driver: ${e}`]; done(); });
</script>
<pre id="result">pending</pre>
"""


def test_page_follows_the_board_and_its_port(tmp_path):
    base_text = (ROOT / "src" / "nanopynq" / "data" / "designs" / "tangnano9k-base" / "base.npq").read_text(
        encoding="utf-8"
    )
    other = json.loads(base_text)
    other["ips"]["sys"]["registers"]["scratch"]["doc"] = "another file"
    out = _run_page(tmp_path, {"base.npq": base_text, "other.npq": json.dumps(other)}, _FOLLOW_DRIVER)
    connected = "Connected: the board runs design 0xabf78d8c"
    assert out["errors"] == []
    assert out["cancelled"] == {"status": "No port chosen. Connect again to choose one.", "connect": True}
    assert out["connected"]["status"] == connected
    # #42: the design ID is read again with every lamp poll
    assert out["reprogrammed"]["status"].startswith(
        "Stopped: The board runs another design: sys.design_id is 0x12345678"
    )
    assert out["reprogrammed"]["writes"] == 0 and out["reprogrammed"]["fieldsets"] == 0
    assert out["silent"]["status"].startswith("Stopped: timeout") and "stopped answering" in out["silent"]["status"]
    assert "wrong port" not in out["silent"]["status"]
    assert out["otherUnplugged"]["status"] == connected
    assert out["fileWhileConnected"]["files"] == 0 and out["fileWhileConnected"]["summary"].startswith("base.npq")
    assert out["unplugged"]["status"] == "Board unplugged"
    assert out["reconnectWhileClosing"]["status"] == connected and out["reconnectWhileClosing"]["fieldsets"] == 3

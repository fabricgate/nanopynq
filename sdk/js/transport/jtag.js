// JTAG over the Tang Nano's onboard debugger (BL702 / BL616, FT2232-compatible interface A) with WebUSB,
// mirroring src/nanopynq/transport/mpsse.py and jtagbridge.py. Values are BigInt (64-bit DR scans).
// Only the MPSSE opcodes the BL702 takes: 0x39/0x3B (write -ve, read +ve), 0x4B/0x6B (TMS), 0x80, 0x85, 0x86, 0x87.
"use strict";

const IFACE_INDEX = 1; // FTDI wIndex for interface A
const EP_OUT = 2, EP_IN = 1; // WebUSB endpoint numbers (0x02 OUT, 0x81 IN)
const DIR = 0x0b; // GPIO low byte: bit0 TCK, bit1 TDI, bit2 TDO (in), bit3 TMS
const IR_USER = 0x42; // GW_JTAG ER1: the nanopynq JTAG bridge
const CHUNK = 100; // bridge commands per USB transfer, as in jtagbridge.py

const mask = (n) => (1n << BigInt(n)) - 1n;

// Clock nbits of value out on TDI (LSB first) while reading TDO; the last bit goes with TMS=1.
function encodeShift(value, nbits) {
  value = BigInt(value);
  const nbytes = Math.floor((nbits - 1) / 8);
  const rest = nbits - 1 - nbytes * 8;
  const cmd = [];
  if (nbytes) {
    const n = nbytes - 1;
    cmd.push(0x39, n & 0xff, n >> 8);
    for (let i = 0; i < nbytes; i++) cmd.push(Number((value >> BigInt(8 * i)) & 0xffn));
  }
  if (rest) cmd.push(0x3b, rest - 1, Number((value >> BigInt(8 * nbytes)) & mask(rest)));
  cmd.push(0x6b, 0, (Number((value >> BigInt(nbits - 1)) & 1n) << 7) | 0x01);
  return cmd;
}

const respLen = (nbits) => Math.floor((nbits - 1) / 8) + ((nbits - 1) % 8 ? 1 : 0) + 1;

// TDO bits of one encodeShift(): bit-mode bytes come MSB-aligned, the TMS bit is bit 7.
function decodeShift(resp, nbits) {
  const nbytes = Math.floor((nbits - 1) / 8);
  const rest = nbits - 1 - nbytes * 8;
  let out = 0n;
  for (let i = 0; i < nbytes; i++) out |= BigInt(resp[i]) << BigInt(8 * i);
  if (rest) out |= BigInt(resp[nbytes] >> (8 - rest)) << BigInt(8 * nbytes);
  out |= BigInt((resp[resp.length - 1] >> 7) & 1) << BigInt(nbits - 1);
  return out;
}

const tmsCmd = (bits) => [0x4b, bits.length - 1, [...bits].reduce((a, b, i) => a | (Number(b) << i), 0)];

// `usb` is a WebUSB USBDevice, or anything with controlTransferOut / transferOut / transferIn like it.
class Mpsse {
  constructor(usb, pkt = 64, timeoutMs = 1000) {
    this.usb = usb;
    this.pkt = pkt; // IN packet size: 64 on the BL702 (full speed), 512 on the BL616 (high speed)
    this.timeoutMs = timeoutMs;
    this._cmd = [];
    this._shifts = [];
    this._stale = false; // set when a flush did not finish: its answer may still arrive
  }

  static async open(usb) {
    await usb.open();
    if (usb.configuration === null) await usb.selectConfiguration(1);
    await usb.claimInterface(0);
    const ep = usb.configuration.interfaces[0].alternate.endpoints.find((e) => e.direction === "in");
    const m = new Mpsse(usb, ep ? ep.packetSize : 64);
    // reset, purge RX, purge TX, latency timer 2 ms, bitmode reset, MPSSE
    for (const [req, val] of [[0x00, 0], [0x00, 1], [0x00, 2], [0x09, 2], [0x0b, 0x0000], [0x0b, 0x0200 | DIR]]) {
      await usb.controlTransferOut({ requestType: "vendor", recipient: "device", request: req, value: val, index: IFACE_INDEX });
    }
    await m._drain();
    await m._write([0x85, 0x86, 5, 0, 0x80, 0x08, DIR]); // loopback off, divisor 5 (TCK ignores it), pins
    return m;
  }

  async _write(bytes) {
    const r = await this.usb.transferOut(EP_OUT, Uint8Array.from(bytes));
    if (r.status !== "ok" || r.bytesWritten !== bytes.length) throw new Error(`USB write: ${r.status}, ${r.bytesWritten}/${bytes.length}`);
  }

  async _read(n) {
    const out = [];
    const end = Date.now() + this.timeoutMs;
    while (out.length < n && Date.now() < end) {
      const r = await this.usb.transferIn(EP_IN, 512 * 8);
      const raw = new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength);
      for (let i = 0; i < raw.length; i += this.pkt) out.push(...raw.subarray(i + 2, i + this.pkt)); // 2 status bytes per packet
    }
    if (out.length < n) throw new Error(`timeout: ${out.length} of ${n} bytes`);
    return out.slice(0, n);
  }

  async _drain() {
    for (let i = 0; i < 20; i++) {
      const r = await this.usb.transferIn(EP_IN, 512 * 8);
      if (r.data.byteLength <= 2) return;
    }
  }

  tms(bits) { this._cmd.push(...tmsCmd(bits)); }

  shift(value, nbits) {
    this._cmd.push(...encodeShift(value, nbits));
    this._shifts.push(nbits);
  }

  // Send everything queued in one USB write; return the TDO of each queued shift in order.
  async flush() {
    const cmd = [...this._cmd, 0x87], shifts = this._shifts;
    this._cmd = [];
    this._shifts = [];
    const n = shifts.reduce((a, k) => a + respLen(k), 0);
    if (this._stale) { // drop a failed flush's late answer before this one (as mpsse.py does)
      await this.usb.controlTransferOut({ requestType: "vendor", recipient: "device", request: 0x00, value: 1, index: IFACE_INDEX });
      await this._drain();
      this._stale = false;
    }
    let resp;
    try {
      await this._write(cmd);
      resp = n ? await this._read(n) : [];
    } catch (e) {
      this._stale = true;
      throw e;
    }
    const out = [];
    let i = 0;
    for (const k of shifts) {
      out.push(decodeShift(resp.slice(i, i + respLen(k)), k));
      i += respLen(k);
    }
    return out;
  }

  async close() {
    try { await this.usb.releaseInterface(0); } finally { await this.usb.close(); }
  }
}

// IDCODE is the instruction after Test-Logic-Reset (as tools/p0/jtag_mpsse_min.py reads it). IR 0x11 (READ_IDCODE)
// gives the same value; 0x19 is what the 8-bit IR shift itself returns (its capture value), not an IDCODE.
async function readIdcode(m) {
  m.tms("11111");
  m.tms("0100"); // Test-Logic-Reset -> Run-Test/Idle -> Select-DR -> Capture-DR -> Shift-DR
  m.shift(0, 32);
  m.tms("10"); // Exit1-DR -> Update-DR -> Run-Test/Idle
  const [id] = await m.flush();
  return Number(id);
}

const command = (addr, write = false, data = 0) =>
  (1n << 63n) | (BigInt(write) << 62n) | (BigInt(addr / 4) << 32n) | (BigInt(data >>> 0) & 0xffffffffn);

// The nanopynq JTAG bridge behind GW_JTAG ER1: one 64-bit DR scan per command, the next scan returns its result.
class JtagBridge {
  constructor(m) { this.m = m; }

  async reset() {
    this.m.tms("11111");
    this.m.tms("01100");
    this.m.shift(IR_USER, 8);
    this.m.tms("10");
    this._dr(0n);
    await this.m.flush();
  }

  _dr(v) {
    this.m.tms("100");
    this.m.shift(v, 64);
    this.m.tms("10");
  }

  async _ops(cmds) {
    const out = [];
    for (let i = 0; i < cmds.length; i += CHUNK) {
      for (const c of cmds.slice(i, i + CHUNK)) this._dr(c);
      this._dr(0n);
      for (const r of (await this.m.flush()).slice(1)) {
        if (r >> 32n !== 1n << 31n) throw new Error(`bridge: bad response 0x${r.toString(16)}`);
        out.push(Number(r & 0xffffffffn));
      }
    }
    return out;
  }

  async read(addr) {
    if (addr % 4) throw new RangeError(`address 0x${addr.toString(16)} is not 4-byte aligned`);
    return (await this._ops([command(addr)]))[0];
  }

  async write(addr, value) {
    if (addr % 4) throw new RangeError(`address 0x${addr.toString(16)} is not 4-byte aligned`);
    await this._ops([command(addr, true, value)]);
  }
}

// ---- Loading a Gowin .fs into SRAM: the sequence of openFPGALoader's Gowin SRAM path (Apache-2.0), reimplemented.
// Checked on the Tang Nano 20K (GW2A-18C); see reports/report_webusb.md.

const GW = { NOOP: 0x02, ERASE_SRAM: 0x05, XFER_DONE: 0x09, INIT_ADDR: 0x12, CONFIG_ENABLE: 0x15, XFER_WRITE: 0x17,
             CONFIG_DISABLE: 0x3a, STATUS: 0x41 };
const ST = { CRC_ERROR: 1 << 0, MEMORY_ERASE: 1 << 5, SYSTEM_EDIT_MODE: 1 << 7, DONE_FINAL: 1 << 13 };
const REV = Uint8Array.from({ length: 256 }, (_, i) => parseInt(i.toString(2).padStart(8, "0").split("").reverse().join(""), 2));

// The .fs text -> its bytes (non-comment lines of '0'/'1' up to the first empty line, 8 characters per byte,
// first character = MSB) and the IDCODE of its header line (key 0x06, 64 bits, low 32 bits).
function parseFs(text) {
  const out = [];
  let idcode = null;
  for (let line of text.split("\n")) {
    line = line.replace(/\r$/, "");
    if (line === "") break;
    if (line[0] === "/") continue;
    if (line.length % 8 || /[^01]/.test(line)) throw new Error(`not a .fs file: line "${line.slice(0, 40)}"`);
    for (let i = 0; i < line.length; i += 8) out.push(parseInt(line.slice(i, i + 8), 2));
    if (idcode === null && line.length === 64 && (parseInt(line.slice(0, 8), 2) & 0x7f) === 0x06) {
      idcode = parseInt(line.slice(32), 2) >>> 0;
    }
  }
  return { data: Uint8Array.from(out), idcode };
}

class GowinSram {
  constructor(m) { this.m = m; }

  _ir(cmd) { // Run-Test/Idle -> Shift-IR, 8 bits, -> Run-Test/Idle, 6 idle clocks
    this.m.tms("1100");
    this.m.shift(cmd, 8);
    this.m.tms("10");
    this.m.tms("000000");
  }

  async cmd(c) { this._ir(c); await this.m.flush(); }

  async reg32(c) {
    this._ir(c);
    this.m.tms("100");
    this.m.shift(0xffffffffn, 32);
    this.m.tms("10");
    const r = await this.m.flush();
    return Number(r[r.length - 1]) >>> 0;
  }

  async status() { return this.reg32(GW.STATUS); }

  async poll(maskBits, value, what, tries = 2000) {
    let s = 0;
    for (let i = 0; i < tries; i++) if (((s = await this.status()) & maskBits) === value) return s;
    throw new Error(`timeout waiting for ${what}: status 0x${s.toString(16)}`);
  }

  // One DR scan of data, each byte first character first on the wire; ends in Run-Test/Idle.
  // chunk: bytes per write-and-read-back. The BL702 (9K / 4K, 64-byte packets) answered only 1024 of 4096 bytes;
  // 1024 works there. The BL616 (20K) was checked with 4096.
  async _dr(data, onProgress, chunk = this.m.pkt === 64 ? 1024 : 4096) {
    this.m.tms("100");
    await this.m.flush(); // reach Shift-DR before the raw 0x39 writes below
    const wire = data.map((b) => REV[b]); // MPSSE 0x39 sends each byte LSB first
    const last = wire.length - 1;
    for (let i = 0; i < last; i += chunk) {
      const part = wire.subarray(i, Math.min(i + chunk, last));
      const n = part.length - 1;
      await this.m._write([0x39, n & 0xff, n >> 8, ...part, 0x87]);
      await this.m._read(part.length);
      if (onProgress) onProgress(i + part.length, wire.length);
    }
    this.m.shift(wire[last], 8); // TMS=1 on its last bit
    this.m.tms("10");
    await this.m.flush();
  }

  // Erase the SRAM and load the .fs text. Returns the final status; throws unless DONE_FINAL.
  async load(fsText, onProgress) {
    const { data, idcode } = parseFs(fsText);
    const board = await readIdcode(this.m);
    if (idcode !== null && ((idcode & 0x0fffffff) >>> 0) !== ((board & 0x0fffffff) >>> 0)) {
      throw new Error(`the .fs is for IDCODE 0x${idcode.toString(16)}, the board is 0x${board.toString(16)}`);
    }
    if ((await this.status()) & ST.CRC_ERROR) {
      throw new Error("the FPGA reports a CRC error from an earlier load; openFPGALoader clears it first (not done here)");
    }
    await this.cmd(GW.CONFIG_ENABLE); // erase
    await this.poll(ST.SYSTEM_EDIT_MODE, ST.SYSTEM_EDIT_MODE, "edit mode");
    await this.cmd(GW.ERASE_SRAM);
    await this.cmd(GW.NOOP);
    await this.poll(ST.MEMORY_ERASE, ST.MEMORY_ERASE, "erase");
    await this.cmd(GW.XFER_DONE);
    await this.cmd(GW.NOOP);
    await this.cmd(GW.CONFIG_DISABLE);
    await this.cmd(GW.NOOP);
    await this.poll(ST.SYSTEM_EDIT_MODE, 0, "edit mode off");
    await this.cmd(GW.CONFIG_ENABLE); // write
    await this.cmd(GW.INIT_ADDR);
    await this.cmd(GW.XFER_WRITE);
    await this._dr(data, onProgress);
    await this.cmd(GW.CONFIG_DISABLE);
    await this.cmd(GW.NOOP);
    const s = await this.status();
    if (!(s & ST.DONE_FINAL)) throw new Error(`load failed: status 0x${s.toString(16)} (no DONE_FINAL)`);
    return s;
  }
}

if (typeof module !== "undefined") {
  module.exports = { encodeShift, decodeShift, tmsCmd, respLen, Mpsse, readIdcode, JtagBridge, command, parseFs, GowinSram, REV };
}

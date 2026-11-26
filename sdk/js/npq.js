// Reader of design metadata files (<name>.npq, docs/spec_design_metadata.md): the checks V1-V11 and the design_id.
// The browser counterpart of src/nanopynq/npq.py, with the same function for each rule. No dependencies.
// Rules are checked one at a time over the whole document in the order of spec 5.9, so an input that breaks several
// rules reports the lowest number. Nothing is repaired: a broken file throws NpqError with the rule and the place.
// A classic script (Chrome refuses ES modules on file:// pages) that defines one global, `npq`, and is also a
// CommonJS module for Node.
"use strict";

const npq = (() => {
  const FORMAT = "nanopynq-design/2";
  // /1 has no bitstream.family, link.usb_vid or link.usb_pid: a page cannot load its .fs without a board table
  const FORMATS = ["nanopynq-design/1", FORMAT];
  const MAX_BYTES = 1 << 20;
  const MAX_DEPTH = 64; // objects and lists; the top object is 1
  const MAX_SAFE = Number.MAX_SAFE_INTEGER;
  const MAX_FILE = 255;
  const DEFAULT_ADDR_RANGE = 0x1000;
  const RESERVED_IDS = ["0x00000000", "0xdeadbeef"];

  const BOARD = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;
  const FILE = /^[A-Za-z0-9_][A-Za-z0-9._-]*$/;
  const SHA256 = /^[0-9a-f]{64}$/;
  const FAMILY = /^[a-z0-9]+$/; // open: a loader refuses a family it does not know
  const USB_ID = /^0x[0-9a-f]{4}$/;
  const DESIGN_ID = /^0x[0-9a-f]{8}$/;
  const NAME = /^[a-z][a-z0-9_]*$/;
  const HEX = /^0x[0-9a-f]+$/;
  const VERSION = "(0|[1-9][0-9]{0,3})\\.(0|[1-9][0-9]{0,3})";
  const TYPE = new RegExp(`^[a-z0-9_]+:[a-z0-9_]+:${VERSION}$`);
  const SYSINFO = new RegExp(`^nanopynq:sysinfo:${VERSION}$`);
  const INT_LITERAL = /^-?(0|[1-9][0-9]{0,15})$/;
  const NUMBER = /-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?/y; // a JSON number token; the text is valid JSON here
  const WS = /[ \t\n\r]*/y;
  const CONTROL = /[\x00-\x1f\x7f]/;

  const IP_FIELDS = ["base", "addr_range", "type", "parameters", "registers", "streams", "doc"];
  const REG_FIELDS = ["offset", "width", "access", "read_effect", "doc"];
  const SECTIONS = ["parameters", "registers", "streams"];

  class NpqError extends Error {
    // rule: V1..V11; path: dotted, e.g. ips.leds.registers.data.width ("" is the whole file)
    constructor(rule, path, detail) {
      super(`${rule} at ${path || "(file)"}: ${detail}`);
      this.name = "NpqError";
      this.rule = rule;
      this.path = path;
    }
  }

  const fail = (rule, path, detail) => {
    throw new NpqError(rule, path, detail);
  };
  const has = (o, k) => Object.hasOwn(o, k); // never `in`: "constructor" in {} is true
  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const isInt = (v) => Number.isInteger(v);
  const matches = (re, v) => typeof v === "string" && re.test(v);
  const entries = (v) => (isObj(v) ? Object.entries(v) : []);
  const hex = (s) => parseInt(s.slice(2), 16);
  const show = (v) => JSON.stringify(v) ?? String(v);

  // ---------------------------------------------------------------- V1: the bytes and the text

  // Spec 5.3: number spelling, duplicate names and depth are checked on the text, because JSON.parse reads 6.0 as 6
  // and drops the first of two duplicates. Runs on text JSON.parse accepted, so every string is closed.
  // open: one entry per open object (a Set of its names, compared after their escapes are decoded) or list (null).
  function scanText(text) {
    const open = [];
    let i = 0;
    while (i < text.length) {
      const c = text[i];
      if (c === '"') {
        let j = i + 1;
        while (text[j] !== '"') j += text[j] === "\\" ? 2 : 1;
        WS.lastIndex = j + 1;
        WS.exec(text);
        if (text[WS.lastIndex] === ":") {
          const names = open[open.length - 1];
          const n = JSON.parse(text.slice(i, j + 1));
          if (names.has(n)) fail("V1", "", `two items named ${show(n)} in one object`);
          names.add(n);
        }
        i = j + 1;
      } else if (c === "{" || c === "[") {
        open.push(c === "{" ? new Set() : null);
        if (open.length > MAX_DEPTH) fail("V1", "", `nested deeper than ${MAX_DEPTH}`);
        i++;
      } else if (c === "}" || c === "]") {
        open.pop();
        i++;
      } else if (c === "-" || (c >= "0" && c <= "9")) {
        NUMBER.lastIndex = i;
        const token = NUMBER.exec(text)[0];
        if (!INT_LITERAL.test(token)) fail("V1", "", `${token.slice(0, 20)} is not an integer of 16 digits or fewer`);
        i += token.length;
      } else i++;
    }
  }

  function parse(bytes) {
    if (!(bytes instanceof Uint8Array)) throw new TypeError("readNpq takes the file contents as a Uint8Array");
    if (bytes.length > MAX_BYTES) fail("V1", "", `more than ${MAX_BYTES} bytes`);
    if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) fail("V1", "", "starts with a BOM");
    let text, doc;
    try {
      // fatal: broken UTF-8 is an error, not U+FFFD; ignoreBOM: keep a BOM in the text (rejected above anyway)
      text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    } catch (e) {
      fail("V1", "", `not UTF-8 (${e.message})`);
    }
    try {
      doc = JSON.parse(text);
    } catch (e) {
      fail("V1", "", `not JSON (${e.message})`);
    }
    scanText(text);
    if (!isObj(doc)) fail("V1", "", "the top level must be an object");
    return doc;
  }

  // ---------------------------------------------------------------- V2, V3: the top level

  function v2(doc) {
    if (!has(doc, "format") || !FORMATS.includes(doc.format)) {
      fail("V2", "format", `must be one of ${show(FORMATS)}, got ${show(doc.format)}`);
    }
  }

  function v3(doc) {
    for (const k of ["board", "bitstream", "link", "design_id", "ips"]) if (!has(doc, k)) fail("V3", k, "missing");
    if (!matches(BOARD, doc.board)) fail("V3", "board", `bad board name ${show(doc.board)}`);
    const v2 = doc.format === FORMAT; // V2 passed: the format is /1 or /2
    const bitFields = v2 ? [["family", FAMILY]] : [];
    const usbFields = v2 ? [["usb_vid", USB_ID], ["usb_pid", USB_ID]] : [];
    const names = (extra) => extra.map(([f]) => f);
    for (const [k, fields] of [["bitstream", ["file", "sha256", ...names(bitFields)]], ["link", ["kind", "baudrate", ...names(usbFields)]]]) {
      if (!isObj(doc[k])) fail("V3", k, "must be an object");
      for (const f of Object.keys(doc[k])) if (!fields.includes(f)) fail("V3", `${k}.${f}`, "unknown field");
    }
    const bit = doc.bitstream;
    for (const [f, re] of [["file", FILE], ["sha256", SHA256], ...bitFields]) {
      if (!has(bit, f)) fail("V3", `bitstream.${f}`, "missing");
      if (!matches(re, bit[f])) fail("V3", `bitstream.${f}`, `bad value ${show(bit[f])}`);
    }
    if (bit.file.length > MAX_FILE) fail("V3", "bitstream.file", `more than ${MAX_FILE} characters`);
    const link = doc.link;
    if (!has(link, "kind")) fail("V3", "link.kind", "missing");
    if (link.kind !== "uart" && link.kind !== "jtag") fail("V3", "link.kind", `must be "uart" or "jtag", got ${show(link.kind)}`);
    if (link.kind === "uart") {
      const b = link.baudrate;
      if (!isInt(b) || b < 1 || b > MAX_SAFE) fail("V3", "link.baudrate", `uart needs an integer 1 .. 2^53 - 1, got ${show(b)}`);
    } else if (has(link, "baudrate")) fail("V3", "link.baudrate", "not allowed with jtag");
    for (const [f, re] of usbFields) {
      if (!has(link, f)) fail("V3", `link.${f}`, "missing");
      if (!matches(re, link[f])) fail("V3", `link.${f}`, `must be 0x and 4 lowercase hex digits, got ${show(link[f])}`);
    }
    if (!matches(DESIGN_ID, doc.design_id)) {
      fail("V3", "design_id", `must be 0x and 8 lowercase hex digits, got ${show(doc.design_id)}`);
    }
    if (RESERVED_IDS.includes(doc.design_id)) fail("V3", "design_id", `${doc.design_id} is reserved`);
    if (!isObj(doc.ips) || Object.keys(doc.ips).length === 0) fail("V3", "ips", "must be an object with at least one IP");
    for (const k of ["name", "doc"]) if (has(doc, k) && typeof doc[k] !== "string") fail("V3", k, "must be a string");
  }

  // ---------------------------------------------------------------- V4 to V10: ips

  function v4(v, path) {
    if (v === null) fail("V4", path, "null");
    if (typeof v === "number" && Math.abs(v) > MAX_SAFE) fail("V4", path, "integer outside -(2^53 - 1) .. 2^53 - 1");
    if (typeof v === "string" && (CONTROL.test(v) || !v.isWellFormed())) fail("V4", path, "control character or unpaired surrogate");
    if (Array.isArray(v)) v.forEach((x, i) => v4(x, `${path}.${i}`));
    else if (isObj(v)) for (const [k, x] of Object.entries(v)) v4(x, `${path}.${k}`);
  }

  function name(n, path) {
    if (n === "doc" || !NAME.test(n)) fail("V5", path, `bad name ${show(n)}`);
  }

  function v5(ips) {
    for (const [ipn, ip] of Object.entries(ips)) {
      name(ipn, `ips.${ipn}`);
      for (const sec of SECTIONS) {
        for (const [n, x] of entries(isObj(ip) ? ip[sec] : null)) {
          name(n, `ips.${ipn}.${sec}.${n}`);
          // doc is a stream field, not a name
          if (sec === "streams") for (const [f] of entries(x)) if (f !== "doc") name(f, `ips.${ipn}.streams.${n}.${f}`);
        }
      }
    }
  }

  function v6(ips) {
    for (const [ipn, ip] of Object.entries(ips)) {
      const p = `ips.${ipn}`;
      if (!isObj(ip)) fail("V6", p, "an IP must be an object");
      for (const k of Object.keys(ip)) if (!IP_FIELDS.includes(k)) fail("V6", `${p}.${k}`, "unknown field");
      for (const k of ["base", "type"]) if (!has(ip, k)) fail("V6", `${p}.${k}`, "missing");
      for (const sec of SECTIONS) if (has(ip, sec) && !isObj(ip[sec])) fail("V6", `${p}.${sec}`, "must be an object");
      for (const [rn, r] of entries(ip.registers)) {
        const rp = `${p}.registers.${rn}`;
        if (!isObj(r)) fail("V6", rp, "a register must be an object");
        for (const k of Object.keys(r)) if (!REG_FIELDS.includes(k)) fail("V6", `${rp}.${k}`, "unknown field");
        for (const k of ["offset", "width", "access"]) if (!has(r, k)) fail("V6", `${rp}.${k}`, "missing");
      }
    }
  }

  function hexOk(v, path) {
    if (!matches(HEX, v)) fail("V7", path, `must be a lowercase 0x hex string, got ${show(v)}`);
    const n = hex(v); // exact below 2^53; anything that large fails the next line
    if (n >= 2 ** 32) fail("V7", path, "2^32 or more");
    if (n % 4) fail("V7", path, "not a multiple of 4");
    return n;
  }

  function v7(ips) {
    for (const [ipn, ip] of Object.entries(ips)) {
      const p = `ips.${ipn}`;
      const base = hexOk(ip.base, `${p}.base`);
      const size = has(ip, "addr_range") ? hexOk(ip.addr_range, `${p}.addr_range`) : DEFAULT_ADDR_RANGE;
      if (size < 4) fail("V7", `${p}.addr_range`, "less than 4");
      if (base + size > 2 ** 32) fail("V7", `${p}.base`, "base + addr_range is more than 2^32");
      for (const [rn, r] of entries(ip.registers)) {
        if (hexOk(r.offset, `${p}.registers.${rn}.offset`) + 4 > size) {
          fail("V7", `${p}.registers.${rn}.offset`, "offset + 4 is more than addr_range");
        }
      }
    }
  }

  const scalar = (v) => isInt(v) || typeof v === "string" || typeof v === "boolean";

  function v8(ips) {
    for (const [ipn, ip] of Object.entries(ips)) {
      const p = `ips.${ipn}`;
      if (!matches(TYPE, ip.type)) fail("V8", `${p}.type`, `bad type ${show(ip.type)}`);
      if (has(ip, "doc") && typeof ip.doc !== "string") fail("V8", `${p}.doc`, "must be a string");
      for (const [n, v] of entries(ip.parameters)) {
        if (Array.isArray(v)) {
          v.forEach((x, i) => {
            if (!scalar(x)) fail("V8", `${p}.parameters.${n}.${i}`, "list items must be integers, strings or booleans");
          });
        } else if (!scalar(v)) fail("V8", `${p}.parameters.${n}`, "must be an integer, string, boolean or a list of them");
      }
      for (const [rn, r] of entries(ip.registers)) {
        const rp = `${p}.registers.${rn}`;
        if (!isInt(r.width) || r.width < 1 || r.width > 32) fail("V8", `${rp}.width`, `must be an integer 1 .. 32, got ${show(r.width)}`);
        if (!["ro", "rw", "wo"].includes(r.access)) fail("V8", `${rp}.access`, `must be ro, rw or wo, got ${show(r.access)}`);
        if (has(r, "read_effect") && typeof r.read_effect !== "boolean") fail("V8", `${rp}.read_effect`, "must be a boolean");
        if (has(r, "doc") && typeof r.doc !== "string") fail("V8", `${rp}.doc`, "must be a string");
      }
      for (const [sn, s] of entries(ip.streams)) {
        const sp = `${p}.streams.${sn}`;
        if (!isObj(s)) fail("V8", sp, "a stream must be an object");
        if (s.dir !== "read" && s.dir !== "write") fail("V8", `${sp}.dir`, "must be read or write");
        if (!isInt(s.mtu) || s.mtu < 1) fail("V8", `${sp}.mtu`, "must be an integer >= 1");
        for (const [f, v] of Object.entries(s)) {
          if (f === "doc" && typeof v !== "string") fail("V8", `${sp}.doc`, "must be a string");
          if (!scalar(v)) fail("V8", `${sp}.${f}`, "must be an integer, string or boolean");
        }
      }
    }
  }

  const span = (ip) => {
    const base = hex(ip.base);
    return [base, base + (has(ip, "addr_range") ? hex(ip.addr_range) : DEFAULT_ADDR_RANGE)];
  };

  function v9(ips) {
    const seen = [];
    for (const [ipn, ip] of Object.entries(ips)) {
      const [b, e] = span(ip);
      for (const [other, ob, oe] of seen) if (b < oe && ob < e) fail("V9", `ips.${ipn}.base`, `address range overlaps ips.${other}`);
      seen.push([ipn, b, e]);
    }
    for (const [ipn, ip] of Object.entries(ips)) {
      const offsets = new Set();
      for (const [rn, r] of entries(ip.registers)) {
        const off = hex(r.offset); // by value: "0x4" and "0x04" are the same offset
        if (offsets.has(off)) fail("V9", `ips.${ipn}.registers.${rn}.offset`, "same offset as another register");
        offsets.add(off);
      }
    }
  }

  function v10(ips) {
    if (!has(ips, "sys")) fail("V10", "ips.sys", "missing");
    const sys = ips.sys;
    if (hex(sys.base) !== 0) fail("V10", "ips.sys.base", "must be 0x0");
    const m = SYSINFO.exec(sys.type);
    if (!m) fail("V10", "ips.sys.type", "must be nanopynq:sysinfo:<version>");
    const regs = has(sys, "registers") ? sys.registers : {};
    const atLeast11 = Number(m[1]) > 1 || (Number(m[1]) === 1 && Number(m[2]) >= 1);
    for (const [rn, off] of [["id", 0x0], ["version", 0x4], ...(atLeast11 ? [["design_id", 0xc]] : [])]) {
      if (!has(regs, rn)) fail("V10", `ips.sys.registers.${rn}`, "missing");
      const r = regs[rn];
      if (hex(r.offset) !== off || r.width !== 32 || r.access !== "ro") {
        fail("V10", `ips.sys.registers.${rn}`, `must be offset 0x${off.toString(16)}, 32 bits, ro`);
      }
      // the host reads these to check the design
      if (r.read_effect === true) fail("V10", `ips.sys.registers.${rn}.read_effect`, "must not be true");
    }
  }

  // ---------------------------------------------------------------- design_id (spec 5.4)

  // Spec 5.4 steps 1-2 on ips that pass V4-V10.
  function normalIp(ip) {
    const registers = {};
    for (const [rn, r] of entries(ip.registers)) {
      registers[rn] = { access: r.access, offset: hex(r.offset), read_effect: has(r, "read_effect") ? r.read_effect : false, width: r.width };
    }
    const streams = {};
    for (const [sn, s] of entries(ip.streams)) streams[sn] = Object.fromEntries(Object.entries(s).filter(([f]) => f !== "doc"));
    return {
      addr_range: has(ip, "addr_range") ? hex(ip.addr_range) : DEFAULT_ADDR_RANGE,
      base: hex(ip.base),
      parameters: has(ip, "parameters") ? ip.parameters : {},
      registers,
      streams,
      type: ip.type,
    };
  }

  // Spec 5.4 step 3. Keys sort by UTF-16 code unit, the same as by code point, since names are ASCII (V5).
  function canonical(v) {
    if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
    if (isObj(v)) return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`;
    return JSON.stringify(v);
  }

  // The design_id (a number) of ips that passed readNpq.
  async function designId(ips) {
    const text = canonical(Object.fromEntries(Object.entries(ips).map(([n, ip]) => [n, normalIp(ip)])));
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return new DataView(digest).getUint32(0, false);
  }

  const hex8 = (n) => `0x${(n >>> 0).toString(16).padStart(8, "0")}`;

  // ---------------------------------------------------------------- reading

  // V1-V11 on the contents of a .npq (spec 5.7 steps 1-2); resolves to the JSON document as written.
  async function readNpq(bytes) {
    const doc = parse(bytes);
    v2(doc);
    v3(doc);
    v4(doc.ips, "ips");
    for (const rule of [v5, v6, v7, v8, v9, v10]) rule(doc.ips);
    const got = await designId(doc.ips);
    if (got !== hex(doc.design_id)) fail("V11", "design_id", `the file has ${doc.design_id}, its ips give ${hex8(got)}`);
    return doc;
  }

  return { FORMAT, MAX_BYTES, NpqError, readNpq, designId, hex8 };
})();

if (typeof module !== "undefined") module.exports = npq;

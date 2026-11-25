// What the panel page decides from a checked .npq, kept apart from the DOM and Web Serial so that Node can test it:
// the serial settings, the check of the board against the file (spec 5.7 steps 5-6, 5.8) and the widgets to build.
// A classic script that defines one global, `panel`, and is also a CommonJS module for Node.
"use strict";

const panel = (() => {
  const NPQ1 = 0x4e505131;
  // sysinfo registers at fixed addresses, as in nanopynq.overlay: a 1.0 file may describe design_id differently
  const SYS_ID = 0x0, SYS_VERSION = 0x4, SYS_DESIGN_ID = 0xc;

  const hex8 = (n) => `0x${(n >>> 0).toString(16).padStart(8, "0")}`;
  const atLeast11 = ([major, minor]) => major > 1 || (major === 1 && minor >= 1);

  // [major, minor] of the sysinfo the file declares (ips.sys.type; its form is checked by V10)
  const fileVersion = (doc) => doc.ips.sys.type.split(":")[2].split(".").map(Number);

  // Options for SerialPort.open(), or an Error for a design this page cannot reach.
  function serialOptions(doc) {
    if (doc.link.kind !== "uart") {
      throw new Error(`This page can use only designs reached over UART; this file has link.kind "${doc.link.kind}". Use it from Python.`);
    }
    return { baudRate: doc.link.baudrate };
  }

  // Reads sys.id, sys.version and (sysinfo 1.1 or later on the board) sys.design_id, and nothing else.
  // Resolves to what was read when the board runs the design of `doc`; throws an Error that says why not otherwise.
  // noAnswer: what to say when sys.id gets no answer (at connect time: the port or the design is wrong).
  async function checkBoard(doc, bone, noAnswer = "wrong port (try the other one), or no design is programmed") {
    let id;
    try {
      id = await bone.read(SYS_ID);
    } catch (e) {
      throw new Error(`${e.message}. No answer: ${noAnswer}.`);
    }
    if (id !== NPQ1) throw new Error(`sys.id is ${hex8(id)}, expected ${hex8(NPQ1)}: this is not a nanopynq design.`);
    const version = await bone.read(SYS_VERSION);
    const board = [version >>> 16, version & 0xffff];
    const file = fileVersion(doc);
    if (!atLeast11(board)) {
      // spec 5.8: without a design ID on the board the browser does not connect, whatever the file declares
      if (atLeast11(file)) {
        throw new Error(`The board runs sysinfo ${board.join(".")} (sys.version ${hex8(version)}), which has no design ID, ` +
          `but the file declares ${doc.ips.sys.type} with design_id ${doc.design_id}: another or an older design is on the board.`);
      }
      throw new Error(`The design on this board has no design ID (sysinfo ${board.join(".")}), so it cannot be checked ` +
        "against the file. Rebuild the design, or use it from Python.");
    }
    const designId = await bone.read(SYS_DESIGN_ID);
    if (hex8(designId) !== doc.design_id) {
      const seen = designId === 0 ? "0x00000000 (built without a design ID)" : hex8(designId);
      throw new Error(`The board runs another design: sys.design_id is ${seen}, the file has ${doc.design_id}.`);
    }
    return { id, version, designId };
  }

  const readable = (r) => r.access !== "wo";
  const writable = (r) => r.access !== "ro";
  // spec 5.3: wo registers and registers with read_effect are read only when the user asks
  const autoRead = (r) => readable(r) && r.read_effect !== true;
  const gpioWidth = (ip) => {
    const w = ip.parameters?.width; // parameters is open: width may be anything V1-V11 let through
    return Number.isInteger(w) && w >= 1 && w <= 32 ? w : null;
  };

  // The widgets for the ips of a checked .npq, in file order:
  //   {kind: "toggles", name, type, doc, addr, count, autoRead}  gpio_out: writes data, reads it once if allowed
  //   {kind: "lamps", name, type, doc, addr, count}               gpio_in: data is read periodically
  //   {kind: "table", name, type, doc, registers: [{name, addr, access, width, readEffect, doc, read, write, autoRead}]}
  // A gpio IP whose width or data register does not fit its widget gets a table, so an odd file cannot break the page.
  function plan(doc) {
    return Object.entries(doc.ips).map(([name, ip]) => {
      const base = parseInt(ip.base, 16);
      const regs = ip.registers ?? {};
      const data = Object.hasOwn(regs, "data") ? regs.data : null;
      const width = gpioWidth(ip);
      const common = { name, type: ip.type, doc: ip.doc ?? "" };
      const at = (r) => base + parseInt(r.offset, 16);
      // one widget per pin, but never past the bits the data register has
      const pins = width && data && Number.isInteger(data.width) ? Math.min(width, data.width) : null;
      if (/^nanopynq:gpio_out:/.test(ip.type) && pins && writable(data)) {
        return { kind: "toggles", ...common, addr: at(data), count: pins, autoRead: autoRead(data) };
      }
      if (/^nanopynq:gpio_in:/.test(ip.type) && pins && autoRead(data)) {
        return { kind: "lamps", ...common, addr: at(data), count: pins };
      }
      const registers = Object.entries(regs).map(([rn, r]) => ({
        name: rn, addr: at(r), access: r.access, width: r.width, readEffect: r.read_effect === true, doc: r.doc ?? "",
        read: readable(r), write: writable(r), autoRead: autoRead(r),
      }));
      return { kind: "table", ...common, registers };
    });
  }

  // A value typed for a register of `width` bits: decimal or 0x hex, in range. null when it is not one.
  function parseValue(text, width) {
    const s = text.trim();
    if (!/^(0x[0-9a-f]+|[0-9]+)$/i.test(s)) return null;
    const v = Number(s);
    return v < 2 ** width ? v : null;
  }

  return { hex8, serialOptions, checkBoard, plan, parseValue };
})();

if (typeof module !== "undefined") module.exports = panel;

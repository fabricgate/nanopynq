// The controls a checked .npq offers (toggles, lamps, register tables) and the parsing of a typed value, kept apart
// from the DOM so that Node can test it. It decides what to show and what may be read or written; drawing it is the
// page's job.
// A classic script that defines one global, `npqControls`, and is also a CommonJS module for Node.
"use strict";

const npqControls = (() => {
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

  return { plan, parseValue };
})();

if (typeof module !== "undefined") module.exports = npqControls;

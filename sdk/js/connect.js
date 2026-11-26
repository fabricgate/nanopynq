// Connecting to a board from a checked .npq, kept apart from the DOM and Web Serial so that Node can test it:
// the serial settings from the file and the check that the board runs the design (spec 5.7 steps 5-6, 5.8),
// as Overlay does in src/nanopynq/overlay.py. `bone` is a UARTBone (transport/uartbone.js) or anything with
// read(addr) -> Promise<number>.
// A classic script that defines one global, `npqConnect`, and is also a CommonJS module for Node.
"use strict";

const npqConnect = (() => {
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

  // The USB IDs of the board's debugger as numbers, for the filters of navigator.serial.requestPort (usbVendorId,
  // usbProductId) and navigator.usb.requestDevice (vendorId, productId). null for a nanopynq-design/1 file, which
  // has none: the page then asks without a filter, or uses its own.
  function usbIds(doc) {
    const { usb_vid: vid, usb_pid: pid } = doc.link;
    return vid === undefined ? null : { vid: parseInt(vid, 16), pid: parseInt(pid, 16) };
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

  return { serialOptions, usbIds, checkBoard };
})();

if (typeof module !== "undefined") module.exports = npqConnect;

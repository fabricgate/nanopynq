// Test only (tests/test_pyodide_page.py injects it before the page's scripts): a Web Serial port that answers the
// LiteX UARTBone protocol like the tangnano9k-base design. navigator.serial.requestPort() returns it.
// It has the real port's streams, and answers later and in two pieces, as USB does: a link that only works when the
// answer is already there when write() returns would pass against a port that answers at once, and fail on the board.
"use strict";
(() => {
  const MEMBERS = ["open", "close", "readable", "writable", "getInfo"];
  const mock = window.__mock = {
    // what the real Chrome has, before this script replaces anything
    real: { serial: "serial" in navigator, missing: typeof SerialPort === "function" ? MEMBERS.filter((k) => !(k in SerialPort.prototype)) : MEMBERS },
    regs: new Map([[0x0, 0x4e505131], [0x4, 0x00010001], [0xc, 0xabf78d8c], [0x1000, 0], [0x2000, 0b01]]), // byte address
    silent: false, // true: the board does not answer (not programmed, or the debugger stopped)
    delayMs: 1, // 0: answer in a microtask (timers nested this deep wait at least 4 ms, which would hide the overhead)
    writes: [], // [byte address, value] in order
    opens: [], // baud rate of each open()
  };
  const later = (f) => (mock.delayMs ? setTimeout(f, mock.delayMs) : queueMicrotask(f));
  const be32 = (v) => [v >>> 24, (v >>> 16) & 255, (v >>> 8) & 255, v & 255];

  class MockPort {
    readable = null;
    writable = null;

    async open({ baudRate }) {
      if (this.readable) throw new DOMException("The port is already open.", "InvalidStateError");
      mock.opens.push(baudRate);
      let rx, tail = Promise.resolve();
      const pending = [];
      const piece = (bytes) => new Promise((done) => later(() => {
        try { rx.enqueue(Uint8Array.from(bytes)); } catch {} // closed meanwhile
        done();
      }));
      // one answer after the other, each in two pieces
      const send = (bytes) => { tail = tail.then(() => piece(bytes.slice(0, 2))).then(() => piece(bytes.slice(2))); };
      this.readable = new ReadableStream({ start(c) { rx = c; } });
      this.writable = new WritableStream({
        write(chunk) {
          pending.push(...chunk);
          for (;;) { // whole frames only: cmd, length, word address (big endian), then the words of a write
            if (pending.length < 6) return;
            const [cmd, n] = pending;
            const addr = new DataView(Uint8Array.from(pending.slice(2, 6)).buffer).getUint32(0) * 4;
            const size = cmd === 0x01 ? 6 + 4 * n : 6;
            if (pending.length < size) return;
            const frame = pending.splice(0, size);
            const reply = [];
            for (let i = 0; i < n; i++) {
              if (cmd === 0x01) {
                const v = new DataView(Uint8Array.from(frame.slice(6 + 4 * i, 10 + 4 * i)).buffer).getUint32(0);
                mock.regs.set(addr + 4 * i, v);
                mock.writes.push([addr + 4 * i, v]);
              } else if (cmd === 0x02) {
                reply.push(...be32(mock.regs.get(addr + 4 * i) ?? 0));
              }
            }
            if (reply.length && !mock.silent) send(reply);
          }
        },
      });
    }

    async close() {
      if (!this.readable) throw new DOMException("The port is already closed.", "InvalidStateError");
      if (this.readable.locked || this.writable.locked) throw new DOMException("The port has a locked stream.", "InvalidStateError");
      this.readable = this.writable = null;
    }

    getInfo() { return { usbVendorId: 0x0403, usbProductId: 0x6010 }; }
  }

  const port = mock.port = new MockPort();
  if (!mock.real.serial) Object.defineProperty(navigator, "serial", { value: {} });
  navigator.serial.requestPort = async () => port;
})();

// A Web Serial port (navigator.serial) as transport/uartbone.js needs it: write(Uint8Array),
// readExactly(n, timeoutMs) -> Uint8Array and resetInput(). The browser end of src/nanopynq/transport/serialport.py.
// A classic script that defines one global, `SerialLink`, and is also a CommonJS module for Node.
"use strict";

// Web Serial has no read timeout or input flush, so a pump fills a buffer and readers wait on it.
class SerialLink {
  // onReadError(error): reading failed while open (unplugged, ...); the pump stops, so later reads time out.
  constructor(port, onReadError = () => {}) {
    this.port = port; this.buf = []; this.waiter = null; this.closed = false; this.onReadError = onReadError;
  }
  async open(options) {
    await this.port.open(options);
    this.writer = this.port.writable.getWriter();
    this.reader = this.port.readable.getReader();
    this.pump = this._pump();
  }
  async _pump() {
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) break;
        this.buf.push(...value);
        if (this.waiter) this.waiter();
      }
    } catch (e) {
      if (!this.closed) this.onReadError(e);
    }
  }
  resetInput() { this.buf.length = 0; }
  write(bytes) {
    if (this.closed) return Promise.reject(new Error("port closed"));
    return this.writer.write(bytes);
  }
  async readExactly(n, timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    while (this.buf.length < n) {
      if (this.closed) throw new Error("port closed");
      const left = deadline - performance.now();
      if (left <= 0) throw new Error(`timeout: expected ${n} bytes, got ${this.buf.length}`);
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, left);
        this.waiter = () => { clearTimeout(timer); resolve(); };
      });
      this.waiter = null;
    }
    return Uint8Array.from(this.buf.splice(0, n));
  }
  async close() {
    this.closed = true;
    if (this.waiter) this.waiter(); // a waiting read fails now, not at its timeout
    try { await this.reader.cancel(); } catch {}
    await this.pump;
    try { this.reader.releaseLock(); this.writer.releaseLock(); } catch {}
    try { await this.port.close(); } catch {}
  }
}

if (typeof module !== "undefined") module.exports = { SerialLink };

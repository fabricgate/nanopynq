// A Web Serial port (navigator.serial) as transport/uartbone.js needs it: write(Uint8Array),
// readExactly(n, timeoutMs) -> Uint8Array and resetInput(). readAtMost(n, timeoutMs) is pyserial's read, which
// nanopynq's Python needs in the browser (src/nanopynq/browser.py, examples/pyodide). The browser end of
// src/nanopynq/transport/serialport.py.
// A classic script that defines one global, `SerialLink`, and is also a CommonJS module for Node.
"use strict";

const QUIET_MS = 100, DRAIN_MAX_MS = 1000; // a Tang Nano 20K delivered 2632 kept bytes within 16 ms of open

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
    // What the board sent while the port was closed (the boot text of the design in the flash) is kept by the
    // debugger and arrives right after open; resetInput() cannot reach it. Drop input until QUIET_MS pass without
    // any, for at most DRAIN_MAX_MS (a design that never stops sending).
    for (let seen = -1, t = 0; seen !== this.buf.length && t < DRAIN_MAX_MS; t += QUIET_MS) {
      seen = this.buf.length;
      await new Promise((resolve) => setTimeout(resolve, QUIET_MS));
    }
    this.buf.length = 0;
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
    await this._fill(n, timeoutMs);
    if (this.buf.length < n) throw new Error(`timeout: expected ${n} bytes, got ${this.buf.length}`);
    return Uint8Array.from(this.buf.splice(0, n));
  }
  // pyserial's read(n): what came within the time, at most n bytes (fewer, or none, at the timeout).
  // A closed link throws "port closed", as pyserial raises on a closed port.
  async readAtMost(n, timeoutMs) {
    if (this.closed) throw new Error("port closed");
    await this._fill(n, timeoutMs);
    return Uint8Array.from(this.buf.splice(0, n));
  }
  // Waits until n bytes are in or the time is up; throws "port closed" when the link closes first.
  async _fill(n, timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    while (this.buf.length < n) {
      if (this.closed) throw new Error("port closed");
      const left = deadline - performance.now();
      if (left <= 0) return;
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, left);
        this.waiter = () => { clearTimeout(timer); resolve(); };
      });
      this.waiter = null;
    }
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

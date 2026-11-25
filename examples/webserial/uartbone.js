// LiteX UARTBone client for the browser, mirroring src/nanopynq/transport/uartbone.py.
// `port` needs write(Uint8Array), readExactly(n, timeoutMs) -> Uint8Array and resetInput().
"use strict";

const CMD_WRITE = 0x01;
const CMD_READ = 0x02;

function frame(cmd, addr, length) {
  if (addr % 4) throw new RangeError(`address 0x${addr.toString(16)} is not 4-byte aligned`);
  if (length < 1 || length > 255) throw new RangeError("length must be 1..255");
  const b = new Uint8Array(6);
  b[0] = cmd;
  b[1] = length;
  new DataView(b.buffer).setUint32(2, addr / 4);
  return b;
}

class UARTBone {
  constructor(port, timeoutMs = 1000) {
    this.port = port;
    this.timeoutMs = timeoutMs;
    this._queue = Promise.resolve(); // one transaction at a time: polling and clicks share the link
  }

  _serial(fn) {
    const run = this._queue.then(fn, fn);
    this._queue = run.catch(() => {});
    return run;
  }

  read(addr) {
    return this._serial(async () => {
      this.port.resetInput();
      await this.port.write(frame(CMD_READ, addr, 1));
      const buf = await this.port.readExactly(4, this.timeoutMs);
      return new DataView(buf.buffer, buf.byteOffset, 4).getUint32(0);
    });
  }

  write(addr, value) {
    return this._serial(async () => {
      const b = new Uint8Array(10);
      b.set(frame(CMD_WRITE, addr, 1));
      new DataView(b.buffer).setUint32(6, value >>> 0);
      this.port.resetInput();
      await this.port.write(b);
    });
  }
}

if (typeof module !== "undefined") module.exports = { UARTBone, frame };

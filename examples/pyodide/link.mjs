// The page's end of webserial_port.py: a byte pipe over the Web Serial port, with pyserial's read (at most n bytes,
// fewer when the timeout passes). Web Serial has no read timeout or input flush, so a pump fills a buffer.
export class Link {
  port = null; // set when the user chooses one
  buf = [];
  waiter = null;
  reader = null;

  async open(baudRate) {
    if (!this.port) throw new Error("no port chosen: press Choose port first");
    // A cell run again after a Stop opens a new Overlay while the old one still holds the port: take it over.
    // shortcut: the old Overlay's close() then closes the new one's port too; track owners if cells keep several.
    if (this.reader) await this.close();
    await this.port.open({ baudRate });
    this.writer = this.port.writable.getWriter();
    this.reader = this.port.readable.getReader();
    this.buf.length = 0;
    const reader = this.reader;
    this.pump = (async () => {
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          this.buf.push(...value);
          this.waiter?.();
        }
      } catch {} // the port went away; read() then times out
    })();
  }

  resetInput() { this.buf.length = 0; }

  write(data) { // data: a Uint8Array, or Python's bytes (a PyProxy, iterable)
    if (!this.reader) return Promise.reject(new Error("port closed"));
    return this.writer.write(Uint8Array.from(data));
  }

  async read(n, timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    while (this.buf.length < n && this.reader) {
      const left = deadline - performance.now();
      if (left <= 0) break;
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, left);
        this.waiter = () => { clearTimeout(timer); resolve(); };
      });
      this.waiter = null;
    }
    return Uint8Array.from(this.buf.splice(0, n));
  }

  async close() {
    const reader = this.reader;
    if (!reader) return;
    this.reader = null;
    this.waiter?.();
    await reader.cancel().catch(() => {});
    await this.pump;
    reader.releaseLock();
    this.writer.releaseLock();
    await this.port.close();
  }
}

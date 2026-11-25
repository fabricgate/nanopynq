// The page's end of page.py's WebSerialPort: SerialLink (sdk/js/transport/webserial.js, which the page loads as a
// classic script before this module) under the names page.py calls, plus what only this page needs: the port is
// chosen after the page loads, Python's bytes arrive as a PyProxy, and a second open takes the port over.
export class Link {
  port = null; // set when the user chooses one
  serial = null; // the SerialLink of the open port

  async open(baudRate) {
    if (!this.port) throw new Error("no port chosen: press Choose port first");
    // A cell run again after a Stop opens a new Overlay while the old one still holds the port: take it over.
    // shortcut: the old Overlay's close() then closes the new one's port too; track owners if cells keep several.
    await this.close();
    const serial = new SerialLink(this.port);
    await serial.open({ baudRate });
    this.serial = serial;
  }

  resetInput() { this.serial?.resetInput(); }

  write(data) { // data: a Uint8Array, or Python's bytes (a PyProxy, iterable)
    if (!this.serial) return Promise.reject(new Error("port closed"));
    return this.serial.write(Uint8Array.from(data));
  }

  read(n, timeoutMs) { // pyserial's read: at most n bytes, fewer (or none) when the timeout passes
    if (!this.serial) return Promise.reject(new Error("port closed"));
    return this.serial.readAtMost(n, timeoutMs);
  }

  async close() {
    const serial = this.serial;
    this.serial = null;
    await serial?.close();
  }
}

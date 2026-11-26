# nanopynq JavaScript

The JavaScript that reads `.npq` files and talks to a board, for front ends that do not run Python: the web pages in
`examples/`, and other programs that want the same checks (a registry's board page, a desktop app). It is not part of
the Python package.

| File | What it is | Mirrors |
|---|---|---|
| `npq.js` | Reads a `.npq`: the checks V1-V11 and the design_id (global `npq`) | `src/nanopynq/npq.py` |
| `connect.js` | The serial settings from a file, and the check that the board runs its design (global `npqConnect`) | the sysinfo check in `src/nanopynq/overlay.py` |
| `controls.js` | The controls a design offers (toggles, lamps, register tables) and parsing a typed value (global `npqControls`) | (UI only; no Python counterpart) |
| `transport/uartbone.js` | LiteX UARTBone client over any port with `write`, `readExactly` and `resetInput` (global `UARTBone`) | `src/nanopynq/transport/uartbone.py` |
| `transport/webserial.js` | A Web Serial port as `uartbone.js` needs it, and with pyserial's read (`readAtMost`) as nanopynq's Python needs it in the browser (global `SerialLink`; the Pyodide page in `examples/pyodide` uses it) | `src/nanopynq/transport/serialport.py` |
| `transport/jtag.js` | JTAG over the onboard debugger with WebUSB, the JTAG bridge and SRAM loading | `src/nanopynq/transport/mpsse.py`, `jtagbridge.py`, `src/nanopynq/gowin.py` |

Only `transport/webserial.js` (Web Serial) and `transport/jtag.js` (WebUSB) use a browser API. The rest runs
anywhere JavaScript does, so a desktop or Node front end replaces only those two.

## No board table

A front end needs no table of boards: a `nanopynq-design/2` file carries what the host side takes from
`boards.yaml` in Python.

- `link.kind` and `link.baudrate`: `npqConnect.serialOptions(doc)`.
- `link.usb_vid` and `link.usb_pid`: `npqConnect.usbIds(doc)` gives them as numbers for the device chooser's
  filter.
- `bitstream.family`: pass it to `GowinSram.load(fsText, onProgress, doc.bitstream.family)`. The loader then makes
  the checks the Python loader makes for that family, and refuses a family it has no sequence for
  (`GowinUnsupportedFamily`) or a GW1N that needs a power cycle (`GowinNotReady`) before it erases anything. Both
  are the error's `name`.
- The IDCODE is read from the `.fs` and compared with the board's.

A `nanopynq-design/1` file has no family and no USB IDs: `usbIds` returns `null`, and `load` without a family
skips the checks that depend on it. Which boards a page lets users write to, and how large a `.fs` it serves,
stay the page's own decisions.

## Module format

Each file is a classic script, so a page opened from `file://` can load it with `<script src>` (Chrome refuses ES
modules there). It defines the global named above and is also a CommonJS module:

```html
<script src="sdk/js/npq.js"></script>
<script src="sdk/js/connect.js"></script>
```

```js
const npq = require("./sdk/js/npq.js");
const npqConnect = require("./sdk/js/connect.js");
```

The files depend on each other only through the objects they are handed (a checked document, a port, a UARTBone),
not through imports, so they can be loaded in any order.

## Changing it

The `.npq` format (`docs/spec_design_metadata.md`) and the wire protocols have a Python side and a JavaScript side:
a change lands in both, in the same pull request. `tests/test_npq_js.py`, `tests/test_webserial_js.py` and
`tests/test_webusb_js.py` run this code (in Node 20 or later, and in headless Chrome where installed) against the
Python implementation and the shared test inputs.

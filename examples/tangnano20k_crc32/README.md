# CRC-32 calculator for the Tang Nano 20K

A CRC-32 checksum in hardware on a Sipeed Tang Nano 20K. You send bytes to the FPGA one at a time and
read back their CRC-32, the same checksum that zip files, PNG images and Ethernet frames use. Python
has it too, as `zlib.crc32`, so you can check the circuit's answer against the computer's.

Built with nanopynq (`examples/tangnano20k_crc32`). Nothing to install: in Chrome or Edge, on this
version's page, press **Open the panel**, then **Write to the board**, **Connect** and
**Open the notebook**.

The circuit is the same as the Tang Nano 9K sample's; only the wiring to the board's pins differs.

## What is on the board

| IP | Address | What it is |
| --- | --- | --- |
| `crc` | `0x7000` | the CRC-32 calculator |
| `leds` | `0x1000` | the six LEDs |
| `buttons` | `0x2000` | buttons S1 and S2 |
| `sys` | `0x0` | design information |

The registers of `crc` (byte offsets):

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| `0x0` | `init` | wo | write anything to start over |
| `0x4` | `data` | wo | the next byte (the low 8 bits of what you write) |
| `0x8` | `crc` | ro | the CRC-32 of the bytes since `init` |
| `0xc` | `length` | ro | how many bytes since `init` |

`init` and `data` are write-only: `register_map` leaves them out, and the panel does not read them.

## Try it

The first cell of the notebook shows `ol.crc.register_map`: `{'crc': 0, 'length': 0}` on a freshly
written board, and `zlib.crc32(b"")` is 0 as well.

The standard check value: the CRC-32 of `b"123456789"` is `0xcbf43926`.

```python
import zlib

def crc32_on_board(data):
    ol.crc.write(0x0, 0)        # init
    for b in data:
        ol.crc.write(0x4, b)    # data
    return ol.crc.read(0x8)

data = b"123456789"
hex(crc32_on_board(data)), hex(zlib.crc32(data)), ol.crc.read(0xc)
```

Random bytes, compared with `zlib`:

```python
import os
data = os.urandom(100)
crc32_on_board(data) == zlib.crc32(data)
```

Each byte is one write over the USB serial link, so this is a demonstration, not a fast checksum:
about a thousand bytes a second.

## License

MIT License

Copyright (c) 2026 FabricGate Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

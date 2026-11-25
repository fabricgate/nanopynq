# Button counter for the Tang Nano 9K

Counts how many times you press each of the two buttons on a Sipeed Tang Nano 9K. A mechanical button
does not switch cleanly: for a few milliseconds its contact bounces, and a naive counter would see one
press as several. The circuit waits until a button has stayed the same for 20 ms before it believes it,
so each press counts once.

Built with nanopynq (`examples/tangnano9k_button_counter`). Nothing to install: in Chrome or Edge, on
this version's page, press **Open the panel**, then **Write to the board**, **Connect** and
**Open the notebook**.

## What is on the board

| IP | Address | What it is |
| --- | --- | --- |
| `counter` | `0x7000` | the press counter |
| `buttons` | `0x2000` | buttons S1 and S2, as they are now (no filtering) |
| `leds` | `0x1000` | the six LEDs |
| `sys` | `0x0` | design information |

The registers of `counter` (byte offsets):

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| `0x0` | `count0` | ro | presses of S1 since the design was written to the board |
| `0x4` | `count1` | ro | presses of S2 |

The counts only go up (after 2^32 presses they start again from 0). There is nothing to write: to count
from now on, keep the value you start from and subtract it. A button held down while the design is
written counts once, 20 ms after the design starts.

## Try it

The first cell of the notebook shows `ol.counter.register_map`, `{'count0': 0, 'count1': 0}` on a freshly
written board. Press S1 a few times and run it again.

Count presses for ten seconds:

```python
import time
start = ol.counter.read(0x0)
time.sleep(10)
(ol.counter.read(0x0) - start) & 0xFFFFFFFF
```

Show the S1 count on the LEDs, in binary, as you press. Press **Stop** to end the loop:

```python
import time
start = ol.counter.read(0x0)
while True:
    n = (ol.counter.read(0x0) - start) & 0xFFFFFFFF
    ol.leds.write(0x0, n & 0x3F)
    time.sleep(0.05)
```

Compare with the raw button: `ol.buttons[0].read()` is 1 only while S1 is held down, so a loop that
reads it can miss a quick press; `count0` remembers every press that lasts 20 ms or more.

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

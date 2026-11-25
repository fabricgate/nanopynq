# LED chaser for the Tang Nano 9K

A light that runs along the six LEDs of a Sipeed Tang Nano 9K. You write the pattern and the speed
once; after that the circuit moves the LEDs by itself. Your code can finish, or even stop, and the
LEDs keep running, because the FPGA does the work, not the notebook.

Built with nanopynq (`examples/tangnano9k_chaser`). Nothing to install: in Chrome or Edge, on this
version's page, press **Open the panel**, then **Write to the board**, **Connect** and **Open the notebook**.

## What is on the board

| IP | Address | What it is |
| --- | --- | --- |
| `chaser` | `0x7000` | the chaser, on all six LEDs while it runs |
| `leds` | `0x1000` | the six LEDs while the chaser is stopped |
| `buttons` | `0x2000` | buttons S1 and S2 |
| `sys` | `0x0` | design information |

The registers of `chaser` (byte offsets):

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| `0x0` | `ctrl` | rw | bit 0: run. bit 1: run the other way. Writing 0 to bit 0 stops the chase and gives the LEDs back to `leds` |
| `0x4` | `pattern` | rw | the LEDs to light, bit 0 = LED 0. Writing it starts the chase over from this pattern |
| `0x8` | `rate` | rw | steps per second (0 to 65535). 0 holds the pattern still |
| `0xc` | `current` | ro | the chaser's pattern now. It is on the LEDs while the chaser runs; while stopped it stays where it stopped and the LEDs show `leds` |
| `0x10` | `steps` | ro | steps since bit 0 of `ctrl` was set |

Each step moves every lit LED one place (from LED 5 back to LED 0 at the end).

## Try it

The first cell of the notebook writes `ctrl=1, pattern=2, rate=3`: one LED runs along at three steps
a second. Run `ol.chaser.register_map` a few times: `current` and `steps` change between runs, with no
code running in between.

Two lights, three LEDs apart, faster, the other way:

```python
ol.chaser.write(0x4, 0b001001)   # pattern: LEDs 0 and 3
ol.chaser.write(0x8, 10)         # 10 steps a second
ol.chaser.write(0x0, 0b11)       # run, the other way
```

Check the speed: the circuit counts its own steps.

```python
import time
s = ol.chaser.read(0x10)
time.sleep(2)
(ol.chaser.read(0x10) - s) / 2   # about 10 steps a second
```

Speed it up and slow it down. Press **Stop** to end the loop; the LEDs keep running at the last speed:

```python
import time
while True:
    for r in list(range(1, 40)) + list(range(40, 1, -1)):
        ol.chaser.write(0x8, r)
        time.sleep(0.1)
```

Stop the chase with `ol.chaser.write(0x0, 0)`. The LEDs then follow `leds`, for example
`ol.leds[0].on()`.

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

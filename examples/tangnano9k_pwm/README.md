# PWM LED for the Tang Nano 9K

A PWM timer that sets the brightness of LED 5 on a Sipeed Tang Nano 9K. You write two numbers, the
period and the high time, and the circuit keeps blinking the LED on its own, far too fast to see, so it
looks dimmer or brighter. It also counts the periods, so you can use it as a timer.

Built with nanopynq (`examples/tangnano9k_pwm`). Nothing to install: in Chrome or Edge, on this
version's page, press **Open the panel**, then **Write to the board**, **Connect** and **Open the notebook**.

## What is on the board

| IP | Address | What it is |
| --- | --- | --- |
| `pwm` | `0x7000` | the PWM timer, on LED 5 |
| `leds` | `0x1000` | LEDs 0-4 |
| `buttons` | `0x2000` | buttons S1 and S2 |
| `sys` | `0x0` | design information |

The registers of `pwm` (byte offsets):

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| `0x0` | `ctrl` | rw | bit 0: run. Writing 0 turns LED 5 off and clears `count` and `wraps` |
| `0x4` | `period` | rw | clocks per period (the clock is 27 MHz) |
| `0x8` | `duty` | rw | clocks per period that LED 5 is on (0: off, `period` or more: fully on) |
| `0xc` | `count` | ro | position in the current period, 0 to `period` - 1 |
| `0x10` | `wraps` | ro | periods completed since `ctrl` was set to 1 |

A new `period` or `duty` takes effect when the next period starts, so the LED never gets a short pulse.

## Try it

The first cell of the notebook writes `ctrl=1, period=2, duty=3`. `duty` is not less than `period`,
so LED 5 is fully on.

Dim LED 5 to 10 %, at 1 kHz:

```python
ol.pwm.write(0x4, 27000)   # period: 27 MHz / 27000 = 1 kHz
ol.pwm.write(0x8, 2700)    # duty: 10 % of the period
ol.pwm.write(0x0, 1)       # run
ol.pwm.register_map
```

Fade it in. Press **Stop** to end the loop early; the LED keeps the last brightness:

```python
import time
for d in range(0, 27001, 900):
    ol.pwm.write(0x8, d)
    time.sleep(0.05)
```

Use it as a timer: while `period` stays the same, the time between two reads of `wraps` is their
difference × `period` / 27,000,000 seconds. (`wraps` counts on when `period` changes; write `ctrl=0`
and then `ctrl=1` to start it from 0.)

```python
import time
w = ol.pwm.read(0x10)
time.sleep(1)
(ol.pwm.read(0x10) - w) * ol.pwm.read(0x4) / 27_000_000   # about 1.0
```

Turn it off with `ol.pwm.write(0x0, 0)`.

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

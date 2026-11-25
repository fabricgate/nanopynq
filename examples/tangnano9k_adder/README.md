# Adder for the Tang Nano 9K

The smallest IP of your own: an adder in the FPGA of a Sipeed Tang Nano 9K. You write two 32-bit
numbers and read their sum, worked out by the circuit, plus a carry bit when the sum does not fit in
32 bits.

Built with nanopynq (`examples/tangnano9k_adder`). Nothing to install: in Chrome or Edge, on this
version's page, press **Open the panel**, then **Write to the board**, **Connect** and
**Open the notebook**.

## What is on the board

| IP | Address | What it is |
| --- | --- | --- |
| `adder` | `0x7000` | the adder |
| `leds` | `0x1000` | the six LEDs |
| `buttons` | `0x2000` | buttons S1 and S2 |
| `sys` | `0x0` | design information |

The registers of `adder` (byte offsets):

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| `0x0` | `a` | rw | the first number |
| `0x4` | `b` | rw | the second number |
| `0x8` | `sum` | ro | `a + b`, the low 32 bits |
| `0xc` | `carry` | ro | 1 when `a + b` does not fit in 32 bits |

## Try it

The first cell of the notebook writes `a=1, b=2` and shows `ol.adder.register_map`:
`{'a': 1, 'b': 2, 'sum': 3, 'carry': 0}`.

Add two numbers:

```python
ol.adder.write(0x0, 3)    # a
ol.adder.write(0x4, 4)    # b
ol.adder.read(0x8)        # sum: 7
```

Overflow:

```python
ol.adder.write(0x0, 0xFFFFFFFF)
ol.adder.write(0x4, 2)
ol.adder.register_map     # sum 1, carry 1
```

Check it against Python on random numbers:

```python
import random
for _ in range(100):
    a, b = random.getrandbits(32), random.getrandbits(32)
    ol.adder.write(0x0, a)
    ol.adder.write(0x4, b)
    assert (ol.adder.read(0xc) << 32) | ol.adder.read(0x8) == a + b
"all 100 match"
```

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

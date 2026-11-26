# nanopynq

PYNQ-style Jupyter control of cheap Gowin FPGA boards over USB, using only open tools.
First target: Sipeed Tang Nano 9K (talks over the onboard USB-UART). The Tang Nano 4K has no
USB-UART wired to the FPGA; its base design talks over the same JTAG link that programs it
(Gowin GW_JTAG through the onboard debugger), so it also needs only the one USB cable.
The Tang Nano 20K base design talks over GW_JTAG the same way. The Tang Mega 138K Pro base design talks
over its onboard USB-UART, like the 9K.

```python
from nanopynq import Overlay
ol = Overlay("base", board="tangnano9k")
ol.leds[0].on()
ol.buttons[0].read()
```

## Getting Started

Requirements: Python 3.11 or newer. nanopynq loads the design into the FPGA's SRAM itself, over the
JTAG interface of the board's onboard USB debugger; openFPGALoader is optional (see
[Using openFPGALoader](#using-openfpgaloader)).

### Linux

```sh
python -m venv .venv && . .venv/bin/activate
pip install nanopynq
# USB permissions (JTAG and UART): install the udev rule shipped with nanopynq, then re-plug the board.
# (`python -m nanopynq doctor` prints this command with the rule's path if the rule is missing.)
sudo cp "$(python -c 'import nanopynq, pathlib; print(pathlib.Path(nanopynq.__file__).parent / "data" / "99-nanopynq.rules")')" /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger
# Serial port permissions: join the dialout group, then log in again.
sudo usermod -aG dialout $USER
python -m nanopynq doctor
```

### Windows

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install nanopynq
python -m nanopynq doctor
```

No driver change is needed when Windows' FTDI driver is on the board (it was on the PCs this was tried
on; a PC without it is untested): nanopynq then talks to the debugger's JTAG through FTDI's D2XX library
(`ftd2xx.dll`, installed with that driver; nanopynq does not ship it). This is checked on the Tang Nano 9K
and 20K; the 4K is not checked yet. After Zadig (the driver of only "Interface 0" replaced with WinUSB,
Interface 1, the UART, left alone) nanopynq opens the board with libusb instead; Zadig is needed for the
WebUSB page (`examples/webusb`) and for openFPGALoader.

D2XX is FTDI's software, and FTDI's licence for it covers products that use FTDI's own chips; the boards'
debuggers (BL702, BL616) are FT2232-compatible chips from another maker. If that matters to you, run Zadig
as above: nanopynq then opens the board with libusb and never through D2XX (it still loads `ftd2xx.dll`
to look for a board when libusb finds one it cannot open, for example while another program holds it).

### Check your setup

```sh
python -m nanopynq doctor [--board tangnano9k]
```

Each check prints `OK <name>` or `NG <name>: <next step>`, and the exit code is 1 if any
required check is `NG`. The checks are: Python version, the debugger's JTAG USB interface (every board
is programmed over it), the board's serial port (Tang Nano 9K, which talks over the UART), the udev
rule (Linux only) or a note on the drivers (Windows only), openFPGALoader (only for a board set up to use
it), and the optional build tools (`pip install nanopynq[build]`), whose `NG` does not change the exit
code.

### Using openFPGALoader

nanopynq does not need [openFPGALoader](https://github.com/trabucayre/openFPGALoader), but it is still
the tool for writing the flash, and you can load the SRAM with it instead of nanopynq's own sequence
(for example if that fails on your board):

```python
from nanopynq import Overlay
from nanopynq.program import program_sram_openfpgaloader

ol = Overlay("base", board="tangnano9k", programmer=program_sram_openfpgaloader)
```

openFPGALoader is taken from `PATH`, or from the environment variable `NANOPYNQ_OPENFPGALOADER`.
Install it with `sudo apt install openfpgaloader` (Linux) or, in an MSYS2 UCRT64 shell,
`pacman -S mingw-w64-ucrt-x86_64-openFPGALoader` (Windows).

### Blink an LED

Open `examples/01_blink.ipynb` in Jupyter and run it from the top. It runs the four lines
above, then blinks an LED.

If `Overlay(...)` raises `BoardNotResponding`, unplug and re-plug the USB cable, then run
`Overlay("base", board="tangnano9k")` again: it programs the board first and then opens the port.
(Re-plugging cuts power and erases the design from SRAM, so `download=False` would not help here.
Use `download=False` only to reopen the port within the same power cycle.)

`Overlay(...)` checks that the board runs the design it opens: it reads the design ID (`sys.design_id`) and
compares it with the design's `base.npq` before touching any other register. If another design is on the board
it raises `DesignMismatch`; with `download=False`, run `Overlay(...)` again with the default `download=True` to
program this one. Designs that have only a `manifest.yaml` (not rebuilt yet) cannot be checked, so
`download=False` warns and goes on.

If `Overlay(...)` raises `PortOpenError`, on Windows call `ol.close()` on the previous `ol` (or restart
the kernel); on Linux join the `dialout` group (see above). `with Overlay(...) as ol:` closes the port
for you.

### Tang Nano 4K

```python
ol = Overlay("base", board="tangnano4k")   # programs over JTAG, then talks over JTAG
ol.leds[0].on()                             # the 4K has one LED (pin 10)
```

`examples/02_led_tangnano4k.ipynb` walks through on / off / toggle, blinking, following a button and
the raw register, then closes the link.

### Tang Nano 4K camera

```python
from nanopynq import Overlay
from nanopynq.camera import Camera
ol = Overlay("camera", board="tangnano4k")
cam = Camera(ol.cam_i2c, ol.cam_capture, ol.cam_dvp)
cam.start()
cam.snapshot()   # 160x120 grayscale, shown in the notebook
```

`examples/03_camera_tangnano4k.ipynb` walks through it. The camera overlay is built from general IPs
(I2C master, DVP front end, frame capture buffer) and the OV2640 driver ported from Espressif's
esp32-camera (Apache-2.0 and MIT parts, see `THIRD_PARTY_NOTICES.md`). Still pictures, about 0.6 s each.

### Tang Nano 4K camera stream

```python
ol = Overlay("camstream", board="tangnano4k")
cam = Camera(ol.cam_i2c, None, ol.cam_dvp, ring=ol.cam_ring)
cam.start()
for frame in cam.stream(20):   # about 2 frames/s over JTAG
    ...
frames = cam.record(50)        # 50 frames at the sensor's rate (about 8.7/s), then read
```

The camstream overlay keeps frames in the 8 MB PSRAM (HyperRAM) inside the FPGA package: a ring of
256 slots of 32 KB that takes every frame at the sensor's rate and drops new ones when it is full
(`ol.cam_ring.dropped`). `examples/04_camera_stream_tangnano4k.ipynb` walks through it.

Programming and talking use the debugger's one JTAG interface (on Windows through FTDI's driver or, after
Zadig, WinUSB; see above). Close a previous `ol` (`ol.close()`) before running `Overlay(...)` again, or
the board's JTAG interface is still in use and cannot be opened. If the onboard debugger stops answering, unplug and re-plug
the USB cable and run `Overlay(...)` again.

### Tang Nano 20K

```python
ol = Overlay("base", board="tangnano20k")  # programs over JTAG, then talks over JTAG
ol.leds[0].on()                            # 6 LEDs (pins 15-20)
ol.buttons[0].read()                       # S1 (pin 88); buttons[1] is S2 (pin 87). 1 while pressed
```

The drivers are as for the 4K (no change needed on Windows; Zadig optional). The 20K's debugger (BL616)
is a USB high-speed device; nanopynq reads its packet size from the device, so nothing else changes.

Designs built with `nanopynq build` (such as `examples/tangnano20k_chaser`) talk over the debugger's UART
instead (FPGA pins 69 / 70, its second serial port). `Overlay` takes the link from the design's `.npq`, so the
call is the same: `Overlay("examples/tangnano20k_chaser/dist")`.

### Tang Nano 20K SDRAM

```python
with Overlay("sdram", board="tangnano20k") as ol:      # programs the SRAM only, never the flash
    ol.sdram.write(0, [1, 2, 3])                      # 8 MB window, byte offsets, 32-bit words
    ol.sdram.read(0, 3)                               # -> [1, 2, 3]
    ol.sdram_test.run(passes=1)                       # whole-SDRAM self-test: SdramTestResult(passes, errors, first_error)
```

The onboard 8 MB SDRAM is a plain memory window on the bus. `ol.sdram_test.run()` writes a pattern, reads it
back and compares, inside the FPGA (about 0.7 s for all 8 MB), (`run()` blocks; the
self-test registers can also be started directly, as `hw_check.py` step 5 does, and the host may then
use `ol.sdram` outside the tested range while it runs). Host transfers over JTAG run at about 16 000 words/s for lists (single-word calls are much
slower). The check on real hardware is `tools/p0/sdram20k/hw_check.py`; results are in `reports/report_sdram20k.md`.

### Tang Mega 138K Pro

```python
ol = Overlay("base", board="tangmega138kpro")  # programs over JTAG, then talks over the UART
ol.leds[0].on()                                # 6 LEDs on the Dock
ol.buttons[0].read()                           # S1 on the Dock; buttons[1] is S2. 1 while pressed
```

For the Tang Mega 138K Pro only (the SOM on the Pro Dock): the non-Pro Tang Mega 138K and the Tang Console
138K have the same FPGA, so nanopynq cannot tell them apart, but their pins differ. Power the Dock from its
12 V DC jack (USB does not power it), and switch it off before plugging or unplugging anything.

The drivers are as for the 9K (no change needed on Windows; Zadig optional). A load takes about 3-4 s. This
board's debugger (BL616) clocks data sent LSB first at only about 0.5 MHz, so nanopynq sends it MSB first
(`msb_first` in `boards.yaml`; `reports/report_tangmega138kpro.md`).

### Tang Mega 138K Pro DDR3

```python
ol = Overlay("ddr3", board="tangmega138kpro")  # about 17 s: the 35 MB bitstream does not compress
ol.ddr3.write(0, [1, 2, 3])                    # 1 GiB window, byte offsets, 32-bit words
ol.ddr3_test.run()                             # whole-DDR3 self-test: SdramTestResult(...)
ol.ddr3_test.speeds                            # (write, read) MB/s of that run
```

The onboard DDR3 (1 GiB, 32-bit) runs from the 50 MHz board clock, CK 50 MHz in DLL-off mode, with
e-karge's controller and 2to1 PHY ([e-karge/gowin-ddr3](https://github.com/e-karge/gowin-ddr3), vendored in
`src/nanopynq/rtl/ddr3/`; nanopynq adds a write of a whole 8-word burst to the controller). The self-test moves
one 8-word (32-byte) burst per access: about 69 MB/s writing and 57 MB/s reading inside the FPGA, so the
self-test of the whole 1 GiB takes about 35 s. `ol.ddr3_test.calib` shows the calibration; after `calib_fail`,
power-cycle the Dock and load again. The host window moves one word per access over the 115200 baud UART, so it
is for checks, not for bulk data. A circuit of your own reaches the DDR3 as master b of `ddr3_arb` in place of
`ddr3_test`: each access writes or reads the 8 words of an aligned burst (`b_wdata` / `b_rd_data` 256 bits, word 0
in the low bits); to write fewer words, enable only their bytes in `b_wmask` (4 bits per word). See
`gateware/boards/tangmega138kpro/ddr3_top.v` and the comment in `src/nanopynq/rtl/ddr3_arb.v`.

The design needs forks of Apicula and nextpnr (registers in the IO blocks, e-karge's `HAS_5A_IDES` for the IDDR
that read DQ, and his GW5A IODELAY with a dynamic delay for the read calibration; `tools/build_base.py` takes them
from `DDR3_OVL`, `DDR3_CHIPDB` and `DDR3_NEXTPNR`). Without `HAS_5A_IDES` (as in Apicula master) every IDDR reads 0
and the calibration fails; nextpnr main stops at the dynamic delay. `build.json` records the fork commits; results are in
`reports/report_ddr3_138k_survey.md`.

### In the browser (Web Serial)

`examples/webserial/index.html` drives a board from a web page, without Python. Open the file directly
(`file://` works, no web server needed) in a Chromium-based browser (Chrome, Edge): other browsers have no
Web Serial. The page does not program the board, so program the design first (for example with
`Overlay("base", board="tangnano9k")`, then `ol.close()`), and the page can use only designs that talk over
UART (the Tang Nano 9K base).

1. Under "Design file", choose the `.npq` of the design on the board. For the 9K base it is
   `src/nanopynq/data/designs/tangnano9k-base/base.npq` in this repository. The page checks the file and
   shows the rule and the place if it is broken.
2. Press Connect and choose the board's port (the debugger shows two; if there is no answer, try the
   other one). The page reads the design ID from the board and stops, with the reason, if the board runs
   another design or a design without an ID.
3. LEDs, buttons and registers are built from the `.npq`.

## Building your own gateware

`pip install nanopynq[build]` installs the YoWASP Yosys and nextpnr-himbaechel-gowin toolchains. With them,
`nanopynq build` turns a design folder into a bitstream and its metadata file, with open-source tools only.
For now it builds for the boards that talk over UART: the Tang Nano 9K, the Tang Mega 138K Pro, and the Tang Nano
20K over its debugger's UART (FPGA pins 69 / 70; the 20K's bundled designs talk over JTAG instead). The 4K talks only
over JTAG, which needs tools pip does not install.

A design folder holds your Verilog, a constraint file and `nanopynq.toml`.
`examples/tangnano9k_pwm` in this repository is one: the base design plus a PWM timer on LED 5.
`examples/tangnano9k_adder` is one with an IP of your own: an adder (`adder.v`) whose registers are written whole in `nanopynq.toml`.
`examples/tangnano9k_chaser` is another: a chaser (`chaser.v`) that keeps running a light along the LEDs once started.
`examples/tangnano9k_button_counter` counts presses of the two buttons (`button_counter.v`, with the contact bounce filtered out).
`examples/tangnano9k_crc32` computes the CRC-32 of bytes written to it (`crc32.v`), the same value as Python's `zlib.crc32`.
`examples/tangnano20k_pwm`, `_chaser`, `_button_counter` and `_crc32` are the same four on the Tang Nano 20K: their own `top.v` and pins, the same RTL (the 9K examples' files, or the shared `pwm_timer.v`).

```toml
name = "pwm"                 # the output files: dist/pwm.fs, dist/pwm.npq
board = "tangnano9k"
top = "top"                  # optional (default "top"); the top takes a DESIGN_ID parameter
seed = 1                     # optional (default 1): the place-and-route seed
# Read in this order. The set of files and their order change the bitstream, so list only what you use.
# nanopynq:<file> is nanopynq's shared RTL (the UART bridge, sysinfo, GPIO, pwm_timer, ...).
sources = [
    "nanopynq:base_regs.v", "nanopynq:pwm_timer.v", "nanopynq:regbus_gpio.v", "nanopynq:sysinfo.v",
    "nanopynq:uart_rx.v", "nanopynq:uart_tx.v", "nanopynq:uartbone_bridge.v",
    "top.v",
]
constraints = "tangnano9k.cst"

# The IPs (spec 5.3) are collected from the Verilog; here only what it does not hold (see below).
[ips.pwm]
parameters = { clock_hz = 27000000 }
```

```
$ nanopynq build examples/tangnano9k_pwm      # or: cd examples/tangnano9k_pwm && nanopynq build
examples/tangnano9k_pwm/dist
  pwm.fs, pwm.npq, build.json
```

The `ips` (the IPs as the host sees them, the same fields as in a `.npq`) are collected from your Verilog.
The build elaborates the design with yosys and makes an IP of every instance of a module nanopynq describes
(`src/nanopynq/ipdesc/`: `sysinfo`, `regbus_gpio` as `gpio_out` or `gpio_in`, `pwm_timer`). Its base is the
`BASE` parameter the module decodes its addresses with, so it cannot drift from the circuit, and its registers
come from the description. The IP's name is the instance attribute `(* npq_name = "pwm" *)`, else the instance
name; `base_regs` names its instances `sys`, `leds` and `buttons`. The attributes do not change the bitstream.
`[ips.<name>]` in `nanopynq.toml` adds to the collected IP of that name: `parameters` the Verilog does not
hold (`pwm_timer`'s `clock_hz`; the build stops if one is missing), and `instance = "timer"` to give that
instance this name without touching the Verilog. An entry with a `base` is an IP written whole, as in a
`.npq` (`registers`, `addr_range`, ...): it takes the place of the collected IP of the same name and of every collected
IP in its address range, so a `nanopynq.toml` with every IP written by hand builds as before. Instances whose
names repeat (a `generate` loop) need `instance =` or entries written by hand, and a module of your own that only
shares its name with one nanopynq describes is left out unless `nanopynq.toml` names it (the build says so). Write your own IPs this way (descriptions of
your own modules are not read yet). The build prints the IPs and where each came from, and writes them to
`build/ips.json`; copy them into `nanopynq.toml` to pin them.

The build checks the `ips` (a broken one stops with the rule and the place, e.g. `V9 at ips.pwm.base`),
computes the design ID from them, builds it into the bitstream (the top's `DESIGN_ID`, handed down to
`sysinfo`), and writes `dist/`: the bitstream, the metadata file (`.npq`, JSON) and `build.json` (the
sources with their sha256, the tool versions, the seed and the clock timing was checked at). With the
same sources and the tool versions recorded in `build.json`, the `.fs` and `.npq` come out the same byte
for byte.
Intermediate files and the log of a failed tool go to `build/`. The link (UART, 115200 baud) comes from the
board. Unknown keys in `nanopynq.toml` are errors.

Place and route checks timing at the board's clock (27 MHz on the 9K and 20K, 50 MHz on the 138K Pro;
nextpnr's `--freq`). A design too slow for it stops the build with nextpnr's
`ERROR: Max frequency for clock '...': ... MHz (FAIL at 27.00 MHz)`. Every clock is checked at that
frequency, a faster one your design makes with a PLL too: `nanopynq build` takes no timing constraints
yet, so such a clock is not checked at its own frequency.

Before synthesis, the build checks the `ips` against your Verilog, with yosys only. It runs on up to 8 cores;
for the example it takes about 5 s on 8 cores, 8 s on 4, 14 s on 2 and 26 s on one, and it grows with the
number of registers and the size of the design.
It puts a test bus master in place of the UART bridge and checks, over the first clocks after configuration:

- every register in `ips` has a slave that can answer at its address: there is some value of the inputs for
  which a read does not return `0xdeadbeef` (error if there is none). This is not a proof for all inputs: a
  register that answers only while, say, a button is held passes,
- no address outside the registers answers, before or after a write to it, inside an IP's range or outside
  all of them. This one is proved for all inputs (error; only a warning inside an IP with `streams`, whose
  data window answers between the registers; an IP with a window but no `streams` gets errors),
- an `rw` register reads back what was written, masked to its width; an `ro` one does not, and reads 0
  above its width (warnings: an `rw` register may read something else, like an SPI data register).

Errors stop the build before synthesis; fix the `ips` or the RTL. They name every register without a slave,
but only one answering address per IP range (and one outside all ranges), so build again after a fix. A
failed build leaves none of its files (`<name>.fs`, `<name>.npq`, `build.json`) in `dist/`, so an older design
cannot be loaded by mistake. Warnings are shown and the build goes on. `build.json` records whether the check
ran and its number of warnings. The check's files (`design.il`, one log per proof) are in `build/crosscheck/`.

The check needs a top that:

1. holds exactly one instance of nanopynq's `uartbone_bridge` (directly or through `base_soc`, not a renamed
   copy), with the slaves on its bus,
2. reads `0xdeadbeef` at unmapped addresses (`base_regs` does),
3. ends its reset within about `depth` - 10 clocks of configuration; an input pin that feeds the reset must
   be pinned with `[check] inputs`,
4. uses no names starting with `npqchk`.

A top that breaks 1 or 3 stops with "cannot check"; one that breaks 2 stops with errors about addresses
that answer. A register that reads `0xdeadbeef` right after reset is reported as missing. It does not see: an `ro` register written wider than it
is (or narrower, when its high bits stay 0 for the first clocks, like a counter), `wo` registers beyond their
address, two slaves answering the same address, and what the values mean. A slave that answers only after
an earlier write is reported as missing. `nanopynq build --no-crosscheck` builds without the check and
says so; the `.npq` does not record it. The optional `[check]` table sets it up:

```toml
[check]
inputs = { btn = 0 }   # top inputs held at a value during the check (default: none; others are free)
depth = 32             # clocks after configuration the check covers (default 32)
```

`dist/` is a design folder for `Overlay`:

```python
from nanopynq import Overlay

ol = Overlay("examples/tangnano9k_pwm/dist")   # programs pwm.fs, checks the design ID
ol.pwm.write(0x4, 27_000_000)                  # period: 1 s at 27 MHz
ol.pwm.write(0x8, 13_500_000)                  # duty: half of it
ol.pwm.write(0x0, 1)                           # enable: LED 5 blinks once a second
```

The bundled designs are built with `tools/build_base.py`, which writes `base.fs`, `base.npq` and
`build.json` (also the commit) into `src/nanopynq/data/designs/<board>-<design>`.
The Tang Nano 9K and Tang Mega 138K Pro base designs are built with the pip tools.
The Tang Nano 4K base design cannot be rebuilt with the pip tools yet. GW_JTAG on the GW1NS-4
is in Apicula master (YosysHQ/apicula#578) but not in a released Apicula / nextpnr.
`tools/build_base.py --board tangnano4k` rebuilds it with Apicula master and a nextpnr chipdb
regenerated from it (see `tools/p0/gwjtag4k/README.md`).
The Tang Nano 20K base design also uses GW_JTAG, which released Apicula has for the GW2A-18C:
`tools/build_base.py --board tangnano20k` rebuilds it with the oss-cad-suite tools (see the script's docstring).

## Designs from FabricGate

[FabricGate](https://github.com/fabricgate/fabricgate) distributes designs and checks their digests; nanopynq
reads the `.npq` and checks the design ID as for any other design. A registered design is used in one of two ways.

Pull it with the `fabricgate` CLI and pass the folder:

```sh
fabricgate pull <namespace>/<design>:<version> --platform tangnano9k/nanopynq --output pwm
```

```python
ol = Overlay("pwm")   # the folder holds FabricGate's manifest.yaml next to the .fs and .npq; only the .npq is read
```

Or let `Overlay` pull it, with `pip install "nanopynq[fabricgate]"` (without it, this raises `ImportError`
saying so):

```python
ol = Overlay("fabricgate://<namespace>/<design>:<version>", board="tangnano9k")
```

- `board` is required: it picks the platform (`tangnano9k/nanopynq`).
- The registry is the one the `fabricgate` CLI uses: `FG_REGISTRY`, else `registry` in
  `~/.fabricgate/config.yaml`, else the production registry.
- The first call pulls the design into
  `~/.cache/nanopynq/fabricgate/<registry>/<namespace>/<design>/<version>/<board>` (under
  `$XDG_CACHE_HOME` if set), where `<registry>` is the registry URL as a folder name, e.g.
  `registry.fabricgate.dev_api_v1`. Later calls use that folder without asking the registry; delete it to pull
  again.
- If the registry says the version is yanked or deprecated, the call warns (`UserWarning`) with its reason, also
  when the folder is reused. A version yanked after its first pull is not noticed until the folder is deleted.
- The extra installs FabricGate 0.7 or later, the first release that reads nanopynq designs carrying a `.npq`.

To publish your own design, see `docs/publish_fabricgate.md`.

## License

nanopynq is released under the MIT License (`LICENSE`). The example designs under `examples/` carry their own
MIT `LICENSE`. Files taken from other projects keep their licenses: see `THIRD_PARTY_NOTICES.md` and `licenses/`.

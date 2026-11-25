# GW_JTAG on Tang Nano 4K (GW1NSR-4C) — P0 spike files

See `reports/report_jtag_bridge_spike.md` sections 9-13. Evaluation material; not part of the package.

The bundled Tang Nano 4K base design (`src/nanopynq/data/designs/tangnano4k-base`) uses GW_JTAG. Build it with
`tools/build_base.py --board tangnano4k`, setting `OSS` (oss-cad-suite folder), `OVL` (the folder holding an
`apycula/` that has GW_JTAG for GW1NS-4) and `CHIPDB` (a chipdb .bin regenerated from that Apicula).

GW_JTAG for GW1NS-4 has been in Apicula master since YosysHQ/apicula#578 (merged 2026-11-05) but is not in a
release yet; PyPI still has 0.35. For `OVL`, unpack the `python-dist` wheel from a master run of Apicula's
"Chipdb builder" workflow (`gh run download <run id> -R YosysHQ/apicula -n python-dist`). Its `GW1NS-4.msgpack.xz`
has the HyperRAM pins (`sip_cst`) that camstream needs. Building that file locally with `chipdb_builder` on Windows
drops them, because its HyperRAM pin search runs the IDE's `gw_sh` the Linux way. The bundled designs were built
with the earlier local patch below (Apicula 0.35 + `patch_apicula_gw1ns4_jtag.py`).

- `allwires_top.vg`: hand-written netlist that routes every GW_JTAG output to a pin. Fed straight to
  Gowin PnR (`add_file -type netlist`), which skips GowinSynthesis and its RP0008 check.
- `userdr_top.v`: ER1 user DR as a 32-bit shift register (sampled on the falling edge of `tck_o`).
  Synthesize with yosys (`synth_gowin -top top; rename -enumerate; write_verilog -noattr -noexpr -defparam`),
  drop the first comment line, then run Gowin PnR on the netlist with `led` on pin 10.
- `userdr_scan.py`: loads IR 0x42 and does DR scans through the BL702 MPSSE subset (uses `../jtag_mpsse_min.py`).
  `NBITS=33` gives exact round trips (see report).
- `jtag_cfg_fuses.py`: compares tile (0,0) of an IDE bitstream with a reference and looks up the
  CFG `JTAG_ER1` / `JTAG_ER2` fuses in Apicula's GW1NS-4 chipdb (run with `uv run --with apycula==0.35`).

## Open toolchain only (report section 12)
- `patch_apicula_gw1ns4_jtag.py`: run next to a copy of Apicula 0.35 (`apycula/` beside it) to add the GW1NS-4
  `jtag` extra function at (0,0) to `GW1NS-4.msgpack.xz` and `get_GW_JTAG_fuses` to `gowin_pack.GW1NS_4`.
  Needs `msgspec` (`uv run --with msgspec --with apycula==0.35`). The local experiment that led to
  YosysHQ/apicula#578. Upstream takes the wires from the DAT tables instead of hard-coding them, with the same result.
- chipdb: `PYTHONPATH=<Apicula with GW_JTAG> python nextpnr/himbaechel/uarch/gowin/gowin_arch_gen.py -d GW1NS-4 -o x.bba`
  (nextpnr source at 6b438a1c, the commit of the oss-cad-suite 2026-10-22 nextpnr), then `bbasm -l x.bba x.bin`.
- `bbasm_noboost_main.cc`: nextpnr's `bba/main.cc` with the Boost option parser replaced by a plain argv loop,
  built in WSL with `g++ -std=c++17 -O2 -o bbasm bbasm_noboost_main.cc`.
- `userdr_open.v` + `led.cst` + `build_open.sh`: the user DR design. It oversamples the GW_JTAG outputs with the
  27 MHz board clock (report section 13); `userdr_stress.py` runs 299 random round trips.
- `userdr_open_tckclk.v`: the earlier variant clocked by `tck_o`; it passes on some placements and fails on others.
- `jtagdiag_top.v` + `jtagdiag_capture.py`: on-chip recorder of GW_JTAG output transitions (27 MHz), read back through ER2.
- `jtagphase_top.v` + `jtagphase_probe.py`: shows in which TCK phase the host samples TDO.
- `en2probe_top.v` + `en2probe.py`: checks that `enable_er2_o` (Q1 at (0,0)) is high only while IR 0x43 is selected
  (report section 14). Build like `userdr_open.v`.

## Tang Nano 9K and 20K (report `report_gwjtag_9k20k.md`)
`build_open.sh` takes `BOARD=4k|9k|20k` (default 4k) and an optional design file, e.g.
`BOARD=9k bash build_open.sh out9k en2probe_top.v`. `led9k.cst` / `led20k.cst` put `clk` and `led` on the
27 MHz clock and LED0 of each board (pins from Apicula's `examples/tangnano9k.cst` / `tangnano20k.cst`).
- 20K (GW2A-18C): GW_JTAG is in Apicula 0.35, so the oss-cad-suite 2026-10-22 chipdb and `gowin_pack` work as they are.
- 9K (GW1N-9C): needs Apicula branch `gw1n9c-gw_jtag` (fork harurun78/apicula), the GW1N-9C Apicula chipdb with
  the `jtag` entry at (0,0), and a nextpnr chipdb regenerated from it (same steps as the 4K above).
- 9K investigation: `allwires_9k.tcl` (IDE PnR of `allwires_top.vg`), `trace_unpacked.py` (OBUF inputs back to their
  source wires in a `gowin_unpack` netlist), `dat_jtag_wires.py` (JtagIns/JtagOuts of the vendor .dat),
  `jtag_cfg_fuses.py <ide.fs> <ref.fs> GW1N-9C`, and `add_jtag_chipdb.py` (adds the `jtag` entry to a wheel's chipdb).

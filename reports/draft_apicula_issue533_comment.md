# 下書き: YosysHQ/apicula issue #533 へのコメント（未送信、2026-11-03 更新）

> 2026-11-04: 送らない。先に PR を出す方針にしたので、`draft_apicula_pr_gw1ns4_jtag.md` に置き換えた。

送る先: https://github.com/YosysHQ/apicula/issues/533 （"Support for GW_JTAG on GW2A devices?"、OPEN）

送る前に確かめること:
- 文面はあなたの言葉として読み直し、必要なら直す。この下書きは Claude（AI）が作った。末尾の一文は、不要なら消す。
- 添付の候補: nanopynq リポジトリの `tools/p0/gwjtag4k/allwires_top.vg`、`userdr_top.v`、`userdr_scan.py`。Gowin が生成したファイルは添付しない（作業用フォルダにだけある）。

---

Hi, and thanks to both of you for the detailed write-up in this thread — I followed the same steps for the **GW1NS-4 (Tang Nano 4K)** and it seems to line up nicely with the GW2A-18C. Sharing in case it's useful, and to ask whether a PR would be welcome.

**Getting a GW_JTAG design through the Gowin tools**

With Gowin IDE V1.9.11.03 Education, instantiating `GW_JTAG` in user Verilog fails in GowinSynthesis on every device I tried, GW2AR-18C included:
```
ERROR (RP0008) : There is no GW_JTAG resource in current device, please change device
```
Two ways around it:
- A GAO-enabled design builds fine (GAO inserts `GW_JTAG u_gw_jtag` after synthesis).
- Handing PnR a hand-written netlist (`add_file -type netlist top.vg`, IBUF/OBUF + `GW_JTAG` only) skips synthesis entirely. The pad ports need IBUF/OBUF on top-level ports; PnR then puts them on the dedicated JTAG pins by itself.

**Cell and wires (GW1NS-4)**

Using an "all outputs to pins" netlist and `gowin_unpack -d GW1NS-4` (Apicula 0.35), everything lands in **R1C1 = (0, 0)**:

| port | GW1NS-4 | GW2A-18C (current) |
|---|---|---|
| tck_o | Q6 | Q6 |
| tdi_o | Q5 | Q5 |
| test_logic_reset_o | Q3 | Q3 |
| run_test_idle_er1_o | Q4 | Q4 |
| run_test_idle_er2_o | F0 | F7 |
| shift_dr_capture_dr_o | Q7 | F6 |
| update_dr_o | Q2 | Q2 |
| enable_er1_o | Q0 | Q0 |
| enable_er2_o | not resolved (trace stops at R1C1_E11; probably Q1) | Q1 |
| pause_dr_o | not from R1C1 (constant from R1C10_F5) | dummy |
| tdo_er1_i / tdo_er2_i | C1 / C2 | C1 / C2 |

**Fuses**

In the GW1NS-4 chipdb, tile (0, 0) is ttyp 50 with a `CFG` shortval table. `JTAG_ER1=USED` and `JTAG_ER2=USED` map to (3, 19) and (3, 20). Both are set in the IDE bitstream and clear in an Apicula blinky, so it looks like the same known CFG attributes as the GW2A-18C.

**Hardware check**

I synthesized a small user DR (32-bit shift register on ER1) with Yosys, ran it through Gowin PnR via the netlist route, and drove it from the host over the Tang Nano 4K's BL702:
- IR **0x42** selects ER1 and the initial register value reads back correctly; IR 0x43 reaches ER2.
- Sampling `tdi_o` on the rising edge of `tck_o` gave `V | (V << 1)`; sampling on the falling edge is clean, so `tck_o` looks inverted (DRCK-like).
- A write/read round trip needs 33-bit scans for a 32-bit register (one bit of latency). I haven't pinned down whether that comes from capture or from the last bit.
- Side note: the BL702 MPSSE emulation rejects the read-only clocking opcodes (0x28/0x2C/0x2A/0x2E) and write-on-rising-edge variants (0x38/0x3C); only 0x39/0x3B and 0x4B/0x6B work.

**Open toolchain check**

I then tried it without any Gowin tools in the loop:
- Patched a copy of Apicula 0.35: added the `jtag` extra function at (0, 0) to the existing `GW1NS-4.msgpack.xz` (wires as above, `enable_er2_o` guessed as Q1) and a `GW1NS_4.get_GW_JTAG_fuses` identical to the GW2A-18C one.
- Regenerated the GW1NS-4 chipdb with `gowin_arch_gen.py` from nextpnr 6b438a1c and `bbasm`, and passed it with `--chipdb` to the oss-cad-suite 2026-10-22 `nextpnr-himbaechel` (which already has the GW_JTAG packer).
- Yosys → nextpnr (`GW_JTAG: 1/1`) → patched `gowin_pack`: the bitstream sets the two CFG fuses, and on a Tang Nano 4K a 32-bit user DR on ER1 round-trips exactly through IR 0x42 at 100 kHz, 1 MHz and 3 MHz. IR 0x43 reaches ER2.
- Timing notes, from an on-chip recorder (27 MHz) of the primitive's outputs:
  - `tck_o` has the same polarity as TCK; `tdi_o` and `shift_dr_capture_dr_o` change on its rising edge; `shift_dr_capture_dr_o` is high from the edge that enters Shift-DR to the edge that leaves it (so the last TDI bit has to be taken one falling edge later).
  - Using `tck_o` directly as a clock for a shift register was placement-dependent: with nextpnr seeds 1-5, one seed failed 275 of 299 random round trips although nextpnr reported no timing violations. `tck_o` (Q6 at (0, 0)) seems to go out over general routing rather than a low-skew clock network.
  - Oversampling the outputs with the 27 MHz board clock and acting on the detected TCK falling edge passed 299/299 on all five seeds with no timing violations. (The Tang Nano 4K's BL702 runs TCK at about 2 MHz regardless of the MPSSE divisor.)
  - This may be worth a note for anyone using `GW_JTAG` from Apicula designs.

**Question**

Would you be happy to review a PR adding GW1NS-4 to `fse_create_jtag` (cell (0, 0), wires above) and a `get_GW_JTAG_fuses` for `GW1NS_4` like the GW2A-18C one? I can't regenerate the chipdb from the vendor files myself (I only have 1.9.11.03, not 1.9.10.03), so any guidance on that part — or on how you'd like `enable_er2_o` confirmed — would be appreciated.

Thanks!

_(This message was drafted with the help of an AI assistant and reviewed by me.)_

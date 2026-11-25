# YosysHQ/apicula への PR「GW1NS-4: add GW_JTAG」（2026-11-04 提出: https://github.com/YosysHQ/apicula/pull/578 、#533 にリンクをコメント済み）

- ブランチ: `<apicula を clone したフォルダ>` の `gw1ns4-gw_jtag`（上流 master 993faec の上に 1 コミット）
- 出し方: fork（harurun78/apicula）へ push → YosysHQ/apicula master へ PR → #533 に PR へのリンクを短くコメント
- 送る前に: 文面を自分の言葉として読み直す。この下書きは Claude（AI）が作った。末尾の AI 支援の一文は残すのを推奨。

---

## PR title

GW1NS-4: add GW_JTAG (Tang Nano 4K)

## PR body

Follow-up to #533 and #537: this adds the `GW_JTAG` primitive for the GW1NS-4 (GW1NSR-4C, Tang Nano 4K), in the same way as the GW2A-18C.

**Changes**
- `chipdb.py` `fse_create_jtag`: GW1NS-4 cell at (0, 0). The wires are the same as on the GW2A-18C except `run_test_idle_er2_o` = F0 and `shift_dr_capture_dr_o` = Q7.
- `gowin_pack.py` `GW1NS_4.get_GW_JTAG_fuses`: same as `GW2A_18C` (CFG `JTAG_ER1` / `JTAG_ER2` = USED, which are (3, 19) and (3, 20) of tile (0, 0)).

**How the wires were found**

GowinSynthesis refuses `GW_JTAG` in user Verilog (`RP0008: There is no GW_JTAG resource in current device`, IDE 1.9.11.03 Education, also on GW2AR-18C), so I gave Gowin PnR a hand-written netlist (`add_file -type netlist`: IBUF/OBUF + `GW_JTAG` with every output on a pin). Then I traced each pin back with `gowin_unpack -d GW1NS-4` (Apicula 0.35):

| port | GW1NS-4 (0, 0) | GW2A-18C (27, 50) |
|---|---|---|
| tck_o | Q6 | Q6 |
| tdi_o | Q5 | Q5 |
| test_logic_reset_o | Q3 | Q3 |
| run_test_idle_er1_o | Q4 | Q4 |
| run_test_idle_er2_o | **F0** | F7 |
| shift_dr_capture_dr_o | **Q7** | F6 |
| update_dr_o | Q2 | Q2 |
| enable_er1_o | Q0 | Q0 |
| enable_er2_o | Q1 (see below) | Q1 |
| pause_dr_o | not driven from (0, 0); left as DUMMY | DUMMY |
| tdo_er1_i / tdo_er2_i | C1 / C2 | C1 / C2 |

The trace of `enable_er2_o` stopped at `R1C1_E11`, so I took Q1 from the GW2A-18C and checked it on hardware (below).

The two CFG fuses are set in the IDE bitstream and clear in an Apicula blinky.

**Testing**

I can't regenerate the chipdb from the vendor files (I only have IDE 1.9.11.03, and `GWVERSION` is 1.9.10.03). So I tested it like this:
- Added the same `jtag` entry to the released 0.35 `GW1NS-4.msgpack.xz`. Rebuilt the nextpnr chipdb with `gowin_arch_gen.py` (nextpnr 6b438a1c) and `bbasm`, and passed it with `--chipdb` to the oss-cad-suite 2026-10-22 `nextpnr-himbaechel`. No nextpnr change was needed; it reports `GW_JTAG: 1/1`.
- This branch's `fse_create_jtag`, applied to the 0.35 chipdbs, gives exactly that entry for GW1NS-4 and leaves GW2A-18C unchanged.
- `gowin_pack` from this branch gives the same bitstream (apart from the comment lines) as the patched 0.35 that I used on hardware. Without the change, master stops with `Not implemented method 'get_GW_JTAG_fuses'`.
- On a Tang Nano 4K (host: the on-board BL702 over its MPSSE subset):
  - A 32-bit user DR on ER1 (IR 0x42) round-trips: 299 random values on each of nextpnr seeds 1-5, no mismatches.
  - IR 0x43 reaches ER2.
  - `enable_er2_o` (Q1): with a small design that counts its rising edges (sampled at 27 MHz), it is 1 only while IR 0x43 is selected. While IR 0x42 is selected it reads 0 and `enable_er1_o` reads 1. Selecting IR 0x43 five times gives five rising edges, and selecting IDCODE gives none. With `tdo_er2_i = enable_er2_o & ~enable_er1_o`, ER2 scans read all ones.

**Note for users**

`tck_o` (Q6 at (0, 0)) does not seem to go over a clock network. A shift register clocked by `tck_o` failed on one of five placements (275/299 bad round trips), although nextpnr reported no timing violation. Oversampling the `GW_JTAG` outputs with the 27 MHz board clock and acting on the TCK falling edge worked on every seed. That is a design matter, not something this PR changes.

_(This PR was prepared with the help of an AI assistant and reviewed by me.)_

## #533 へのコメント（PR を出した後）

I opened #⟨PR番号⟩ adding `GW_JTAG` for the GW1NS-4 (Tang Nano 4K), following #537. The cell is at (0, 0) and uses the same CFG fuses; the details and hardware checks are in the PR. Thanks for the write-up in this thread, it made it straightforward.

# Tang Nano 9K / 20K の GW_JTAG をオープンなツールで使う（準備 2026-11-13、実機 2026-11-15）

## 結論と要約
- **9K（GW1N-9C）の GW_JTAG を Apicula に足した。** fork（harurun78/apicula）のブランチ `gw1n9c-gw_jtag`（上流 master 20d6af9 の上に 1 コミット）。部品の位置は 4K と同じ (0,0)。配線名（DAT の `JtagIns`/`JtagOuts`）も設定ビット（CFG の `JTAG_ER1`/`JTAG_ER2`）も 4K と同じだった。
- **20K（GW2A-18C）は改修不要。** oss-cad-suite 2026-10-22 に同梱の chipdb と `gowin_pack`（Apicula 0.35）のままで、`GW_JTAG` を (27,50) に置いてビットストリームまで作れた。
- **nextpnr と openFPGALoader は改修不要。** nextpnr の GW_JTAG 対応はデバイスに依存しない（9K も chipdb を作り直すだけで `GW_JTAG: 1/1`）。openFPGALoader は `tangnano9k` / `tangnano20k` のボード ID と両方の IDCODE を持っている。4K のときもフォークして改修したのは Apicula だけで、nextpnr と openFPGALoader はフォークしていない。
- **試験用の 4 デザイン（userdr_open、en2probe、jtagdiag、jtagphase）を 9K と 20K 向けにビルドした。** どれも `GW_JTAG: 1/1`、タイミング違反なし。
- **2026-11-15: 20K の実機で GW_JTAG が動いた（6 章）。** oss-cad-suite 2026-11-15 だけで作ったビットストリームで、ER1 のユーザー DR の往復が 4999 回中 0 回不一致（配置のシード 1〜5 すべて 0 回）、ER2 の enable も合格。BL616 の TCK は分周設定にかかわらず約 3.5 MHz（BL702 の約 2 倍）で、27 MHz での取り込みは通るが余裕は小さい。BL616 の USB は High Speed（パケット 512 バイト）で、nanopynq の `transport/mpsse.py` の 64 バイト前提は直す必要がある（nanopynq PR #13 で直した）。
- **2026-11-15: 9K の実機でも GW_JTAG が動いた（7 章）。** fork ブランチ `gw1n9c-gw_jtag` の Apicula と作り直した chipdb で作ったビットストリームで、ER1 のユーザー DR の往復が配置のシード 1〜5 ですべて 0 回不一致、ER2 の enable も合格。推定だった shift_dr_capture_dr_o = Q7 も正しかった。上流に PR を出した（YosysHQ/apicula#608）。

## 1. 9K の調べ方と結果
| 確認 | 方法 | 結果 |
|---|---|---|
| 配線名 | Gowin IDE（1.9.11.03 Education と 1.9.12.04）の `GW1NR-9C.dat` を Apicula の `dat_parser` で読む | `JtagIns` = C1/C2（tdo_er1_i/tdo_er2_i）、`JtagOuts` = Q6/Q5/Q3/Q4/F0/Q7/Q2/Q0/Q1。GW1NSR-4C と同一。GW2A-18C は run_test_idle_er2_o=F7、shift_dr_capture_dr_o=F6 だけ違う |
| 部品の位置 | `allwires_top.vg`（4K と同じネットリスト）を IDE の配置配線に直接渡し（`allwires_9k.tcl`、合成は飛ぶ）、`gowin_unpack -d GW1N-9C` の結果を出力ピンから逆にたどる（`trace_unpacked.py`）。どのポートがどのピンに出たかは IDE のピンレポートで見た | 下の表。出力 8 本と入力 2 本が R1C1（0 始まりで (0,0)）に行き着いた。1 本は R1C1 で途切れ、2 本は定数 |
| 設定ビット | `jtag_cfg_fuses.py` と同じ方法で、IDE のビットストリームと GW_JTAG の無い 9K のビットストリーム（同梱の `tangnano9k-base`）の (0,0) を比べる | `JTAG_ER1=USED` → (3,19)、`JTAG_ER2=USED` → (3,20)。IDE 版では立ち、比較対象では立っていない。4K と同じビット位置 |

ポートごとの照合（IDE の配置配線。ピン → IOB はピンレポートの `IOL<行>[A/B]`（左端の列）/ `IOT<列>[A/B]`（上端の行））:
| ポート | ピン（IOB） | たどった先 | DAT |
|---|---|---|---|
| tck_o | 14（R22C1 B） | R1C1_Q6 | Q6 |
| tdi_o | 13（R21C1 B） | R1C1_Q5 | Q5 |
| test_logic_reset_o | 11（R16C1 B） | R1C1_Q3 | Q3 |
| run_test_idle_er1_o | 10（R15C1 A） | R1C1_Q4 | Q4 |
| run_test_idle_er2_o | 4（R5C1 A） | R1C1_F0 | F0 |
| shift_dr_capture_dr_o | 3（R1C2 A） | R1C1_E11 で途切れた（unpack が E11 の駆動元を知らない。4K でも 1 本がここで途切れた） | Q7（残る出力は Q7 だけなので消去法で一致とみる） |
| pause_dr_o | 86（R1C8 A） | R1C8_F5（定数） | なし（DUMMY） |
| update_dr_o | 85（R1C8 B） | R1C1_Q2 | Q2 |
| enable_er1_o | 84（R1C10 A） | R1C1_Q0 | Q0 |
| enable_er2_o | 83（R1C10 B） | R1C1_Q1 | Q1 |
| tdo_er1_i（入力） | 15（R25C1 B） | R1C1_C1 に届く | C1 |
| tdo_er2_i（入力） | 82（R1C11 A） | R1C1_C2 に届く | C2 |
| tdo_pad_o | 8（専用ピン） | R13C1_F5（定数。JTAG の専用の経路とみる） | なし（DUMMY） |

## 2. Apicula の変更（`gw1n9c-gw_jtag`、b667bf2）
- `chipdb.py` の `fse_create_jtag`: `GW1N-9C` を (0,0) に追加（4K と同じ分岐）。
- `gowin_pack.py` の `GW1N_9C`: `get_GW_JTAG_fuses`（4K・20K と同じ中身）。
- GW1N-9（C なし、TEC0117 など）は確かめる手段が無いので足していない。
- 確かめたこと:
  - 上流 CI の wheel（run 43094366218、20d6af9）の chipdb に、このブランチの `fse_create_jtag` を手元の DAT で当て直すと、GW1NS-4 と GW2A-18C は wheel の `jtag` の項目と一致した（作り方の確認）。
  - GW1N-9C は (0,0) に `jtag` が増え、それ以外の `extra_func` は変わらなかった。
  - そこから nextpnr（6b438a1c）の `gowin_arch_gen.py` と bbasm で chipdb を作り、`userdr_open.v` を配置配線すると `GW_JTAG: 1/1`、bel は X0Y0。pnr.json の配線では、使っている出力は X0Y0 の Q0/Q2/Q5/Q6/Q7 から出て、tdo_er1_i/tdo_er2_i は X0Y0 の C1/C2 に入る。pack したビットストリームでは (0,0) の (3,19)/(3,20) が立つ。
  - 作り直した chipdb（12,892,240 バイト）は同梱版（12,910,129 バイト）より小さい。GW_JTAG を使わない `blinky.v` を両方で配置配線すると、資源の総数（GW_JTAG 0/1 が増えた以外）、配置、最大周波数は同じで、配線のチェックサムだけが違った。差は Apicula 0.35 と master 20d6af9 の chipdb の違いとみている（中身は未確認）。
  - 手順のスクリプト: `add_jtag_chipdb.py`（wheel の chipdb に `jtag` を足す。作り直すと同じ chipdb になることを確認）、`dat_jtag_wires.py`、`trace_unpacked.py`、`jtag_cfg_fuses.py`（デバイスを引数に取るようにした）。
- 確かめていないこと: ベンダーのファイルからの Apicula の chipdb の再生成（上流は IDE 1.9.10.03）。9K には PSRAM があり、4K と同じく Windows の `chipdb_builder` では SDRAM のピン探索が動かない見込みなので、wheel の chipdb に `jtag` の 1 項目だけを足す方法をとった。

## 3. 20K
- oss-cad-suite 同梱の `chipdb-GW2A-18C.bin` で配置配線すると、GW_JTAG は X50Y27（Apicula の (27,50)）に置かれた。
- 同梱の `gowin_pack`（0.35）と上流 master の `gowin_pack` は、コメント行を除いて同じビットストリームを出した。

## 4. ビルド手順（nanopynq）
- `tools/p0/gwjtag4k/build_open.sh` に `BOARD=4k|9k|20k` を足した（既定は 4k）。`led9k.cst` / `led20k.cst` は Apicula の例の制約から、27 MHz のクロックと LED0 を取った。
- Windows ネイティブの yosys / nextpnr が `/c/...` の形のパスを読めないので、`pwd -W`（`C:/...`）にした。4K でも同じ結果になることをビルドで確かめた。

## 5. 実機が届いたら（順に）
0. 9K は先に、新しい chipdb で作った GW_JTAG なしの `blinky` を書き込む（LED が数える）。失敗したときに、原因が chipdb か GW_JTAG かを切り分けるため。
1. Zadig で JTAG 側のインターフェースを WinUSB にする（4K と同じ。20K の BL616 の USB ID は未確認）。
2. `jtag_mpsse_min.py --expect` で IDCODE を読む（9K 0x0100481b、20K 0x0000081b。openFPGALoader の一覧の値）。BL616 が BL702 と同じ MPSSE のコマンドを受け付けるかは未確認。
3. `userdr_open` を書き込み、`userdr_scan.py` / `userdr_stress.py` で往復を確かめる。
4. `jtagdiag_top` で TCK の速さを測る。27 MHz での取り込みは TCK の数倍の速さが前提（13.4 章）。20K の TCK が速ければ PLL で取り込みのクロックを上げる。
5. `en2probe_top` で enable_er2_o（Q1）を確かめる。
6. 9K が通れば、Apicula の上流に PR を出す（4K の #578 と同じ形）。

## 6. 20K の実機（2026-11-15）
道具: oss-cad-suite 2026-11-15（Yosys 0.71+34 e419c4ee、nextpnr 0.11.1-92 5e2718b6、同梱 Apicula 0.36.dev41+gda0e33e02、openFPGALoader v1.2.0）。
`OVL` は同じコミット（da0e33e）の上流 CI の wheel を展開したもの、`CHIPDB` は同梱の `chipdb-GW2A-18C.bin`。nextpnr は
20K の ALU の不具合（Apicula #514 / #541）の修正 6030081a15 を含む。書き込みはすべて SRAM（フラッシュには書いていない）。

| 確認（5 章の番号） | 結果 |
|---|---|
| 1. USB | BL616 は `0403:6010`、製造者 SIPEED、製品名 `USB Debugger`。USB 2.0 High Speed（bcdUSB 0x200、bcdDevice 0x500）、Interface 0 / 1 ともバルク 512 バイト。Windows の既定は両方 FTDI（COM4/COM5）。Zadig で Interface 0 だけ WinUSB にした（Interface 1 は COM5 のまま） |
| 2. IDCODE | openFPGALoader `-b tangnano20k --detect` で 0x0000081b（GW2A(R)-18(C)、IR 8 ビット）。`jtag_mpsse_min.py --expect 0x81b` でも同じ値（200 回で 1692 回/秒）。BL702 と同じ MPSSE のコマンドで動く |
| 3. ユーザー DR（ER1、`userdr_open`） | `userdr_stress.py`: シード 1 で 4999 回中 0 回不一致。シード 2〜5 で各 1999 回中 0 回不一致 |
| 4. TCK の速さ（`jtagdiag_top`） | 分周設定 100 kHz / 1 MHz / 3 MHz / 6 MHz のどれでも、High が 27 MHz の 2〜3 刻み（74〜111 ns）、周期 7〜8 刻み（約 3.5 MHz）。BL702（約 2 MHz、High 5〜8 刻み）より速い。記録回路は 1 回きりなので速さごとに書き込み直して測った |
| 4'. TDO を読む瞬間（`jtagphase_top`） | IR 0x42 / 0x43 とも `0101…`。BL702 と同じく TCK が High の間に読む |
| 5. ER2 の enable（`en2probe_top`） | RESULT: PASS（全項目 ok） |

考察:
- 27 MHz の 2 段のフリップフロップでの取り込み（`userdr_open.v`、13.4 章の作り）は 20K でも通った。ただし High が 2 刻みの TCK もあり、余裕は BL702 より小さい。土台の回路では、取り込みのクロックを PLL で上げる（例: 81 MHz 以上）と余裕ができる。
- BL616 はパケットが 512 バイトなので、FTDI の状態バイト 2 バイトは 512 バイトごとに入る。nanopynq の `transport/mpsse.py`（と `jtag_mpsse_min.py`）は 64 バイトごとに取り除くので、62 バイトを超える読み出しは崩れる。今回の試験は読み出しが短く、この問題に当たらない。パケット長はエンドポイントの `wMaxPacketSize` から取ればよい。

## 7. 9K の実機（2026-11-15）
ビットストリームは 2026-11-13 に作ったもの（oss-cad-suite 2026-10-22、`OVL` = `apycula-20d6af9-gw1n9c`、`CHIPDB` = 作り直した
`chipdb-GW1N-9C-20d6af9-jtag.bin`。2 章）。書き込みは openFPGALoader v1.2.0（oss-cad-suite 2026-11-15）で、すべて SRAM。

| 確認（5 章の番号） | 結果 |
|---|---|
| 1. USB | BL702 は `0403:6010`、製品名 `JTAG Debugger`、シリアル `FACTORYAIOT_PRO`。Interface 0 / 1 ともバルク 64 バイト（Full Speed）。Zadig で Interface 0 だけ WinUSB にした（Interface 1 は COM3 のまま。9K の base は UART で使う） |
| 2. IDCODE | openFPGALoader `-b tangnano9k --detect` は 0x0100481b（GW1N(R)-9C）。生の値は 0x1100481b（`jtag_mpsse_min.py`）。openFPGALoader は上位 4 ビット（版）を隠して照合するので、5 章の期待値 0x0100481b はその値だった |
| 0. GW_JTAG なしの blinky | 書き込みは成功（DONE）。下の 3〜5 が通ったので、切り分けのための目視はしていない |
| 3. ユーザー DR（ER1、`userdr_open`） | シード 1 で 4999 回中 0 回不一致。シード 2〜5（同じ道具でビルドし直した）で各 1999 回中 0 回不一致 |
| 4. TCK の速さ（`jtagdiag_top`） | 分周設定 100 kHz と 6 MHz のどちらも、High が 27 MHz の 5〜7 刻み、周期 12〜13 刻み（約 2.1 MHz）。4K の BL702 と同じ。sdr（Q7）は Shift-DR の間だけ 1 になり、TCK と揃って変わった |
| 4'. TDO を読む瞬間（`jtagphase_top`） | IR 0x42 / 0x43 とも `0101…`（TCK が High の間に読む） |
| 5. ER2 の enable（`en2probe_top`） | RESULT: PASS（全項目 ok）。pause_dr_o は常に 1 を読んだ（1 章の表で定数とした配線。どの試験でも使っていない） |

nanopynq PR #13 の確認も、この 9K でした: マージ後の `transport/mpsse.py` は BL702 のパケットを 64 バイトと読み、20 回分の IDCODE（140 バイト、3 パケット）をすべて 0x1100481b と読んだ。4K も BL702 なので、4K の基板が故障していても、この点は確かめられたとみる。

## 確認できなかったこと
- 作り直した 9K の chipdb が同梱版より小さい理由。
- 9K の chipdb を oss-cad-suite 2026-11-15 の nextpnr（5e2718b6）向けに作り直すこと（今の chipdb は 6b438a1c の `gowin_arch_gen.py` で作ったもの）。

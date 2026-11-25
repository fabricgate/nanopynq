# オープンなツールでの Gowin ボードの対応状況（2026-11-04）

## 結論と要約
- **ボード単位では、Sipeed の Tang 系は全部が「対応済み」に名前が載っている。** Yosys（`synth_gowin -family gw1n/gw2a/gw5a`）、nextpnr-himbaechel（11 デバイスの chipdb）、Apicula（README の対応ボード一覧）、openFPGALoader（ボード ID）のすべてにある。
- **ただし、中身の成熟度は大きく 3 段に分かれる。**
  1. **GW1N / GW2A 系（Tang Nano / 1K / 4K / 9K / 20K、Primer 20K）は実用段階。** PLL、BSRAM、DSP、IO の直並列変換、LVDS は Apicula の例でビルドされている。実機での自動試験（HIL）があるのは Tang Nano 20K と TEC0117 だけ。
  2. **Tang Primer 25K（GW5A-25A）は主な部品がそろう。** 例がある。
  3. **Tang Console 60K（GW5AT-60B）と Tang Mega 138K（GW5AST-138C）は初期段階。** Apicula の README でも「とても単純な回路だけ動く」「基本的なクロックだけ」とされている。
- **nanopynq にとって重い未対応は GW_JTAG（USB 1 本で通信するのに使う）。** 上流で使えるのは GW2A-18C（20K、Primer 20K）だけ。GW1NS-4（4K）は PR #578 を出した（審査待ち）。GW1N-9C（9K）と GW5A 系は未実装。
- **openFPGALoader は、SRAM への書き込みはすべての Tang で可、フラッシュへの書き込みはボードしだい。** `boards.yml` では Primer 25K と Mega 138K のフラッシュが「TBD」。
- nanopynq が実機で確かめているのは 4K と 9K だけ。4K の GW_JTAG だけは手元で直した Apicula に頼っている。

## 1. 調べ方と版
| ツール | 見たもの | 版・コミット |
|---|---|---|
| Apicula | `readme.md`、`apycula/gowin_pack.py`、`apycula/chipdb.py`、`examples/Makefile`、`examples/gw5a/Makefile` | master 993faec（2026-11-02）。最新のリリースは 0.35（2026-10-20） |
| nextpnr-himbaechel | `himbaechel/uarch/gowin/CMakeLists.txt` のデバイス一覧 | main のうち gowin を最後に変えた dd574ddc（2026-10-26） |
| openFPGALoader | `doc/boards.yml`、`src/board.hpp`、`src/gowin.cpp`、`doc/vendors/gowin.rst` | master e3d8d947（2026-11-03） |
| Yosys | 手元の `help synth_gowin` | 0.70+190（485b63564） |
| 手元の oss-cad-suite | `VERSION` と同梱物 | 20261022（nextpnr 0.11.1-77-g6b438a1c、Apicula 0.35、openFPGALoader v1.2.0、gowin の chipdb 11 個） |

- 2 章の部品の表は次の 2 つから作った。
  - **(a) `gowin_pack` の判定**: デバイスごとのクラスで、各部品の `get_<部品>_fuses` が実装されているか、`error_not_supported_cell_type` / `error_not_implemented_method` を呼ぶだけかを、継承をたどって機械的に調べた（AST で解析）。
  - **(b) 例のビルド対象**: Apicula の `examples/Makefile` で、ボードごとにビルド対象になっている例。
- (a) で拒否されないことは、使えることを意味しない。chipdb 側に部品が無ければ nextpnr で配置できない。**そのため「例あり」を対応の根拠にし、「pack が拒否しないが例が無い」は未確認として分けた。**

## 2. ボード × ツール
| ボード | FPGA（Apicula / nextpnr のデバイス） | Yosys family | Apicula の README | nextpnr chipdb | openFPGALoader ID（SRAM / フラッシュ） | Apicula の例 | 実機の自動試験 |
|---|---|---|---|---|---|---|---|
| Tang Nano | GW1N-1 | gw1n | 対応 | あり | `tangnano`（OK / 記載なし） | あり | なし |
| Tang Nano 1K | GW1NZ-1 | gw1n | 対応 | あり | `tangnano1k`（OK / IF） | あり | なし |
| **Tang Nano 4K** | GW1NS-4 | gw1n | 対応 | あり | `tangnano4k`（OK / IF・EF） | あり | なし |
| **Tang Nano 9K** | GW1N-9C | gw1n | 対応（`--vopt family` が要る） | あり | `tangnano9k`（OK / IF・EF） | あり | なし |
| Tang Nano 20K | GW2A-18C | gw2a | 対応（同上） | あり | `tangnano20k`（OK / EF） | あり | **あり** |
| Tang Primer 20K | GW2A-18C | gw2a | 対応（同上） | あり | `tangprimer20k`（OK / EF） | あり | なし |
| Tang Primer 25K | GW5A-25A | gw5a | 対応 | あり | `tangprimer25k`（OK / **TBD**） | あり（`examples/gw5a`） | なし |
| Tang Console 60K | GW5AT-60B | gw5a | **作業中**（単純な回路だけ） | あり | `tangconsole`（OK / OK） | 5 個（入出力、シフト、OSC） | なし |
| Tang Mega 138K | GW5AST-138C | gw5a | **初期**（基本的なクロックだけ、HCLK や segment なし） | あり | `tangmega138k`（OK / **TBD**） | 3 個（シフト、attosoc、UART） | なし |
| Trenz TEC0117 | GW1N-9 | gw1n | 対応 | あり | `tec0117`（OK / IF） | あり | **あり** |
| Seeed RUNBER | GW1N-4 | gw1n | 対応 | あり | `runber`（OK / IF・EF） | あり | なし |
| Szfpga | GW1N-9 | gw1n | 対応 | あり | なし | あり | なし |

- **フラッシュ欄の略号**: openFPGALoader の `boards.yml` の値をそのまま載せた。IF は内部フラッシュ、EF は外部 SPI フラッシュと読んでいる（凡例の文書は見つけられなかった）。
- **openFPGALoader の文書の食い違い**: `doc/vendors/gowin.rst` は「フラッシュへの書き込みは TEC0117、RUNBER などだけ」と書いている。一方 `boards.yml` とソースは、Tang Nano 4K / 9K にも内部・外部フラッシュがあるとしている。文書が古いとみているが、フラッシュへの書き込みは nanopynq では確かめていない。
- **Apicula の一覧に無いが、openFPGALoader に ID がある Gowin のボード**: `lilygo-t-fpga`（GW1NSR-4C）、`brs-100-gw1nr9`、`epm11`（どちらも GW1NR-9）。FPGA が同じなので、Apicula でもピンを決めれば使えるはず（未確認）。
- **「Tang Console」の ID の扱い**: ソースの ID `tangconsole` は 60K と 138K のどちらの SOM も指す。Tang Mega 60K 単体の ID は無い。
- **YoWASP（pip 版）は遅れている**: 以前の調査（`report_jtag_bridge_spike.md` 結論）では Apicula 0.32 に固定されていて、GW_JTAG を含まない。nanopynq の 9K の土台は YoWASP で作っている。

## 3. デバイス × 部品（nanopynq に関係するもの）
記号:
- ✓ = Apicula の例がビルド対象にある
- ✓n = nanopynq が実機で確かめた
- △ = `gowin_pack` は拒否しないが例が無い（未確認）
- ✗ = `gowin_pack` が拒否する（未実装・非対応）
- PR = 上流に PR 済み、手元のパッチで実機確認済み

| 部品 | GW1N-1（Nano） | GW1NZ-1（1K） | GW1NS-4（4K） | GW1N-9C（9K） | GW2A-18C（20K） | GW5A-25A（25K） | GW5AT-60B（60K） | GW5AST-138C（138K） |
|---|---|---|---|---|---|---|---|---|
| PLL | ✓ rPLL | ✓ rPLL | ✓ PLLVR（nanopynq はビルドだけ） | ✓ rPLL | ✓ rPLL | ✓ PLLA | △ PLLA | △ PLLA |
| BSRAM | ✓ | ✓ | ✓n SDPX9B（例は無い） | ✓ | ✓ | ✓ | △ | △ |
| DSP | △（GW1N-1 に DSP は無いはず） | △（同） | ✓ | ✓ | ✓ | ✓ | △ | △ |
| IDDR/ODDR/IDES/OSER | ✓ | ✓ | ✓（IDES16/OSER16 も） | ✓ | ✓ | ✓ | △ | △ |
| LVDS（TLVDS/ELVDS） | ✓ ELVDS | ✓ ELVDS | ✓ 両方 | ✓ 両方 | ✓ 両方 | ✓ TLVDS | △ | △ |
| 内部発振器 | ✓ OSCH | ✓ OSCZ | ✓ OSCZ | ✓ OSC | ✓ OSC | ✓ OSCA | ✓ OSCA | △ OSC |
| **GW_JTAG** | ✗ | ✗ | **PR（#578）**、✓n | ✗ | ✓（例は無い） | ✗ | ✗ | ✗ |
| ユーザーフラッシュ | ✗ | ✓ FLASH64KZ | △ FLASH256K | ✓ FLASH608K | ✗ | ✗ | ✗ | ✗ |
| Cortex-M3（EMCU） | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| ADC | — | — | — | — | — | ✓ | — | — |
| MIPI | △ | △ | ✓ 出力 | ✓ 入出力 | △ | △ | △ | △ |
| 内蔵のメモリ | — | — | ✓n HyperRAM（1 チャンネル目だけ） | 未調査（PSRAM） | 未調査（SDRAM） | — | — | — |

- GW_JTAG の 20K は、#533 と #537 で実機での報告がある（Apicula の例・HIL には無い）。
- 4K の BSRAM は Apicula の例に `bsram-*` が無い。nanopynq のカメラ用の回路で、SDPX9B を実機で使っている（`report_camera4k.md`、`report_psram_stream.md`）。
- 4K の HyperRAM は、Apicula の chipdb に 2 チャンネル目が載っている。しかし、その位置は JTAG のピンに重なるので、実在しないとみている（`report_p0_psram4k.md`）。
- GW5A 系の BSRAM は、`Bitstream_GW5A.write_with_bsram` が基底クラスでは未実装。デバイスごとのクラスでの扱いは読んでいない（25K は例があるので動くとみている）。
- 「—」は、そのデバイスに部品が無いか、`gowin_pack` にその部品の処理が無いもの。

## 4. nanopynq での実機確認（参考）
| ボード | 確かめたこと | ツール |
|---|---|---|
| Tang Nano 4K | LED、GW_JTAG ブリッジ（ER1）、カメラ（DVP + I2C + BSRAM）、HyperRAM のリングバッファ | oss-cad-suite 20261022 + **手元で直した Apicula 0.35 と chipdb**（GW_JTAG のため） |
| Tang Nano 9K | UART ブリッジの土台（LED など） | YoWASP |
| その他 | 未確認 | — |

## 5. 未対応・注意点のまとめ
- **GW_JTAG**: 上流で使えるのは GW2A-18C だけ。GW1NS-4 は PR #578（2026-11-04 時点で OPEN、レビューなし）。GW1N-9C と GW5A 系は手つかず。9K を USB 1 本で使うには、4K と同じ調査（配線の逆引き、設定ビット、実機での確認）が要る。
- **GW5A 系（25K / 60K / 138K）**:
  - 25K は例がそろっている。
  - 60K と 138K は、例が数個で、Apicula 自身が「作業中」「初期」としている。
  - openFPGALoader のフラッシュへの書き込みは、25K と 138K で「TBD」。
- **実機での自動試験**: あるのは Tang Nano 20K と TEC0117（GW1N-9）だけ。ほかのボードの「例あり」は、ビルドが通ることまでしか保証しない。
- **pip 版（YoWASP）**: Apicula が古いので、新しい部品（GW_JTAG など）は oss-cad-suite か、ソースからのビルドが要る。

## 確認できなかったこと
- 3 章の △ の部品が実際に使えるか（ビルドも実機も試していない）。
- 9K の PSRAM と 20K の SDRAM を、Apicula から使えるか。
- openFPGALoader のフラッシュの略号（IF/EF）の正式な定義。
- Apicula の CI（`.github/workflows`）がどのボードの例をビルドしているか。ワークフローの中身は読んでいない。
- Tang Mega 60K（単体）や Tang Mega 138K Pro など、上の一覧に無い Sipeed のボード。

# Yosys 系のオープンなツールが対象にしている FPGA ベンダー（2026-11-04）

## 結論と要約
- **Sipeed は基板のメーカーで、Tang 系の FPGA は Gowin 製。** Yosys 系のツールは Gowin 以外にも多くのベンダーを対象にしている。ただし、どこまでオープンなツールで作れるかで 3 段に分かれる。
  1. **ビットストリームまでオープンなツールで作れる**: Lattice の iCE40 と ECP5、Gowin、Cologne Chip の GateMate、Lattice Nexus。安定している。Lattice MachXO2、Xilinx 7 系、Intel（Altera）Cyclone V は試験段階。
  2. **配置配線まではオープン、ビットストリームはベンダーのツール**: NanoXplore NG-Ultra（Impulse が要る）。
  3. **合成（Yosys）だけ。配置配線とビットストリームはベンダーのツール**: Achronix、Analog Devices、Anlogic、eASIC、Efinix、Intel の MAX10 と Cyclone IV、Microchip の PolarFire、SmartFusion2 / IGLOO2、QuickLogic、Xilinx の UltraScale(+) と Spartan 6 など。
- **手元の Windows 版 oss-cad-suite（20261022）で完結するのは、iCE40、ECP5、MachXO2、Nexus、GateMate、Gowin。** Xilinx、Cyclone V、NG-Ultra の配置配線は入っていない。使うにはソースからビルドするか、別の配布物が要る。
- **書き込み（openFPGALoader）は 7 ベンダーに対応している。** Anlogic、Cologne Chip、Efinix、Gowin、Altera、Lattice、Xilinx。

## 1. 調べ方と版
| 対象 | 見たもの | 版 |
|---|---|---|
| Yosys | 手元の `help`（`synth_*` の一覧と各 `-family` / `-arch`） | 0.70+190（485b63564） |
| nextpnr | 上流の README とフォルダの構成（`himbaechel/uarch/*`）、Xilinx の例の手順 | main 937c770c（2026-11-04） |
| 手元の oss-cad-suite | `bin/` の nextpnr と各ビットストリームのツール、`share/nextpnr/himbaechel/` | 20261022（Windows 版） |
| openFPGALoader | `doc/FPGAs.yml` のベンダー | master e3d8d947（2026-11-03） |
| Project Tang（Anlogic） | GitHub の `mmicko/prjtang` | 最後の push は 2022-12-25 |

## 2. ベンダー × ツール
記号:
- **完結** = 合成からビットストリームまでオープン
- **試験** = 完結するが、nextpnr の README で experimental
- **P&R まで** = 配置配線までオープン
- **合成だけ** = 配置配線とビットストリームはベンダーのツール

| ベンダー | family | Yosys | 配置配線 | ビットストリーム（データベース） | 段階 | 手元の oss-cad-suite | openFPGALoader |
|---|---|---|---|---|---|---|---|
| Lattice | iCE40 | `synth_ice40` | `nextpnr-ice40` | `icepack`（Project IceStorm） | 完結 | あり | あり |
| Lattice | ECP5 | `synth_ecp5` | `nextpnr-ecp5` | `ecppack`（Project Trellis） | 完結 | あり | あり |
| Lattice | Nexus（CrossLink-NX、Certus-NX など） | `synth_nexus` / `synth_lattice` | `nextpnr-nexus` | `prjoxide`（Project Oxide） | 完結（※1） | あり | あり |
| Lattice | MachXO2 | `synth_lattice -family xo2` | `nextpnr-machxo2` | `ecppack`（Project Trellis） | 試験 | あり | あり |
| Lattice | MachXO3 / XO3D | `synth_lattice` | — | — | 合成だけ（※2） | — | あり |
| Gowin | LittleBee（GW1N）、Arora（GW2A）、Arora V（GW5A） | `synth_gowin` | `nextpnr-himbaechel`（gowin） | `gowin_pack`（Project Apicula） | 完結（GW5A の一部は初期。`report_oss_board_support.md`） | あり | あり |
| Cologne Chip | GateMate | `synth_gatemate` | `nextpnr-himbaechel`（gatemate） | `gmpack`（Project Peppercorn） | 完結 | あり | あり |
| Xilinx（AMD） | 7 系 | `synth_xilinx -arch xc7` | `nextpnr-himbaechel`（xilinx） | FASM を Project X-Ray のツールで .bit に変換 | 試験 | なし | あり |
| Xilinx（AMD） | UltraScale(+)、Spartan 6 など | `synth_xilinx` | — | — | 合成だけ | — | あり |
| Intel（Altera） | Cyclone V | `synth_intel_alm` | `nextpnr-mistral` | Mistral | 試験 | なし | あり |
| Intel（Altera） | MAX10、Cyclone IV | `synth_intel` | — | — | 合成だけ | — | あり |
| NanoXplore | NG-Ultra | `synth_nanoxplore` | `nextpnr-himbaechel`（ng-ultra、Project Beyond） | **Impulse（ベンダー）が要る** | P&R まで | なし | なし |
| NanoXplore | NG-Medium、NG-Large | `synth_nanoxplore` | — | — | 合成だけ | — | なし |
| Anlogic | EG4 など | `synth_anlogic` | — | Project Tang は形式の文書化だけ（2022 年で止まっている） | 合成だけ | — | あり |
| Efinix | Trion など | `synth_efinix` | — | — | 合成だけ | — | あり |
| Microchip | PolarFire | `synth_microchip` | — | — | 合成だけ | — | なし |
| Microchip | SmartFusion2、IGLOO2 | `synth_sf2` | — | — | 合成だけ | — | なし |
| QuickLogic | PolarPro 3、K6N10f | `synth_quicklogic` | （nextpnr には無い。※3） | — | 合成だけ（Yosys 系の範囲では） | — | なし |
| Achronix | Speedster22i | `synth_achronix` | — | — | 合成だけ | — | なし |
| Analog Devices | `-tech t40lp`（BRAM の種類だけに効く） | `synth_analogdevices` | — | — | 合成だけ | — | なし |
| eASIC | — | `synth_easic` | — | — | 合成だけ | — | なし |
| （自作の FPGA） | FABulous の eFPGA | `synth_fabulous` | `nextpnr-generic` | FABulous | 完結（自作のファブリック向け） | nextpnr-generic はある | — |

- ※1: nextpnr の README は、Nexus を対応一覧（試験の印なし）に載せている。一方、ビルドの節では「試験段階のアーキテクチャ（いまは nexus）」とも書いていて、食い違っている。
- ※2: `synth_lattice` は MachXO3 / XO3D の合成に対応している。しかし nextpnr の対応一覧に MachXO3 は無い（`nextpnr-machxo2` が扱うかは確かめていない）。
- ※3: QuickLogic には、VPR を使う F4PGA の流れがある。Yosys と nextpnr の範囲の外なので、今回は調べていない。
- 「—」は該当なし。手元の oss-cad-suite の欄の「—」は、そもそもオープンな配置配線が無いもの。

## 3. 手元の oss-cad-suite（Windows 版 20261022）に入っているもの
- 配置配線: `nextpnr-ice40`、`nextpnr-ecp5`、`nextpnr-machxo2`、`nextpnr-nexus`、`nextpnr-generic`、`nextpnr-himbaechel`（uarch は gatemate と gowin だけ）。
- ビットストリーム: `icepack`、`ecppack`、`prjoxide`、`gmpack`、`gowin_pack`。
- 入っていない: `nextpnr-mistral`、himbaechel の xilinx と ng-ultra、Project X-Ray のツール。
- Linux や macOS 版の oss-cad-suite に、これらが入っているかは確かめていない。

## 4. nanopynq から見た意味
- nanopynq の「オープンなツールだけでビルドする」前提を保ったまま、Gowin 以外に広げるなら、候補は **Lattice（iCE40 / ECP5）** と **GateMate**。手元の oss-cad-suite だけで完結し、成熟度も高い。
- Xilinx 7 系（Arty など）と Cyclone V（DE10-Nano など）は試験段階で、Windows の配布物にも入っていない。手を出すと、ツールのビルドから始めることになる。
- GW_JTAG にあたる「ユーザーが使える JTAG」の対応状況は、ベンダーごとには調べていない。ECP5 の JTAGG、Xilinx の BSCANE2 などがある。

## 確認できなかったこと
- 2 章の「試験」の各フローを、実際に動かしてはいない。
- `nextpnr-machxo2` が MachXO3 を扱えるか。
- QuickLogic の F4PGA の流れ、Efinix や Anlogic の非公式なオープンの取り組み。
- openFPGALoader の欄は、ベンダー単位の有無だけを見た。family ごとの書き込みの対応（SRAM、フラッシュ）は見ていない。

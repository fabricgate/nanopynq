# Tang Mega 138K Pro の DDR3 をオープンツールで使うための調査

2026-11-22。目的: Pro の DDR3 を、FPGA 内の回路から大きなメモリとして使う。足りないツールの機能は、フォークで足して上流に出す。

## 結論
- **上流の Apicula master(bd8c167、2026-11-19)と nextpnr main(15b77f5、2026-11-20)だけでは、GW5AST-138C で DDR3 の PHY を組めない。**
  - 足りないもの: PLL、HCLK/CLKDIV、DQS、DDRDLL、*_MEM。
  - 黙って誤った出力を出すもの: 138C の IOLOGIC(ODDR/IDDR)、IODELAY の遅延値、SSTL15 の IO_TYPE。
- **オープンツールで 138K の DDR3 を動かした前例は e-karge/gowin-ddr3(Apache-2.0)だけ。**
  - 方式: DLL-off(CK 125 MHz 以下)、I/O は LVCMOS15、ODDR/IDDR と IODELAY で読み出しを校正する。
  - 実績: Tang Console 138K で、CK 25/50/100 MHz が通った(作者の申告。試したのは 4〜16 MB)。
  - 要るツールの修正は、作者のフォークの次のブランチにある。上流には出ていない。
    - apicula: `gw5a-iob-regs`、`gw5a-iodelay`、`gw5a-pll`
    - nextpnr: 同じ名前の `gowin-gw5a-*`
- **Pro の DDR3 は 1 GiB、32 ビット幅**(SK hynix H5TQ4G63EFR-RDC × 2)。DDR3 の 71 本のピンは、FPGA のダイ上で Console と同じ IOB に出ている(chipdb で照合)。
- **方針(利用者と合意、2026-11-22)**:
  - まず e-karge 方式を土台に、段階 1(遅い PHY、CK 25 MHz)、段階 2(2to1 PHY、CK 100 MHz)と進める。
  - 2026-11-22 の時点: 段階 1 と、段階 2 の CK 50 MHz(PLL なし)まで済み。同梱の `ddr3` は 2to1 の PHY、CK 50 MHz(末尾の「段階 2」の節)。CK 100 MHz はまだ。
  - 将来は、DQS、DDRDLL、*_MEM を使う本来の速さを目指す。
  - 使い道は FPGA 内の回路。PC との通信(UART)は今のままでよい。

## ボードの事実
- DDR3: H5TQ4G63EFR-RDC × 2。1 個あたり 4 Gbit、x16、ROW 15 / COL 10 / BA 3。2 個でアドレス、コマンド、CK、CS、CKE、ODT を共有する。
- バンク: bank 6 が DQ/DM/DQS(44 本)、bank 7 がアドレス/コマンド/CK/RESET#。どれも左辺。BANK_VCCIO は 1.5。
- ピン(Sipeed `pro_ddr_test/src/pro.cst`。LiteX の platform とも一致):
  - A[0..14] = N1 R1 R2 N2 P1 T2 N4 U1 T4 T3 M1 P4 N3 U2 U5
  - BA[0..2] = M4 L5 K3
  - RAS# H2、CAS# H1、WE# J3、CS# L4、CKE L3、ODT J1、RESET# N8
  - CK/CK# M2/L2
  - DM[0..3] = F4 H9 E3 A3
  - DQS0 J4/H4、DQS1 H7/G7、DQS2 B5/A5、DQS3 C1/B1
  - DQ[0..7] = G4 J6 L8 G5 K7 J5 K8 K6
  - DQ[8..15] = E6 H8 H6 G8 D6 F8 G6 F7
  - DQ[16..23] = C4 F3 B4 E5 D3 D5 A4 D4
  - DQ[24..31] = E1 A2 G2 C2 F2 E2 G1 D1
- CK と DQS0〜3 は、138C では真の LVDS の対。Apicula にはエミュレートした LVDS が無いので、e-karge は P と N を別々の ODDR で駆動している。
- Sipeed の作例は、Gowin の DDR3 IP(暗号化済み)を 1:4、400 MHz で使う。プリミティブは IDES8_MEM、OSER8_MEM、OSER8、IODELAY、DQS、DDRDLL、CLKDIV、ELVDS。
- 確かめていないこと: -RDC の速度区分、VREF の配線(回路図)。

## ツールの対応状況(GW5AST-138C)

| 機能 | 状態 | 根拠 / フォーク |
|---|---|---|
| global クロック | BUFG が 1 個。配線できる pin が限られる | apicula #636、#549 |
| PLL | 欠落 | e-karge `gw5a-pll` |
| HCLK、CLKDIV、DHCEN、DCS | 欠落 | aquasock のフォーク `epic/gw5ast138c` |
| SSTL15 / SSTL15D | 誤り(`io_type_alias` が GW5 に無い名前にするので、フューズが立たない) | aquasock に修正のコミットがある |
| VREF、ODT、SSTL135 | 欠落 | — |
| ODDR / IDDR | 誤り(GW2A 用の属性を書き、`HAS_5A_IDES` も無い) | e-karge 5c7025a1 |
| OSER/IDES 4/8 | 欠落(FCLK を配線できない) | — |
| *_MEM、DQS、DDRDLL | 欠落(yosys の宣言だけ) | aquasock(作りかけ) |
| IODELAY | 静的な値が書かれない。動的な遅延は nextpnr がエラーにする | e-karge bf8fd42c |
| BSRAM | 実装はあるが、試験は軽いものだけ | apicula #463 |
| タイミングモデル | GW2A の仮の値 | nextpnr #1907 |

- 25A(Primer 25K)は、PLL、HCLK、OSER/IDES が上流にそろっている。IODELAY、SSTL、*_MEM の穴は 138C と共通。

## 先行例

| プロジェクト | 方式 | ツール | 実機 | ライセンス |
|---|---|---|---|---|
| e-karge/gowin-ddr3 | DLL-off、ODDR/IDDR と IODELAY、校正 | yosys + nextpnr + Apicula(フォーク) | Console 138K、CK 100 MHz | Apache-2.0 |
| LiteDRAM GW5DDRPHY | DQS/DDRDLL/_MEM、1:2 と 1:4 | Gowin IDE | Pro、DLL-off 100 MHz で誤り 0 | BSD-2 |
| aquasock/TinyVCMI | DQS/DDRDLL/_MEM | フォークした Apicula | training までは通る。読み書きは失敗 | — |
| Schoning-Labs/pipemig | OSER8/IDES8 と動的 IODELAY、300 MHz | Gowin IDE | Pro の 16 ビットで通る。32 ビットの校正は失敗 | GPL-3.0(考え方だけ参考にする) |

## 調べ方
- 2 つの調査を並行して走らせた。
- 読んだもの:
  - Sipeed の作例(cst、IP の設定、合成レポート)
  - LiteDRAM と litex-boards(コードと PR #402、#780、#867)
  - e-karge、pipemig、aquasock
  - Apicula master、nextpnr main
  - oss-cad-suite-20261115 の chipdb の中身
- ビルドと実機での実行は、まだしていない。

## 試作の結果(2026-11-22、使い捨て)
**結論: e-karge の遅い PHY(`ddr3_phy_slow`、`IOBFF=1`)は、Pro(B 版のシリコン)でもそのまま動いた。** CK 25 MHz、DLL-off、LVCMOS15。

- 校正は `calib ok delays 01 02 01 01` で、4 レーンとも通った。
- 100 万語(4 MB)を書いて読み返す試験は、40 秒で 23 回続けて誤り 0 件だった。1 GiB のうち、試したのは先頭の 4 MB だけ。
- ツール(どれも手元だけ。`~/tools/ddr3-138k`、WSL の `~/ddr3-138k`):
  - Apicula: e-karge/apicula `gw5a-iob-regs`(acaecb0)。
    - 138C の DB は、上流の CI と同じ Docker イメージ `pepijndevos/apicula:1.9.10.03` で作った。
    - 手元の Gowin 1.9.11.03 と 1.9.12.04 の .fse は、この版の Apicula の `fse_parser` でも、上流に近い b667bf2 でも読めなかった(`Unknown type -0x1`)。
  - nextpnr: e-karge/nextpnr `gowin-gw5a-iob-regs`(58896df3)。
    - WSL の Docker(Ubuntu 26.04、GCC 15)でビルドした。Ubuntu 24.04 の GCC 13 では `indexed_store` の iterator でコンパイルが止まる。
    - chipdb は上の Apicula から `gowin_arch_gen.py` と `bbasm` で作った。
  - yosys: oss-cad-suite-20261115。e-karge の SystemVerilog をそのまま読めた。
- 移し替え: 例の cst のうち、DDR3 のピンは IOB の名前で書かれているので、そのまま使えた。Pro に合わせて替えたのは、clk(P16)、led(J14)、uart_tx(P15)の 3 本だけ。
- 書き込み: nanopynq の `program_sram`(GW5A、MSB 先送り)。
- 気づいたこと: フォークの `gowin_pack` は、`-c` を付けても .fs を圧縮しなかった(34 MB)。理由は見ていない。

## 段階 1 の受け入れ(2026-11-22)
**結論: DQ を IO ブロックの IDDR で読むように直した `ddr3`(base.fs の sha256 3e54e435…)は、電源を入れた直後から 2 回続けて、1 GiB 全体の試験が誤り 0 件で通った。**
そのあと最終レビューの指摘で、校正に失敗したときは DRAM に届けないように直し、作り直した(d15bda0e…、57b6d78)。こちらも 1 GiB で誤り 0 件だった。ただし、電源は入れ直さずに書き込み直して試した。

### 最初のビルドの失敗
- 直す前のビルド(sha256 ed0a9425…、DQ を一般の論理のレジスタで取り込む)では、1 GiB の試験で誤りが出た。
  - 1 回で 110 件、4 MB ずつに分けると 129 件。全バンクにまばらに出た。
  - 全件が DQ15 だけで、1 のはずが 0 になっていた。
  - 誤った語を窓から読み直すと、正しい値だった。書き込みではなく、読み出しのときの誤り。
- 試作のビットストリームは、同じ基板、同じ時間帯に、4 MB を 142 回試して誤り 0 件だった。違いはビルドだけ。
- 取り込みのレジスタは、ピンから 40〜60 タイル離れて置かれていた。ピンからの遅延には制約が無く、nextpnr も 12 MHz を目標にしている。このため、取り込む時刻がビルドとピンごとに変わる。試作のビルドでも同じくらい離れていたので、距離だけでは説明しきれない。実際の配線遅延は測っていない。

### 直し方
- e-karge の `ddr3_phy_slow` に `IDDR` パラメータを足した(a1fa2a3)。
  - DQ を IO ブロックの IDDR で読む。
  - Gowin の GW5A の IDDR は、出力が 2 クロック遅れる(シミュレーションのライブラリによる)。その分、取り込みの位置をずらす。
  - 既定値 0 では e-karge の版と同じ動きになる。2 つの取り込み方が遅延 0〜7 で同じビートを読むことを、Icarus で確かめた。
- 138C の IDDR を正しく読むには、Apicula に `HAS_5A_IDES` が要る。
  - e-karge/apicula 5c7025a にあるが、上流には入っていない。
  - 無いと、ビルドはエラーなく終わるのに、読み出しが全部 0 になり、校正が失敗した(実機で確認)。
  - フォークのブランチ `gw5a-iob-regs` に cherry-pick した(7347630、作者は Eric Karge)。B ピンの IO ロジックの部分は、上流の #639 ですでに入っている。

### 実機の結果(Windows、D2XX)

| ビルド | 条件 | 校正(遅延) | 1 GiB | 時間 |
|---|---|---|---|---|
| 直す前(ed0a9425…) | 電源を入れた直後 | ok(1 1 1 1) | 誤り 110 件 | 432.5 s |
| IDDR、seed 1(3e54e435…) | 書き込み直し | ok(1 1 1 1) | 0 件 | 443.8 s |
| IDDR、seed 2(e745b670…) | 書き込み直し | ok(1 1 1 1) | 0 件 | 443.9 s |
| 同梱(3e54e435…) | 電源を入れた直後 1 回目 | ok(1 1 1 1) | 0 件 | 443.8 s |
| 同梱(3e54e435…) | 電源を入れた直後 2 回目 | ok(1 1 1 1) | 0 件 | 測れず(下の注) |
| 同梱(d15bda0e…、校正失敗の扱いを直した版) | 書き込み直し | ok(1 1 1 1) | 0 件 | 443.9 s |

- どの回も、窓の読み書き(先頭、真ん中、末尾)は正しかった。誤りを 1 つ入れた試験(1 MB)は、真ん中の 1 件を報告した。
- 書き込みは約 17 s(34.7 MB の .fs)。
- 速さは、書き込みと読み出しを合わせて約 4.8 MB/s(1 回のアクセスで 32 ビットの 1 語)。
- 注: 電源を入れた直後の 2 回目は、1 GiB の試験の途中で PC と基板のシリアル通信が切れた(Windows の `WriteFile failed`、アクセス拒否)。原因は分かっていない。
  - FPGA の中の試験は走り続けていた。書き込み直さずにレジスタを読むと、1 回分を終えて誤り 0 件だった。
  - 窓の読み書きと誤りを入れた試験は、同じ電源投入のまま、あとで確かめ直した。

## 8 語まとめて書く(2026-11-22)
**結論: master b(自己試験)が 1 回のアクセスで BL8 の 8 語を運ぶようにした `ddr3`(base.fs の sha256 7b3e757f…)は、1 GiB の試験が誤り 0 件で、書き込み 35.9 MB/s、読み出し 41.9 MB/s だった。1 GiB の試験は 444 s から 55.5 s になった。**
- e-karge の制御器は、1 回の書き込みで BL8 の 8 語を送るのに、同じ語を 8 つ並べて 7 語をマスクしていた。`burst`、`din_burst`、`be_burst` を足し、8 語を 1 回で書けるようにした。読み出しは、もともと 8 語を読んでいた(`dout_burst`)。
- CK(25 MHz)と、1 回ごとにページを閉じる動きは変えていない。1 回のアクセスにかかる時間はほぼ同じで、運ぶ量が 8 倍になった(段階 1 の約 4.8 MB/s は、書き込みと読み出しを合わせた値)。
- 速さは自己試験のレジスタ(`WR_CYCLES`、`RD_CYCLES`、50 MHz のクロック数)から出した。リフレッシュの時間も含む。
- nextpnr の最大周波数は 60.85 MHz(50 MHz で動かす)。

### 実機の結果(Windows、D2XX)

| 条件 | 校正(遅延) | 1 GiB | 時間 | 書き込み / 読み出し |
|---|---|---|---|---|
| 書き込み直し 1 回目 | ok(1 1 1 1) | 0 件 | 55.5 s | 35.9 / 41.9 MB/s |
| 同じ状態で 2 回目 | ok(1 1 1 1) | 0 件 | 55.5 s | 35.9 / 41.9 MB/s |
| 電源を入れ直した直後 | ok(1 1 1 1) | 0 件 | 55.5 s | 35.9 / 41.9 MB/s |

- どの回も、誤りを 1 つ入れた試験(1 MB)は真ん中の語(バイト 0x80000)の 1 件を報告し、窓(master a、1 語ずつ)の書き込みと読み出しは正しかった(2 回目は試験だけ)。

## 段階 2: 2to1 の PHY、CK 50 MHz(2026-11-22)
**結論: e-karge の `ddr3_phy_2to1`(`GW5A=1`)に替えた `ddr3`(base.fs の sha256 f2d03e4e…)は、1 GiB の試験が誤り 0 件で、書き込み 69.4 MB/s、読み出し 56.7 MB/s だった。1 GiB を 30 パス続けても(約 17 分)誤り 0 件だった。1 GiB の試験は 55.5 s から 34.5 s になった。**
- CK = clk = 50 MHz(ボードのクロックのまま、PLL なし)。制御器は毎クロック動く(今までの PHY は 2 クロックに 1 回)。読み出しは DQ を IODELAY と IDDR で取り、較正は 1 レーン 64 段(6 ビット)。
- 書き込みは約 2 倍になった。読み出しは、PHY が READ から 18 クロック後にデータを出す(`RD_WAIT`)ので、伸びが小さい(41.9 → 56.7 MB/s)。どちらも設計の確認で数えた見込み(約 69 / 56 MB/s)どおり。
- nextpnr の最大周波数は 59.69 MHz(50 MHz で動かす)。

### ツール
- Apicula `gw5a-iob-regs` に e-karge の bf8fd42(GW5A の IODELAY、static と dynamic の遅延)を載せた: 53c6866。ぶつからなかった。
- nextpnr `gw5a-iob-regs` に e-karge の 54ee443a(GW5A の IODELAY の dynamic の遅延と入力の遅延のピン)を載せた: 0171b1da。上流の 420ed448(dynamic の遅延で黙って落ちずにエラーにする)とぶつかった。dynamic の遅延は e-karge のとおり使えるようにし、Apicula が扱わない adaptive の遅延(ADAPT_EN)は 420ed448 のとおりエラーにした。
- このツールで段階 1 の同梱(slow PHY、7b3e757f…)を作り直すと、ビット単位で同じだった。
- yosys は、e-karge の `.sv` を `read_verilog -defer` で読む。2to1 の PHY には GW2A 用の枝があり、既定のパラメータ(`GW5A=0`)で先に組み立てると、GW5A の部品表に無い IODELAY の口(SETN)で止まるため。

### 試作(使い捨て)
- e-karge の `examples/tang-mega-138k-2to1-50mhz` を Pro の cst で作った(最大周波数 123.17 MHz)。`calib ok delays 23 23 23 23`(16 進、35)のあと、4 MB の試験が 2 分間に 111 パス、誤り 0 件だった。

### 実機の結果(Windows、D2XX)

| 条件 | 校正(遅延) | 1 GiB | 時間 | 書き込み / 読み出し |
|---|---|---|---|---|
| 書き込み直し 1 回目 | ok(35 35 35 35) | 0 件 | 34.5 s | 69.4 / 56.7 MB/s |
| 同じ状態で 2 回目 | ok(35 35 35 35) | 0 件 | 34.5 s | 69.4 / 56.7 MB/s |
| 同じ状態で 30 パス | ok(35 35 35 35、終わった後も同じ) | 0 件 | 1032.9 s | |
| 電源を入れ直した直後 | ok(35 35 35 35) | 0 件 | 34.5 s | 69.4 / 56.7 MB/s |

- 誤りを 1 つ入れた試験(1 MB)は真ん中の語の 1 件を報告し、窓(master a)の書き込みと読み出しは正しかった(書き込み直し 1 回目と、電源を入れ直した直後)。
- 50 MHz では、読み出しの細かい遅延(36 タップ × 7 段、約 3.15 ns)が 1 サンプル(10 ns)の約 3 割にしか届かない。較正で通った窓の幅は読めないので、余裕は数字では分からない。長く回す試験で代えた(利用者の判断)。

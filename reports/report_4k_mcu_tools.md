# Tang Nano 4K の M3 ファームウェアに使える Gowin の道具の調査（2026-11-06）

## 結論
- **goConfig は EMCU の設定には使えない。** goConfig は、FPGA の設定用フラッシュを動いたまま書き換える（バックグラウンド書き込み）ための IP で、M3 にもユーザーフラッシュにも触らない。しかも GW1NS-4C / GW1NSR-4C には対応していない（UG290 の表 3-5 に「Not Supported」）。以前のメモ「TN715 / TN726 は GW1NS-4C に当てはまらない」は正しかった。
- **EMCU の構成を決めるのは、IDE の Gowin_EMPU(GW1NS-4C) IP。** SRAM の大きさ、UART / GPIO、ファブリックへの拡張バス（APB2 のマスター 12 本、AHB2 のマスターとスレーブ）を選ぶ。生成される回路は暗号化される。私たちは Apicula で EMCU のプリミティブを直接置く（3.8 で、`emcu-blinky` で実機の動作を確認済み）ので、この IP は配線の参考にとどめる。
- **ファームウェアは手元の道具で作れる。** GMD 2025.01 に xPack の arm-none-eabi-gcc 13.3.1 が入っていて、`bin` を PATH に足せばコマンドラインから使える。デバイスのヘッダー、startup、リンカースクリプトは EMPU SDK V2.0 にある（GMD には入っていない）。
- **書き込みの道は 3 つ**:
  1. openFPGALoader `--mcufw`（3.8 で実機の動作を確認済み）
  2. Gowin Programmer の MCU Mode（操作 27〜30。ビットストリームとファームウェアを一緒に指定する）
  3. OpenOCD の `gowin_cm3` ドライバ（操作 23 で JTAG を M3 に切り替えてから）

  2 と 3 は、このボードのデバッガー（BL702）で動くか、まだ確かめていない。
- **Gowin の道具で、ユーザーフラッシュを読み戻すことはできない**（SUG502 に「セキュリティのため対応しない」）。ファブリックからも読めない（report_4k_peripherals.md 3.8）。読むには、M3 のコードでフラッシュを読み、UART か拡張バスで外に出すしかない。
- **M3 のデバッグは、JTAG を M3 に渡して OpenOCD で行う形**（DAP の IDCODE 0x4BA00477、JTAG のみ。SWD の根拠は無い）。BL702 で動くかと、FPGA の JTAG への戻し方は分かっていない。

## 1. 調べたもの
出典の略号は report_4k_peripherals.md と同じ。
- **[me]**: 私が一次資料で確かめた
- **[agent]**: 調査担当のエージェントが読んだもので、私は読み直していない

調べた範囲:
- Gowin MCU Designer（GMD）2025.01（`GMD_2025.01_win`）
- Gowin Programmer 1.9.11.02（build 2518）
- Gowin IDE 1.9.11.03 Education（`ipcore`、`doc`、同梱の Programmer の文書）
- Gowin_EMPU(GW1NS-4C) V2.0 の SDK

どれも読むだけで、ボードには触っていない。Gowin のファイルはリポジトリに写していない（以下の文は要約）。

## 2. goConfig
| 版 | 対応デバイス（ipspec） | 書き換えるもの |
|---|---|---|
| goConfig JTAG / SPI | GW1N-2C、GW1NR-2C、GW1N-1P5C | 内蔵の設定用フラッシュ |
| goConfig UART | GW1N(R)-9 / 9C、GW2A、GW5A | 外付けの SPI の設定用フラッシュ |
| goConfig I2C | ipspec のデバイスの一覧は空。DLL の中の名前は GW1N-1P5C / 2C、GW2AN など | 設定用フラッシュ |

- どの版の資料にも GW1NS の名前は無い [agent]。
- UG290 の表 3-5 で、GW1NS-4C / GW1NSR-4C / GW1NSER-4C のバックグラウンド書き込みは「Not Supported」[agent]。
- UG290 の脚注: M3 を使うときは、JTAG のバックグラウンド書き込みが使えない [agent]。
- SUG100 の表 4-10: GoConfig の設定値は C 版の GW1N-2 / 1P5 と GW2AN にだけあり、GW1NS-4C は表に無い [agent]。
- Programmer の「GoConfig IP Mode」は、goConfig の IP を入れた設計を確かめるためのもの [agent]。

## 3. EMCU の構成（IDE の Gowin_EMPU(GW1NS-4C) IP と SDK）
- **IP**（`ipcore/gowin_empu_gw1ns4`、対応は GW1NS-4C / GW1NSR-4C / GW1NSER-4C）[agent]
  - 選べるもの: SRAM の大きさ（8 KB = SDPB 4 個、16 KB = 8 個。2 / 4 KB の対応は未確認）、UART0 / UART1、GPIO（入出力両用にもできる）、TPIU、ユーザー割り込み 6 本、RTC、SPI、I2C、APB2 のマスター 1〜12（それぞれ別の PSEL）、AHB2 のマスター（M3 → ファブリック、0xA0000000）、AHB2 のスレーブ（ファブリック → M3 のバス）。
  - ブートやフラッシュの配置、「MCU モード」の設定は無い。
- **SDK の参考回路**（開発キット DK_START_GW1NSR4C 用。Tang Nano 4K とはピンが違う）
  - [me] 平文のネットリスト `gowin_empu.vo` で確かめたこと:
    - DAP のピンは固定されている（SWDITMS = GND、NTRST = VCC）。
    - `MTXREMAP` は 1111。
  - [agent] PORESETN / SYSRESETN は reset_n につながる（nextpnr はこれらを切り離す。つないでも効かない）。
  - [agent] FLASH256K のつなぎ方:
    - XE と YE は reset_n。
    - SE とアドレスは、ソフトの状態機械から出る。
    - DOUT は EMCU の HRDATA へ。
    - PROG / ERASE / NVSTR / DIN は GND（M3 は自分のフラッシュを書き換えられない）。
  - [agent] M3 の SRAM は、SRAM0 のポートにつないだ SDPB で作る。
- **メモリーの割り当て**（[me] SDK の `gw1ns4c_flash.ld` と `gw1ns4c.h`）

| 領域 | アドレス |
|---|---|
| フラッシュ | 0x0、32 KB |
| RAM | 0x20000000、16 KB（IP の SRAM の大きさと合わせる） |
| APB1 | 0x40000000（TIMER0 +0x0、TIMER1 +0x1000、UART0 +0x4000、UART1 +0x5000、RTC +0x6000、WDOG +0x8000 [agent]） |
| APB2 | 0x40002000（I2C +0x0、SPI +0x200 [agent]、**APB2 マスター 1 が +0x400**、以降 0x100 おきに 12 本） |
| AHB1 | 0x40010000（GPIO0 +0x0、SYSCON +0xF000 [agent]） |
| **AHB2（ファブリック）** | **0xA0000000** |

- 速さ: SDK の `system_gw1ns4c.c` は、コアのクロックを既定で 150 MHz としている [agent]。`emcu-blinky` は FCLK に 27 MHz を入れていて、LED の点滅はほぼ 1 秒周期だった（ユーザーが確認）。どのクロックで動いているかは、確かめる必要がある。

## 4. ファームウェアを作る道具（GMD 2025.01）
- [me] GMD の中身は、普通の Eclipse Embedded CDT 2024-12 に次のものを足しただけ。
  - xPack の gcc / gdb / make
  - Gowin Programmer 1.9.11.02
  - Gowin の手が入った OpenOCD 0.12
- [agent] Gowin 独自のプラグインはリンクやランチャーだけで、BSP やプロジェクトの雛形は無い。SDK は別に入手する前提。
- [me] コンパイラーは `toolchain/gowin/gcc_arm/bin/arm-none-eabi-gcc.exe`（13.3.1 20240614）。
  - [agent] 同じ場所に gdb 14.2.90、objcopy、size があり、make 4.4.1 は `toolchain/gowin/build_tools/bin` にある。
  - [agent] PATH に足すだけで、Git Bash からフルパスで呼べた。
- [me] OpenOCD の `target/gowin_cm3.cfg`:
  - DAP（irlen 4、IDCODE 0x4BA00477）を JTAG でつなぐ。
  - 0x0 から 32 KB のフラッシュを `gowin_cm3` ドライバで扱う。
  - work area が 0x0（フラッシュの上）になっている。不思議な設定で、使うときは 0x20000000 に変える必要があるかもしれない（推定）。
- [agent] ボードの設定ファイル（`gowin_ftdi_dual_m3.cfg` など）は FT2232H（0403:6010）で、BL702 と同じ VID / PID。ただし ADBUS4〜6 を動かす設定なので、BL702 でそのまま動くかは分からない。

## 5. 書き込みと読み戻し（Gowin Programmer）
- [me] `programmer_cli.exe --help` で確かめたこと:
  - デバイス名 `GW1NSR-4C`。
  - 操作: 23「Connect to JTAG of MCU」、27〜30「Firmware Erase / Program / Verify」（27 は Securely）。
  - `--mcuFile`（ファームウェアの .bin）。
  - `--filestransform 8`「GW1NS4C の M3 の .bin を .fs に足す」。
  - ケーブルの番号 4 が「USB Debugger A」。
- [agent] SUG502 §3.4.7: MCU Mode でファームウェアを書くときは、ビットストリームとファームウェアの両方を指定する。ファームウェアを読む操作は無い。
- [agent] SUG502 §3.12: ユーザーフラッシュは書けるが、セキュリティのため読み戻しには対応しない。
- [agent] UG290 §7.2: 内蔵フラッシュは、書くときに「読める」印を付けたときだけ読める。起動用の印（普通の書き込み）では読めない。
- [agent] Programmer の中には「embFlash Read Only」という内部の操作があるが、コマンドラインの一覧には無く、使えるかは分からない。
- ファームウェアがフラッシュのどこに置かれるか（Programmer 側の値）は、ファイルからは分からなかった。openFPGALoader はページ 0x380 に置く（report_4k_peripherals.md 3.8）。
- ケーブル: BL702 が Programmer に認識されるか（`--scan-cables`）は試していない。FTDI の D2XX ドライバを使うので、openFPGALoader が使う WinUSB / libusb とぶつかるかもしれない（推定）。

## 6. 調査担当の報告のうち、採らなかったもの
- 「SDK のネットリストでは、FLASH256K の DOUT がふつうのファブリックの信号なので、ファブリックから読めるはず」という推定は採らない。
  - ネットリストの接続は論理上のもの。
  - 実機では、M3 が正しく動いている最中でも、ファブリック側の DOUT はすべて 0 だった（report_4k_peripherals.md 3.8 の盗み見）。

## 7. 設計の前に決めること
1. **M3 とファブリックの受け渡し**
   - 案 A: APB2 のマスター（0x40002400〜）。ファブリック側の作りが簡単。
   - 案 B: AHB2 のマスター（0xA0000000）。
   - 案 C: UART。`emcu-blinky` は UART にピン 44 / 46 を使うが、これはカメラの I2C と共用。

   どれでも、今の JTAG のブリッジと同じバスにつなげば、ホストから読める。
2. **書き込みの道**: openFPGALoader `--mcufw`（確認済み）を使うか、Programmer / OpenOCD を試すか。
3. **デバッグを用意するか**: 操作 23 と OpenOCD を、BL702 で試すか。
4. **SDK の扱い**: SDK のヘッダーやドライバは Gowin の著作物。リポジトリに入れずに、ビルドのときに SDK の場所を指すか、必要なレジスターのアドレスだけを自前のヘッダーに書くか。
5. **BSRAM の割り当て**: M3 の SRAM は SDPB で作る（16 KB なら 8 個、8 KB なら 4 個）。チップの BSRAM は 10 個で、camhdmi は 2 個使う。

## 8. 実験: Apicula で EMCU の構成を作る、Programmer で書く（2026-11-06）
### 8.1 Apicula で、IP の選択肢をすべて作れるか
- [me] Apicula の chipdb（`fse_create_emcu`）は、IP の選択肢が使う EMCU のピンを、すべて配線できるピンとして持っている。
  - UART0/1、GPIO（16 本の入力・出力・出力の有効）、SRAM0（アドレス 13 ビット、データ 32 ビット、バイトごとの書き込み）
  - AHB2 のマスター（TARGEXP0）一式、AHB2 のスレーブ（INITEXP0）一式、APB2（PSEL、PADDR 12 ビット、データ 32 ビット）、GPINT、RTC のクロック

  配線できないのは、リセット（GSR）、DAP の入力、MTXREMAP だけ（nextpnr が切り離す）。
- [me] IDE の「APB2 のマスター 12 本」は、プリミティブの中では 1 本の APB で、PADDR[11:8] = 4〜15 をファブリック側でデコードしたもの（上流の `emcu-with-apb-blinky.v` の `psel1` と、SDK のアドレス 0x40002400 + 0x100 × n から）。
- 道具の確認: GMD の gcc と SDK（パスで参照、写していない）で自前のファームウェアを作り、`openFPGALoader --mcufw` で書いた。LED が毎秒約 5 回で点滅した（ユーザーが確認）。SysTick を 27 MHz として作ったので、**M3 のコアは FCLK = 27 MHz で動いている**（SDK の既定の 150 MHz は、この配線には当てはまらない）。
- 試験の top（Apicula。JTAG のブリッジ、EMCU、FLASH256K を含む）:
  - SRAM 16 KB（4096 語、バイトごとに推論した RAM で、BSRAM 8/10）
  - GPIO（出力 0 を LED へ、入力 = 0xA55A）
  - UART0（ファブリック内で TX を RX に折り返す）
  - APB2 のスロット 1〜12
  - AHB2 のスレーブ（レジスター 4 つ）
- 試験のファームウェアと結果:

| 調べたこと | 結果 |
|---|---|
| 0x20000100〜0x20003000 のメモリーテスト（8 KB の境目をまたぐ。スタックはその上） | 誤り 0 |
| UART0 の 4 バイトの折り返し | 一致 |
| GPIO の入力 | 0xA55A |
| AHB2 に 4 語を書いて読む | 一致 |
| APB2 の 12 スロットに書いて読む | 一致（ホストからも `c0de0001`〜`c0de000c` が読めた） |
| 結果のビット | 0x3F（全部合格） |
| 心拍 | 毎秒 2 ずつ増えた |

- **結論: IP の選択肢（SRAM の大きさ、UART / GPIO、APB2 の 12 本、AHB2 のマスター）は、すべて Apicula で手で配線して実機で動いた。** AHB2 のスレーブ（INITEXP0）は試していない。
- 途中の誤り 1: 最初の版は、FLASH256K の DOUT をどこにもつながなかったので、yosys が FLASH256K を消した（上流のように `TARGFLASH0HRDATA` につなぐと残る。nextpnr はその接続を切るが、セルは残る）。
- 途中の誤り 2（`flash_polarity.py` を直した）: 角のタイル R1C1 には LUT が無い（F の配線はフラッシュの DOUT など）。なのに、「LUT が出てこない = INIT 0xFFFF = 1」として数えていた。DOUT のあるタイルの F の配線は「不明」として出すように直した。1K / 9K の結果は、ふつうのロジックのタイルで、0 と 1 の両方のヒューズを読んで確かめたので、変わらない。

### 8.2 フラッシュを使わない Apicula の設計（新しい疑問）
- Gowin の IDE は、フラッシュを使わない設計でも、PROG / ERASE / NVSTR / INUSEN を VSS につなぐ（IDE の何も無い設計で確かめた）。
- Apicula は、FLASH256K が無いと、これらを既定の配線のまま残す（値は不明）。同梱の土台も、今までの 4K の設計も同じ。
- 確かめたこと: フラッシュに `emcu-blinky` と 5 Hz のファームウェアがある状態で、同梱の土台を SRAM で 30 秒ほど動かした。そのあと電源を入れ直すと、5 Hz の点滅が続いていた（ユーザーが確認）。この時間では、フラッシュは壊れていない。長い時間の保証ではない。

### 8.3 書き込み（a）: Gowin Programmer
- `programmer_cli --scan-cables L` で、BL702 が「Gowin USB Cable(WINUSB)」として見えた（`F` では「USB Debugger A」として見えたが、操作 0 で何も返さなかった）。
- 操作 0（Read Device Codes）、ケーブル番号 5: IDCODE 0x0100981B、usercode 0xF666（フラッシュの土台）。
- 操作 30（Firmware Erase, Program, Verify）、ケーブル番号 5、`--fsFile` に上の試験のビットストリーム、`--mcuFile` にファームウェア: ビットストリームとファームウェアの両方で「Verify Success」、「Program and Verify firmware successfully」（25 秒）。そのまま起動した設計から、8.1 の結果をブリッジで読めた。**（a）は使える。**

### 8.4 書き込み（c）: OpenOCD（M3 のデバッグ）
- `openFPGALoader -b tangnano4k --conmcu` は、JTAG の命令 0x7A（`SWITCH_TO_MCU_JTAG`）を送るだけ（ソースの `connectJtagToMCU`）。FPGA は再構成されない。
- OpenOCD は GMD のもの（0.12、Gowin が手を入れた版）を使った。インターフェースの設定は Gowin のもの（ADBUS4〜6 を動かす `0x0048 0x007b`）を使わずに、openFPGALoader の `ft2232` と同じ設定で自作した（`tools/p0/emcu4k/bl702.cfg`: チャネル A、`layout_init 0x0008 0x000b`）。ターゲットは `target/gowin_cm3.cfg`。work area は 0x20000000 に移した。
- **デバッグ: 使える。**
  - DAP 0x4BA00477 が見え、「Cortex-M3 r2p1」と表示された。
  - 止める、レジスターを読む、メモリーを読む（0x0 のベクター表、0xA0000000 の AHB2 のレジスター）、`reset run` で動かし直す、ができた。
- **読み戻し: できる（チェックリストの 8 の目的）。** M3 のバス越しに 32 KB を読んだ。
  - 先頭の 1532 バイトは、Programmer で書いたファームウェアと完全に一致した。残りは 0xFF（M3 から見ると、消えた状態は 0xFF）。
  - 注意: `dump_image` で 32 KB を一度に読むと、BL702 が `mpsse_flush()` で止まる。256 バイトずつの `mdw` なら止まらない（`tools/p0/emcu4k/ocd_readback.sh`）。
- **フラッシュへの書き込み: できない。** `flash write_image` で OpenOCD がセグメンテーション違反で落ちる（`-d3` で、書き込みの直前に落ちていることを確かめた）。
  - バイナリの中の `gowin_cm3` ドライバには `flash_bank_command`、`probe`、`auto_probe` しか無く、消去と書き込みの処理が無い（同じバイナリの aducm360 には `flash_write_code` がある）。
  - フラッシュは変わらなかった（読み戻して、元のファームウェアのまま）。
- **JTAG を FPGA に戻すには、電源を本当に切る必要がある。**
  - 1 回目の挿し直しでは戻らなかった。M3 も止まったままだった（DHCSR = 0x00030003。電源が入り直していれば、デバッグも止まる設定も消える）。
  - USB を抜いて 10 秒待つと戻った（IDCODE 0x0100981B、usercode 0xF8BF = Programmer で書いた試験のビットストリーム）。そのまま起動した M3 は、8.1 の結果を返した（`emcu_cfg_check.py` で PASS）。

### 8.5 まとめ（2026-11-06）

| やりたいこと | 使える道 | 確かめたこと |
|---|---|---|
| EMCU を構成する | Apicula で EMCU のプリミティブを手で配線する（`tools/p0/emcu4k/emcu_cfg_top.v`） | SRAM 16 KB、GPIO、UART0、APB2 の 12 本、AHB2 のマスター。実機で全部合格 |
| ファームウェアを作る | GMD の gcc と SDK（パスで参照。`tools/p0/emcu4k/build_fw.sh`） | 実機で動いた。コアは 27 MHz |
| 書き込む | openFPGALoader `--mcufw`、または Gowin Programmer の操作 30（ケーブル番号 5 = WinUSB） | 両方とも実機で動いた。Programmer は書いた後に照合もする |
| デバッグする | `openFPGALoader --conmcu` と OpenOCD（`bl702.cfg`） | 止める、読む、動かし直す |
| フラッシュを読み戻す | 上の OpenOCD で、256 バイトずつ読む | 32 KB を読み、書いたものと一致 |
| OpenOCD でフラッシュに書く | できない（ドライバに書き込みが無く、落ちる） | — |

- 今のボードの内蔵フラッシュ: 試験のビットストリーム（`emcu_cfg_top.v`、usercode 0xF8BF）と試験のファームウェア（`emcu_cfg.c`）。電源を入れると M3 が動き、LED が 2 Hz で点滅する。土台はいつもどおり SRAM に載せて使える。
- 残る疑問: Apicula でフラッシュを使わない設計は、PROG / ERASE / NVSTR / INUSEN を既定の配線のまま残す（8.2）。30 秒の試験では壊れなかったが、Gowin の IDE と違う。

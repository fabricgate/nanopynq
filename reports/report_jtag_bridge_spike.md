# JTAG ブリッジの検証（設計書 4.11）2026-10-30

## 結論
- **（2026-11-04 更新）enable_er2_o の配線名 Q1 を実機で確かめた（14章）。上流の Apicula に PR を出した（https://github.com/YosysHQ/apicula/pull/578 、本文は `reports/draft_apicula_pr_gw1ns4_jtag.md`）。**
- **（2026-11-03 更新）オープンなツールだけで、4K の GW_JTAG が実機で動いた（12章）。** Apicula の写しに 4K の項目を足し、nextpnr の chipdb を作り直して、yosys + nextpnr + gowin_pack で作ったビットストリームで、IR 0x42 の 32 ビットの往復が正しく通った。上流への取り込みは未提案。
- **（2026-11-03）4K の GW_JTAG は実機で動いた（9〜10章）。** Gowin の配置配線を使えば、ユーザー用の命令 0x42 でホストから 4K の回路に届く。位置は R1C1、設定ビットは既知の CFG の属性。オープンなツールだけで使うには、Apicula と nextpnr への追加が残る（11章）。
- **（2026-10-30 時点）今のオープンなツールでは、Tang Nano 4K と 9K で JTAG ブリッジは作れない。** Apicula の最新のソース（2026-10-29 の e88d450）でも、`GW_JTAG` を扱えるのは GW2A-18C（Tang Nano 20K）だけ。GW1NS-4（4K）と GW1N-9C（9K）は「未実装」のまま。
- **ホスト側は、自前の小さなドライバで動いた（4章）。** 最初に試した pyftdi では読めなかった: Windows の WinUSB（Zadig 後）のまま、Python（pyusb + pyftdi + oss-cad-suite の libusb-1.0.dll）から 4K のデバッガを開き、MPSSE のコマンドを送るところまでは動いた。ただし IDCODE は正しく読めなかった。BL702 のファームウェアが、pyftdi の使う MPSSE のコマンドの一部を受け付けず、「Bad Command」（0xFA）の応答を返している、と推定している。
- **20K では候補として残る。** 上流の Apicula には GW2A-18C 向けの `GW_JTAG` がある。ただし pip 版の YoWASP（Apicula 0.32 固定）には入っておらず、nextpnr 側の対応も未確認。

## 1. Apicula の上流の対応状況
`git clone --depth 1 https://github.com/YosysHQ/apicula`（HEAD e88d450、2026-10-29）を読んだ:
- `apycula/chipdb.py` の `fse_create_jtag`: `if device not in {'GW2A-18C'}: return`（コメント `# XXX`）。`GW_JTAG` の部品を作るのは GW2A-18C だけ。
- `apycula/gowin_pack.py`: 基底クラスの `get_GW_JTAG_fuses` は `error_not_implemented_method('get_GW_JTAG_fuses')`。実装があるのは `class GW2A_18C`（"Tangnano20k board"）だけで、`JTAG_ER1` と `JTAG_ER2` を `USED` にする。
- 手元の pip 版（Apicula 0.32）には `GW_JTAG` の文字列自体が無い（`JTAG_AS_GPIO` のみ）。

## 2. Python から 4K の JTAG を読む
スクリプト: `tools/p0/jtag_idcode.py`（パッケージの依存には入れていない。`uv run --with pyftdi` で実行）

```
PATH="$OSS/lib:$PATH" uv run --with pyftdi python tools/p0/jtag_idcode.py --expect 0x100981b
idcode 0x03fa2cfa
expected 0x0100981b
```
- 6 MHz、1 MHz、300 kHz のどれでも、`reset()` → `read_dr(64)` は毎回 `0xfa07fa2cfa` を返した（安定して同じ値）。
- 期待値は openFPGALoader が読んだ `0x0100981b`。
- 応答に `0xFA` が繰り返し現れる。FTDI の MPSSE は、知らないコマンドに `0xFA <コマンド>` を返す。このため、BL702 のエミュレーションが pyftdi の送るコマンドの一部に対応していない、と推定している（未確認。生の送受信は記録していない）。
- USB の記述子: bcdDevice 0x0500（FT2232C/D として名乗る）、bcdUSB 2.0、両インターフェースとも最大パケット 64 バイト。
- openFPGALoader は同じ経路で IDCODE を読めている（report_p0_tangnano4k_windows.md 2章）ので、使うコマンドを絞れば読める見込みはある。

## 3. ここから先の選択肢（3 は 4章で試した）
1. **20K を待つ**: 上流の Apicula に `GW_JTAG` があるので、YoWASP の版が上がれば（または上流に依頼すれば）回路側は作れる。ホスト側は、BL616 のエミュレーションで同じ問題が出るかを確かめる必要がある。
2. **4K と 9K の `GW_JTAG` を Apicula に貢献する**: GW1NS-4 と GW1N-9C で JTAG_ER1/ER2 の設定ビットを調べる作業（Gowin の IDE でのファジングが要る見込み）。規模は大きい。
3. **ホスト側の自前 JTAG ドライバ**: openFPGALoader と同じく、BL702 が受け付ける MPSSE のコマンドだけを使う小さなドライバを書く。2 や 1 とは独立に進められる。

## 確認できていないこと
- pyftdi が実際に送ったコマンド列（pyftdi のソースと生のバイト列は見ていない。4章で、読むだけのコマンドが拒否されることは確かめた）
- nextpnr-himbaechel（YoWASP 0.11.1）の `GW_JTAG` 対応
- 9K と 20K のデバッガ（BL702 / BL616）で、MPSSE の対応範囲が 4K と同じか

## 4. 追試: 最小の自前 MPSSE ドライバ（2026-10-30）
スクリプト: `tools/p0/jtag_mpsse_min.py`（pyusb だけを使う。使うコマンドは 0x85、0x86、0x80、0x4B、0x39、0x87 のみ）

```
PATH="$OSS/lib:$PATH" uv run --with pyusb python tools/p0/jtag_mpsse_min.py --expect 0x100981b
idcode 0x0100981b
200 IDCODE reads in 0.117 s -> 1704 reads/s
```
- **Windows の WinUSB のまま、Python から 4K の JTAG で IDCODE を正しく読めた**（openFPGALoader と同じ値）。JTAG は 1 MHz（FT2232D として名乗るので、12 MHz の基準クロックを分周）。
- 1回の読み出し（TMS の操作 4回 + 32 ビットのシフト + 応答の待ち）で、毎秒約 1700 回。USB の往復が支配的とみられる（推定）。

### BL702 が受け付けないコマンド（同じスクリプトの `Mpsse` で1つずつ送って確かめた）
| コマンド | 意味 | 結果 |
|---|---|---|
| 0x28 / 0x2C | 読むだけ（バイト単位） | 拒否（`0xFA` + コマンド。後に続く引数も別のコマンドとして拒否される） |
| 0x2A / 0x2E | 読むだけ（ビット単位） | 拒否 |
| 0x39 / 0x3B | 書きながら読む（バイト / ビット） | 応答あり |
| 0x4B / 0x6B | TMS（読み無し / 読み有り） | 応答あり |
| 0x81 / 0x83 | GPIO の読み取り | 応答あり |
| 0x8A / 0x8D / 0x97 | FT2232H 専用の設定 | 拒否の応答は無し（受け付けたか無視したかは不明） |

- 応答が1つ後ろの試験にずれて届くことがあったので、上の表は「拒否の応答 `0xFA <コマンド>` が、どのコマンドについて返ったか」で判定している。
- pyftdi の `read_dr` は「読むだけ」のコマンドを使うので、BL702 では読めなかった、と説明がつく（pyftdi のソースは読んでいない。未確認）。

### 意味すること
- PC 側の JTAG ドライバは、「書きながら読む」コマンドだけを使えば自前で書ける。規模は小さい（このスクリプトで約 100 行）。
- 残る障害は FPGA 側（`GW_JTAG` が 20K のチップでしか使えないこと）。4K と 9K では、引き続き作れない。

## 5. 4K（GW1NS-4）の GW_JTAG を Apicula に足す作業の見積もり（2026-10-30、ソースを読んだだけ）
- **20K の対応を足した変更は小さい**: Apicula a6d988f（2026-09-08、Alastair M. Robinson、"under instruction from YRabbit"）は 3 ファイル +46 行。中身は次の3つ。
  - `chipdb.py` の `fse_create_jtag`: JTAG の部品を置くタイルの位置（GW2A-18C は row 27, col 50）と、各ポートの配線名（`tdo_er1_i: C1`、`tck_o: Q6` など）を手で書いた表。
  - `gowin_pack.py` の `GW2A_18C.get_GW_JTAG_fuses`: 設定 `JTAG_ER1` / `JTAG_ER2` を `USED` にするビット。
  - `attrids.py`: 属性 ID の追加。
- **nextpnr 側はデバイスに依存しない**: nextpnr e47c2589（2026-09-09）は、Apicula の chipdb に `jtag` があればその場所に `GW_JTAG` の部品を作る汎用の実装（`gowin_arch_gen.py:1152`、`pack.cc:208`）。4K でも Apicula 側を足せば使えるはず（推定）。ただしこの変更は nextpnr 0.11.1 の後なので、pip 版（YoWASP 0.11.1）には入っていない。
- **4K で必要になる調べもの**（20K の表と同じものを GW1NS-4 で作る）:
  1. GW1NSR-4C で Gowin の IDE が `GW_JTAG` を受け付けるか（未確認）。
  2. IDE で `GW_JTAG` を使う小さなデザインを作り、ビットストリームを読み解いて、部品のタイルの位置と各ポートの配線名を突き止める（Apicula の他の部品のコメントにある「テストのコンパイルで配線を追う」方法）。
  3. GW1N 系で `JTAG_ER1` / `JTAG_ER2` に当たる設定ビットを探す（GW2A とは設定の表が違う可能性がある）。
  4. 実機で確かめる: 4章の自前ドライバでユーザー用の命令（20K では 0x42 / 0x43）を送り、回路まで届くかを見る。
- **必要なもの**: Gowin のベンダーツール（Apicula が前提にしている版は 1.9.10.03）。Docker の手順もある（readme.md「Getting started for contributors」）。
- **使えるようになるまでの道のり**: Apicula に取り込まれる → Apicula のリリース → nextpnr のリリース（GW_JTAG 対応を含むもの）→ YoWASP の更新。どれも上流の都合に依存する。

## 6. Gowin IDE（V1.9.11.03 Education）での確認（2026-10-30）
- IDE には `GW_JTAG` の定義がある（`IDE/data/ipcores/gw_jtag.v`、`/* synthesis syn_black_box */` 付きの Verilog。ポートは retroramblings の記事と同じ）。
- `GW_JTAG` を1つ置き、ユーザー用の DR（ER1）を 32 ビットのシフトレジスタにした小さなデザインを `gw_sh` で合成した。結果は3つのデバイスすべてで同じ:
  ```
  ERROR (RP0008) : There is no GW_JTAG resource in current device, please change device
  ```
  | デバイス（set_device） | 結果 |
  |---|---|
  | GW1NSR-4C / GW1NSR-LV4CQN48PC6/I5（4K） | RP0008 |
  | GW1NR-9C / GW1NR-LV9QN88PC6/I5（-device_version C、9K） | RP0008 |
  | GW2AR-18C / GW2AR-LV18QN88C8/I7（-device_version C あり・なし、20K） | RP0008 |
- **20K でも同じエラーになるので、この結果だけでは「4K と 9K に GW_JTAG が無い」とは言えない。** 20K では retroramblings（2025-07）が Gowin の IDE で動かしており、Apicula も対応している。
- 考えられる理由（どれも未確認）: IDE の版（記事の版も Apicula の前提 1.9.10.03 も、手元の 1.9.11.03 と違う）、Education 版の制限、`GW_JTAG` を有効にする何らかの設定。
- IDE の DLL には `GW_JTAG used in design conflicts with GAO`、`... cannot be used as regular IO because GW_JTAG used in design` という文字列があり、GAO（Gowin の内蔵ロジックアナライザ）も `GW_JTAG  u_gw_jtag` を使う（GaoUtils.dll）。GAO を有効にしたデザインなら、IDE 自身が `GW_JTAG` を入れたビットストリームを作る可能性がある（未確認）。
- 使ったファイル（使い捨て）: `<作業用の一時フォルダ>\gwjtag4k\`（top.v、top.cst、build.tcl）

## 7. GAO 経由での確認（2026-10-30）
- GAO（Gowin の内蔵ロジックアナライザ）を有効にした 4K のデザイン（27 MHz のカウンタ4ビットを観測）を `gw_sh` でビルドした。GAO の設定ファイルは、IDE 付属の例（`IDE/data/examples/FFT/src/FFT.gao`）の形に合わせて手で作り、`add_file -type gao top.gao` で渡した。
  - 合成の後に「Post-Synthesis GAO」が走り、ビットストリームまで生成できた（`impl/pnr/ao_0.fs`）。
  - 生成された `impl/gao/gw_gao_top.v` には `GW_JTAG u_gw_jtag(...)` があり、JTAG のパッドは IBUF/OBUF 経由でつながれている。
  - タイミングレポートでは `u_gw_jtag/tck_pad_i → u_gw_jtag/tck_o`（ファンアウト 205）が GAO の回路のクロックとして配線されている。
- **したがって、4K（GW1NSR-4C）のシリコンには GW_JTAG があり、Gowin の配置配線はそれを使える。** 6章の RP0008 は、合成（GowinSynthesis）の段階で、利用者が直接書いた `GW_JTAG` を受け付けない、という制限とみられる（パッドをトップのポートに出しても同じエラーだった。GAO は合成の後で挿入されるので、この制限を通らない）。
- **部品の位置（タイル）と配線名は、まだ突き止められていない。**
  - Education 版の `-gen_posp 1` は、配置情報の無い空のファイルを出した。
  - Apicula 0.35 の `gowin_unpack -d GW1NS-4` で ao_0.fs をネットリストに戻し、FF のクロックを配線の割り当てからさかのぼったが、グローバルクロック網（GB10 など）の先が表現されておらず、tck_o の出どころにたどり着けなかった。
- 使ったファイル（使い捨て。Gowin が生成したファイルを含むのでリポジトリには入れていない）: `<作業用の一時フォルダ>\gao4k\`、`...\scratchpad\gwjtag4k_b\`、`...\scratchpad\gao4k_unpacked.v`

### ここまでの判断材料
- 4K で JTAG ブリッジを作るには、(1) 部品の位置と配線名、(2) 有効にする設定ビット、の2つを GW1NS-4 について突き止める必要がある。20K の対応は Apicula のメンテナー（YRabbit）の指示のもとで作られているので、同じ方法を聞くのが最短とみられる（推定）。
- 合成の制限（RP0008）があるので、Gowin の IDE で「GW_JTAG だけを入れた小さなデザイン」を作って差分を取る方法は使えない。差分を取るなら、GAO の有無や観測する信号の違いで比べる工夫が要る。

## 8. 上流の議論（YosysHQ/apicula issue #533、2026-11-02 に読んだ）
- issue #533 "Support for GW_JTAG on GW2A devices?"（OPEN）で、20K の対応がどう調べられたかが公開されている。
  - YRabbit（collaborator）の手順: `GW_JTAG` の出力をピンに出すデザインを作る → `gowin_unpack` で配線をたどり、部品が1つのセルか散らばっているかを見る → そのセルの機能ビットを、IDE と Apicula のビットストリームで比べる → ビットが既知の shortval の表にあれば、調べものは終わり。
  - robinsonb5（20K の対応の作者）は、出力を全部ピンに出した `allwires` デザインで、R28C51（0始まりで 27,50）に集まることを突き止めた。
  - 機能ビットは shortval の表 20 と 60（既知）に属していた。
- このスレッドに、4K（GW1NS-4）について続ける形で相談する。下書き: `reports/draft_apicula_issue533_comment.md`（未送信）。

## 9. 4K の GW_JTAG の位置・配線・設定ビット（独自調査、2026-11-03）
issue #533 の手順に沿って進めた。ファイルは `tools/p0/gwjtag4k/`。

### 合成の制限（RP0008）の回避
- 手書きのネットリスト（`allwires_top.vg`。IBUF/OBUF と `GW_JTAG` だけ）を `add_file -type netlist` で渡すと、Gowin は「Skip synthesis, because there is only one netlist file」として合成を飛ばし、配置配線からビットストリームまで作った。RP0008 は出ない。
- JTAG のパッドは、トップのポート（`tms_pad_i` など）に IBUF/OBUF を付けておくと、Gowin が専用ピン（6=TMS、7=TCK、3=TDI、4=TDO）に自動で割り当てた。パッドを付けないと配置の途中で黙って止まった。

### 部品の位置と配線名（allwires のビットストリームを Apicula 0.35 の gowin_unpack で読み、各出力ピンから配線を逆にたどった）
| ポート | 4K（R1C1 = 0始まり (0,0)） | 20K（Apicula、R28C51） |
|---|---|---|
| tck_o | Q6 | Q6 |
| tdi_o | Q5 | Q5 |
| test_logic_reset_o | Q3 | Q3 |
| run_test_idle_er1_o | Q4 | Q4 |
| run_test_idle_er2_o | F0 | F7 |
| shift_dr_capture_dr_o | Q7 | F6 |
| update_dr_o | Q2 | Q2 |
| enable_er1_o | Q0 | Q0 |
| enable_er2_o | 未確定（R1C1 の E11 で途切れた。Q1 と推定） | Q1 |
| pause_dr_o | R1C1 から出ていない（R1C10 の F5 に定数） | DUMMY |
| tdo_er1_i / tdo_er2_i | C1 / C2（入力ピンから R1C1_C1 / R1C1_C2 に届く） | C1 / C2 |

### 設定ビット
- Apicula 0.35 の GW1NS-4 のデータベースで、タイル (0,0)（ttyp 50）の shortval の表 `CFG` から、`JTAG_ER1=USED` と `JTAG_ER2=USED` のビットを引くと (3,19) と (3,20) になる。
- IDE の allwires のビットストリームではこの2ビットが立ち、Apicula で作った blinky では立っていない（`jtag_cfg_fuses.py`）。**新しい表を調べる必要は無く、20K と同じ既知の CFG の属性で足りる見込み。**

## 10. 実機での確認（Tang Nano 4K、2026-11-03）
- yosys（YoWASP 0.70）で `userdr_top.v` を Gowin のセルに合成し、ネットリストを Gowin の配置配線に通して書き込んだ（openFPGALoader、CRC Success）。
- `userdr_scan.py`（自前の MPSSE ドライバ）で IR に 0x42 を入れ、DR をスキャンした:
  - 1回目の読み出しで、回路の初期値 `0xC0FFEE42` が返った。**ユーザー用の命令 0x42 で、4K の回路にホストから届いた。**
  - IR 0x43（ER2、`tdo_er2_i=1` に固定）は全ビット 1 を返した（2本目の経路も動いている）。
- 気づいたこと:
  - `tck_o` の立ち上がりで TDI を取り込むと、読み戻しが `V | (V<<1)` に崩れた（周波数 100 kHz〜3 MHz で同じ）。立ち下がりで取り込むと崩れなくなった。`tck_o` は反転した TCK（Xilinx の DRCK 相当）として出ていると推定している。
  - 32 ビットで書いて 32 ビットで読むと 1 ビットずれる（`0x12345678` → `0x2468acf0`）。**33 ビットでスキャンすると、書いた値がそのまま返った**（`0x00000001`、`0x80000000`、`0x12345678`、`0xFFFFFFFF`）。キャプチャか最後のビットの扱いで 1 ビット分の遅れがあるとみられる（原因は未確定）。
- BL702 は、`0x38`/`0x3C`（書き込みを立ち上がりで行う組み合わせ）も拒否した。使えるのは 0x39/0x3B と 0x4B/0x6B。
- 途中で一度、BL702 が応答しなくなった（`ftdi_usb_reset failed`）。USB の抜き差しで戻った。

## 11. オープンなツールで使えるようにするまでに残ること
1. Apicula: `chipdb.py` の `fse_create_jtag` に GW1NS-4（(0,0) と上の表の配線名）を足し、`gowin_pack.py` の `GW1NS_4` に `get_GW_JTAG_fuses`（`JTAG_ER1`/`JTAG_ER2` を USED）を足す。そのうえで GW1NS-4 の chipdb を作り直す（Gowin のツールと fuzzer の環境が要る）。
2. nextpnr: GW_JTAG の対応（e47c2589）は 0.11.1 より後なので、ソースからビルドし、GW1NS-4 の chipdb も作り直す。
3. enable_er2_o の配線名の確定（今回は推定で Q1）。
4. 1〜2 ができれば、yosys + nextpnr + Apicula だけで `userdr_top.v` を作り、今回と同じ結果になるかで確かめられる。

## 12. オープンなツールだけで動かした（2026-11-03）
ファイルは `tools/p0/gwjtag4k/`（README の「Open toolchain only」）。

### 手順
1. oss-cad-suite（2026-10-22）の nextpnr は `nextpnr-0.11.1-77-g6b438a1c`。GW_JTAG の対応（e47c2589）を含む（`git merge-base --is-ancestor` で確認）。同梱の Apicula は 0.35。
2. Apicula 0.35 の写しを作り、`patch_apicula_gw1ns4_jtag.py` で次の2つを足した（oss-cad-suite 本体には手を入れていない）。
   - `GW1NS-4.msgpack.xz` の `extra_func[(0,0)]['jtag']`（9章の配線名。enable_er2_o は推定の Q1）
   - `gowin_pack.GW1NS_4.get_GW_JTAG_fuses`（CFG の `JTAG_ER1`/`JTAG_ER2` を USED。20K と同じ）
   - Apicula のデータベースをベンダーのツールから作り直す代わりに、出来上がったデータベースに後から1項目を足した。
3. nextpnr のソース（6b438a1c）の `gowin_arch_gen.py` を、写しの Apicula を先に読む `PYTHONPATH` で動かし、4K 用の .bba を作った。
4. nextpnr の `bbasm` は Boost を使うので、引数の解析だけを書き換えた版を WSL の g++ でビルドし、.bba を .bin にした。
   - 修正していない Apicula から作った .bin は、oss-cad-suite 同梱の .bin と一致しなかった（10,257,210 対 10,256,822 バイト）。そのまま nextpnr の `--chipdb` に渡して使えたので、作り方は互換とみている（差の原因は未確認）。
5. yosys（oss-cad-suite）→ `nextpnr-himbaechel --chipdb <作った .bin> --timing-allow-fail --seed 1` → 写しの `gowin_pack`。
   - nextpnr の報告は `GW_JTAG: 1/1 100%`。ビットストリームでは (0,0) の `JTAG_ER1`/`JTAG_ER2` の2ビットが立っていた。
   - `--timing-allow-fail` が無いと、`negedge tck` のホールド違反（-0.24 ns）1件でエラーになる。

### 実機（Tang Nano 4K）
- `userdr_open.v` をこの手順で作って書き込み、IR 0x42 で 32 ビットの DR をスキャンした。**`0x00000001`、`0x80000000`、`0x12345678`、`0xFFFFFFFF` が、100 kHz、1 MHz、3 MHz のどれでも、32 ビットでそのまま往復した。** IR 0x43（ER2、`tdo_er2_i=1`）は全ビット 1 を返した。
- そこに至るまでのタイミングの試行（どれも 32 ビットのスキャン）:
  | 回路の作り | 結果 |
  |---|---|
  | `tck_o` の立ち上がりで TDI を取り込む | 2 ビットずれ、隣のビットと混ざる |
  | `tck_o` の立ち下がりで TDI を取り込む、TDO = sr[0] | 下位 31 ビットは正しく、最上位ビットが落ちる |
  | 上に加え、シフトの条件を半周期だけ保持する（`userdr_open.v`） | **すべて正しい** |
  - 最上位ビットが落ちたのは、Shift-DR を抜ける辺では `shift_dr_capture_dr_o` がすでに下がっているため、とみている。
  - 10章（Gowin の配置配線）では 33 ビットが必要だったのに対し、こちらでは 32 ビットで合う。配置配線が違えば、`tck_o` まわりの遅れも違うと考えられる。ホールド違反も出ているので、**このタイミングは配線しだいで変わりうる**。土台の回路に組み込む前に、`GW_JTAG` の出力の振る舞いをもっと調べる必要がある。

### 残ること
- 上流への提案（#533）。下書きをこの結果で更新した。
- enable_er2_o の配線名（推定の Q1）の確認。
- タイミングの安定化（ホールド違反の解消、配線に依存しない回路の作り）。
- Tang Nano 9K（GW1N-9C）で同じ調査をする。

## 13. タイミングの詰め（2026-11-03）
ファイルは `tools/p0/gwjtag4k/`。どれもオープンなツールだけで作ったビットストリームで、Tang Nano 4K の実機で確かめた。

### 13.1 GW_JTAG の出力の振る舞い（`jtagdiag_top.v`：27 MHz で出力の変化を記録し、ER2 で読み出す）
IR 0x42 → Run-Test/Idle で3クロック → 4 ビットの DR スキャン、を記録した。
- **BL702 の TCK は、MPSSE の分周設定にかかわらず約 2 MHz**（立ち上がりから立ち下がりまで 27 MHz で 5〜8 刻み ≒ 200〜300 ns）。これまで「100 kHz、1 MHz、3 MHz で同じ」だったのは、実際には同じ速さだったため。
- `tck_o` は TCK と同じ極性（待機中は 0、パルスで 1）。10章の「反転している」という推定は誤りだった。
- `tdi_o` は TCK の立ち上がりで変わる（記録の分解能 37 ns の範囲で同時）。
- `shift_dr_capture_dr_o` は、Shift-DR に入る立ち上がりで 1 になり、Shift-DR を抜ける立ち上がり（TMS=1 の最後のビット）で 0 になる。Capture-DR の間は 0 だった（名前に反して、この記録では Capture の区間は見えない）。
- `update_dr_o` は Update-DR の1周期だけ 1。

### 13.2 ホストが TDO を読む瞬間（`jtagphase_top.v`）
- 立ち上がりで進むカウンタと立ち下がりで進むカウンタの偶奇を TDO に出して読んだ。どちらも `0101…` になり、**BL702 は TCK が High の間（立ち上がりの後、立ち下がりの前）に TDO を読んでいる**と分かった。
- したがって TDO は立ち下がりでだけ変えればよい。

### 13.3 tck_o をクロックにすると、配置しだいで壊れる
| 回路 | 配置のシード 1〜5（各 299 回のランダムな往復、`userdr_stress.py`） |
|---|---|
| `userdr_open_tckclk.v`（`tck_o` をクロックに使う、12章の版） | シード 3 だけ 275 回失敗。他の4つは 0 回。nextpnr はどれもタイミング違反を出さなかった |
| `tck_o` の立ち下がりだけで動かす版（論理的には正しいはず） | シード 1 で `0x80000000` → `0xE0000000` などに崩れた |
| `userdr_open.v`（27 MHz で取り込む、下記） | **5つとも 0 回**。タイミング違反なし、`--timing-allow-fail` も不要 |
- `tck_o`（R1C1 の Q6）は低スキューのクロック網に乗らず、普通の配線で配られる。シフトレジスタのように隣のフリップフロップの出力を取り込む回路では、クロックの届く時刻のずれでデータが隣へ漏れる、とみている（`V | (V<<1)` のような崩れ方と一致）。nextpnr の時間の見積もりは、この経路を捉えていない（未確認）。

### 13.4 採用する作り（`userdr_open.v`）
- `tck_o` はクロックに使わない。基板の 27 MHz で `tck_o`、`tdi_o`、`shift_dr_capture_dr_o`、`update_dr_o`、`enable_er1_o` を2段のフリップフロップで取り込み、TCK の立ち下がりを検出した時点で処理する。
  - シフトの条件は「いまの shift_dr」と「1つ前の立ち下がりでの shift_dr」の OR（最後のビットを取るため）。
  - TDO は shift レジスタの最下位ビットで、立ち下がりの後にだけ変わる。ホストが読む High の間は安定している。
- 前提: 取り込みのクロックが TCK より十分速いこと。BL702 の約 2 MHz に対して 27 MHz は約 13 倍。TCK の速いデバッガ（20K の BL616 など。速さは未確認）では、PLL で上げたクロックが要るかもしれない。

### 13.5 土台の回路への持ち込み
- JTAG ブリッジを土台の回路に入れるなら、この「基板のクロックで取り込む」作りを使う。UART のブリッジ（Task 2）と同じクロックの領域に収まるので、レジスタバスへの接続も UART 版と同じ形にできる。
- 残る確認: 20K（BL616）での TCK の速さ。（enable_er2_o は 14章で確認済み）

## 14. enable_er2_o の確認と上流への変更（2026-11-04）
ファイルは `tools/p0/gwjtag4k/en2probe_top.v` と `en2probe.py`。12章と同じパッチ済み Apicula 0.35 と chipdb で作り（`GW_JTAG: 1/1`、配線は (0,0) の Q0〜Q7 から出ている）、Tang Nano 4K で確かめた。

### 回路
- 27 MHz で GW_JTAG の出力を取り込み、`enable_er2_o`（Q1）、`enable_er1_o`、`run_test_idle_er2_o` の立ち上がりを数える。
- ER1（IR 0x42）で、数えた値と、いまの各出力の値を 32 ビットで読む。
- ER2（IR 0x43）の TDO には `enable_er2_o & ~enable_er1_o` を出す。

### 結果（`RESULT: PASS`）
| 操作 | 結果 |
|---|---|
| IR 0x42 で読む | en1=1、en2=0 |
| IR 0x43 で DR を 3 回読む | 3 回とも 0xFFFFFFFF（Shift-DR の間 en2=1、en1=0） |
| IR 0x43 を 1 回選んでから 0x42 で読む | en2 の立ち上がり +1、run_test_idle_er2_o も立ち上がった |
| IR 0x11（IDCODE、0x0100981b）を選んでから 0x42 で読む | en2 の立ち上がり ±0 |
| IR 0x43 と 0x42 を 5 回交互に選ぶ | en2 の立ち上がり +5 |

- **Q1 は ER2 の enable（IR 0x43 を選んでいる間だけ 1）。** 推定どおりで、20K と同じ。
- 気づいたこと（未確認）:
  - 「en1 と en2 が同時に 1」の印が、0x43 と 0x42 を交互に選んだ最後の区間で 1 回立った。それより前の区間（0x43 → 0x42 を 1 回）では立たなかった。IR が切り替わる瞬間に、27 MHz の 1 刻み（37 ns）程度だけ重なることがあるとみている。
  - `test_logic_reset_o`（Q3）は、Test-Logic-Reset 以外の状態で読んでも 1 だった。負論理か、別の意味の信号かは調べていない。配線名は 9章の逆引きで Q3 と分かっているので、上流の変更には影響しない。
  - `pause_dr_o`（DUMMY）は常に 1。
- 書き込みの前に BL702 が 2 回応答しなくなり、USB の抜き差しで戻った（10章と同じ症状）。

### 上流向けの変更
- 上流 master（993faec）の上に 1 コミット（手元の apicula のクローン、ブランチ `gw1ns4-gw_jtag`）。`chipdb.py` の `fse_create_jtag` に GW1NS-4（(0,0)、run_test_idle_er2_o=F0、shift_dr_capture_dr_o=Q7、ほかは 20K と同じ）、`gowin_pack.py` の `GW1NS_4` に `get_GW_JTAG_fuses`（20K と同じ）。
- 確かめたこと:
  - このコミットの `fse_create_jtag` を配布版 0.35 の chipdb に適用すると、GW1NS-4 は 12章のパッチの項目と一致し、GW2A-18C は変わらない。
  - このコミットの `gowin_pack` で en2probe の配置配線結果を pack すると、12章のパッチ版と（コメント行を除き）同じビットストリームになる。変更を外すと `Not implemented method 'get_GW_JTAG_fuses'` で止まる。
- 確かめていないこと: ベンダーのファイルからの chipdb の再生成（上流は IDE 1.9.10.03、手元は 1.9.11.03）。メンテナに任せる旨を PR に書く。

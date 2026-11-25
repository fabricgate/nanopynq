# Tang Nano 20K の base 設計（GW_JTAG、2026-11-15）

## 結論と要約
- **`Overlay("base", board="tangnano20k")` が実機で動いた。** 4K と同じく、書き込みも通信も GW_JTAG（ER1、IR 0x42）で、USB は 1 本。
- **nanopynq 側で直したのは 1 か所だけ。** 20K のデバッガ（BL616）は USB High Speed で、受信パケットが 512 バイト。`transport/mpsse.py` は FTDI の状態バイト（2 バイト）を 64 バイトごとに取り除く前提だったので、エンドポイントの `wMaxPacketSize` から取るようにした。古い前提のままだと、100 ワードの読み出しが受信不足になる（909 バイト中 883 バイト）ことを実機で確かめた。
- **TCK の取り込みは 27 MHz のまま（PLL なし）。** BL616 の TCK は約 3.5 MHz で、High の間は最短で 27 MHz の 2 刻み（`report_gwjtag_9k20k.md` 6 章、ブランチ feat/gwjtag-9k20k）。それでも配置のシード 1〜3 で誤りは 0 回だった。余裕は BL702（4K）より小さいので、誤りが出たら取り込みのクロックを PLL で上げる。
- **ボタンはアクティブ High（押すと 1）。** 基板に外付けのプルダウンがある。LED はアクティブ Low（4K や 9K と同じ）。どちらも目視で確かめた。

## 1. 道具
oss-cad-suite 2026-11-15（Yosys 0.71+34、nextpnr 0.11.1-92 5e2718b6、openFPGALoader v1.2.0）。nextpnr は、20K で ALU の計算が狂う不具合（Apicula #514 / #541）の修正 6030081a15 を含む。
Apicula は上流 master da0e33e（oss-cad-suite 同梱と同じコミット）。CHIPDB は同梱の `chipdb-GW2A-18C.bin`。
`tools/build_base.py --board tangnano20k` に、`OSS` / `OVL` / `CHIPDB` を渡してビルドする（スクリプトの docstring に書いた）。

## 2. 変更
| ファイル | 内容 |
|---|---|
| `src/nanopynq/transport/mpsse.py` | 受信パケットの長さを IN エンドポイント（0x81）の `wMaxPacketSize` から取る（BL702 は 64、BL616 は 512） |
| `src/nanopynq/data/boards.yaml` | `tangnano20k`（GW2AR-LV18QN88C8/I7、family GW2A-18C、`synth_gowin -family gw2a`、`host_link: jtag`） |
| `gateware/boards/tangnano20k/` | `top.v`（4K の top に LED 6 個、ボタンは反転なし）、`tangnano20k.cst`（clk 4、LED 15〜20、S1 88、S2 87。Apicula の `examples/tangnano20k.cst` と同じ） |
| `tools/build_base.py` | 20K を受け付ける。GW_JTAG 版のビルドで、ボードに family があれば nextpnr に `--vopt family=` を渡す（4K は family が無いので変わらない） |
| `src/nanopynq/data/designs/tangnano20k-base/` | 同梱のビットストリーム（シード 1、sha256 71805340…f524）とマニフェスト |
| README、テスト | 20K の節を追加。`test_boards` / `test_bundled_designs` / `test_mpsse`（64 バイトと 512 バイトで 900 バイトの応答を読むテスト）を追加 |

## 3. 実機での確認（すべて SRAM への書き込み）
| 確認 | 結果 |
|---|---|
| ボタンの向き | 内部プルダウンの版でも内部プルアップの版でも、押していないときは Low → 外付けのプルダウンがある。アクティブ High |
| LED とボタン（目視） | LED0 と LED5 を点け、S1 で LED1、S2 で LED2 を点けるスクリプトで確認した。LED0 と LED5 が点き、ボタンを押している間だけ LED1・LED2 が点いた（LED はアクティブ Low で合っている）。押した記録は S1 → `[1, 0]`、S2 → `[0, 1]`、離すと `[0, 0]` |
| Overlay | sys の id 0x4E505131、version 0x10000、スクラッチレジスタの往復も正常 |
| `tools/stress_link.py` | シード 1 で 5000 回（7469 ワード）、シード 2 と 3 で 3000 回ずつ。どれも不一致 0 回、約 2900〜3400 ワード/秒 |
| バースト読み出し | 長さ 1〜1000 ワードを 200 回（合計 39042 ワード）。不一致 0 回、14756 ワード/秒。1 回の USB 転送で最大 909 バイトを受け取る |
| `python -m nanopynq doctor --board tangnano20k` | 終了コード 0（`usb` が OK） |
| 単体テスト | 201 件すべて通過 |

## 確認できなかったこと
- 4K（BL702）で `wMaxPacketSize` が実機で 64 と読めるか。BL702 は Full Speed 専用なので、理屈の上では従来の固定値と同じ。4K の基板が直ったら、`Overlay("base", board="tangnano4k")` と `stress_link.py` で確かめる。
- 20K の Linux での動作（Windows でしか試していない）。

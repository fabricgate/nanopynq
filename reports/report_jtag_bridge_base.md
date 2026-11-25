# JTAG ブリッジを土台に組み込んだ結果（設計書 4.12）2026-11-03

## 結論
- Tang Nano 4K で、`Overlay("base", board="tangnano4k")` → `ol.leds[0].on()` が、外付けの UART なしに USB 1本で動いた。書き込みは openFPGALoader、通信は同じ Interface 0 の GW_JTAG（ユーザー命令 0x42）を使う。
- ランダムな読み書きの負荷試験は、配置のシード 1〜5 で作ったどの土台でも失敗 0 件だった（各 500 回、同梱のシード 1 はさらに 2000 回）。
- 速さは、32 ビットの読み書きで毎秒約 2000〜2800 語。1語ごとに USB を1往復させている（まとめて送る工夫は未実装）。
- 9K の UART 経路は変えていない。既存のテストはすべて通る。9K の同梱の土台は、SCRATCH を足したので作り直した。

## 1. 作ったもの
| 部分 | ファイル | 中身 |
|---|---|---|
| FPGA | `gateware/rtl/jtag_bridge.v` | GW_JTAG の出力を基板の 27 MHz で取り込む（`tools/p0/gwjtag4k/userdr_open.v` の取り込み部をそのまま 64 ビットに広げた）。64 ビットの DR 1回で1件のコマンド、応答は次のスキャンで出る |
| FPGA | `gateware/rtl/base_regs.v` | sysinfo・LED・ボタン・既定のスレーブ。UART 版（`base_soc.v`）と JTAG 版で共有する |
| FPGA | `gateware/rtl/sysinfo.v` | `+0x8` に SCRATCH（32 ビット、読み書き）を足した。4K の LED は1ビットなので、32 ビットの往復はこれで確かめる |
| FPGA | `gateware/boards/tangnano4k/top.v` | GW_JTAG → jtag_bridge → base_regs。UART のピンは外した |
| ホスト | `src/nanopynq/transport/mpsse.py` | pyusb と libusb-package で BL702 の Interface A を開く。BL702 が受け付けるコマンド（0x39/0x3B/0x4B/0x6B/0x80/0x85/0x86/0x87）だけを送る |
| ホスト | `src/nanopynq/transport/jtagbridge.py` | `JTAGBridge`。`read`/`write` の形は `UARTBone` と同じ |
| ホスト | `overlay.py`、`doctor.py`、`data/boards.yaml` | Board DB の `host_link.kind` が `jtag` なら JTAG を開く。doctor はシリアルポートの代わりに USB のインターフェースを確かめる |
| ビルド | `tools/build_base.py` | JTAG のボードは、手元で直したツール（環境変数 `OSS`、`OVL`、`CHIPDB`）で作る。`--seed` と `--out` を足した |
| 試験 | `tools/stress_link.py` | Overlay 越しのランダムな往復の負荷試験（UART のボードでも使える） |

コマンドと応答の形:
- コマンド（ホスト → FPGA）: `[63] 有効, [62] 書き込み, [61:32] ワードアドレス, [31:0] データ`。Update-DR で実行する。
- 応答（次のスキャン）: `[63] 完了, [62:32] 0, [31:0] 読み出しデータ（書き込みは 0）`。有効でないコマンドの後は 0。ホストは `[63:32]` が `0x80000000` でない応答を `BridgeError` にする。

## 2. 実機の結果（Tang Nano 4K、Windows 11、Interface 0 は WinUSB）
### 2.1 ビルド
| シード | base.fs の sha256（先頭） | nextpnr の最大周波数 | GW_JTAG |
|---|---|---|---|
| 1（同梱） | ba0951f2… | 139.55 MHz | 1/1 |
| 2 | 4c71533e… | 137.23 MHz | 1/1 |
| 3 | 8580642a… | 134.12 MHz | 1/1 |
| 4 | b4a0b1af… | 記録なし | 1/1 |
| 5 | 18348636… | 記録なし | 1/1 |
- シード 1 は2回作って同じハッシュになった。9K（YoWASP）も2回作って同じハッシュ（d856e531…）。
- タイミング違反はなく、`--timing-allow-fail` は使っていない。

### 2.2 負荷試験（`tools/stress_link.py`。SCRATCH への 32 ビットの乱数の書き込みと読み戻し、ID の読み出し、LED の書き込みと読み戻し、未割り当てのアドレスの読み出しを混ぜる）
| 土台 | 回数 | 不一致 | 速さ |
|---|---|---|---|
| 同梱（シード 1） | 500 | 0 | 2785 語/秒 |
| 同梱（シード 1） | 2000 | 0 | 2111 語/秒 |
| シード 2 | 500 | 0 | 2462 語/秒 |
| シード 3 | 500 | 0 | 2105 語/秒 |
| シード 4 | 500 | 0 | 2494 語/秒 |
| シード 5 | 500 | 0 | 2023 語/秒 |

### 2.3 失敗のときの振る舞い
- 前の Overlay を閉じずに次の Overlay を開くと、openFPGALoader が失敗し、`ProgramError` に「`ol.close()`」の案内が出た。閉じた後は開き直せた。
- 土台でないデザイン（blinky）を載せた状態で `Overlay(..., download=False)` を開くと、`BoardNotResponding`（`bad JTAG response 0x0000000000000000`）で止まった。
- `python -m nanopynq doctor --board tangnano4k` の `usb` の検査は OK だった。
- LED（ピン 10）: `ol.leds[0].on()` の後に点灯していることを、ユーザーが目で確かめた（2026-11-03）。

### 2.4 レビュー後の修正（独立したレビューの指摘）
- pyusb の失敗（書き込み・読み出しのタイムアウト以外の USB の失敗、libusb の NOT_SUPPORTED、開く途中の失敗）を、すべて `TransportTimeout` か `PortOpenError` に変えた。開く途中で失敗したら interface を解放する。Overlay は ID の確認で何が起きても通信路を閉じる。
- flush が途中で終わった後は、次の flush の前に受信側を一度だけ空にする（遅れて届いた応答で、以降の応答が1つずつずれるのを防ぐ）。TAP の状態は戻さないので、その後の応答が壊れていれば `BridgeError` で止まる（黙って誤らない）。
- `JTAGBridge` は 32 ビットを超えるアドレスと負のアドレスを拒む（ワードアドレスが書き込みのビットに入り、読み出しが書き込みに化けるのを防ぐ）。
- 修正後の実機の再試験: 同梱の土台で 1000 回、不一致 0 件、2242 語/秒。

## 3. 確かめられなかったこと
- **Linux**: 動かしていない。カーネルのドライバ（ftdi_sio）を外す処理と、libusb の権限（openFPGALoader の udev ルールで足りるか）は未確認。
- **Zadig を入れていない Windows**: 「見つからない」と「開けない」のどちらの経路になるかは確かめていない（手元の Interface 0 は WinUSB のまま）。どちらの文面にも Zadig の案内を入れた。
- **BL702 が固まったとき**: 今回の作業中は一度も固まらなかった。読み出しは 1 秒で諦めて `BoardNotResponding` になる作り（ユニットテストで確認）。
- **9K と 20K**: 範囲外。9K（GW1N-9C）は GW_JTAG の調査をしていないので UART のまま。`enable_er2_o` の配線名（推定の Q1）は、この土台では使っていない。

## 4. 制約とハブへの影響
- 4K の土台は pip で入るツール（YoWASP）では作れない。同梱の `base.fs` は、手元で直した Apicula と作り直した chipdb で作った（`tools/p0/gwjtag4k/README.md`）。上流に取り込まれるまで、4K の利用者が自分のモジュールを手元でビルドすること（P2）はできない。
- 4K のマニフェストの `transport` は `jtag` にした。ハブの仕様の値は `spi|pio|uart` なので、ハブ側に `jtag` を足す必要がある（ハブの変更はユーザーが行う。設計書 4.7）。
- マニフェストの `sys` に `scratch`（`0x8`、32 ビット、rw）を足した（両ボード）。

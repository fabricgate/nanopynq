# Tang Nano 20K を Linux で試した(2026-11-20)

## 結論
- **修正前は、Linux で 20K の JTAG が開けなかった(4K も同じコードを通る)。** `Mpsse.open()` の `set_configuration()` が `[Errno 16] Resource busy` で失敗していた。直したのは 1 か所(`src/nanopynq/transport/mpsse.py`)。
  - 原因: Linux では、カーネルのドライバ ftdi_sio が Interface 0(JTAG)と Interface 1(UART)の両方をつかむ。nanopynq は Interface 0 だけを外す。Interface 1 をドライバがつかんでいる間は、usbfs がコンフィギュレーションの設定を断る。カーネルのログには `usbfs: interface 1 claimed by ftdi_sio while 'python' sets config #1` と出た。
  - 修正: コンフィギュレーションがまだ設定されていないときだけ、`set_configuration()` を呼ぶ。
  - 影響: 20K の `Overlay(..., board="tangnano20k")` と、`python -m nanopynq doctor` の `usb` の項目。どちらも、差し直した直後の状態で失敗した。失敗のときの文面は差し直しを勧めるが、差し直しても直らない。4K の `Overlay` も同じコードを通るが、4K では確かめていない。
- **修正後は、Windows で確かめた 20K の項目が Linux でも全部通った。** base の `Overlay`、`download=False`、識別値の不一致、sysinfo 1.0 の回路、`stress_link`、SDRAM の 5 手順、バーストの読み書き。往復は Windows より速い(Python で 0.17 ms。Windows は 0.40 ms)。
- **長時間でも誤りは出なかった。** SDRAM のデザインで 80 分(7861 万語、自己試験 156 回)、base で 80 分(3258 万語)、どちらも不一致 0 回、例外 0 回。20K の TCK の取り込みの余裕は小さいとされている(`report_tangnano20k_base.md`)。しかし、同梱の 2 つの配置(シード 1)では、この時間の範囲で誤りは出なかった。
- **書き込みと開閉を繰り返しても、失敗は出なかった。** openFPGALoader で 300 回書き込み(開閉 600 回)、Python の SRAM ローダーで 100 回書き込み(開閉 200 回)。どちらも失敗 0 回。
- **Linux の Chrome の WebUSB は、Interface 0 を ftdi_sio がつかんでいると開けない。** `claimInterface` が `Unable to claim interface` で失敗する。Windows で Zadig を使わなかったときと同じ文面。Chrome はカーネルのドライバを外さない。
  - Interface 0 からドライバが外れていれば、全部通った。つなぐ、IDCODE、SRAM への書き込み(base 0.78 s、SDRAM 4.15 s)、ブリッジでの読み取り(往復 0.24〜0.33 ms)。
  - 外れているかどうかは、直前に何を動かしたかで変わる。nanopynq の Python(`Overlay`、`doctor`)は外したまま閉じる。openFPGALoader は閉じるときに付け直す。差し直すと付く。
  - ブラウザだけで使う利用者のための手順(例: udev の規則で Interface 0 からドライバを外す)は、まだ無い。root が要るので試していない(5 章)。

## 1. 環境
- Ubuntu 24.04.5 LTS、カーネル 7.0.0-38-generic、Python 3.13.14、pyusb 1.3.1。
- openFPGALoader v0.12.0(apt)。Windows の確認は v1.2.0(oss-cad-suite)だった。
- Google Chrome 157.0.8103.78。ページは `file://` で開いた。
- udev の規則は `/lib/udev/rules.d/99-openfpgaloader.rules`(パッケージ同梱)。`/dev/ttyUSB*` のグループは plugdev。利用者は dialout に入っていない。
- ボードは Tang Nano 20K(デバッガは `SIPEED USB Debugger`、0403:6010)。書き込みはすべて SRAM。フラッシュには触れていない。

## 2. Python 側(修正後)
差し直した直後と同じ状態を、root なしで作れる。pyusb の `attach_kernel_driver(0)` で、ftdi_sio を Interface 0 に付け直せる。各項目は、この状態から始めたものを含む。

使ったスクリプトは `tools/p0/linux20k/` にある。`fresh_overlay.py`(修正前と修正後の比較)、`check_20k.py`(`Overlay` の中身)、`mismatch_20k.py`(不一致と、読み書きの記録)、`burst_20k.py`(バースト)、`soak.py`(長時間)、`cycles.py`(書き込みと開閉の繰り返し)。ブラウザ側は `cdp.mjs` と `x.py`。

| 確認 | 結果 |
|---|---|
| 差し直した直後の状態から `Overlay("base", board="tangnano20k")`、修正前の `mpsse.py` | `PortOpenError: ... [Errno 16] Resource busy` |
| 同じ状態から、修正後 | 開けた。`sys.id 0x4E505131`、`sys.design_id 0xABF78D8C` |
| `python -m nanopynq doctor --board tangnano20k` | 修正前は `NG usb`(EBUSY)。修正後は終了コード 0 |
| `Overlay` の中身(書き込みあり) | 開くまで 0.43 s。版 `0x00010001`、識別値が一致。scratch の往復が一致。LED 6 個を順に点けて読み戻すと `0x01`→`0x3F`、消して `0x00`。ボタンは `[0, 0]`(押していない)。往復 0.17 ms(200 回の平均) |
| 同じボードに `download=False` | 開くまで 0.07 s。同じ値が読めた |
| SDRAM のデザインを載せ、base を `download=False` で開く | `DesignMismatch`(`0x1ef753ef` と `0xabf78d8c`)。読んだのは `0x0`、`0x4`、`0xC` だけで、書き込みは 0 回 |
| 作り直す前の base(sysinfo 1.0、5316cbc の `.fs`)を載せ、`download=False` | `DesignMismatch`(sysinfo 1.0)。読んだのは `0x0`、`0x4` だけ |
| `tools/stress_link.py --n 5000` | 不一致 0 回、5923 ワード/秒(Windows は 2924) |
| `tools/stress_link.py --n 200000` | 300260 ワードで不一致 0 回、50.7 s、5921 ワード/秒 |
| `tools/p0/sdram20k/hw_check.py`(5 手順) | 全部 PASS。誤りの出ない RD_LAT は 2〜5(Windows と同じ)。自己試験 0.71 s。1 語ずつの読み書きは書き 5939、読み 5934 語/s(Windows は 3473、3719)。連続の読み書きは 16588、16633 語/s(Windows は 16105、16355) |
| SDRAM のバースト(長さ 1〜1000 語、位置はランダム、200 回) | 207188 語で不一致 0 回、16898 語/s |
| 長時間、SDRAM のデザイン(`soak.py --design sdram --minutes 80`) | 80 分で 7861 万語。不一致 0 回、例外 0 回。30 秒ごとの自己試験 156 回で誤り 0。16377 語/s で、最初の 1 分から最後まで変わらなかった |
| 長時間、base(`soak.py --design base --minutes 80 --seed 2`) | 80 分で 3258 万語(照合 2036 万回)。不一致 0 回、例外 0 回。6787 語/s で一定 |
| `tools/p0/webusb/gowin_sram.py`(openFPGALoader を使わない SRAM への書き込み、#49 の土台)、差し直した直後の状態から | SDRAM のデザイン(577 KB)を 4.09 s(138 KB/s)。状態 `0x6020`。そのあと `Overlay("sdram", download=False)` で照合が通り、自己試験は誤り 0 |
| openFPGALoader v0.12.0 で書き込み | base 0.35 s、正常に終わった |
| 書き込みと開閉の繰り返し、openFPGALoader(`cycles.py --rounds 300`) | base と SDRAM のデザインを交互に 300 回書き込み、開閉は 600 回(書き込みのあとと `download=False`)。失敗 0 回、346 s。回ごとのドライバの状態は記録していない。3 章のとおり openFPGALoader が ftdi_sio を付け直すなら、書き込みのあとの 300 回は、付いた状態から JTAG を開いたことになる(sysfs を見たのは 2 回だけ) |
| 同じ繰り返し、Python の SRAM ローダー(`cycles.py --rounds 100 --loader gowin_sram`) | 書き込み 100 回、開閉 200 回。失敗 0 回、269 s。毎回、書き込んだあとに識別値が書き込んだデザインのものと一致した |

## 3. ブラウザ側(Chrome、WebUSB、`examples/webusb/index.html`)
機器の選択の画面は、CDP の `DeviceAccess` には出てこなかった。画面の撮影と、XTest でのクリックで選んだ。

| 確認 | Interface 0 を ftdi_sio がつかんでいる | Interface 0 からドライバが外れている |
|---|---|---|
| 選択の画面 | `USB Debugger` が出る | 同じ |
| つなぐ | `Failed to execute 'claimInterface' on 'USBDevice': Unable to claim interface.` | 開けた。受信のパケットは 512 バイト。9〜11 ms |
| IDCODE | - | `0x0000081b` |
| base の書き込み(108 KB) | - | 0.78 s、状態 `0x6020`。そのあと `sys.design_id 0xabf78d8c`(書き込む前は SDRAM のデザイン)。Windows は 0.80 s |
| SDRAM のデザインの書き込み(577 KB) | - | 4.15 s、状態 `0x6020`。そのあと `sys.design_id 0x1ef753ef`。Windows は 4.17 s |
| ブリッジでの読み取り | - | 往復 0.24 ms(base)、0.33 ms(SDRAM のデザイン)。Windows は 0.54〜0.61 ms |
| 切る | - | `released interface 0`。Chrome は ftdi_sio を付け直さない |
| 事前に要った設定 | - | 追加なし(udev の規則は導入済み) |

Interface 0 のドライバの状態は、次のように変わった。
- 差し直した直後: ftdi_sio が付いている(`/dev/ttyUSB0` と `/dev/ttyUSB1` がある)。
- nanopynq の Python が JTAG を開いて閉じたあと: 外れたまま。
- openFPGALoader のあと: ftdi_sio が付いている。付いた状態から `--detect` を実行したときも、外れた状態から書き込んだときも、付いていた。
- Chrome が切ったあと: 外れたまま。

このため、`Overlay(...)`(書き込みあり)は毎回、ftdi_sio が Interface 0 に付いた状態から JTAG を開く。今回直した経路を、毎回通る。

## 4. 単体テスト
- `uv run pytest -q`: 652 件通った。
- `uv run pytest -q -m toolchain`: 44 件通った。
- `sim` は実行していない(この PC の PATH に Icarus Verilog が無い)。
- `tests/test_mpsse.py` に 2 件足した。設定済みなら `set_configuration()` を呼ばないこと、未設定なら呼ぶこと。偽物の `set_configuration()` は、設定済みのとき EBUSY を出すようにした。修正前の実装では、21 件のうち 12 件が落ちることを確かめた。

## 5. 確認できなかったこと
- **ブラウザだけで使う Linux の利用者の手順。** 候補は、udev の規則で Sipeed のデバッガの Interface 0 から ftdi_sio を外すこと。root が要るので試していない。0403:6010 だけで絞ると、Sipeed 以外の FT2232 の Interface 0 のシリアルポートも消えてしまう。製造元の文字列(`SIPEED`)でも絞る必要がある。
- **9K の Linux での確認。** 9K は手元につないでいない。対象は、WebUSB の書き込みと Web Serial の同時の利用、Web Serial のページで未確認の項目(`report_webserial_spike.md` 3 章)。
- **4K の Linux での確認。** 基板が故障している。同じ修正で開けるようになるはずだが、確かめていない。
- **LED が光ること(目視)。** 読み戻しだけを見た。
- **Linux でのビルドと、ほかのシードの配置での長時間の試験。** 20K のビルドには oss-cad-suite が要る(`tools/build_base.py`)。この PC には入っていない。
- 長時間の試験と繰り返しのログ(`reports/linux20k_logs/`)は、コミットしていない(`*.log` が無視の対象)。表の数値は、ログの最後の行から写した。
- **Windows での修正後の動き。** 修正後に Windows の実機では動かしていない。WinUSB では機器が常に設定済みなので、`set_configuration()` を省くだけになるはず。ただし、これはコードを読んだうえでの推定で、測っていない。マージの前に、Windows で `python -m nanopynq doctor --board tangnano20k` と `Overlay("base", board="tangnano20k")` を確かめる必要がある。
- `tools/p0/jtag_mpsse_min.py`(試作の道具)にも、同じ `set_configuration()` がある。直していない。Linux で使うと同じ EBUSY になるはず。

## 6. 次の判断のための材料
- Linux で 20K を使う利用者は、修正前は README の手順どおりにしても使えなかった(4K も同じはず)。リリースに含めるかを決める。
- ブラウザの方式(#23、#28)を Linux で使うには、Interface 0 からドライバを外す手段が要る。候補は 3 つ。
  - udev の規則を配る(root が 1 回要る)。
  - `python -m nanopynq doctor` を先に 1 回実行する。いまも結果として外れるが、その副作用に頼ることになる。
  - ページの `Unable to claim interface` に、Linux 向けの案内を出す。

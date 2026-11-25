# Tang Nano 4K のカメラ（静止画）の受け入れ（設計書 4.13）2026-11-03

## 結論
- ノートブックで `Overlay("camera", board="tangnano4k")` を開き、`Camera(ol.cam_i2c, ol.cam_capture, ol.cam_dvp)` を組み立てると、`cam.start()` の後の `cam.snapshot()` で 160×120 のグレーの画像が表示された。被写体（明るい照明と、斜めに走る物の縁）が判別できた。
- 20 枚を続けて撮り、毎回 19200 バイトで、あふれは無かった。1 枚あたり約 0.59 秒。そのうち 19.2 kB の読み出しが 0.40 秒で、残りは次のフレームを待つ時間。
- 部品は汎用の IP（`i2c_master`、`capture`）と DVP の前段に分かれている。カメラの組み立てはノートブックで行い、階層化の仕組みは作っていない（ユーザーの決定）。
- OV2640 の初期化表と解像度の計算は esp32-camera（コミット 281d951）から移植した（`THIRD_PARTY_NOTICES.md`）。初期化表は Espressif の Apache-2.0、解像度の計算とレジスタの名前は OpenMV（Ibrahim Abdelkader）の MIT のファイルから来ている。OpenMV の LICENSE のファイルは上流から取れなかった（404）ので、ファイルの冒頭の著作権表示に MIT の標準の許諾文を合わせて同梱した。

## 1. 作ったもの
| 部分 | ファイル | 中身 |
|---|---|---|
| FPGA | `gateware/rtl/base_regs.v` | 外付けのスレーブの口（`ext_hit`、`ext_dat_r`、`ext_ack`）。土台の top はすべて 0 につなぐ |
| FPGA | `gateware/rtl/i2c_master.v` | バイト単位の命令（START、STOP、WRITE、READ）。ホストは busy を読んで待つ |
| FPGA | `gateware/rtl/dvp_frontend.v` | XCLK（27 MHz の 2 分周）を出す。行ごとに全部・偶数番目・奇数番目のバイトを残す。どちらの VSYNC の極性をフレームとみなすかを選ぶ。VSYNC の回数を数える |
| FPGA | `gateware/rtl/capture.v` | 2 つのクロックで使う 32 ビット幅の BSRAM に 1 フレームを貯める。読み出し窓は、読んでも中身が変わらない。あふれたら印を立てる |
| FPGA | `gateware/boards/tangnano4k/camera_top.v`、`camera.cst` | 4K の土台に上の3つを足したオーバーレイ |
| ホスト | `drivers/i2c.py`、`capture.py`、`dvp.py` | 汎用のドライバ |
| ホスト | `sensors/ov2640.py` | OV2640（esp32-camera の移植） |
| ホスト | `camera.py` | `Camera`（組み立て）と `Frame`（標準ライブラリだけで PNG にしてノートブックに表示） |
| 通信路 | `transport/jtagbridge.py` | 1 回の USB の往復で最大 100 語をまとめて送る（毎秒約 12600 語） |
| 例 | `examples/03_camera_tangnano4k.ipynb` | 実機で上から実行した |

アドレス: `cam_i2c` 0x3000、`cam_dvp` 0x4000、`cam_capture` 0x10000（窓は +0x8000、20480 バイト）。

## 2. 実機の結果（Tang Nano 4K、Windows 11）
- ビルド: 2 回作って同じハッシュになった。BSRAM 10/10、PLL は使っていない、GW_JTAG 1/1。PCLK 側の最大周波数は 100 MHz 前後で、PCLK（数 MHz の見込み）に対して十分な余裕がある。
- Y がどちらのバイトか: 偶数番目は 0〜255 に広がり（標準偏差 51）、奇数番目は 92〜146 で 128 のまわりに集まった（標準偏差 3.8、色差）。Y は偶数番目で、`Camera` の既定値もそれにした。
- 全部のバイトを残すと 38400 バイトでバッファを超え、`CaptureOverflow` になった（設計どおり）。
- `start()` の直後の 1 枚は暗い（明るさの平均 79。2 枚目以降は 130 前後）。自動露出が落ち着くまでの差で、捨てずにノートブックで説明した。
- 土台（`base_regs` を変えたので作り直した）の負荷試験は 500 回で失敗 0 件。

## 3. 途中で分かったこと
- **VSYNC の極性**: P0（初期化の前）では VSYNC はフレームの間に短い High のパルスを出していた。ところが esp32-camera の初期化表の後は、フレームの間ずっと High で、区切りが短い Low になった（High が約 9 割）。最初の版は P0 の極性を前提にしていたので、0 バイトしか取り込めなかった。`dvp_frontend` の CTRL の bit3 で極性を選ぶようにし、OV2640 のクラスに「High がフレーム」を持たせた。
- **ホストからの1ビットずつの SCCB**: P0 の試験用デザインで初期化表を流すと 8.6 秒かかった。`i2c_master` を使うと `start()` は約 1.2 秒。

## 4. 確かめられなかったこと
- 色（RGB565 や YUV の色差を使った画像）、QVGA 以上の大きさ、JPEG、PSRAM。どれも範囲外。
- 画像の向きと上下左右。被写体は判別できたが、向きの基準は決めていない（OV2640 の REG04 の反転の設定は esp32-camera の初期化表のまま）。
- 9K の土台の実機。`base_regs` を変えたので作り直したが、9K が手元に無い。
- 画質の調整（露出、ホワイトバランス）。初期化表の既定のまま。

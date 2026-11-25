# P0 評価レポート（Windows PC・実機なし分）

## 結論と要約

- ハードウェア不要の再現ビルド検証は完了。Tang Nano 4K / 9K とも、2 回のビルドで `.fs` の sha256 が完全一致した（Windows 11、毎回別フォルダでビルド）。
- 最終レビュー I1 の修正後の値。Apycula は `.fs` をテキストモードで書くため、Windows では CRLF になり、OS によってバイト列が変わっていた。`build_gowin` が LF に正規化するようにしたので、修正前の値（4K: `62659563...`、9K: `716a15bd...`）は無効。
- 得られた sha256 は同梱の `src/nanopynq/data/designs/<board>-base/manifest.yaml` の値と一致する（4K: `51f4bba2...`、9K: `71498371...`）。確認したのは Windows のみ。Linux での一致は未確認（LF への正規化により一致するはずだが、実測していない）。
- 実機を要する項目（Step 3〜6）は未実施。「実機確認待ち」節にコマンドを用意した。結果は未記入であり、推測で埋めていない。
- 判定（Step 6）は実機結果が揃うまで保留。

## 実施済み: repro_build（Windows、`tools/p0/repro_build.py`）

コマンド: `uv run python tools/p0/repro_build.py --board <board> --runs 2`（I1 修正後に再実行。`.fs` は LF に正規化済み）
対象ソース: `gateware/rtl/*.v` + `gateware/boards/<board>/top.v` + `<board>.cst`（ベースデザイン）。
各 run は別の一時フォルダでビルド。各段の時間は `build_gowin` の `run` フックで計測。

注: 時間はマシンの負荷でばらつく（この再実行では run 2 の方が遅い）。初回の WASM コンパイルの影響は断定しない。時間の比較には使わず、sha256 の一致だけを根拠にする。

### repro_build: tangnano4k

- OS: Windows-10-10.0.26200-SP0
- Python: 3.11.15
- yowasp-yosys: 0.70.0.0.post1259
- yowasp-nextpnr-himbaechel-gowin: 0.11.1.0.post826
- Apycula: 0.32

| run | sha256 | synth [s] | pnr [s] | pack [s] | total [s] |
|---|---|---|---|---|---|
| 1 | `51f4bba233ae2fd2dc5d3d6f2db85b0393c03619265ab3fbbaedea1cd529afcd` | 3.6 | 7.8 | 4.0 | 15.4 |
| 2 | `51f4bba233ae2fd2dc5d3d6f2db85b0393c03619265ab3fbbaedea1cd529afcd` | 10.4 | 10.1 | 14.7 | 35.3 |

Result: REPRODUCIBLE (all sha256 identical)

### repro_build: tangnano9k

- OS: Windows-10-10.0.26200-SP0
- Python: 3.11.15
- yowasp-yosys: 0.70.0.0.post1259
- yowasp-nextpnr-himbaechel-gowin: 0.11.1.0.post826
- Apycula: 0.32

| run | sha256 | synth [s] | pnr [s] | pack [s] | total [s] |
|---|---|---|---|---|---|
| 1 | `71498371e9c0032b1008b550298b9bdf0a91ae61bee424b81f87a43baa294d55` | 3.6 | 6.6 | 3.5 | 13.7 |
| 2 | `71498371e9c0032b1008b550298b9bdf0a91ae61bee424b81f87a43baa294d55` | 9.7 | 7.2 | 4.0 | 21.0 |

Result: REPRODUCIBLE (all sha256 identical)

## 実機確認待ち

以下は未実施。**実機（Tang Nano 4K / 9K）が手元に届いてから**、ユーザーが実行して結果を記入する。
(a)〜(f) の各項目は Windows と Linux の両方で記録する（Linux 環境は未構築）。

### 共通の準備

PowerShell（Windows）:

```powershell
# openFPGALoader を使うセッションごとに PATH を通す
$env:PATH = "$env:OSS\bin;$env:OSS\lib;$env:PATH"
openFPGALoader --Version
cd <nanopynq を clone したフォルダ>
uv sync --extra build
```

bash（Linux）:

```bash
cd nanopynq && uv sync --extra build   # openFPGALoader は distro / oss-cad-suite のものを PATH に置く
```

同梱ベースデザインの書き込み先ビットストリーム: `src/nanopynq/data/designs/<board>-base/base.fs`
LED 点滅確認用のビットストリーム（`gateware/boards/<board>/blinky.v`）のビルド:

```powershell
uv run python -c "from pathlib import Path; from nanopynq.boards import get_board; from nanopynq.build.gowin import build_gowin; b='tangnano4k'; print(build_gowin([Path(f'gateware/boards/{b}/blinky.v')], Path(f'gateware/boards/{b}/blinky.cst'), get_board(b), Path(f'build/blinky-{b}')))"
```

（bash でも同じ 1 行でよい。`b='tangnano9k'` に替えれば 9K 用。）

### Step 3: Tang Nano 4K（Linux）

```bash
uv run python tools/p0/repro_build.py --board tangnano4k --runs 3      # 期待: 3 回とも同じ sha256
openFPGALoader -b tangnano4k build/blinky-tangnano4k/top.fs            # 期待: LED が点滅
python -m serial.tools.list_ports -v                                   # 出力を記録
# 外付け USB-UART をつなぐ（配線は下記「4K の外付け USB-UART の配線」。ベースデザインを書き込んだ状態で）:
openFPGALoader -b tangnano4k src/nanopynq/data/designs/tangnano4k-base/base.fs
uv run python tools/p0/bench_uart.py --port /dev/ttyUSB0 --baud 115200   # 結果表を記録
```

記録先: `reports/report_p0_tangnano4k_linux.md`

- [ ] sha256 が 3 回とも一致
- [ ] LED が点滅
- [ ] `list_ports -v` の出力を貼付
- [ ] `bench_uart.py` の結果表を貼付

#### 4K の外付け USB-UART の配線

4K のオンボード USB-UART の有無は未確認のため、外付け変換器を前提にする。`gateware/boards/tangnano4k/tangnano4k.cst` の割り当て（`uart_rx` = pin 44、`uart_tx` = pin 46、`clk` = pin 45）に従い、次のようにクロスでつなぐ。

| USB-UART 変換器 | 4K の FPGA ピン | 信号 |
|---|---|---|
| TX | 44 | `uart_rx`（FPGA が受信） |
| RX | 46 | `uart_tx`（FPGA が送信） |
| GND | GND | 共通グラウンド |

**変換器は 3.3 V ロジックに設定する（5 V は禁止）。** 5 V の変換器や 5 V 設定のままつなぐと、3.3 V の FPGA の入力ピンを壊すおそれがある。VCC 線はつながない（4K は USB から給電する）。

### Step 4: Tang Nano 4K（Windows）

```powershell
uv run python tools/p0/repro_build.py --board tangnano4k --runs 2      # 実施済み（上表）
openFPGALoader -b tangnano4k build\blinky-tangnano4k\top.fs
python -m serial.tools.list_ports -v
Get-PnpDevice -PresentOnly | ? InstanceId -match "VID_0403"            # Zadig の前
# Zadig で Interface 0 だけを WinUSB にする
Get-PnpDevice -PresentOnly | ? InstanceId -match "VID_0403"            # Zadig の後
uv run python tools\p0\bench_uart.py --port COM5 --baud 115200         # COM 番号は list_ports で確認
```

記録先: `reports/report_p0_tangnano4k_windows.md`

- [ ] Zadig 前後の `Get-PnpDevice` 出力を貼付
- [ ] 外付け USB-UART での bench 結果を貼付

### Step 5: Tang Nano 9K（届いたら、Linux と Windows の両方）

事前に 9K のベースデザインを書き込む。

```powershell
openFPGALoader -b tangnano9k src\nanopynq\data\designs\tangnano9k-base\base.fs
python -m serial.tools.list_ports -v
Get-PnpDevice -PresentOnly | ? InstanceId -match "VID_0403"
```

```bash
openFPGALoader -b tangnano9k src/nanopynq/data/designs/tangnano9k-base/base.fs
python -m serial.tools.list_ports -v
```

- [ ] **(a) オンボード UART で ID（0x4E505131）が読めるか**（2 台とも）

  ```powershell
  uv run python -c "import serial; from nanopynq.transport.uartbone import UARTBone; p=serial.Serial('COM5',115200,timeout=0.5); print(hex(UARTBone(p,115200).read(0)))"
  ```
  ```bash
  uv run python -c "import serial; from nanopynq.transport.uartbone import UARTBone; p=serial.Serial('/dev/ttyUSB1',115200,timeout=0.5); print(hex(UARTBone(p,115200).read(0)))"
  ```
  （9K のオンボード FT2232 は 2 ポート。UART 側のポートを `list_ports -v` で確認すること。）

- [ ] **(b) 書き込み → UART を開く → もう一度書き込む、で抜き差しが要るか**
  上記 (a) の後、ポートを閉じてから `openFPGALoader -b tangnano9k ...base.fs` を再実行し、成功するか。毎回の抜き差し（USB の再接続）が必要かを記録する。

- [ ] **(c) 3 種類のボーレートでの速度**
  `top.v` の `.BAUD(115200)` をボーレートごとに書き換え、**`build/` 配下へ** `build_gowin` でビルドして、その `.fs` を書き込んでから測る。
  **`tools/build_base.py` は使わない**（同梱デザイン `src/nanopynq/data/designs/<board>-base/` の `base.fs` と `manifest.yaml`（sha256）を上書きし、`tests/test_bundled_designs.py` が壊れ、後続の手順が別デザインを書き込むことになる）。
  `build_gowin` には parameter 上書き機能が無いため `top.v` を編集する。bench は一致しないボーレートを "no response" と表示する。

  ```powershell
  # 例: 9K を 1000000 baud で測る（3000000 も同様に値を替える）
  $b = "tangnano9k"; $baud = 1000000
  (Get-Content gateware\boards\$b\top.v -Raw) -replace '\.BAUD\(115200\)', ".BAUD($baud)" | Set-Content gateware\boards\$b\top.v -NoNewline
  uv run python -c "import sys; from pathlib import Path; from nanopynq.boards import get_board; from nanopynq.build.gowin import build_gowin; b=sys.argv[1]; g=Path('gateware'); print(build_gowin(sorted((g/'rtl').glob('*.v'))+[g/'boards'/b/'top.v'], g/'boards'/b/f'{b}.cst', get_board(b), Path(f'build/{b}-baud{sys.argv[2]}')))" $b $baud
  openFPGALoader -b $b build\$b-baud$baud\top.fs
  uv run python tools\p0\bench_uart.py --port COM5 --baud $baud
  git restore gateware\boards\$b\top.v          # 測定後に必ず top.v を元に戻す
  ```
  ```bash
  b=tangnano9k; baud=1000000
  sed -i "s/\.BAUD(115200)/.BAUD($baud)/" gateware/boards/$b/top.v
  uv run python -c "import sys; from pathlib import Path; from nanopynq.boards import get_board; from nanopynq.build.gowin import build_gowin; b=sys.argv[1]; g=Path('gateware'); print(build_gowin(sorted((g/'rtl').glob('*.v'))+[g/'boards'/b/'top.v'], g/'boards'/b/f'{b}.cst', get_board(b), Path(f'build/{b}-baud{sys.argv[2]}')))" $b $baud
  openFPGALoader -b $b build/$b-baud$baud/top.fs
  uv run python tools/p0/bench_uart.py --port /dev/ttyUSB1 --baud $baud
  git restore gateware/boards/$b/top.v            # 測定後に必ず top.v を元に戻す
  ```
  115200 は同梱ベース（`base.fs` を書き込み済み）でそのまま測れる:
  `uv run python tools\p0\bench_uart.py --port COM5 --baud 115200`
  測定後は同梱ベースを書き込み直してから (d) 以降へ進むこと。

  結果の表（`baud | 1-word reads [/s] | 255-word burst [kB/s]`）を貼付する。

- [ ] **(d) LED とボタンの極性**
  `top.v` は active-low 想定（未確認）。LED が 0 書き込みで点灯するか、ボタン押下で 0/1 どちらが読めるかを記録する。
  確認したら `gateware/boards/tangnano9k/top.v` と `boards.yaml` の値を測定値で確定する。

- [ ] **(e) Zadig の後も COM ポートが残るか**（Windows のみ）
  Interface 0 だけを WinUSB にした後、`python -m serial.tools.list_ports -v` で COM ポート（Interface 1）が残るか、`Get-PnpDevice` の前後で確認する。

- [ ] **(f) 第三者製 PyPI パッケージ `openfpgaloader` で書き込めるか**

  ```powershell
  uv pip install openfpgaloader     # 隔離した環境で試すこと（本体の依存に入れない）
  openfpgaloader-cli -b tangnano9k src\nanopynq\data\designs\tangnano9k-base\base.fs
  ```
  ```bash
  uv pip install openfpgaloader
  openfpgaloader-cli -b tangnano9k src/nanopynq/data/designs/tangnano9k-base/base.fs
  ```
  書き込めれば、同梱する候補として報告する（設計書 4.6）。

記録先: `reports/report_p0_tangnano9k_linux.md` / `reports/report_p0_tangnano9k_windows.md`

### Step 6: 判定ルール（設計書 4.8）

次のどれかに当たったら、**ここで止まり**、ユーザーに報告して最初のボードを Tang Nano 20K または pico-ice に替える判断を仰ぐ。

1. 9K で (a) が 2 台とも失敗する
2. (b) で毎回の抜き差しが必要
3. pip 版のツールチェーンでビルドできない（Windows では repro_build が通っているため、Linux で再確認する）

どれにも当たらなければ、`boards.yaml` の極性（d）とボーレート（c）を測定値で確定して次へ進む。

## 補足・制約

- `bench_uart.py` はボーレート切替に伴うビットストリームの再ビルド・再書き込みを自動化しない（`build_gowin` に Verilog の define / parameter 上書きが無いため、(c) の手順で `top.v` を一時編集し `build/` へビルドする）。
- 本レポート時点の確認範囲: Windows 上の再現ビルド（実行ログは上表）と、`tests/test_bench_uart.py`（フェイクデバイスでの bench ロジック）のみ。openFPGALoader の実機書き込み、シリアル実測は未実施。

# Pyodide と Web Serial の試作(#28)2026-11-20

## 結論
- **(2026-11-21 追記)実機でも確かめた(9.1 章)。** Linux、Chrome 157、Tang Nano 9K で方式 A を動かした。LED とボタンのレジスタの読み書き、3 種類のループの Stop(6 回とも `KeyboardInterrupt`)、止めたあとの再実行が通った。レジスタの読み取り 1 回は 2.02 ms だった。方式 B と Windows は未実施。
- **(2026-11-20)ブラウザの中で、nanopynq の Python をそのまま動かせた。ただし相手は模擬のポートで、実機ではまだ確かめていない(4 章、9 章)。** ページの入力欄に書いた `ol = Overlay("base", board="tangnano9k")`、`ol.leds[0].on()`、`ol.buttons[0].read()`、LED を点滅させるループが、Pyodide の上でそのまま動いた。本物の Chrome 157 を Playwright で自動で操作し、UARTBone のプロトコルに応答する模擬の Web Serial ポートを相手にして確かめた。
- **A(Worker と共有メモリ)も B(JSPI)も成り立った(4 章)。** 「同期的な API と、非同期的な Web Serial のずれ」は、どちらの方法でも越えられた。
- **判断: デザインのページにノートブックのセルを置く方式として、進めてよい。採るのは A。** ただし、実機での 4 項目(9 章)を先に確かめることが条件。A を採る理由は次の 3 つ。
  - A では、ページがいつまでも固まらない。
  - 入出力のない計算のループ(`while True: pass`)も、止めるボタンで止まる。
  - Pyodide で「実験的」とされている `run_sync` に頼らない。

  A の代わりに要るのは、セルを置くページへの HTTP ヘッダ 2 つ(7.1 章)。B はヘッダを付けられない場所の予備として残せる。ただし B では、入出力のない計算のループのあいだ、タブが固まって止められない(実測で 1.5 秒の計算のあいだ、ページのタイマーが 1504 ms 止まった)。
- **止めるボタンは、Pyodide の割り込みの仕組みをそのまま使うと効かない場面がある(4.3 章)。** 見つかったのは次の 3 つ。
  - `time.sleep` のループは、A でも B でも止まらなかった。
  - B では、入出力のループでも取りこぼしうる。sleep と同じ `run_sync` を通るためで、入出力のループで取りこぼしたところは見ていない。
  - A では、ときどき `KeyboardInterrupt` ではない別のエラー(`ConversionError`)として届いた。

  ページの側で手当てをしたあとは、A と B のどちらでも、入出力のループが 30 回中 30 回、sleep のループが 15 回中 15 回、`KeyboardInterrupt` で止まった。応答しないボードを待っているあいだも止まったが、止まるのは、読み取りの時間切れ(1 秒)を待ってからになる。
- **nanopynq の本体を変えなくても動いた(5 章、7 章)。** `Overlay(download=False, port=..., open_port=...)` の既存の差し替え口で足りた。勧める変更は 2 つ。
  - 依存に環境マーカーを付ける。付ければ `micropip.install` で入るようになる(確かめた)。
  - `.npq` だけを開けるようにする。今は `download=False` でも `.fs` が要る。(2026-11-26 追記)この変更は入った(5 章の追記)。
- **読み込みの大きさは、転送で 6.7 MB(展開すると 14.0 MB)。時間は、ページを開いてから使えるまで約 2.2 秒(この環境、キャッシュなし)(6 章)。** 時間の大半は、Pyodide 自体の読み込みと初期化(約 1.8 秒)で、キャッシュがあっても約 2.0 秒かかる。
- **往復時間は、模擬のポートでの「上乗せ分」だけを測った(6.2 章)。** レジスタの読み取り 1 回あたり、Python を通すと、JavaScript だけのときより A で 0.16〜0.21 ms、B で 0.32〜0.41 ms 増える(5 回の実行の幅)。実機の往復時間(#21 の JavaScript で 2 ms)に足すと 2.2〜2.4 ms ほどになる見込みだが、これは推定で、実測ではない。

## 1. 作ったもの
- `examples/pyodide/index.html`: 入力欄、「Choose port」「Run」「Stop」の各ボタン、出力。`?mode=a` か `?mode=b` で方式を選ぶ(指定しなければ、ヘッダがあれば A、無ければ B)。
- `examples/pyodide/page.py`: ページの Python の側。中身は次の 3 つ。
  - `WebSerialPort`: pyserial の代わり。`UARTBone` が使う `write` / `read` / `reset_input_buffer` と、`close` を持つ。
  - `overlay_factory`: `Overlay` に `download=False` とポートを渡しておく。
  - `stoppable_sleep`: 止めるボタンが効く `time.sleep`。
  - `stop_check`: B で、止める印を確かめる。
- `examples/pyodide/link.mjs`: Web Serial のポートの上の、バイトの送り口と受け口。`read(n, timeoutMs)` の返し方は pyserial と同じで、時間切れになると n バイトより少なく(空のこともある)返す。
- `examples/pyodide/worker.mjs`: A の Worker。Pyodide を動かし、ポートの操作はページに頼んで、共有メモリで返事を待つ。
- `examples/pyodide/pyload.mjs`: Pyodide と nanopynq を読み込む。A と B の両方が使う。
- `examples/pyodide/serve.py`: nanopynq の wheel を作り、A に要るヘッダを付けてフォルダを配信する。
- `tests/test_pyodide_port.py`: `page.py` を CPython の上で確かめる(偽の link を使う。13 件)。CI でも走る。
- `tests/test_pyodide_page.py`: 本物の Chrome を Playwright で操作し、ページを確かめる(20 件)。Playwright は依存に入れていないので、CI では skip する。
- `tests/js/mock_serial.js`: 模擬の Web Serial ポート。テストだけが、ページのスクリプトより先に差し込む。

## 2. 確かめ方
- 環境: Linux、Google Chrome 157.0.8103.78(ヘッドレス、`--headless=new` 相当)、Playwright 1.64.1、Pyodide 314.0.8(Python 3.14.2、jsDelivr の CDN から)。
- A と B の判定は、すべて本物の Chrome の中で動かした結果による。Node での結果は使っていない。Playwright は Chrome を外から操作しているだけで、Python とページのコードはすべて Chrome の中で動く。
- 模擬のポート(`tests/js/mock_serial.js`)は、本物の `SerialPort` が持つ要素(`open`、`close`、`readable`、`writable`、`getInfo`)だけを持つ。この 5 つが本物の `SerialPort.prototype` にあることも、テストで確かめた。応答は、本物の USB と同じく `write` のあとで少し遅れて届き、さらに 2 つに分かれて届く。こうしないと、「書いた時点でもう応答が届いている」ことに頼る壊れた実装でも、テストを通ってしまう。
- 模擬のポートの応答は、tangnano9k-base を模している。`sys.id` は 0x4E505131、`sys.version` は 1.1、`sys.design_id` は 0xabf78d8c、ボタンは 0b01。

## 3. 「やること」の結果

| 項目 | 結果 |
| --- | --- |
| Pyodide を読み込み、nanopynq を入れる。入らない依存の外し方を記録する | **成功**(3.1 章) |
| Web Serial を呼ぶ通信の層(`write`、`read`、`reset_input_buffer`) | **成功**(模擬のポートで確認。4.1 章) |
| A を試す | **成り立つ**(4.2 章) |
| B を試す | **成り立つ**。ただし入出力のない計算のあいだはタブが固まる(4.2 章) |
| 入力欄の Python を実行し、実機が動くことを確かめる | **模擬のポートでは成功。実機は未実施**(9 章) |
| `Overlay(download=False)` で足りるか。足りない処理をどう外すか | **足りる**。ただし `.fs` が要る(5 章) |
| 実行中に、止めるボタンが効くか | **模擬のポートでは成功**。ページ側の工夫が要った(4.3 章)。**実機は未実施** |
| 測る: 読み込みの大きさと時間 | **測った**(6.1 章) |
| 測る: レジスタの読み書き 1 回の往復時間 | **模擬のポートで上乗せ分だけ測った。実機での往復時間は未実施**(6.2 章) |

## 3.1 Pyodide への導入と、入らない依存の外し方
- pyyaml は Pyodide に同梱されている(6.0.3)。pyserial、pyusb、libusb-package は使わない。nanopynq がこの 3 つを import するのは関数の中だけで、ページは、その関数を通らない経路(5 章)を使う。
- ページでは、依存を入れずに wheel を読み込む: `pyodide.loadPackage(["pyyaml", "<wheel の URL>"])`。この方法なら、本体を変えなくて済む。
- 依存ごと入れようとすると失敗する。`micropip.install("<wheel の URL>")` のエラーは次のとおり(Chrome で実際に出たもの):
  ```
  ValueError Can't find a pure Python 3 wheel for 'libusb-package>=1.0.30'.
  ```
- **依存に環境マーカー(`; sys_platform != 'emscripten'`)を付けると、`micropip.install` だけで入るようになる。** pyproject の一時コピーで wheel を作り、Chrome の Pyodide で確かめた(使い捨てのスクリプト。リポジトリには入れていない)。入ったのは `PyYAML`、`micropip`、`nanopynq` の 3 つで、USB まわりの 3 つは入らなかった。
- wheel の大きさは 377 KB。そのうち 269 KB は、全ボード分のビットストリーム(`.fs`)が占める。展開すると `.fs` だけで 9.7 MB になり、Pyodide のメモリ上のファイルシステムに置かれる。ブラウザで使うのは 9K の 1 つ(428 KB)だけ。

## 4. 通信の層と、A / B

### 4.1 通信の層
ページの JavaScript が Web Serial のポートを持つ。Python の `WebSerialPort` は、ポートの操作をその JavaScript(`link`)に頼む。A と B で違うのは「返事の待ち方」(`wait`)だけ。

| 操作 | A(Worker) | B(JSPI) |
| --- | --- | --- |
| `open` / `close` / `write` / `read` | Worker が共有メモリで止まって待ち、結果がそのまま返る | Promise が返り、`pyodide.ffi.run_sync` で待つ |
| `reset_input_buffer` | 同上 | 同期的(待たない) |

A でも B でも、`Overlay` は「ボードに応答がない」ときに `BoardNotResponding` を出し、ポートを閉じた(模擬のポートを黙らせて確かめた)。応答を戻すと、同じページで開き直せた。ポートが開けないときは `PortOpenError` を出した(CPython のテストで確かめた)。

### 4.2 A と B の構成と、要るもの
- **A**:
  - **構成**: Pyodide は Worker で動かす。Web Serial の入出力は、ページ(メインスレッド)で行う。
    - Worker は、ポートの操作を `postMessage` でページに頼み、`Atomics.wait` で、共有メモリに返事が書かれるのを待つ。
    - ページは、操作が失敗しても必ず返事を書く。書かないと、Worker が待ち続けて止められなくなる。
  - **要るもの**: `crossOriginIsolated` が `true` であること。このために、ページに COOP と COEP のヘッダが要る(7.1 章)。ヘッダなしで A を開くと、ページは「Not loaded」になり、ヘッダが要る旨を出す(テストで確認)。
  - **Web Serial を Worker の中から使えるか**: `navigator.serial.getPorts()` は、Worker の中にもあった(Chrome 157 で確認)。ただし、ポートを選ばせる `requestPort()` はページでしか使えない。また A では、待っているあいだ Worker が止まるので、入出力を Worker の中で行うことはできない。止まったスレッドは、自分の非同期の読み取りを進められないからだ。そのため、入出力はページで行った。Worker の中で Web Serial を使う意味があるのは、入出力だけを受け持つ 2 つ目の Worker を作る場合だけで、今回は要らなかった。
  - **ヘッダの要らない A の変種**: Worker が同期の XHR を投げ、Service Worker がそれを待たせて答える方式がある。共有メモリが要らないのでヘッダも要らない。検証していない代替として挙げておく。
- **B**:
  - **構成**: Pyodide はページで動かす。セルは `runPythonAsync` で走らせ、ポートの Promise は `run_sync` で待つ。
  - **要るもの**: ヘッダは要らない(`crossOriginIsolated` が `false` のまま動くことを確認)。要るのは JSPI(`WebAssembly.Suspending`)で、Chrome 157 にはあった。
  - **制限**:
    - `run_sync` は、Pyodide の資料で「Experimental」とされている。
    - `run_sync` が効くのは、`runPythonAsync` や async 関数から入った呼び出しの中だけ。同期の `runPython` の中では、`can_run_sync()` が `False` を返した(使い捨てのスクリプトで確認)。そのため、ボタンなどのイベントから同期的に呼ばれた Python の関数では、`ol.leds[0].on()` を使えない。
- **ページの応答性**: 1.5 秒の計算(入出力なし)のあいだ、10 ms ごとのタイマーがいちばん長く止まった時間を測った。

  | | A | B |
  | --- | --- | --- |
  | 入出力のない計算のループ | 23 ms(止まらない) | 1504 ms(計算のあいだ固まる。止めるボタンも押せない) |
  | `time.sleep(0.1)` のループ | 22 ms | 24 ms |

### 4.3 止めるボタン
Pyodide の割り込みの仕組み(割り込み用のバッファに SIGINT を書くと、`KeyboardInterrupt` になる)を、そのまま使うと、次のことが起きた。確かめ方は項目ごとに違う。

- 1 と 2: 使い捨てのスクリプトで、各 8 秒待って確かめた。
- 3: 推定。
- 4: レビューの試験と、手当ての前のテストで再現した。


1. **`time.sleep` のループ(`while True: time.sleep(0.1)`)が、A でも B でも止まらない。** Pyodide 0.28 以降の `time.sleep` は、中で `run_sync(asyncio.sleep(t))` を使う(Pyodide の PR #5686)。`KeyboardInterrupt` は Pyodide の asyncio のコード(`webloop.py` の `call_later` など)の中で発生し、トレースバックが出力されるだけで、セルには届かなかった。
2. **sleep ばかりのループでは、割り込みがなかなか届かない。** Pyodide が割り込みを見るのは、Python の命令がある数だけ進むごとらしい。`time.sleep(0.001)` のループは、止まるまで 12 秒かかった。
3. **B では、入出力のループでも取りこぼしうる(推定)。** 入出力のループも、1 と同じく `run_sync` を通る。その中の asyncio のコードで発生すれば、セルに届かないはずだ。ただし、入出力のループで取りこぼしたところは見ていない。手当ての前のテストでは、2 回とも止まった。
4. **A では、`KeyboardInterrupt` が別のエラーとして届くことがある。** Python の bytes を JavaScript へ変換している途中に割り込みが入ると、Pyodide はそれを `pyodide.ffi.ConversionError` に包む。`KeyboardInterrupt` は、その原因(`__cause__`)として残るだけになる。
   - 影響: セルの `except KeyboardInterrupt` では捕まらず、`except Exception` では握りつぶされる。
   - 頻度: レビューの試験で 15 回中 3 回起きた。手当ての前のテスト(10 回)でも再現した。

ページの側でとった手当て(`page.py`):
- **`time.sleep` の差し替え**: 50 ms ずつ JavaScript で待ち、そのたびに止める印を確かめる。A では Worker を `Atomics.wait` で止め、`pyodide.checkInterrupt()` を呼ぶ。B では Promise を `run_sync` で待つ。
- **B での止め方**: Pyodide の割り込み用のバッファは使わない。ページの印を、Python の側から確かめる。確かめる場所は、各通信の始め(`reset_input_buffer`)と、sleep の 50 ms ごと。通信の途中では止めない。途中で止めると、まだ届いていない応答のバイトが、次の通信の読み取りに混ざりうるからだ。CPython のテストで確かめたのは、通信と通信の間でだけ止まること。混入そのものは再現していない(レビューの 15 回でも出なかった)。
- **別のエラーに包まれた割り込みを戻す**: ポートの操作と sleep で、原因(`__cause__`)が `KeyboardInterrupt` のエラーが出たら、`KeyboardInterrupt` として投げ直す(4 の手当て)。
- **止めたあとの再実行**: 止めたセルは `ol.close()` まで進まないので、ポートが開いたまま残る。手当ての前は、そのままセルを実行し直すと、`Overlay(...)` が `PortOpenError` になった。そこで、ポートが開いていれば、ページの `link` がいったん閉じてから開き直すようにした。CPython の Linux では同じポートを 2 回開けるので、それと同じ振る舞いになる。
  - 残る制限: 古い `ol` の `close()` を呼ぶと、新しい `ol` のポートも閉じる。

手当てのあとの結果。回数は、テストを 3 回走らせた合計で、出力の最終行が `KeyboardInterrupt` だった回数。時間は、そのうち 1 回の実行(入出力は 10 回、sleep は 5 回)で、押してから「Ready」に戻るまで。Playwright の操作の時間を含む。

| ループ | A | B |
| --- | --- | --- |
| LED を切り替え続ける(入出力のループ) | 30/30、68〜69 ms | 30/30、68〜69 ms |
| `time.sleep(0.1)` を続ける | 15/15、64〜83 ms | 15/15、47〜49 ms |
| 入出力のない計算 | 止まった | 止められない(ページが固まる) |
| 応答しないボードを待っているあいだ(`Overlay(...)` の照合中) | 止まった、532 ms | 止まった、1036 ms |

応答しないボードを待っているあいだに止めると、読み取りの時間切れ(1 秒)を待ってから止まる。Overlay の再試行が終わるまで(約 4 秒)は待たない。
- A: Python はすぐ止まる。Worker は、押してから 14 ms で印に気づいた(一時的に記録を足して確かめた)。ただ、そのあと `Overlay` がポートを閉じる。ページはポートの操作を 1 つずつ順に受けるので、この `close()` は、時間切れを待っている読み取りのあとになる。
- B: 印を確かめるのは次の通信の始め。そのため、読み取りの時間切れと、nanopynq の再試行の待ち(0.5 秒)を過ぎてから止まる。

残ること:
- A では、割り込みは Pyodide の仕組みのままなので、通信の途中で止まることがある(CPython で Ctrl-C を押したときと同じ)。
- セルの中で `await asyncio.sleep()` を使うループは、B で止まらなかった(使い捨てのスクリプトで確認。A は試していない)。1 と同じ理由と見られる。
- 1、2、4 は Pyodide 側の振る舞いで、上流に報告する候補。
- A には、最後の手段として Worker を作り直す方法(`worker.terminate()`)もある。止めるボタンが効かない場合や、Worker が止まったまま戻らない場合のためのもの。実装も検証もしていない。

## 5. `Overlay(download=False)` で足りるか
足りた。nanopynq の本体は変えていない。ページは `Overlay` に次の 3 つを渡しておく(`page.overlay_factory`)。
- `download=False`: openFPGALoader の呼び出し(`program_sram`)を通らない。
- `port="webserial"`: ポートを探す処理(`find_port`。中で pyserial の `list_ports` を import する)を通らない。
- `open_port=...`: pyserial の `Serial` の代わりに、`WebSerialPort` を開く。ボーレートは `.npq` の値(115200)が渡される。`ol.close()` でポートも閉じる。

ファイルの読み込みは、そのまま動いた。同梱のデザインは wheel の中にあり、Pyodide のメモリ上のファイルシステムから読める。ただし、`.npq` の読み込みは、`download=False` でも `.fs` の sha256 を照合する(V12)。そのため、`.fs` が無いとエラーになる。`.npq` だけを置いて開いたときのエラー(Chrome で実際に出たもの):
```
NpqError V12 at bitstream.sha256: base.fs: not found
```
FabricGate のページで、`.npq` だけを渡して開く使い方をするなら、7.2 章の 2 の変更が要る。

(2026-11-26 追記)7.2 章の 2 の変更は入った。`download=False` では `.fs` を読まず(`load_npq(check_bitstream=False)`、仕様 5.7 の 3)、デザインは `sys.design_id` で照合する。ページの `Overlay` は `.npq` だけで開き、上のエラーは出ない。開いたときの `manifest.sha256` は `None` になる。ボードの `sys.design_id` が違えば `DesignMismatch` になる。どちらも `tests/test_pyodide_page.py` の `test_a_npq_opens_without_its_fs` で確かめている。

## 6. 測定

### 6.1 読み込みの大きさと時間(Chrome 157、この環境のネットワーク)
「キャッシュなし」は、Playwright の新しいコンテキスト(HTTP キャッシュが空)で開いた結果。「キャッシュあり」は、同じコンテキストでもう一度開いた結果。時間は、ページの読み込みが始まってから「Ready」になるまで。

| | A キャッシュなし | A キャッシュあり | B キャッシュなし | B キャッシュあり |
| --- | --- | --- | --- | --- |
| Pyodide の読み込みと初期化 | 1790 ms | 1645 ms | 1779 ms | 1760 ms |
| pyyaml と nanopynq の wheel | 181 ms | 177 ms | 218 ms | 185 ms |
| `page.py` と `import nanopynq` | 142 ms | 150 ms | 161 ms | 141 ms |
| 「Ready」まで | 2186 ms | 2007 ms | 2211 ms | 2107 ms |
| 転送したバイト数 | 6.73 MB | 0 | 6.74 MB | 0 |
| 展開後の大きさ | 14.0 MB | 14.0 MB | 14.0 MB | 14.0 MB |

ファイルごと(転送 / 展開後): `pyodide.asm.wasm` 3.44 MB / 9.60 MB、`python_stdlib.zip` 2.51 MB / 2.55 MB、`pyodide.asm.mjs` 262 KB / 1.25 MB、nanopynq の wheel 377 KB、pyyaml の wheel 112 KB、`pyodide-lock.json` 25 KB / 119 KB、そのほか数 KB。A の数値には、Worker のモジュールのスクリプト(`worker.mjs`、`pyload.mjs`、`pyodide.mjs`。計 11 KB ほど)が入っていない。リソースの記録に現れなかったため。

注意:
- この環境のネットワークは速く、キャッシュがあってもなくても、時間の差は 0.2 秒ほどしかない。遅い回線では、6.7 MB の転送の時間が加わる。たとえば 10 Mbps なら、約 5 秒増える(計算による見積もり)。
- キャッシュがあっても約 2 秒かかるのは、WebAssembly のコンパイルと Python の初期化のため。

### 6.2 往復時間の上乗せ分(模擬のポート、応答の遅れなし)
`ol.sys.read(0x8)` を 300 回くり返した 1 回あたりの時間と、同じ模擬のポートと同じ `link.mjs` を使って、JavaScript だけで同じフレームを送って読んだ時間を比べた。表はある 1 回の実行の値。上乗せ分の幅は、レビューの実行を含めて 5 回の実行で見た範囲。

| | Python(nanopynq) | JavaScript だけ | 上乗せ分(この実行) | 上乗せ分の幅(5 回) |
| --- | --- | --- | --- | --- |
| A | 0.181 ms | 0.021 ms | 0.16 ms | 0.16〜0.21 ms |
| B | 0.397 ms | 0.019 ms | 0.38 ms | 0.32〜0.41 ms |

1 回の読み取りで、Python はポートを 3 回呼ぶ(`reset_input_buffer`、`write`、`read`)。A では、3 回ともスレッドをまたいで返事を待つ。実機の往復時間は、未実施。

## 7. サイトの側に要る設定と、その影響、本体に要る変更

### 7.1 HTTP ヘッダ(A に要る)
A には、`crossOriginIsolated` が `true` であることが要る。そのために、セルを置くページに次の 2 つのヘッダを付ける。
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Embedder-Policy: credentialless`(または `require-corp`)

ヘッダはページごとに付けられるので、サイト全体に付ける必要はない。COEP の値ごとに、ほかのサイトの資源がどう読み込まれるかを、Chrome で確かめた。
- 相手のサイト: CORP ヘッダを付けない、別のポートのサーバー。
- 確かめた読み込み方: `fetch(url, { mode: "no-cors" })` だけ。画像やスクリプトの要素も、仕様では同じ検査を通るが、要素では試していない。

| COEP | `crossOriginIsolated` | CORP を付けないサイトの資源 |
| --- | --- | --- |
| なし | false | 読める |
| `require-corp` | true | **読めない** |
| `credentialless` | true | 読める |

- `credentialless` を勧める。
  - 仕様では、Cookie を付けずに取りに行くので、Cookie の要らない外部の資源はそのまま読める。Cookie を付けずに送っていることは、測っていない。
- Pyodide の CDN(jsDelivr)は、どちらの値でも読めた。
  - `credentialless`: テストで確かめた。
  - `require-corp`: 最初の使い捨てのスクリプトで確かめた。
  - jsDelivr は、`access-control-allow-origin: *` と `cross-origin-resource-policy: cross-origin` を返す(curl で確認)。
- 影響の残るもの(試していない):
  - 外部の iframe(動画の埋め込みなど): `<iframe credentialless>` か、埋め込まれる側の対応が要る。
  - COOP `same-origin`: 別のサイトのポップアップとの `window.opener` を使ったやり取り(OAuth のログインのポップアップなど)が切れる。
  - Cookie が要る外部の資源: 上の表の範囲を外れるので、読み込めるかは分からない。
- B にはヘッダは要らない。

### 7.2 nanopynq の本体に要る変更(勧めるもの。今回はしていない)
1. **依存の分け方**: `pyserial`、`pyusb`、`libusb-package` に `; sys_platform != 'emscripten'` を付ける。付ければ、`micropip.install` が依存ごと通る(3.1 章で確認)。付けなければ、今回のように依存を入れずに読み込む必要がある。
2. **`.npq` だけで開く**: `download=False` のときは `.fs` の sha256 の照合(V12)を飛ばし、デザインの照合を `sys.design_id` に任せる。この変更をしないなら、ページでは `.fs` も一緒に渡す必要がある(9K の base で 428 KB)。仕様(V12)の変更を伴うので、別の issue で決める。(2026-11-26 追記)入った(5 章の追記)。
3. **通信の層の差し替え口**: 今の `open_port=`(と `transport=`)で足りた。公開の API として残すなら、名前と型を決めて、文書に書く。`page.py` の `WebSerialPort` を `nanopynq.transport` に移すかは、セルを FabricGate に組み込むときに決めればよい。
4. **(小さい)ブラウザでは使わない `.fs` を wheel から外せる**: ブラウザ向けの配布で 269 KB(展開後 9.7 MB)減る。
5. **(小さい)ポートが開けないときの案内**: ブラウザでは、Linux 向けの「dialout のグループに入っていない」という案内が出る。Pyodide では `sys.platform` が `emscripten` で、`overlay._open_hint()` が Linux の案内を選ぶためだ。
   - いつ起きたか: 手当ての前のページで、止めたセルを実行し直したとき(4.3 章)。
   - 手当てのあと: ページの側で開き直すようにしたので、この経路では出なくなった。
   - 残る経路: 開くのに失敗したときは、同じ案内が出る。
   - 直し方: ブラウザ向けの案内を足す。

## 8. 対応するブラウザ
- 確かめたのは、Linux の Chrome 157(ヘッドレス)だけ。
- Web Serial があるのは、Chromium 系のデスクトップのブラウザだけ(Firefox / Safari には無い。#21 と同じ)。
- A は、`SharedArrayBuffer` と COEP `credentialless` を使う。`credentialless` は Chrome 96 から使える([Chrome の記事](https://developer.chrome.com/blog/coep-credentialless-origin-trial)、[caniuse](https://caniuse.com/mdn-http_headers_cross-origin-embedder-policy_credentialless))。
- B は JSPI を使う。JSPI は、Chrome 137 から既定で有効と、第三者の記事([OpenReplay](https://blog.openreplay.com/jspi-javascript-wasm-bridge/))にある。公式の資料では、Chrome 123〜128 の origin trial までしか確かめていない([V8 の記事](https://v8.dev/blog/jspi-ot))。
- Chrome 157 より前の版と、Edge、Windows、macOS、Android は、確かめていない。

## 9. 実機で確かめる手順(Linux の方式 A は 2026-11-21 に実施。結果は 9.1 章)
2026-11-20 は実機(Tang Nano 9K)をつないでいなかった(`lsusb` に出なかった)。2026-11-21 に、Linux で方式 A の 1〜6 を行った(9.1 章)。7(方式 B)と Windows は未実施。

1. ボードに base デザインを書き込む: `uv run python -c 'from nanopynq import Overlay; Overlay("base", board="tangnano9k").close()'`。書き込んだら、ポートを閉じる。USB は抜かない。抜くと SRAM のデザインが消える。
2. `uv run python examples/pyodide/serve.py` を起動し、Chrome で `http://127.0.0.1:8000/?mode=a` を開く。「Ready」になるまで待つ。
3. 「Choose port」で、9K のポートを選ぶ。Linux では 2 つ出るうちの後ろ、Windows では 1 つ(#21、#50)。
4. **LED とボタン**: 入力欄の初めの例をそのまま「Run」する。確かめることは次の 3 つ。
   - LED 0 が点く。
   - `button 0:` の値が、ボタンを押しているかどうかで変わる。ボタンを押したまま Run したときと、離して Run したときで比べる。
   - LED 1 が 0.2 秒ごとに点滅する(10 回)。
5. **止めるボタン**: 次のセルを「Run」し、「Stop」を押す。`KeyboardInterrupt` が出て「Ready」に戻ること。そのあと `ol.leds[0].on()` が効くことも確かめる。
   - `ol = Overlay("base", board="tangnano9k")` に続けて、`while True: ol.leds[0].toggle()`
   - `while True: time.sleep(0.1)`
6. **往復時間**: 次を Run し、表示された値を記録する。JavaScript だけのときの 2 ms(#21)と比べる。
   ```python
   import time
   ol = Overlay("base", board="tangnano9k")
   t = time.perf_counter()
   for _ in range(300):
       ol.sys.read(0x8)
   print((time.perf_counter() - t) / 300 * 1e3, "ms")
   ol.close()
   ```
7. 2〜6 を、`?mode=b` でもくり返す(`serve.py --coep none` で配信すれば、ヘッダなしで確かめられる)。

### 9.1 結果(2026-11-21、Linux、方式 A)
- 環境: Linux、Google Chrome 157.0.8103.78、Tang Nano 9K(base デザイン、sysinfo の ID `0x4E505131`)、`serve.py --port 8765`。Chrome は新しいプロファイルで開き、CDP で操作した。ポートの選択の画面だけは、画面を撮って XTest で選んだ。
- ポートの選択の画面に出たのは「JTAG Debugger(ttyUSB1)」の 1 つだけだった(3 で書いた「Linux では 2 つ」とは違った)。
- **LED とボタン**: `ol.leds[0].on()` のあと、leds のデータのレジスタは `0x1` を読み返した。`ol.buttons[0].read()` は `0` を返した。LED 1 を 10 回反転させたあと、データは `0x1` に戻った。LED の見た目と、ボタンを押したときの値の変化は、人の目と手が要るので確かめていない。レジスタの読み返しで代えた。
- **止めるボタン**: 次の 3 つのループを、それぞれ 2 回ずつ Run し、1.5〜2 秒後に Stop を押した。6 回とも `KeyboardInterrupt` が出て、「Ready」に戻った。
  - 入出力のループ(`while True: ol.leds[0].toggle()`)。1 回目は書き込みの途中、2 回目は読み取りの途中で止まった。
  - `while True: time.sleep(0.1)`(`stoppable_sleep` の中の `checkInterrupt` で止まった)
  - 計算だけのループ(`while True: pass`)
- **止めたあと**: 同じセルをもう一度 Run できた。全部のあとで `ol.leds[0].on()` が効き、sysinfo の ID も読めた。止めた直後の読み書きが、残った応答とずれることはなかった。
- **往復時間**: レジスタの読み取り 1 回が 2.024 ms(200 回の平均)。JavaScript だけのときの 2 ms(#21)と、ほぼ変わらない。書き込みは 0.093 ms(応答を待たないため)。200 回の書き込みのあと、scratch は最後の値 199 を読み返した。
- **書き込みとの関係**: Python から書き込んだ直後(`Overlay("base", board="tangnano9k")`)は、sysinfo の ID が返らず `BoardNotResponding` になった。`download=False` で開き直すと読めた。書き込み直後に 1 回だけ UART が答えない現象に見える。

## 10. 再現の手順
- CPython 上のテスト(CI でも走る): `uv run pytest -q tests/test_pyodide_port.py`
- Chrome を使うテスト。Chrome、ネットワーク(Pyodide の CDN)、Playwright が要る。数値は `MEASURE` の行に出る。
  ```
  uv run --with playwright==1.64.1 pytest -s tests/test_pyodide_page.py
  ```
  結果: 20 passed(2026-11-20)。Playwright は、システムの Chrome(`/usr/bin/google-chrome` など)を使う。ブラウザのダウンロードは要らない。
- 次の 4 つは、使い捨てのスクリプトで確かめたので、リポジトリには残していない:
  - 止めるボタンが Pyodide のままでは効かないこと(4.3 章の 1〜3。4 は、手当ての前のテストで再現した)
  - 環境マーカーを付けた wheel(3.1 章)
  - `runPython` の中では `can_run_sync()` が `False` になること(4.2 章)
  - COEP `require-corp` の下でも、jsDelivr から Pyodide を読み込めること(7.1 章)

  4.3 章の 1〜3 は、`page.py` の手当てを外し、`while True: time.sleep(0.1)` を Run して Stop を押せば再現する。

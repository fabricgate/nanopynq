# WebUSB で、ブラウザからの書き込みと 4K / 20K の操作ができるか(#23、2026-11-19、20K と 9K)

## 結論
- **書き込み(SRAM)は、できる(条件つき)。** Tang Nano 20K と 9K に、Chrome(Windows)から `.fs` を SRAM へ書き込めた。openFPGALoader は使っていない。
  - 条件: Chromium 系のブラウザであること。確かめたのは、Windows で Interface 0 のドライバを WinUSB(Zadig)にした状態だけ。これは nanopynq が JTAG を使うときと同じ設定。既定のドライバのままで動くかは確かめていない(5 章)。
  - 時間(20K): 同梱の base(108 KB)が 0.80 s、SDRAM のデザイン(577 KB)が 4.17 s。openFPGALoader(0.45 s、1.91 s)の 1.8〜2.2 倍かかる。遅い理由の推定は 3 章。
  - 時間(9K): 同梱の base が 0.45 s、作り直す前の base が 0.48 s。
  - 4K と Linux は確かめていない(5 章)。
- **9K では、WebUSB(Interface 0)で書き込みながら、Web Serial(Interface 1)で操作できる。** 2 つのタブで確かめた。
  - タブ A: WebUSB で Interface 0 をつかんだまま、`.fs` を書き換えた。
  - タブ B: Web Serial のページ(#33)で COM ポートにつないだ。
  - 古い回路(sysinfo 1.0)を書き込んだあとは、タブ B が理由を出してつながずに止まった。今の base に書き換えたあとは、照合が通り、LED を操作できた。
  - 抜き差しは要らなかった。JTAG で書き込んだあとに、UART がそのまま使えた。
- **JTAG でつなぐボードの操作は、できる(条件つき: 20K で確かめた。4K は確かめていない)。** 同じページから、JTAG ブリッジで `sys` のレジスタを読めた。
  - 1 回の読み取りの往復は 0.54〜0.61 ms。Python は 0.40 ms で、その 1.4〜1.5 倍。Python の値は、同じ 20K で `Overlay` の `sys.read(0)` を 200 回読んだときのもの(`docs/plan_design_metadata_experiments.md` の 2026-11-19 の 20K の行)。
  - 4K は、基板が故障中で確かめていない。ページは、BL702(4K)で確かめた MPSSE の命令の組(`src/nanopynq/transport/mpsse.py` の冒頭)だけを使っていて、その組が BL616(20K)でも通った。なので 4K でも同じ形で動く見込みだが、確かめてはいない。
- **ブラウザの中に要る実装は小さい。** `examples/webusb/jtag.js` の 301 行(約 12 KB)に、次の 3 つが入る。
  - MPSSE と JTAG の層
  - nanopynq の JTAG ブリッジ
  - Gowin の SRAM への書き込み
- **ブラウザが Interface 0 を開いているあいだは、Python(nanopynq の `Mpsse`)はボードを開けない。** 試したときのエラーは `Access denied`。ページで Disconnect したあとは、Python から開けた(そのまま IDCODE などを読んだ)。openFPGALoader も同じ libusb で開くので同じになる見込みだが、試していない。

## 1. 作ったもの
| ファイル | 中身 |
|---|---|
| `examples/webusb/jtag.js` | 3 つの部分からなる。<br>(1) WebUSB の MPSSE。`transport/mpsse.py` と同じバイト列を作る。<br>(2) JTAG ブリッジのクライアント。`transport/jtagbridge.py` と同じ。<br>(3) `.fs` の読み取りと、Gowin の SRAM への書き込みの手順。 |
| `examples/webusb/index.html` | 試作のページ。つなぐ、IDCODE を読む、`sys` を読む、`.fs` を SRAM に書き込む、切る、の 5 つの操作がある。`file://` で開ける。 |
| `tests/test_webusb_js.py` | Node で次の 3 点を確かめる。<br>・JS のシフトの符号化と復号、TMS、ブリッジのコマンドが、Python のものと同じ値になること。<br>・`.fs` から作る送信のバイト列が、Python で別に読んだものと同じになること。<br>・TAP を真似た偽の USB 機器で、ビットストリームの全部のビットが Shift-DR の中で順に送られること。失敗した flush のあとに受信を空にすること。 |
| `tools/p0/webusb/gowin_sram.py` | 同じ書き込みの手順を、Python(nanopynq の `Mpsse`)で書いた試作。手順は、ブラウザに移す前にこちらで固めた。 |

書き込みの手順は、openFPGALoader v1.2.0 の Gowin の SRAM の経路(`src/gowin.cpp` の `programSRAM`、`eraseSRAM`、`writeSRAM` と、`src/fsparser.cpp`。Apache-2.0)を読んで、自分で書き直した。コードは写していない。手順は次のとおり。
1. 消去
   1. CONFIG_ENABLE(0x15)を送り、SYSTEM_EDIT_MODE を待つ
   2. ERASE_SRAM(0x05)と NOOP(0x02)を送り、MEMORY_ERASE を待つ
   3. XFER_DONE(0x09)、NOOP、CONFIG_DISABLE(0x3A)、NOOP を送り、SYSTEM_EDIT_MODE が消えるのを待つ
2. 書き込み
   1. CONFIG_ENABLE、INIT_ADDR(0x12)、XFER_WRITE(0x17)を送る
   2. ビットストリームを、1 回の DR スキャンで送る
   3. CONFIG_DISABLE と NOOP を送る
   4. 状態レジスタ(0x41)の DONE_FINAL を見る
3. 命令を送るたびに、Run-Test/Idle で 6 クロックを足す
4. 送るデータ: `.fs` の注釈を除いた全部の行(ヘッダの行も含む)を、8 文字で 1 バイトにする。行の先頭の文字が、線に最初に出る

## 2. 実機での結果(Tang Nano 20K、Windows 11、Chrome)
| 確認 | 結果 |
|---|---|
| つなぐ(`requestDevice` で選び、Interface 0 を確保) | 通った。受信のパケットは 512 バイト(BL616 は High Speed)。開くのにかかったのは 16〜37 ms |
| IDCODE | `0x0000081b`。Test-Logic-Reset の直後の DR から読む(3 章の 1 つ目) |
| `.fs` の書き込み、SDRAM のデザイン | 4.17 s、状態 `0x6020`。そのあと `sys.design_id` は `0x1ef753ef` |
| `.fs` の書き込み、base | 0.80 s、状態 `0x6020`。そのあと `sys.design_id` は `0xabf78d8c` |
| JTAG ブリッジ | `sys.id`、`sys.version` `0x00010001`、`sys.design_id` を読めた。1 回の読み取りの往復は 0.54〜0.61 ms(200 回の平均) |
| ブラウザが開いているあいだの Python | `Mpsse.open` が `Access denied` で失敗した。Disconnect のあとは開けた |

### 2.1 Tang Nano 9K(Windows 11、Chrome、2 つのタブ)
| 確認 | 結果 |
|---|---|
| つなぐ(タブ A、WebUSB) | 通った。受信のパケットは 64 バイト(BL702 は Full Speed)。開くのにかかったのは 33 ms |
| IDCODE | `0x1100481b`(openFPGALoader が表示する `0x0100481b` は、版の 4 ビットを隠した値) |
| 作り直す前の base(sysinfo 1.0)の書き込み | 0.48 s、状態 `0x3f020` |
| タブ B(Web Serial、COM3)でつなぐ | `The board runs sysinfo 1.0 … another or an older design is on the board.` で止まった |
| 今の base の書き込み(タブ A はつないだまま) | 0.45 s、状態 `0x3f020` |
| タブ B でつなぎ直す | `sys.design_id 0xabf78d8c: matches the file`。LED の書き込みも通った |
| Zadig のあとの UART | Interface 0 を WinUSB にしたあとも、COM3 は残っていた(#42 の未確認の点) |

同じ手順の Python の試作でも、9K で、base と作り直す前の base を交互に書き込めた。書き込むたびに、`Overlay(download=False)` で UART から確かめた。今の base は識別値が一致し、作り直す前の base は `DesignMismatch` で止まった。

同じ手順の Python の試作で、先に確かめたこと(20K):
- 同梱の base と SDRAM のデザインを、交互に書き込めた。書き込むたびに、`Overlay(download=False)` で識別値が切り替わったのを確かめた
- 書き込みのあとの状態は `0x6020`。openFPGALoader で書き込んだ直後に、この試作の `--status` で読んだ値も `0x6020` だった
- usercode は、どちらで書き込んだかで変わる
  - この手順(0x0A を送らない): `.fs` のヘッダの CheckSum と同じ値になる。base は `0xac96`、SDRAM のデザインは `0x0a0c`
  - openFPGALoader: 自分で計算したチェックサムを 0x0A で書くので、その値になる。base では `0xa758` で、ヘッダの値と違う(圧縮した `.fs` の読み方の差とみられる。#4 に関係する可能性があるが、確かめていない)。SDRAM のデザイン(圧縮なし)では、ヘッダと同じ `0x0a0c`
  - 確かめ方: 同じ `.fs` を、openFPGALoader とこの手順で交互に書き込み、そのつど usercode を読んだ
- ビットの順を逆にして送ると、FPGA は構成されない(状態 `0x0`、ボードは応答しない)。0x0A を送らない今の手順では、DONE_FINAL が立たず、失敗として止まる

## 3. 分かったこと
- **IDCODE の読み方の訂正。** 最初の版は、IR に 0x11 を入れて読み、`0x00000019` が出た。これを「20K は 0x11 で IDCODE を返さない」と判断したが、誤りだった。
  - 実際は、取り出す値を間違えていた。DR の値ではなく、8 ビットの IR のシフトで返る値(IR の捕捉値)を見ていた。
  - DR の値は、正しく `0x0000081b` だった。
  - いまの実装は、Test-Logic-Reset の直後の DR から読む。`tools/p0/jtag_mpsse_min.py` と同じ読み方で、同じ値になる。
  - コミット `71cf5e8` のメッセージにある「IR 0x11 gives 0x19」は誤り。
- **openFPGALoader が書き込みの最後に送る「0x0A、32 ビットのチェックサム、0x08」は、20K では要らない。** 外しても状態は同じで、usercode は `.fs` のヘッダの CheckSum になる(2 章)。
  - 注意: この手順を入れると、送ったデータが壊れていても DONE_FINAL が立つことがあった。データを Shift-DR の外で送っていた、試作の不具合のときに、同じ壊れ方のデータで比べた。
    - 0x0A なし: 状態 `0x20`(DONE_FINAL なし)
    - 0x0A あり: 状態 `0x2020`(DONE_FINAL あり)。ただしボードは応答しない
    - ビットの順を正しくした場合と逆にした場合の、どちらも同じ結果だった
  - 今の手順(0x0A なし)で試した失敗は 2 種類で、どちらも DONE_FINAL は立たなかった。1 つはこの不具合、もう 1 つはビットの順を逆にしたもの(2 章)。ほかの壊れ方でも DONE_FINAL が立たないかは確かめていない。ページは DONE_FINAL を見たうえで、そのあと `sys` を読んで識別値を確かめる使い方を想定している。
  - openFPGALoader は GW2A では usercode を照合せず、DONE_FINAL だけで成功と判定する。0x0A を送るので、上の注意がそのまま当てはまる可能性がある(試していない)。
- **試作で一度はまった不具合。** Shift-DR に入る TMS の命令を待ち行列に積んだまま、データのバイトを直接書いていた。そのため、データは Run-Test/Idle のときに送られていた。データを送る前に、待ち行列を送り切るように直した(`jtag.js` の `GowinSram._dr`)。`tests/test_webusb_js.py` に、TAP を真似た偽の USB 機器で、全部のビットが Shift-DR の中で送られることを確かめるテストを足した。
- **BL702(9K)は、書きながら読むと、1 回に 1024 バイトまでしか答えなかった。** 4096 バイトごとに読み戻すと、1024 バイトで止まって書き込みに失敗した。1024 バイトと 512 バイトでは通った。そこで `jtag.js` は、受信のパケットが 64 バイトの機器(BL702)では 1024 バイトずつ、BL616(20K)では確かめた 4096 バイトずつ送る。`jtagbridge.py` も、1 回の転送を 100 語(1 語 9 バイト)にしている。理由は、そのコメントにあるとおり「BL702 は 1 回の転送で約 1 KB を返す」こと。
- **openFPGALoader より遅い理由(推定。測っていない)。** 候補は次の 2 つ。
  - こちらは、書きながら読む命令(0x39)で、4096 バイトごとに書いて読み戻すのを待つ。openFPGALoader はビットストリームを、TDO を読まずに送る(`writeSRAM` の `shiftDR(ptr, NULL, ...)`)。
  - JS の配列の展開などの、ページの側の処理。
  - 書くだけの命令(0x19)が BL702 で通るかは記録が無いので、使うなら先に確かめる。いまの実装は、BL702 で確かめた命令の組(`mpsse.py` の冒頭)だけを使っている。
- **20K の Overlay の照合の流れ(#32)は、ブラウザでもそのまま組める。** 識別値を読むのは、`sys` の 3 語だけで済む。

## 4. 利用者に要る事前の設定
- Windows: Zadig で Interface 0 を WinUSB にした状態で試した。既定のドライバのままで WebUSB が開けるかは試していないので、WinUSB が必須だとは確かめていない(5 章)。
  - 4K と 20K の利用者: nanopynq で JTAG を使うときと同じ設定なので、ブラウザのために増えるものは無い。
  - 9K の利用者: いまの Web Serial のページは、UART(Interface 1)だけを使い、Zadig は要らない。ブラウザから書き込みもするなら、Zadig の手順が増える。Zadig で Interface 0 だけを WinUSB にしても、UART のポート(COM)は残った(2.1)。
  - Interface 1(UART)は、そのままにする。以前の作業で、9K と 20K を差し替えたあとに、Interface 0 のドライバが元に戻っていたことがある。その場合は Zadig をやり直す(このレポートでは確かめていない)。
- Linux: 確かめていない(5 章)。

## 5. 確認できなかったこと
- **Linux**: 次の 2 点を確かめていない。
  - Chrome が、ftdi_sio のつかんでいる Interface 0 を開けるか
  - udev の権限(openFPGALoader の規則で足りるか)
  - Windows の 1 台だけで試した。
- **Web Serial と WebUSB の同時の利用**: 9K(BL702)と Windows でだけ確かめた(2.1)。20K(BL616)では試していない。
- **Windows で、Interface 0 が既定のドライバのままのとき**: WebUSB で開けるかを試していない。
- **4K**: 基板の故障のため試していない(`mpsse.py` と同じ BL702)。
- **前回の書き込みで CRC エラーが残っている場合**: openFPGALoader は、GW2A で状態の CRC_ERROR が立っているとき、消去の前に別の手順で状態を戻す。この手順は実装していない。CRC_ERROR が立っていれば、理由を出して止まる。立った場合の動きは試していない。
- **ほかのブラウザ**: Edge(Chromium)では試していない。Firefox と Safari は WebUSB を持っていない。
- **フラッシュへの書き込み**: 対象外(SRAM だけ)。
- **通信が途中で止まったあと**: Python の `Mpsse` は、失敗した読み取りのあとに受信を空にしてから次を送る。ページも、同じ処理を `flush` に入れた。ただし、実機で失敗を起こして試してはいない。

## 6. 次の判断のための材料
- `.fs` を取得してから SRAM へ書き込み、識別値の照合を経て操作するまでを、ブラウザの中だけで組める見込みが立った。20K で確かめた。#28(Pyodide)と合わせて、FabricGate のデザインのページで「取得」と「書き込み」を隠す案(#23、#28 のオーナーの方針)の前提は、20K については満たしている。
- 9K でも、取得から書き込み、照合、操作までをブラウザの中だけで済ませられる。書き込みは WebUSB、操作は Web Serial で、同時に使える(2.1)。Windows では Zadig の手順が 1 つ増える。
- 先に確かめるとよいもの: Linux(ftdi_sio と udev)。
- 書き込みの手順は、Python の `tools/p0/webusb/gowin_sram.py` でも動く。nanopynq が openFPGALoader なしで SRAM に書き込める道もある(いまは openFPGALoader を呼んでいる。`src/nanopynq/program.py`)。採るかは別に決める。

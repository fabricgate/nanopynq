# Windows で Zadig を使わずに、デバッガの JTAG(Interface 0)を使う方法(#50、2026-11-19)

## 結論
| 経路 | 結論 | 根拠 |
|---|---|---|
| **Python: FTDI の D2XX**(`ftd2xx.dll`、Python の `ftd2xx`) | **できる(条件つき)** | 9K で、Zadig を使わない既定のドライバのまま、次の 3 つができた(2 章)。<br>・IDCODE を読めた<br>・SRAM に書き込めた(0.37 s)<br>・書き込みのあと、UART(COM3)を抜き差しせずに使えた<br>条件は 3 つ。<br>(1) D2XX の利用条件は「FTDI の正規の部品を使う製品に限る」。BL702 / BL616 は互換品。<br>(2) Python の `ftd2xx` は、保守する人がいない。<br>(3) 20K と、D2XX の上の JTAG ブリッジ(4K と 20K の操作に使う)は試していない。 |
| Python: libusb(nanopynq の今の `Mpsse`、openFPGALoader) | **できない** | 既定のドライバのままでは開けない。`Entity not found`、`usb_open() failed`(2 章) |
| ブラウザ: WebUSB | **できない**(既定のドライバのままでは) | 選択の画面に機器は出るが、`claimInterface` が `Unable to claim interface` で失敗した(2 章) |
| ブラウザ: Web Serial で JTAG(Interface 0 を VCP として使う) | **できない**(見込み) | 既定のドライバでは、Interface A に COM が付かない(1 章)。仮に付いても、MPSSE は D2XX の API(ビットモードの切り替え)からだけ使える。COM ポートからは MPSSE を通せない。ただし、これを明記した FTDI の一次資料は確かめていない |
| デバッガのファームウェアを新しくする(Sipeed の BL702 の新しいファームウェア) | **見込みあり、確かめていない** | Sipeed の README に、MS OS 2.0 の記述子で Interface A に WinUSB を自動でつけると書かれている。そうなれば、libusb、openFPGALoader、WebUSB のどれも、Zadig なしで動くはず(3 章)。<br>・手元の 9K は古いファームウェアだった<br>・書き換えは、この issue の範囲の外<br>・20K(BL616)向けの公開のファームウェアは見つからなかった |
| libusb の UsbDk のバックエンド | **確かめていない** | 机上の調査だけ(3 章)。<br>・Zadig の代わりに UsbDk を入れる必要がある。<br>・一度入れれば、インターフェースを選ぶ手順や、ボードを差し替えたあとのやり直しが要らなくなる可能性がある(確かめていない)。<br>・UsbDk はデバイスを丸ごとつかむ作りなので、UART(Interface 1)が使えなくなる可能性がある(確かめていない)。<br>・libusb の文書には、安定性の注意がある |

- **Python のライブラリとして Zadig をなくすなら、D2XX が唯一、実機で動いた経路。** #49(nanopynq が自分で書き込む)で、通信の層を D2XX でも動くようにすれば、Windows では Zadig も openFPGALoader も要らなくなる見込み。
  - 9K は書き込みだけなので、今回の確認で足りる。
  - 4K と 20K は、操作にも JTAG ブリッジを使う。D2XX の上でブリッジが動くかは、まだ確かめていない。
  - 利用条件をどう扱うかを先に決める必要がある(4 章)。
- **ブラウザから JTAG を使うには、Windows では WinUSB が要る。** WebUSB は WinUSB の上でしか動かず、Web Serial では JTAG を扱えないため。WinUSB を得る方法は 2 つで、Zadig か、デバッガのファームウェアの更新。

## 1. Windows の既定のドライバ(9K、Zadig をかける前)
Zadig の WinUSB を Interface 0 から外し(デバイスのアンインストールと、ドライバの削除)、USB を差し直したあとの状態。

| デバイス | ドライバ | COM |
|---|---|---|
| USB Composite Device | Microsoft `usbccgp` | - |
| USB Serial Converter A(Interface 0) | FTDI `FTDIBUS`(`oem159.inf`、FTDI 2.12.36.20) | **付かない** |
| USB Serial Converter B(Interface 1) | FTDI `FTDIBUS` | COM3 |

- FTDI のドライバは、この PC には既に入っていた。新しい PC で Windows Update が自動で入れるかは、確かめていない
- Interface A に COM が付かないのは、FTDI のドライバの「VCP を読み込む」の設定によるとみている(確かめていない)
- **Web Serial の選択の画面に出るポートは 1 つだけ(`JTAG Debugger (COM3)`)。** Zadig の前も後も同じだった。名前はデバッガの製品名で、中身は UART(Interface 1)

## 2. 既定のドライバのままで試したこと(9K、Windows 11)
| 試したこと | 結果 |
|---|---|
| nanopynq の `Mpsse.open`(pyusb + libusb) | `[Errno 2] Entity not found` |
| openFPGALoader v1.2.0 `-b tangnano9k --detect` | `unable to open ftdi device: -4 (usb_open() failed)` |
| Chrome の WebUSB(`examples/webusb/index.html`) | 選択の画面には `JTAG Debugger` が出る。つなぐと `Failed to execute 'claimInterface' on 'USBDevice': Unable to claim interface.` |
| D2XX: 機器の一覧 | 2 つ出る: `USB Debugger B`(番号 0)、`USB Debugger A`(番号 1)。種別は 4(FT2232C)。**B が先に出る。** 説明の末尾の ` A` で選ぶ |
| D2XX: Interface A を MPSSE に | 通った。不正な命令 0xAA への答えは、MPSSE の決まりどおり `0xFA 0xAA` |
| D2XX: IDCODE、状態レジスタ | `0x1100481b`、状態 `0x0003f020` |
| D2XX: SRAM への書き込み | 作り直す前の base(sysinfo 1.0)が 0.37 s、今の base が 0.36 s。どちらも DONE |
| 書き込みのあと、UART(COM3)で `Overlay(download=False)` | 古い回路では `DesignMismatch`(sysinfo 1.0)。今の base では、識別値 `0xabf78d8c` が一致 |

- 道具: `ftd2xx` 1.3.8(PyPI)、FTDI のドライバ 2.12.36。
- 試作は `tools/p0/nozadig/d2xx_jtag.py`。nanopynq の `Mpsse` の、開く、書く、読む、受信を空にする、閉じるの 5 つを D2XX に置き換えた。MPSSE の命令の組み立てと、書き込みの手順(`tools/p0/webusb/gowin_sram.py`)は、そのまま使った。JTAG ブリッジは使っていない(9K は UART で操作するため)。
- BL702 の、1 回の書き込みと読み戻しを 1024 バイトまでにする制限(#23)は、D2XX でも同じに扱った。
- 注意: 一度、D2XX の一覧で 2 つのインターフェースとも「開いている」(flags=1、名前が空)になり、開けなかった。そのとき、止めた試作のプロセスと、Chrome のタブ(Web Serial と WebUSB のページ)の両方が残っていた。どちらが原因かは切り分けていない。タブを閉じて USB を差し直すと、開けるようになった。

## 3. 机上の調査(実機では確かめていない)
- **Sipeed の BL702 の新しいファームウェア**(`sipeed/RV-Debugger-BL702`、main、2026-09-07 の更新)。README に、次のことが書かれている。
  - Windows では、MS OS 2.0 の記述子で、Interface A だけに WinUSB を通知する
  - Interface B は、FTDI のシリアルのドライバ(`FTDIBUS`)のまま
  - BOS の記述子を見つけさせるために `bcdUSB` を 2.1 にしている。速度は Full Speed のまま
  - シリアル番号は `BL702_FTDI_<chip-id>` の形
- **手元の 9K のデバッガは、古いファームウェアだった。** `bcdUSB` は `0x0200`、シリアル番号は `FACTORYAIOT_PRO`。
- **ファームウェアの書き込み方**(README): BL702 の boot のボタンを押したまま USB を差し、Bouffalo Lab の書き込みの道具を使う。
  - 9K の基板で、boot のボタンをどう押すかは確かめていない
  - 失敗したときの戻し方も確かめていない
- **20K の BL616 向けの、同じ機能を持つ公開のファームウェアは見つからなかった**(GitHub の sipeed の組織で検索した)。
- **UsbDk**(libusb の Windows の別のバックエンド): デバイスを Windows の PnP から外して、libusb に直接渡す。
  - 利用者は UsbDk(MSI)を入れる必要があり、管理者の権限が要る
  - libusb の Wiki は、安定性の問題があるとして WinUSB を勧めている
  - pyusb から使えるようにする方法は、確かめていない
- **D2XX の利用条件**: NuGet で配られている D2XX の利用条件には、「FTDI の正規の部品を使う製品とだけ使う」とある。FTDI の配布ページにも、同じ趣旨が書かれている(検索結果の抜粋で見た。全文は取れなかった)。
- **Python の `ftd2xx`**(MIT、ctypes で `ftd2xx.dll` を呼ぶ): README で、保守する人を募集している。D2XX の本体(DLL)は、FTDI のドライバと一緒に入る。

## 4. 次の判断のための材料
- **D2XX を採るか(#49 と合わせて決める)。** 採る場合は、次のように作れる。
  - Windows で Interface 0 が `FTDIBUS` のときは D2XX、WinUSB のときは今の libusb、と切り替える
  - 試作の差し替えは 50 行ほどだった(開く、書く、読む、受信を空にする、閉じる)。
  - 試作には、移していない処理がある。`Mpsse.flush` は、読み取りに失敗したあと、次の送信の前に受信を空にする。この処理は、USB を直接呼ぶ(`dev.ctrl_transfer`)。試作の D2XX の版では、ここが動かない(`dev` が無い)。本実装では、D2XX の purge に置き換える
  - ただし、利用条件(正規の FTDI の部品に限る)の扱いは、オーナーが決めること
  - `ftd2xx` を依存に入れるか、ctypes で直接呼ぶかも決める
- **デバッガのファームウェアの更新を、利用者に勧めるか。** 次のことを先に確かめる。
  - 9K で書き換えられるか
  - 元に戻せるか
  - Sipeed が正式に配っている形か
  - 20K に同じものがあるか
- **Web Serial のページの文言**(#42)。「デバッガは 2 つのポートを出す」という前提を直す。Windows の 9K では、どちらの状態でも 1 つだった。

## 5. 確認できなかったこと
- 20K(BL616)での D2XX
- 20K での、Windows の既定のドライバ(1 章は 9K だけ)
- D2XX の上の JTAG ブリッジの往復(#50 の調べる点 2。4K と 20K の操作に要る。9K は UART で操作するので試していない)
- D2XX で Interface A を開いたまま、同時に UART を使うこと(試したのは、書き込みのあとに UART を使う順の操作だけ)
- 読み取りに失敗したあとの立ち直り(試作には移していない。4 章)
- Windows Update だけの、新しい PC での既定のドライバ
- UsbDk、ファームウェアの更新(机上だけ)
- D2XX の速さの限界(BL702 の 1024 バイトの制限の中で試しただけ)
- Linux(この issue の範囲の外)

## 6. 本体に入れた D2XX の経路(#64、2026-11-20)
オーナーが D2XX を使うと決めた(利用条件を承知のうえで)。

### 6.1 作り
- `src/nanopynq/transport/d2xx.py`: ctypes で `ftd2xx.dll` を直接呼ぶ(PyPI の `ftd2xx` は使わない)。
  - `D2xxMpsse` は、`Mpsse` の USB の読み書きだけを差し替える。命令の組み立てと、書き込みのかたまりごとの待ちは、`Mpsse` のものを使う。
  - Interface A は、説明の末尾の ` A` で選ぶ。9K では、一覧で B が先に出るため。
  - flags の bit 1(High Speed)で、受信のパケットの大きさを決める(BL616 は 512、BL702 は 64)。これで、`max_read` と 1 回の書き込みの大きさが、libusb の経路と同じになる。
- `open_jtag`: libusb を先に試す。Windows で開けなければ D2XX を試す。
  - D2XX でも見つからなければ、libusb のエラー(Zadig の案内つき)を出す。
  - テストで偽の USB を差し込んだとき(`find=`)は、D2XX に移らない。
- `doctor` と README: Zadig を任意にした。Zadig が要るのは、WebUSB のページと openFPGALoader を使うときだけ。

### 6.2 実機での結果(Windows 11、openFPGALoader なし)
| ボード | Interface 0 | 確認 | 結果 |
|---|---|---|---|
| 9K | WinUSB | 経路、`Overlay("base")` を 3 回 | libusb(`Mpsse`)で開いた。0.41〜0.53 s で、3 回とも通った |
| 9K | FTDIBUS | `doctor` | 終了コード 0 |
| 9K | FTDIBUS | 経路 | D2XX(`D2xxMpsse`)、`max_read` 1024 |
| 9K | FTDIBUS | `Overlay("base")` を 3 回 | 書き込みのあと UART で照合して、3 回とも通った(0.47〜0.51 s) |
| 9K | FTDIBUS | 書き込みを 40 回 | 40 回とも通った(中央値 0.45 s)。そのあと UART も答えた |
| 20K | FTDIBUS | `doctor` | 終了コード 0 |
| 20K | FTDIBUS | 経路 | D2XX、`max_read` 4096、1 回の書き込み 16 KiB |
| 20K | FTDIBUS | `check_20k.py`(書き込みあり) | 開くまで 0.83 s。識別値は一致 |
| 20K | FTDIBUS | `stress_link` 5000 回 | 不一致 0、4357 語/s(WinUSB では約 3500) |
| 20K | FTDIBUS | `cycles.py --rounds 50` | 失敗 0。80 s(WinUSB では 67〜68 s。毎回、先に libusb で開こうとして失敗する分) |
| 20K | FTDIBUS | `Overlay("sdram")` | 2.45 s。自己試験の誤りは 0 |

### 6.3 途中で分かったこと
- **9K の BL702 が固まった。**
  - Interface 0 が WinUSB のまま、libusb で開くと `Pipe error` を返し続けた。
  - そのとき D2XX の一覧には、`flags=1` で ID も名前も空の項目が 1 つだけ出た(B のはず。COM3 は開けた)。
  - 抜き差しで直った。直ったあとの一覧では、B は `flags=0`、名前は `USB Debugger B`。
  - 固まったきっかけは分からない。
- **D2XX の「使われている」の判断を直した。**
  - 最初の作りは、名前の無い「開かれている」項目を見て、「JTAG が使われている」と出していた。そのため、libusb の本当のエラーが隠れた。
  - 今は、Interface A と分かる項目が開かれているときだけ「使われている」とする。

### 6.4 確かめていないこと
- 4K(#62)。
- FTDI のドライバが入っていない PC(新しい PC で、Windows Update が自動で入れるか)。
- 20K を、変更のあとに WinUSB で確かめること。libusb の経路は変えていない。9K の WinUSB で確かめた。

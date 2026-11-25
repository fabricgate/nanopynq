# UsbDk で、Zadig を使わずに Interface 0 を開けるか(2026-11-20、机上の調査)

## 結論
- **UsbDk は採らない。実機でも試さない。**
- 技術的には使える見込みがある。nanopynq が使う libusb に、UsbDk の経路が入っているため。
- 採らない理由は次の 3 つ。
  - UsbDk の開発は、2020 年 3 月を最後に止まっている。
  - Windows 11 24H2 で、入れると起動できなくなる報告などが、未解決のまま残っている。
  - 利用者に入れてもらうのは、システム全体の USB に効くカーネルのフィルタードライバーになる。Zadig(1 つのインターフェースのドライバの差し替え)より重く、壊れたときの影響も大きい。
- **Windows で Zadig を不要にする道は、D2XX(#64)を優先する。**
  - D2XX は、Windows の既定の FTDI のドライバのまま使え、何も入れなくてよい。
  - 9K と 20K で、書き込みと JTAG ブリッジが動くことを確かめ済み(#50)。
- 実機の試験はしていない。この PC には UsbDk を入れていない。

## 1. 手元で確かめたこと
- nanopynq の環境(pyusb 1.3.1、`libusb-package` 1.0.30.1)の libusb は 1.0.30。
  - `libusb_set_option` と `libusb_init_context` がある。
- `libusb-1.0.dll` に `UsbDkHelper.dll` と `UsbDk_StartRedirect` の文字列がある。UsbDk の経路が組み込まれている。
- pyusb 1.3.1 は `libusb_init` を呼ぶだけで、UsbDk を選ぶ設定はしない。使うなら、nanopynq が pyusb より先に、同じ DLL の `libusb_set_option(NULL, LIBUSB_OPTION_USE_USBDK)` を呼ぶ必要がある。
  - NULL を渡すと、あとで作られる context の既定値になる。libusb 1.0.22 から。
  - 試していない。

## 2. Web で調べたこと
### 2.1 UsbDk の仕組み
- UsbDk は、機器を Windows の PnP の管理とドライバから切り離し、アプリに独占させる(UsbDk の README)。
- libusb の UsbDk の経路は、次のように動く(`libusb/os/windows_usbdk.c`)。
  - 開く(`libusb_open`)ときに、機器全体を切り離す(`UsbDk_StartRedirect`)。
  - 閉じるときに戻す(`UsbDk_StopRedirect`)。
  - インターフェースの確保(`claim_interface`)は何もしない。
  - つまり、インターフェースだけを取る仕組みは無い。
- 閉じたあと、元のドライバに戻るまでには時間がかかる。FT2232 互換(`0403:6010`)で、その間に開けなかった事例がある(UsbDk の issue #39)。

### 2.2 保守の状況と、既知の問題
- 最新のリリースは v1.00-22(2020-03-17)。
- 未解決の issue:
  - #134: Windows 11 24H2 で、入れると Windows 全体が使えなくなる(2025-02)。
  - #110: Windows 10 で BSOD。
  - #115: WDF_VIOLATION。
  - #133: USB-C でクラッシュ。
  - #135: Windows 11 ARM に入れられない。
- libusb の wiki: UsbDk は「安定性に問題があるようだ」とし、WinUSB を勧めている。
- VirtualBox の USB のパススルーと競合する報告がある(#134 のコメント)。
- openFPGALoader、OpenOCD、sigrok が、FTDI の MPSSE に UsbDk を勧めている記録は見つからなかった。

## 3. nanopynq の使い方に当てはめると
| ボード | 書き込み | 操作 | UsbDk が機器全体を取ることの影響 |
|---|---|---|---|
| 4K、20K | JTAG(Interface 0) | JTAG ブリッジ(Interface 0) | UART は使わないので、困らない |
| 9K | JTAG(Interface 0) | UART(Interface 1) | 書き込みのあいだ、COM ポートが消える。閉じたあとも、戻るまで待つ必要がある(2.1)。書き込みと操作は順に行うので、待てば使える見込み。確かめていない |

- 調べる前は「UART が使えなくなる」を一番の心配としていた。しかし、nanopynq の使い方では決め手にならない。
- 決め手は、保守の状況と、システム全体への影響の大きさ(2.2)。

## 4. もし試すなら
- Windows を壊しても困らない検証用の PC で行う。#134 の復旧の手順(WinRE から UsbDk のサービスを止め、USB のクラスの UpperFilters から外す)を、先に確かめておく。
- 確かめること:
  - 9K で、`UsbDkController -n` で COM ポートが残るか。
  - libusb で Interface 0 を開いて閉じたあと、何秒で COM ポートが戻るか。
  - 20K で、JTAG ブリッジの往復が WinUSB と同じか。

## 出典
- UsbDk: https://github.com/daynix/UsbDk (README、releases、issues #39、#110、#115、#133、#134、#135)
- libusb: https://github.com/libusb/libusb (`libusb/core.c`、`libusb/libusb.h`、`libusb/os/windows_usbdk.c`)、https://github.com/libusb/libusb/wiki/Windows
- OpenOCD のメーリングリスト(複合の親を WinUSB にすると COM が消えた例): https://sourceforge.net/p/openocd/mailman/message/35254658

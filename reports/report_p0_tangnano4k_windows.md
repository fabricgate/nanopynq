# P0 実機記録: Tang Nano 4K / Windows 11（2026-10-30）

## 結論（途中）
- 4K の基板上デバッガは FT2232 互換（VID 0403 / PID 6010、シリアル番号 `FACTORYAIOT_PRO`）として見え、Interface A と B の2つを持つ。B 側は COM3 として、ドライバの導入なしに現れた。
- openFPGALoader は、Zadig を実施していない状態では FTDI を開けない（`Error code -5 Entity not found`）。

## 1. Zadig 実施前の USB の見え方
`Get-PnpDevice -PresentOnly | ? InstanceId -match "VID_0403"`:

| Status | Class | FriendlyName | InstanceId |
|---|---|---|---|
| OK | USB | USB Serial Converter B | USB\VID_0403&PID_6010&MI_01\7&2FEB2BE7&1&0001 |
| OK | USB | USB Composite Device | USB\VID_0403&PID_6010\FACTORYAIOT_PRO |
| OK | Ports | USB Serial Port (COM3) | FTDIBUS\VID_0403+PID_6010+FACTORYAIOT_PRO&2\0000 |
| OK | USB | USB Serial Converter A | USB\VID_0403&PID_6010&MI_00\7&2FEB2BE7&1&0000 |

`uv run python -m serial.tools.list_ports -v`:
```
COM3
    desc: USB Serial Port (COM3)
    hwid: USB VID:PID=0403:6010 SER=FACTORYAIOT_PRO
```
- pyserial の `location` は空だった。`find_port` は候補が1つなのでこれを選ぶ（インターフェース番号による B 側の判定は効かない）。

`openFPGALoader --scan-usb`（oss-cad-suite 2026-10-22 の v1.2.0）:
```
Error: can't open device with vid:vid = 0x0403:0x6010. Error code -5 Entity not found
```

## 6. 回路図で確かめた BL702 の配線（Tang_Nano_4K_3603_Schematic、2021-08-11、2ページ目 2_BL702-SchDoc）
- BL702（U4, BL702C_A0-Q2I）から FPGA へ出ている信号は JTAG の4本だけ:
  - GPIO_0 → JTAG_TDI#、GPIO_1 → JTAG_TDO#、GPIO_2 → JTAG_TMS#、GPIO_15 → JTAG_TCK#（それぞれ 0Ω と保護ダイオード経由で FPGA の IOT2A/TDI、IOT2B/TDO、IOT3A/TMS、IOT3B/TCK へ）
  - GPIO_7 / GPIO_8 は USB の D+ / D−、GPIO_17 は状態表示の LED（DS1）
  - GPIO_14 と GPIO_23〜28 には、FPGA へ向かうネットが描かれていない（GPIO_28 側は Boot_Strap のみ）
- したがって、Windows に見える COM3（FT2232 互換の B 側）は、4K では FPGA につながっていない。4K で UART を使うには、外付けの USB-UART 変換器が必要（boards.yaml の `uart-external` のとおり）。
- 初代 Tang Nano（CH552T）のように、デバッガの UART が FPGA の兼用ピン（DONE / RECONFIG_N）に来ている形（qiita-ciniml の記事）は、4K には当てはまらない。
- 回路図の GPIO_9 の先は図の範囲で読み切れていない（未確認）。

## 2. Zadig 実施後（Interface 0 = "JTAG Debugger" だけを WinUSB に、ユーザーが実施）
`Get-PnpDevice`: Interface 0 は `USBDevice / JTAG Debugger`（WinUSB）に変わり、Interface B の `USB Serial Port (COM3)` は残った。

| Status | Class | FriendlyName | InstanceId |
|---|---|---|---|
| OK | USB | USB Serial Converter B | USB\VID_0403&PID_6010&MI_01\7&2FEB2BE7&1&0001 |
| OK | USB | USB Composite Device | USB\VID_0403&PID_6010\FACTORYAIOT_PRO |
| OK | Ports | USB Serial Port (COM3) | FTDIBUS\VID_0403+PID_6010+FACTORYAIOT_PRO&2\0000 |
| OK | USBDevice | JTAG Debugger | USB\VID_0403&PID_6010&MI_00\7&2FEB2BE7&1&0000 |

- Zadig での表示名は「JTAG Debugger (Interface 0)」「JTAG Debugger (Interface 1)」。USB ID 欄の末尾 `00` が Interface 0。

`openFPGALoader --scan-usb`:
```
001 004    0x0403:0x6010 FTDI2232   SIPEED       FactoryAIOT Pro JTAG Debugger
```
`openFPGALoader -b tangnano4k --detect`:
```
Jtag frequency : requested 6.00MHz    -> real 6.00MHz
idcode 0x100981b / manufacturer Gowin / family GW1NSR / model GW1NSR-4C / irlength 8
```

## 3. blinky の SRAM 書き込み
`openFPGALoader -b tangnano4k build/blinky-tangnano4k/top.fs`（pip 版ツールでビルドした .fs）:
```
Erase SRAM Load SRAM: 100.00%  DONE
CRC check: Success
```
- 3 blinky: ユーザーが LED の点滅を目視で確認（2026-10-30）

## 4. 同梱の土台デザイン + COM3（オンボードの B 側）
`Overlay('base', board='tangnano4k', port='COM3')`: 書き込みは成功したが、ID の問い合わせに応答なし → `BoardNotResponding`。
- 4K の土台デザインは UART を外付け変換器用のピン（rx=44 / tx=46、カメラ用ピン）に出しているので、COM3 から応答が無いのは想定どおり。
- COM3 に 115200 bps で `02 01 00 00 00 00` を直接送っても、0.5 秒以内の受信は 0 バイト。

## 5. JTAG と UART の排他（4K）
COM3 を開いて閉じた前後で `openFPGALoader -b tangnano4k --detect` は2回とも成功（idcode 0x100981b）。
- 4K では、COM3 を開いた後でも抜き差しなしで JTAG が使えた。ただし COM3 が FPGA につながっていない可能性があり、9K の (b) の代わりにはならない。

## 気づいた点
- `BoardNotResponding` の英語のメッセージの中に日本語（「USBを抜き差し」）が混ざっており、Git Bash の端末では文字化けした。表示言語を揃えるべき（軽微）。

## 未実施
- 4K の UART の通信と速度（3.3V の USB-UART 変換器が必要。配線は reports/report_p0_windows.md）
- Tang Nano 9K での (a)〜(f)、Linux での確認

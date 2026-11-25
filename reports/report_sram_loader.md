# openFPGALoader なしで SRAM に書き込む(#49、#60、#61、2026-11-20)

## 結論
- **9K と 20K で、`Overlay(..., download=True)` が、openFPGALoader の無い環境で、書き込みから照合まで通った。** Windows 11 で、Interface 0 は WinUSB。
  - 確認の条件: openFPGALoader が PATH に無く、`NANOPYNQ_OPENFPGALOADER` も無い PowerShell。
- **openFPGALoader と同じか、それより速い。**
  - 20K の base: 約 0.4 s(openFPGALoader 0.45 s)。
  - 20K の SDRAM のデザイン: 約 2.0 s(openFPGALoader 1.91 s)。
  - 9K の base: 0.24 s(データの転送)。
  - 理由: ビットストリームを、TDO を読まない命令(0x19)で送るようにしたため。前の試作は 0x39 で書いては読んでいた。
- **BL702(9K、4K)は、1 回の USB の転送で約 1 KB までしか受け取らない。** それを超えた分は、拒まずに捨てる。そのため、書き込みの大きさをデバッガごとに分けた(BL702 は 1024 バイト、BL616 は 16 KiB)。
- **TDO を読まずに送り続けると、ホストがデバッガを追い越す。** 3.1 に記録した。
  - 1 KB ずつでも、9K では数回に 1 回失敗した。
  - 失敗のあと一度、FPGA が POR=0、IDCODE `0x1100581b` の状態になり、電源を入れ直すまで戻らなかった。
  - 対応: かたまりごとに、最後の 1 バイトを読み戻し(0x39)、その答えを待ってから次を送る。これで 9K は 40 回とも通った(中央値 0.36 s)。
- **CRC_ERROR の立つ状態は、20K で作れなかった。** そのため、openFPGALoader の立て直しの手順は入れていない(設計書 5.7)。CRC_ERROR が立っていたら、電源を入れ直すよう案内して止める。
- 4K(#62)と Linux(#63)は、確かめていない。

## 1. 作ったもの

- `src/nanopynq/transport/jtag.py`
  - `Jtag` Protocol: `tms`、`shift`、`shift_bytes`、`flush`、`close`、`max_read`
  - `open_jtag`: デバッガを開く唯一の場所
  - 実装は `Mpsse`(libusb)だけ。
- `src/nanopynq/gowin.py`: `.fs` の読み取り、`load_sram`(IDCODE の照合 → 消去 → 書き込み → DONE_FINAL)。
- `program_sram` は、`boards.yaml` の `programmer.tool` で振り分ける。
  - 9K、4K、20K は、いずれも `nanopynq`。
  - openFPGALoader は `program_sram_openfpgaloader` として残し、`Overlay(programmer=...)` から使える。
- `doctor`:
  - openFPGALoader の確認は、`tool: openfpgaloader` のボードだけ。
  - 9K でも、Interface 0 を開けるかを確かめる。
  - udev は、同梱の `99-nanopynq.rules` か openFPGALoader の規則があれば OK。

## 2. 実機での結果(Windows 11)
| ボード | 確認 | 結果 |
|---|---|---|
| 20K | 試作(`gowin_sram.py`)を `shift_bytes` に載せ替えて書き込む | base は data 0.32 s、DONE。SDRAM は data 1.69 s、DONE。前の試作は 0.77 s と 4.10 s |
| 20K | `doctor --board tangnano20k` | 終了コード 0。openFPGALoader の行は出ない |
| 20K | `check_20k.py`(書き込みあり) | 開くまで 0.66 s(書き込みなしなら 0.25 s)。識別値 `0x4E505131 / 0x00010001 / 0xABF78D8C`、LED、ボタンが期待どおり |
| 20K | `cycles.py --rounds 50`(base と SDRAM を交互に書き込み、開閉) | 50 回(開閉 100 回)67 s、失敗 0 |
| 20K | `stress_link.py --n 5000` | 不一致 0。3421〜3626 語/s(前は約 3200) |
| 20K | `Overlay('sdram')` → `sdram_test.run(passes=1)` | 開くまで 2.08 s(書き込みなしなら 0.10 s)。誤り 0 |
| 9K | 試作を `shift_bytes` に載せ替えて書き込む | 16 KiB ずつ: FAIL(DONE_FINAL なし)。修正のあと(1024 バイトずつ): data 0.24 s、DONE |
| 9K | `doctor --board tangnano9k` | 終了コード 0。`OK usb`、`OK port: COM3` |
| 9K | `Overlay('base', board='tangnano9k')` | 0.56〜0.60 s(UART を開いて照合するまで)。`sys.id` は `0x4e505131`。LED 0 が点いた |

## 3. BL702 の書き込みの大きさ(9K)
- 1 回の USB の書き込みを 16 KiB にすると、DONE_FINAL が立たなかった。
  - 送る速さが 468 KB/s と出た。これは TCK(約 2 MHz、約 250 KB/s)より速い。BL702 は、受け取りきれない分を拒まずに捨てているとみられる。
- 命令は 0x19 のまま、1 回の大きさだけを変えた結果:

  | 大きさ | 結果 |
  |---|---|
  | 4096、2048 | FAIL |
  | 1024 | DONE(3 回続けて) |
  | 64 | DONE |

- BL702 は、書いて読み戻すときも 1 回に 1024 バイトまでしか答えない(#23)。同じ上限とみている。
- BL616(20K)は、16 KiB の書き込みで通った。
- 対応: `Mpsse._write_chunk`。受信のパケットが 64 バイトのデバッガ(BL702)は 1024、それ以外は 16 KiB。

### 3.1 送る速さを抑える(9K、PR #65 のマージのあとに分かったこと)
- **1024 バイトずつでも、TDO を読まずに送ると、ときどき失敗した。**
  - #66 を main に合わせたあとの確認で、3 回の書き込みのうち 1 回が DONE_FINAL なしで止まった。
  - 前に 1024 で続けて通っていたのは、たまたまだった。
- **失敗のあと、FPGA がおかしな状態になった。** 状態は `0x00021020`。POR(bit 16)と READY(bit 15)が落ちていた。
  - IDCODE は、nanopynq と openFPGALoader の `--detect` のどちらで読んでも `0x1100581b`(GW1NR-9)だった。本来は `0x1100481b`。
  - その状態では、新しい手順の IDCODE の照合が、書き込みを止めた。
  - USB を抜いて約 10 秒待ち、挿し直したら戻った(IDCODE `0x1100481b`、状態 `0x0003f020`)。フラッシュには書いていない。
- **原因**: TDO を読まない送り方では、ホストが、デバッガがどこまで処理したかを知る手段が無い。そのため、デバッガが溜めきれなくなることがある。
- 送り方を変えて、9K で続けて書き込んだ結果(失敗したら止める):

  | 送り方 | 結果 | 書き込みの時間(中央値。開くところから) |
  |---|---|---|
  | A: 0x19 を 1024 バイトずつ、待たない | 数回に 1 回失敗 | ― |
  | B: 0x19 のあとに 0x81(ピンの読み取り。TCK を動かさない)を挟み、その答えを待つ | 50 回とも通った | 0.35 s |
  | C: 0x39 で全部を読み戻す(前の試作) | 30 回とも通った | 0.48 s |
  | **D: かたまりの最後の 1 バイトだけ 0x39 で読み戻し、その答えを待つ** | **40 回とも通った** | **0.36 s** |

- **D を採った。** 速さは B と同じで、使う命令(0x19、0x39)が、BL702 と BL616 の両方で確かめ済みのものだけで済むため。0x81 は、BL616 で確かめていない。
- 本体のコードにしたあと、9K で 40 回とも通った(中央値 0.35 s)。`Overlay('base')` も通った(0.56 s)。

## 4. CRC_ERROR(20K、設計書 5.7)
| 試したこと | 書き込みの結果 | そのあとの状態 |
|---|---|---|
| base の `.fs` の 3/4 の位置で 1 ビットを反転 | `ProgramError`(DONE_FINAL なし) | `0x00004460`(MEMORY_ERASE、PREAMBLE)。書き込み直後は `0x00004000` |
| base の `.fs` を半分で切る | `ProgramError`(DONE_FINAL なし) | `0x00004460` |

- どちらも、CRC_ERROR(bit 0)は立たなかった。
- そのあと、正しい base は、そのまま書き込めた(DONE、識別値も一致)。
- 状態の bit 14 は、名前の表に無い。何を表すかは調べていない。

## 5. 確かめていないこと
- 4K(#62)。BL702 なので、9K と同じ 1024 バイトの書き込みになる。
- Linux(#63)。同梱の udev の規則だけで動くか。9K で、JTAG で書き込んだあと UART を開けるか。
- CRC_ERROR が実際に立った状態からの書き込み。
- D2XX の経路(#64)。

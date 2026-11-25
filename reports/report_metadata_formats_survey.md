# レジスタの記述とデザインの定義の、既存の形式の調査 2026-11-19

issue #44 の判断 3(「FabricGate や、オープンソースのビルドのツールが使っているメタ情報ファイルの形式も考慮して、なるべく共通の形式にする」)のための調査。各リポジトリを取得して実物を読み、PyPI と GitHub の情報を照会した。記憶ではなく、読んで確かめたことを書く。確かめられなかった点は 6 章。

## 結論
- **IP の型ごとのレジスタの記述(ファイル 1)に、そのまま採れる既存の形式は無い。** パラメータに依存する幅と個数、同じモジュールがパラメータで別の型になる場合、データの窓、ホストの側の値を、宣言として書ける形式は見つからなかった。唯一近い SystemRDL は、専用のコンパイラ(ANTLR)が要り、ブラウザで動く実装が見つからない。
- **勧める形: 独自の TOML のまま、語彙を既存の形式に合わせ、変換(書き出し)で既存の道具とつなぐ。** 純粋な Python とブラウザの JavaScript で読める形式は、JSON、TOML、XML だけ(YAML は、どちらも標準に無い)。
- **書き出しは、展開したあとの定義(`.npq` の `ips`)の側で用意するのが現実的。** CMSIS-SVD(デバッグ用の既存の道具が読む)と、PYNQ の `ip_dict` の形への変換は、後から足せる。既存の形式からの取り込みは、パラメータの式が失われるので、静的な IP に限られる。
- **デザインの定義(ファイル 2、`nanopynq.toml`)に、FuseSoC の core ファイルをそのまま使うのは勧めない。** YAML が必須で依存が大きく、ソースのパスに「絶対パスは不可、`../` で始まるものは不可」の制約があり、共有のライブラリのファイルを指す使い方と合わない。
- **代わりに、語彙を FuseSoC / EDAM に合わせ、EDAM の形の JSON を書き出せるようにするのがよい。** Edalize(FuseSoC の裏側)には、Apicula(Gowin)のフローがあり、Tang Nano 9K と 20K のボードの定義を持っている。

## 1. 形式ごとの比較

「式」は、レジスタの幅や個数を、式やパラメータで宣言できるか。

| 形式 | 表せる範囲 | 式 | 手で書く量 | Python / JS の実装 | オープンソースの FPGA での普及 |
| --- | --- | --- | --- | --- | --- |
| IP-XACT(IEEE 1685、XML) | memoryMap / addressBlock / register / field / dim / access / readAction / VLNV | あり(2014 の XSD で、`addressOffset`、`width`、`range` などが式の型) | 多い | Python: `ipyxact` 0.3.2(MIT、最終は 2022-06)。JS: 見つからず | 低い |
| SystemRDL 2.0 | regfile / reg / field / 配列 / パラメータ / sw・hw / onread | あり(言語の機能) | 中(レジスタ 5 個で 20〜30 行) | Python: `systemrdl-compiler` 1.33.0(MIT、ANTLR に依存)。JS: 実用的なものは見つからず | 中(PeakRDL。yosys の周辺では見つからず) |
| CMSIS-SVD(XML) | peripheral / register / field / dim / access / readAction / enumeratedValues | 無い(静的な数値だけ) | 多い | Python: `cmsis-svd` 0.6(Apache-2.0、lxml に依存)。ブラウザ: `DOMParser` | 中(デバッグ用の道具が読む) |
| LiteX の `csr.json` / `csr.csv` / SVD | アドレス、大きさ、rw / ro。SVD にはフィールドも | 無い(生成したあとの値) | 生成物(手では書かない) | `json` / `csv`。ホストの側は `litex_client` | LiteX では事実上の標準 |
| OpenTitan の reggen(Hjson) | register / multireg / window / swaccess / hwaccess / param_list | `multireg` の `count` にパラメータの名前を書ける | 中 | Python: `hjson`(MIT)と reggen。JS: `hjson` | 低〜中 |
| hdl-registers(TOML / YAML / JSON) | register / register_array / constant / field、mode | 無い(静的な `width`) | 少ない | Python 8.2.0(BSD-3。依存が多い) | 低い |
| cheby(CERN、YAML) | memory-map / block / reg / field / repeat | `repeat.count` は数値 | 少ない | Python(GPL-3、pyyaml) | 低い |
| Corsair(YAML / JSON) | regmap / bitfields / access / enums | 見つからず | 中 | MIT。リポジトリは保管済み(archived) | 低い |
| PYNQ の `ip_dict` / `.hwh` | IP ごとの phys_addr / addr_range / type / parameters / registers / fields | 無い(展開したあとの値) | 手で書く形ではない(Vivado の出力) | `pynq` 4.0.0、`pynqmetadata` | Xilinx / PYNQ |
| デバイスツリー | `reg`、`compatible` | 無い | アドレスだけ | — | Linux の FPGA のオーバーレイ |
| amaranth-soc | CSR のアクセス(r / w / rw / nc)、MemoryMap(resources / windows) | Python の式そのもの | Python のコード | `amaranth-soc`(BSD-2) | Amaranth の利用者 |

## 2. 確かめた事実(主なもの)

### IP-XACT
- 2014 版の XSD を取得して読んだ(https://www.accellera.org/XMLSchema/IPXACT/1685-2014/memoryMap.xsd)。`accessType` は `read-only` / `write-only` / `read-write` / `writeOnce` / `read-writeOnce`。`readAction` は `clear` / `set` / `modify`。`dim` がある。`width`、`addressOffset`、`range` などは式の型。
- XSD のライセンスの文は、そのままの複製と配布を認め、派生のスキーマを作ることを認めていない(https://www.accellera.org/XMLSchema/IPXACT/1685-2014/index.xsd)。
- 型を VLNV(ベンダー:ライブラリ:名前:版)で識別するのは、IP-XACT が本家。

### SystemRDL
- 2.0 は 2018-01-26 付(https://www.accellera.org/downloads/standards/systemrdl)。
- `systemrdl-compiler` のソースで確かめた語彙: アクセスは `na` / `rw` / `r` / `w`、読み取りの副作用は `rclr` / `rset` / `ruser`(https://github.com/SystemRDL/systemrdl-compiler)。
- パラメータ化は言語の機能(型のパラメータ `WIDTH` で `field {} f[WIDTH];`)。
- `systemrdl-compiler` 1.33.0 は MIT。依存は `antlr4-python3-runtime` など 4 つ。PeakRDL の本体と regblock は LGPLv3、`peakrdl-ipxact` は GPL-3。
- JavaScript の側は、文法だけのパッケージ(`tree-sitter-systemrdl`)などが見つかっただけ。

### CMSIS-SVD
- 仕様は https://github.com/Open-CMSIS-Pack/svd-spec (Apache-2.0)。XSD を読んだ。`accessType` は IP-XACT と同じ 5 つ。`readActionType` は `clear` / `set` / `modify` / `modifyExternal`。数値は静的(式は無い)。

### LiteX
- `litex/soc/integration/export.py` を読んだ(https://github.com/enjoy-digital/litex)。`csr.json` のキーは `csr_bases`、`csr_registers`、`constants`、`memories`、`cores`。`csr_registers` は `{名前: {addr, size, type: "rw"|"ro"}}`。フィールドの情報は無い。
- SVD の出力はフィールドを含むが、`access` の出力はコメントで外されている。コードのコメントは、「読み取り専用のレジスタも、書き込みで状態が変わり得るので、`access` は嘘になる」と述べている。
- ホストの側の `litex_client` は、カレントのフォルダに `csr.csv` があれば自動で読み、名前でレジスタを引く。

### OpenTitan の reggen
- `util/reggen/README.md` を読んだ(https://github.com/lowRISC/opentitan、Apache-2.0)。`swaccess` は `none` / `ro` / `rc` / `rw` / `r0w1c` / `rw1s` / `rw1c` / `rw0c` / `wo`。`param_list` があり、`multireg` の `count` は「整数か、`param_list` の名前」。データの窓は `window`。OpenTitan に固有の項目(TL-UL のバス、クロックの定義など)が多く、小さな道具がそのまま採るには重い。

### hdl-registers
- https://hdl-registers.com/rst/user_guide/toml_format.html を読んだ。レジスタは TOML のテーブル。`mode` は `r` / `w` / `r_w` / `wpulse` / `r_wpulse`。フィールドは `enable.type = "bit"` のような、ドットつきのキー。`register_array` と `constant` がある。パラメータに依存する幅の書き方は、文書に見つからなかった。「TOML でレジスタを書く」という点で、いちばん近い。

### PYNQ
- `pynq` 4.0.0 の `pynq/registers.py` と `pynq/overlay.py` を読んだ(https://github.com/Xilinx/PYNQ)。`registers` の項目は `{名前: {address_offset, access: "read-only"|"write-only"|"read-write", size, description, fields}}`。`fields` は `{名前: {access, bit_offset, bit_width, description}}`。`ip_dict` の IP の項目は `phys_addr` / `addr_range` / `type` / `parameters` / `registers` / `state`。

### FuseSoC と Edalize
- FuseSoC のリポジトリの中の文書を読んだ(https://github.com/olofk/fusesoc)。core ファイルは YAML で、先頭の行は `CAPI=2:`。名前は VLNV。`filesets.<名前>.files` は順序つきのリストで、「道具に、その順序のまま渡される」と書かれている。`targets.<名前>` は `filesets` / `toplevel` / `default_tool` / `parameters` を持つ。**ソースのファイル名は、絶対パスは不可、`../` で始まるものも不可。** 依存(`depend`)の並びは、順序を意味しない。
- FuseSoC 2.4.7 の依存は `edalize`、`pyparsing`、`pyyaml`、`pydantic`、`simplesat`。
- Edalize 0.6.8(BSD-2。主な依存は Jinja2)の文書を読んだ(https://github.com/olofk/edalize)。EDAM は、「YAML か JSON にできる、道具に依らない dict」。キーは `name`(必須)、`files`、`toplevel`、`parameters`、`flow_options`、`tool_options` など。`files` の各項目は `name` と `file_type`(どちらも必須)。パラメータの種類(`paramtype`)は `vlogparam` など。
- **Edalize には Apicula(Gowin)のフローがある**(`edalize/flows/apicula.py`)。yosys → nextpnr → gowinpack → openfpgaloader。ボードの定義に `tangnano9k`(GW1NR-LV9QN88PC6/I5)と `tangnano20k`(GW2AR-LV18QN88C8/I7)がある。nextpnr の道具は、`file_type == "CST"` のファイルを制約として受け取る。

### Bender
- `Bender.yml` は YAML(https://github.com/pulp-platform/bender)。`sources` は順序つきの文字列のリストで、グループ(`include_dirs`、`defines`、`target`、`files`)も書ける。実装は Rust。

### ビルドの入出力
- yosys の `write_json` のヘルプは、「この形式を処理するプログラムは、知らない項目を無視しなければならない」と書いている。

## 3. 語彙の対応(アクセスと副作用)

| 意味 | SystemRDL | SVD / IP-XACT / PYNQ | OpenTitan / cheby | hdl-registers | LiteX | amaranth-soc | いまの `.npq` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 読み取り専用 | `sw=r` | `read-only` | `ro` | `r` | `ro` | `r` | `ro` |
| 読み書き | `sw=rw` | `read-write` | `rw` | `r_w` | `rw` | `rw` | `rw` |
| 書き込み専用 | `sw=w` | `write-only` | `wo` | `w` | (無い) | `w` | `wo` |
| 読むとクリア | `onread=rclr` | `readAction=clear` | `rc`(OpenTitan) | (無い) | (無い) | (無い) | `read_effect: true` |
| 読むとセット | `onread=rset` | `readAction=set` | (無い) | (無い) | (無い) | (無い) | `read_effect: true` |
| 読むと変わる(種類を問わない) | `onread=ruser` | `readAction=modify` | (無い) | (無い) | (無い) | (無い) | `read_effect: true` |

- いまの `.npq` のアクセスの書き方(`ro` / `rw` / `wo`)は、OpenTitan、cheby、LiteX と同じ。SVD、IP-XACT、PYNQ の長い書き方(`read-only` など)へは、機械的に変換できる。
- `.npq` の `read_effect`(真偽)は、SVD と IP-XACT の `readAction` の 3 つの値を、1 つにまとめたものにあたる。変換するときは、`true` を `modify` にすれば意味が合う。
- `readAction` と `onread` は、既存の形式ではフィールド(ビットフィールド)の単位の属性。

## 4. ファイル 1(IP の型ごとの記述)の方針

| 方針 | 現実性 | 評価 |
| --- | --- | --- |
| 既存の形式をそのまま採る | 低い | パラメータへの依存と窓を表せるのは SystemRDL だけ。専用のコンパイラが要り、ブラウザで読めない |
| 既存の形式の部分集合を採る | 低〜中 | IP-XACT や SVD の静的な部分では、パラメータの式と窓が表せない |
| 独自の形式 + 変換(取り込み・書き出し) | 中 | 書き出し(SVD、PYNQ の形)は実装が小さく、既存の道具につながる。取り込みは静的な IP に限られる |
| **独自の形式だが、語彙を合わせる** | **高い** | 依存を増やさず、`tomllib` とブラウザで読める |

## 5. ファイル 2(デザインの定義)の方針

| 方針 | 現実性 | 理由 |
| --- | --- | --- |
| FuseSoC の core ファイルをそのまま採る | 低い | YAML と大きな依存。パスの制約。VLNV の名前と先頭の行が必須 |
| core ファイルの部分集合を採る | 低〜中 | YAML が必須。パスの制約で、共有のライブラリのファイルは、依存の仕組みを通す必要がある |
| **独自の TOML + EDAM の形の JSON の書き出し** | **高い** | EDAM は JSON にでき、`files`(`name` と `file_type`)、`toplevel`、`parameters` の語彙がそのまま使える。Edalize の Apicula のフローに渡せる見込み(試していない)。`files` の順序は、明示した並びを保てる |
| Bender の語彙を借りる | 中 | `sources` のグループの語彙は参考になる。YAML で、実装は Rust |

語彙の対応の案: 順序つきの一覧は `files`(FuseSoC / EDAM / Bender で共通)。ファイルの種類は EDAM の `file_type` の値(`verilogSource`、`CST` など)。top は `toplevel`。Verilog のパラメータは `parameters` の `paramtype = "vlogparam"`。

## 6. 確かめられなかった点
- IEEE 1685-2022 の本文と、IP-XACT の式の文法。2014 の XSD で「式の型である」ことだけを確かめた。
- SystemRDL 2.0 の PDF の本文(語彙は、コンパイラのソースで確かめた)。
- ブラウザ向けの SystemRDL、IP-XACT の実用的な実装が「無い」こと(npm の検索で見つからなかっただけ)。
- yosys / nextpnr / Apicula の周辺で、SystemRDL や IP-XACT が実際に使われているか(GitHub の検索で見つからなかっただけで、網羅していない)。
- wbgen2、RgGen、airhdl、Hog、SiliconCompiler、orbit、hdlmake の形式の中身。
- cheby の `repeat.count` がパラメータの式を許すか。hdl-registers がパラメータへの依存を書けないこと(文書に記載が無いことからの推測)。
- Edalize の Apicula のフローで、実際にビルドが通るか。
- ここに書いた版と日付は、2026-11-19 に取得した情報。

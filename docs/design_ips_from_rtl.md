# IP の定義を RTL から集める(issue #44)設計の案 2026-11-19

状態: 2026-11-19 と 2026-11-20 にオーナーが決めた(下の「決まったこと」)。段階 1(9K の範囲、7 章)を実装した。収集は `src/nanopynq/build/collect.py`、記述は `src/nanopynq/ipdesc/*.toml`、テストは `tests/test_collect.py`。試作(`tools/p0/ips44/`、`tests/test_p0_ips44.py`)は本体に置き換えたので消した。4K / 20K の型の記述を含む試作は、コミット `d1ace28` にある。以下の 1〜9 章は、判断の前に書いた案のまま残す(段階 1 で変えた点は「決まったこと」に書く)。

## 決まったこと(オーナーの判断)

| # | 項目 | 判断 |
| --- | --- | --- |
| 1 | 主となる案 | E(インスタンスの `BASE` パラメータを読む)。自作の IP 向けに、A(属性 `npq_base`)を逃げ道として残す(2026-11-19) |
| 2 | IP の名前の出どころ | 既定はインスタンスの名前。属性 `npq_name` で上書き。回路を変えたくなければ `nanopynq.toml` の `instance =`(2026-11-19) |
| 3 | IP の記述の形 | **独自の TOML のまま、語彙を既存の形式に合わせ、書き出しで既存の道具とつなぐ**(2026-11-20。`reports/report_metadata_formats_survey.md` の勧めのとおり)。式を許すことは 2026-11-19 に合意 |
| 4 | 手書きとの関係 | 手書きが勝つ。いまの定義ファイルは、そのまま動く(2026-11-19) |
| 5 | 識別値の安定 | 記述のレジスタの形を変えたら、型の版を上げる。テストで縛る(2026-11-19) |
| 6 | 最初の PR の範囲 | 9K の範囲。そのあとは、4K ではなく 20K を先にする(2026-11-19) |

判断 3 の中身(この文書での決め):
- 記述は、1 ファイルに 1 つの型の TOML。純粋な Python(`tomllib`)とブラウザで読める形で、依存を増やさない。既存の形式(SystemRDL、IP-XACT など)は、パラメータに依存する幅と個数を宣言として書けないか、専用のコンパイラが要るので採らない(調査の 1、4 章)。
- 語彙は、仕様 5.3 の `ips` の 1 項目と同じにする。キーは `type`、`base`、`parameters`、`registers`(`offset`、`width`、`access`)。いまの `access` の値(`ro` / `rw` / `wo`)は、OpenTitan、cheby、LiteX と同じ。SVD、IP-XACT、PYNQ の `read-only` / `read-write` / `write-only` へは、機械的に変換できる。`read_effect: true` は `readAction=modify` にあたる(調査の 3 章)。`type` の `ベンダー:名前:版` は、IP-XACT の VLNV の形にならう。
- 記述だけにあるキーは `module`(Verilog のモジュール名。IP-XACT の `moduleName` にあたる)、`when`、`user_parameters` の 3 つ。レジスタの繰り返しが要る型(clk_meter、4K)を足すときは、cheby の `repeat` の語を使う(段階 2)。
- 既存の道具とは、書き出しでつなぐ: 展開したあとの `ips` から CMSIS-SVD と PYNQ の `ip_dict` の形へ、`nanopynq.toml` から EDAM の形の JSON へ。**最初の PR(段階 1)には入れない**(7 章の段階 1 に無いため)。`nanopynq.toml` のキーを FuseSoC / EDAM の語(`files`、`toplevel`)に改めるかどうかも、EDAM の書き出しと合わせて決める。いまのキー(`sources`、`top`)のままにしたのは、判断 4(いまの定義ファイルはそのまま動く)と、段階 1 の範囲に無いため。

段階 1 で、案から変えた点:
- **`base` のある `[ips.X]` は、まるごと手書きの IP として扱う。** 5 章の案は「`[ips.X]` は集めた X に重ねる(`parameters` はキーごとに足し合わせる)」だった。しかし `base_regs.v` に `npq_name` を足したので、いまの手書きの `nanopynq.toml` の `[ips.leds]` は、集めた `leds` と名前が同じになる。重ねると、手書きに無い `parameters` が集めた側から足され、識別値が変わり得る(判断 4 に反する)。そこで、`base` のある項目は、同じ名前の集めた IP と、アドレスの範囲(`base` から `addr_range`)が重なる集めた IP の両方を置き換える(案の「同じ `base`」では、`addr_range` の広い手書きの IP が、その中の集めた IP と重なって V9 で止まる)。手書きのファイルが、回路にある記述つきの IP を 1 つ書き漏らしていると、その IP は集めた側から足され、識別値が変わる。ただし、そのファイルは以前も突き合わせの検査の `outside` で止まっていた(通るのは `--no-crosscheck` のときだけ)。`base` の無い項目だけが、集めた IP に重なる(`parameters` を足し、ほかのキーを置き換える)。`base` が無く、集めた IP のどれにも当たらない項目は、エラーにする(名前の付け忘れを、分かりにくい規則違反でなく、集めた名前の一覧つきで知らせるため)。
- **名前の重複と、記述に合わないモジュールは、`nanopynq.toml` を当てたあとで判断する**(PR #56 のレビュー)。集めた IP は、インスタンスのパスで持つ。generate ループの中の IP や、同じ部品を 2 回置いた中の IP は、既定の名前(パスの最後の要素)が必ずぶつかる。名前の重複は、手書きの項目による置き換えと `instance =` の付け替えのあとで、残った IP にだけエラーにする。ループでは `npq_name` を片方だけに付けられないので、エラー文は `instance =` を案内する。記述と同じ名前で、記述の読むパラメータ(`BASE`、`IS_INPUT` など)を持たない利用者のモジュールは、`nanopynq.toml` が `instance =` か、同じ名前の `base` の無い項目で指したときだけエラーにし、そうでなければ IP にしない。レビューの案は「残ったものはエラー」だった。しかし、式を評価できないインスタンスは `base` が分からず、範囲の重なりでは置き換えられない。そのため、属性の無いいまのファイル(手書きの `[ips.pwm]` と、インスタンスの `timer`)が止まる(判断 4 に反する)。記述の式の誤りで IP が黙って落ちないように、IP にしなかったインスタンスは、パス、モジュール、合わなかった記述ファイルと理由を、stderr に 1 行ずつ表示する(`not an IP: ...`。`--no-crosscheck` のときも出る。オーナーの判断、2026-11-20)。
- ビルドの順序は「設定 → ツールの確認 → 収集・重ね合わせ → 識別値(5.9 の検査) → 突き合わせの検査 → 合成」になった。`ips` は回路を展開しないと決まらないので、`ips` の規則違反(V9 など)は、ツールが無いと見つからなくなった(以前はツールの確認より前に止まった)。
- 記述に書けるキーは、9K の型が使う 7 つ(`type`、`module`、`when`、`base`、`parameters`、`user_parameters`、`registers`)に絞り、知らないキーはエラーにした。`addr_range`、`streams`、`repeat`、`checks` は、それを使う型(4K / 20K)と一緒に段階 2 で足す。式の演算から、`<<` を外した(使う記述が無い)。

## 結論と要約
- **勧める案: E。** インスタンスの `BASE` パラメータ(IP がデコードに使う値)を、yosys で展開した結果(`hierarchy -top; proc; write_json -selected`)から読む。レジスタは、IP の型ごとの記述(TOML)から補う。
- **調査の前提が違っていた。** 「アドレスのデコードは top に手で書かれていて、IP は自分のベースアドレスを知らない」と考えていたが、いまのリポジトリでは成り立たない。top の中のデコードは 1 件も無く、`src/nanopynq/rtl/` のバスにつながる IP は、`sysinfo`(0 番地に固定)を除いてすべて `parameter BASE` を持ち、自分で `hit` を計算している。`BASE` の値がデコードそのものなので、「定義と回路がずれない」性質は、新しい部品を足さなくても既にある。
- 名前は、`(* npq_name *)` の属性か、`nanopynq.toml` の `instance =` で決める。回路に無いパラメータ(`clock_hz` など)は、`nanopynq.toml` に書く。
- 例の PWM では、`nanopynq.toml` の `ips` が **30 行から 2 行**になる(top に属性を 1 行足す。足さない場合は 3 行)。同梱の base は 0 行。
- 組み立てた `ips` の識別値は、8 つのデザインで手書きと一致した: 9K base `0xabf78d8c`、20K base `0xabf78d8c`、例の PWM `0x556fae35`、4K の base `0x79d574b7`、pwm `0x3964d834`、camera `0x68fd1327`、camstream `0xca950154`、camhdmi(手書きの値と一致)。
- 属性を足しても、9K base の `.fs` はビットまで同じだった(同梱の `.fs` と sha256 が一致)。インスタンスの名前を変えると `.fs` は変わる。
- 組み立てた `ips` には、突き合わせの検査がそのままかけられる。記述のオフセットの誤りはエラーになる。`rw` のレジスタの幅を狭く書いた誤りは、警告にしかならない(検査の既存の性質)。

## オーナーに決めてほしいこと
1. **主となる案**: E(`BASE` を読む)+ 型ごとの記述にするか。自作の IP でデコードを top に書く利用者には、A(インスタンスの属性 `npq_base`)を逃げ道として残すか。B と C は採らない、でよいか。
2. **IP の名前の出どころ**: インスタンスの名前(`timer`、`gpio_leds`)と IP の名前(`pwm`、`leds`)は、どのデザインでも違う。「既定はインスタンスの名前 / 属性 `(* npq_name = "pwm" *)` で上書き / top を変えたくない利用者は `nanopynq.toml` に `[ips.pwm] instance = "timer"`」の組み合わせでよいか。
3. **記述の形**: TOML にするか(`=` で始まる文字列を、四則演算・比較・条件式・`len()` だけの式として評価する)。置き場所は `src/nanopynq/rtl/` の隣にするか。
4. **手書きとの関係**: 手書きの項目が、同じ `base` で集めた IP を置き換える(いまの `nanopynq.toml` はそのまま動く)、でよいか。代わりに「集めるのは明示したときだけ」というスイッチにする手もある。
5. **識別値の安定**: 記述のレジスタの形を変えたら、型の版(`nanopynq:pwm_timer:1.0` → `1.1`)を必ず上げる。これを、型と版ごとに記述のハッシュを固定するテストで縛るか。
6. **最初の PR の範囲**: 7 章の段階 1 でよいか。より小さく「D だけ」(回路は読まない)にするか。

## 1. 前提の確認(確かめた事実)
- **top にアドレスのデコードは無い。** `git grep -nE "adr\[29|20'h|- *BASE" -- '*.v'` を実行しても、top の中のデコードは 1 件も見つからなかった。`gateware/boards/**` と `examples/` の top は、`pwm_timer #(.BASE(32'h0000_7000)) timer (...)` のように IP に `BASE` を渡し、`hit` を OR して `base_regs` の `ext_*` につないでいるだけ。
- `BASE` を持つ IP: regbus_gpio、pwm_timer、clk_meter、i2c_master、dvp_frontend、capture、frame_ring、hdmi_testpat、spi_master、cam_fb、uflash_reader、bus_cdc。
- 例外: `sysinfo` は 0 番地に固定。camhdmi では、`bus_cdc` と `cam_fb` がどちらも `BASE=0x6000` を持つ。`bus_cdc` には記述が無いので、IP としては拾わない。

## 2. yosys で確かめたこと(YoWASP yosys 0.70)
小さな例(モジュール・インスタンス・パラメータ・配線・ポートに属性を付けたもの)を、段階ごとに `write_json` して確かめた。

| 対象 | `hierarchy` のあと | `proc` | `flatten` のあと | `opt` のあと |
| --- | --- | --- | --- | --- |
| モジュールの属性 | 残る。パラメータ付きで作られたモジュール `$paramod$<hash>\leaf` にも写り、元の名前が `hdlname` に入る | 残る | モジュールは消える。`$scopeinfo` セルに `module_<名前>` として残る | 残る(`$scopeinfo`) |
| インスタンスの属性 | セルに残る。整数は 32 ビットの 2 進の文字列、文字列はそのまま | 残る | `$scopeinfo` に `cell_<名前>` として残る | 残る |
| パラメータの属性 | **`read_verilog` の時点で消える**(RTLIL に出ない) | — | — | — |
| 配線・ポートの属性 | 残る | 残る | 階層名(`a.q`)の配線に残る | 残る |
| パラメータの値 | セルの `parameters` は空になる。値は、作られたモジュールの `parameter_default_values` に入る。既定値のままのインスタンスは元のモジュールを指し、`module_not_derived=1` が付く | 同じ | **消える**(`$scopeinfo` にはモジュールの名前しか無く、作られたモジュールも消える) | — |
| localparam | `parameter_default_values` に出ない(frame_ring の `WIN` など) | | | |

ほかに分かったこと:
- `hierarchy` の直後の `write_json` は、プロセスが残っているためエラーになる。`proc` が要る。
- Gowin の部品のライブラリ(`read_verilog -lib +/gowin/cells_sim.v`)を読むと、ライブラリの中の ALU のプロセスで `write_json` が止まる。**`write_json -selected` で回避**できる(箱のモジュールを書かない)。
- `write_json` は、`01xz` だけからなる文字列の末尾に空白を 1 つ足す(ビット列と区別するため)。
- 展開にかかる時間は、各デザインで 0.2〜0.3 秒。
- **読む段階は `flatten` の前。** 突き合わせの検査の前処理(`flatten` まで進む)とは、同じ JSON を共有できない。展開は 0.3 秒なので、別に 1 回走らせてかまわない。
- 回路に対する影響(9K base を実際に合成・配置配線して確かめた):
  - `base_regs.v` のインスタンスに `npq_name` の属性を付けても、`.fs` の sha256 は同じ(`0e1516…61ef8`。同梱の `base.fs` とも一致)。行がずれる形で写しを作っても同じ。テスト `test_the_attributes_do_not_change_the_bitstream` で縛っている。
  - インスタンスの名前を変えると、`.fs` は変わる(`eaadfd…a3de8e`)。さらに、`leds` のようにポートと同じ名前には、名前を変えられない(yosys がエラーにする。Verilog では、同じモジュールの中で名前を共有するため)。**「IP の名前 = インスタンスの名前」だけでは決めきれず、属性か対応表が要る。**

## 3. 代替案と、試した結果

| | 現状維持 | A: インスタンスの属性 `npq_base` | **E: `BASE` パラメータを読む** | B: デコードを持つ共通の部品 | C: `sat` で番地を探す | D: 名前・型・ベースだけ手で書く |
| --- | --- | --- | --- | --- | --- | --- |
| 試した結果 | — | 小さな自作 IP(top でデコード)で、ベースを読めた(テスト)。`BASE` と食い違うとエラーにする処理も試した | 8 デザインで識別値が一致 | **作っていない**(下の推定) | **走らせていない**(下の推定) | `fill()` を実装。例の PWM、9K base、4K pwm、camstream で一致 |
| 例の PWM で書く量(`ips` の部分) | 30 行 | 名前と `clock_hz` のぶん。top に属性が要る | **2 行**(+ top に 1 行。top を変えないなら 3 行) | E と同じ程度 + top の書き換え | 型と名前は結局書く | 15 行(空行を除く) |
| ずれの起きにくさ | 検査頼み | 属性とデコードがずれ得る(検査で見つかる) | **ずれない**(パラメータがデコードそのもの) | ずれない | — | ベースはずれ得る(検査で見つかる) |
| top を縛る度合い | 無し | 属性だけ | 無し(属性も任意) | 部品を通すよう書き換える | 無し | 無し |
| 既存の 11 本の移行 | — | 属性を足す | **不要**(名前は toml の `instance=` でも決められる) | 全部書き換え | — | `registers` を消すだけ |
| 実装の量 | 0 | E に含まれる | `collect.py` の約 250 行(D を含む) | 部品と記述 | 大 | 約 10 行 + 記述 |
| リスク | 書き写しの誤り | 小 | yosys の JSON の形に依存(版を固定しているので小) | 書き換えで `.fs` が全部変わる | 時間とあいまいさ | 小 |

- **B を作らなかった理由(推定)**: nanopynq の IP は、すでに `BASE` からデコードしている。B の部品は、これと同じことをする外側の箱になる。そのうえ、部品とその先の IP の型を結ぶ印が別に要る。自作の IP 向けの小さな部品として、後で配る価値はある。
- **C を走らせなかった理由(推定)**: 測った手がかりは、例の PWM の突き合わせの検査が 35 回の問い合わせで 5.1 秒だったことだけ。「応答する番地を 1 つ見つけ、除外して次を探す」探索は、応答する語の数だけ問い合わせが要る(capture の窓は 5120 語、frame_ring の窓は 256 語)。同じ型の IP が 2 個あると、どちらがどれかは決められない。名前、型、パラメータも決まらない。見つけた番地の検証(いまの検査)には向くが、定義の出どころとしては割に合わない。

## 4. IP の記述の形
1 ファイルに 1 つの型を書く。形は仕様 5.3 の `ips` の 1 項目に、`module`、`when`、`user_parameters`、`checks` を足したもの。`=` で始まる文字列は式として評価する(Python の `ast` で、許した節点だけを評価する約 25 行。`__import__` などはエラー)。

- `base` と `parameters` の式は、Verilog のパラメータ(`BASE`、`WIDTH`)を見る。
- `registers` と `streams` の式は、IP のパラメータ(`width`)を見る。このため、同じ記述が D(Verilog を読まない)でも使える。

```toml
# desc/gpio_out.toml(regbus_gpio は IS_INPUT で 2 つの型に分かれる)
type = "nanopynq:gpio_out:1.0"
module = "regbus_gpio"
when = "=IS_INPUT == 0"
base = "=BASE"
parameters.width = "=WIDTH"
registers.data = { offset = "0x0", width = "=width", access = "rw" }
```
```toml
# desc/pwm_timer.toml(clock_hz は回路に無い: nanopynq.toml が与える)
type = "nanopynq:pwm_timer:1.0"
module = "pwm_timer"
base = "=BASE"
user_parameters = ["clock_hz"]
registers.ctrl = { offset = "0x0", width = 1, access = "rw" }
registers.period = { offset = "0x4", width = 32, access = "rw" }
registers.duty = { offset = "0x8", width = 32, access = "rw" }
registers.count = { offset = "0xc", width = 32, access = "ro" }
registers.wraps = { offset = "0x10", width = 32, access = "ro" }
```
```toml
# desc/clk_meter.toml(レジスタの数がパラメータで変わる)
type = "nanopynq:clk_meter:1.0"
module = "clk_meter"
base = "=BASE"
user_parameters = ["gate_hz", "channels"]
registers.status = { offset = "0x0", width = "=8 + len(channels)", access = "ro" }
registers."count{i}" = { repeat = "=len(channels)", offset = "=4 + 4 * i", width = 24, access = "ro" }
checks = ["=len(channels) == N", "=W == 24"]
```

- ストリームを持つ型の例は `desc/frame_ring.toml`(`addr_range = "0x2000"`、`parameters.slot_words = "=SLOT_WORDS"`、`window = 1024`(localparam なので定数で書く)、`streams.video = {...}`)。
- 洗い出した、実際に要る表現: 値をそのまま写す(gpio の `width`、frame_ring の `slot_words` / `slots`)/ 演算(capture の `capacity = DEPTH*4`、clk_meter の `status` の幅 `8+N`)/ 条件で型を選ぶ(regbus_gpio の `IS_INPUT`)/ レジスタの繰り返し(clk_meter の `count0..N-1`)/ 回路に無い値(`clock_hz`、`gate_hz`、`channels`、cam_fb の `hdmi`)。「Verilog のパラメータの値を写すだけ」では足りないので、式は要る。
- **置き場所**: nanopynq が配る分は、`src/nanopynq/rtl/` の隣(パッケージの中)。利用者の分は、デザインのフォルダの中(たとえば `ip/*.toml`)に置き、nanopynq の分のあとに読む。Python のデータにすると、ビルドのときに利用者のコードを実行することになるので、TOML を勧める。
- **記述の誤りは見つかるか(確かめた)**: pwm の `wraps` のオフセットを `0x14` にした記述 → 検査のエラー(`no_slave ips.pwm.registers.wraps` と `undeclared 0x7010`)。gpio_out の `data` の幅を 4 にした記述(回路は 5)→ **警告だけ**(`not_rw`)。
- 記述と回路の食い違いのうち、記述の中で確かめられるもの(clk_meter の `channels` の数と `N`)は、`checks` でエラーにする(テスト済み)。

## 5. 利用者から見た形
例の PWM、前(`ips` の部分 30 行、ファイル全体 47 行):
```toml
[ips.sys]
base = "0x0000"
type = "nanopynq:sysinfo:1.1"
registers.id = { offset = "0x0", width = 32, access = "ro" }
# ... 4 つの IP、レジスタ 12 個
```
後(ファイル全体 19 行):
```toml
# sys, leds, buttons は base_regs から、pwm は pwm_timer の BASE から集める。回路に無い値だけ書く。
[ips.pwm]
parameters = { clock_hz = 27000000 }
```
top は 1 行足すだけ(足さない場合は、toml に `instance = "timer"` を書く):
```verilog
    (* npq_name = "pwm" *)
    pwm_timer #(.BASE(32'h0000_7000)) timer ( ... );
```
nanopynq 側の `base_regs.v` の変更(属性 3 つ。`.fs` は変わらないことを確かめた):
```verilog
    (* npq_name = "sys" *)
    sysinfo #(.DESIGN_ID(DESIGN_ID)) si ( ... );
    (* npq_name = "leds" *)
    regbus_gpio #(.BASE(32'h0000_1000), ...) gpio_leds ( ... );
    (* npq_name = "buttons" *)
    regbus_gpio #(.BASE(32'h0000_2000), ...) gpio_btns ( ... );
```
D の形(回路は読まない。15 行):
```toml
[ips.sys]
base = "0x0000"
type = "nanopynq:sysinfo:1.1"
[ips.leds]
base = "0x1000"
type = "nanopynq:gpio_out:1.0"
parameters = { width = 5 }
# ...
```

- **手で書く形との関係**: toml の `[ips.X]` は、集めた X に重ねる。`parameters` はキーごとに足し合わせ、ほかの項目は置き換える。`instance =` で名前を付け替えられる。集めた IP に当たらない項目は、手書きの IP として扱う(完全に書く必要がある)。同じ `base` の、集めた IP を置き換える。**今の `nanopynq.toml` を今の(属性の無い)ファイルにかけると、`ips` は手書きのものとまったく同じになる**(テスト `test_todays_nanopynq_toml_on_todays_files`)。
- **確かめ方(案)**: ビルドのときに、集めた IP の表(名前、インスタンスの階層名、ベース、型)を表示する。集めた `ips` を `build/ips.json` に書く。`.npq` には、もともと完全な `ips` が入る。
- **識別値への影響**: 集めた `ips` は、nanopynq の版に入っている記述に依存する。共通の回路(`src/nanopynq/rtl/`)と同じく、記述も「nanopynq の版」という入力の一部として扱う(`build.json` は nanopynq の版をすでに記録している)。そのうえで、次の決まりを置く。
  1. レジスタの形を変えたら、型の版を上げる。テストで、型と版ごとに記述のハッシュを固定する。
  2. 固定したい利用者は、`build/ips.json` を `nanopynq.toml` に写せば、手書きが勝つ。
  3. 識別値の計算は `ips` だけから行う、という仕様 5.4 は変えない。
- **移行の手間**: 同梱の 5 件は、`base_regs.v` に属性を 3 つ足せば、`tools/build_base.py` の `ips` のテンプレートが要らなくなる(9K と 20K の base は、toml 0 行)。4K の確認用のデザインは、`instance =` で名前を対応させ、回路に無いパラメータだけを書く(top は変えなくてよい。テスト済み)。例は、toml の 28 行を消し、top に 1 行足す。

## 6. セルフ反論と応答
- **反論**: `BASE` は nanopynq の中だけの慣習で、利用者の IP は従わないかもしれない。
  **応答**: 記述の `base` は式なので、どのパラメータの名前でも指せる(`"=ADDR"`)。パラメータが無い IP は、属性 `npq_base` で書ける。属性がデコードとずれても、検査で見つかる。両方あって食い違えば、エラーにする(テスト済み)。
- **反論**: 式の小さな言語を、新しく持つことになる。
  **応答**: 許すのは、整数・文字列・四則・比較・条件式・`len` だけ。代わりに Python で書かせると、利用者のコードを実行することになり、もっと重い問題になる。
- **反論**: 結局、名前のために RTL か toml に何か書く。
  **応答**: そのとおり。名前は回路から決めきれない(ポートと同じ名前に、インスタンスの名前を変えられない)。それでも書くのは 1 行で、`.fs` は変わらない。
- **反論**: 「同じ `base` なら置き換える」は暗黙で、誤解を招く。
  **応答**: 手書きのベースを誤ると、集めた IP が残って手書きの IP と並ぶ。その場合は、範囲の重なり(V9)か、検査の `no_slave` で止まる。暗黙が嫌なら、明示のスイッチ(決めてほしいことの 4)にする。
- **反論**: nanopynq の版を上げると、同じソースから違う `.fs` ができる。
  **応答**: 共通の回路でも同じことがすでに起きる。型の版の決まりと、手書きでの固定で扱う(5 章)。
- **反論**: generate のインスタンス(`meter.ch[0].u`)の名前は、IP の名前の決まりに合わない。
  **応答**: 記述のある IP で決まりに合わない名前はエラーにし、`npq_name` か `instance=` を求める(試作で実装済み)。

## 7. 段階の切り方
- **段階 1(1 つの PR。2026-11-20 に実装)**:
  - 9K で使う型の記述(sysinfo、gpio_out、gpio_in、pwm_timer)をパッケージに入れる。
  - 収集(展開、収集、重ね合わせ)を `src/nanopynq/build/` に置く。
  - `nanopynq.toml` の `ips` を省略できるようにする。
  - `base_regs.v` に属性を 3 つ足す。
  - 集めた結果の表示と `build/ips.json` を足す。
  - 例を新しい形に移す。
  - 識別値が一致するテストと、記述のハッシュのテストを足す。
  - 4K の型、利用者の記述のフォルダ、D の `fill()` は入れない。
- **段階 2**: 利用者の記述のフォルダ、4K / 20K の型の記述(4K / 20K が `nanopynq build` の対象になるのに合わせて)、`tools/build_base.py` のテンプレートを収集に置き換える。
- より小さい代わり: 段階 0 として **D だけ**(記述 + `fill()`、約 10 行 + 記述)。回路を読まないので、ずれの面では今と同じ。書く量は 30 行から 15 行になる。

## 8. 関連する候補の見立て(深追いしていない)
- **アドレスの自動割り当て**: IP がすでに `BASE` を持つので、「割り当てた値を `chparam` で渡し、`build/addrmap.toml` に記録して固定する」形は自然に乗る。B の部品は要らない。ただし、`chparam` の値は `.fs` に効き、記録の扱いは再現性の決まりに関わるので、別の issue で決めるのがよい。
- **ボードの部品から `.cst` を作る**: `boards.yaml` にピンの情報が無いので、まずその項目を足すところからになる。この issue の範囲とは独立している。

## 9. 確かめられなかったこと
- B と C は、実際に作っても走らせてもいない(3 章の推定)。A は、小さな自作 IP 1 つと、PWM での食い違いの検出だけで試した。
- 4K と 20K は、展開(`hierarchy`)まで。合成と配置配線、属性が `.fs` に影響しないことは、9K でだけ確かめた。
- 記述を書いていない型がある: spi_master、hdmi_testpat、uflash_reader(pllcheck、spiflash、hdmi は試していない)。
- capture の窓の扱い(#32 の「定義に無い番地が応答する」)は、記述では解決していない。
- 符号付きのパラメータや、x / z を含むパラメータの読み取りは扱っていない。
- Windows での動作は確かめていない。
- `nanopynq build` への組み込み、表示、`build/ips.json` は作っていない(範囲の外)。

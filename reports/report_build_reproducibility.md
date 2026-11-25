# ビルドの再現性(Tang Nano 9K の base)2026-11-18

issue #31 の調査。実機は使っていない(書き込みなし)。

## 結論
- **同じ PC・同じ入力なら、何度作っても同じ `.fs` になる。** 今の `main`(4011740)から 9K の base を 3 回作ると、3 回とも `f12bfd3e…` だった。出力先、一時フォルダ、チェックアウトの場所、ソースの改行を変えても、結果は変わらなかった。
- **同梱の `.fs`(`3a2b9bec…`)は再現できた。原因も特定できた。** 同梱を最後に作ったコミット df998b8 を取り出して今の道具で作ると、`3a2b9bec…` とバイト単位で一致した。道具の版、種、OS は原因ではない。
- **原因: `tools/build_base.py` が `gateware/rtl/*.v` をすべて yosys に読ませていること。** df998b8 のあとに、9K の base が使わないファイルが 12 個増えた。そのうち `cam_fb.v`(10d2337)か `clk_meter.v`(ba54d18)の 1 つを足すだけで、合成した `top` が変わり(セル 781 → 815)、配置配線も変わる。読み込む順番を変えただけでも sha256 が変わる。
  - 確かめた事実: yosys の出力は、読み込むファイルの組と順番で変わる。使わないモジュールのファイルでも変わる。
  - 仕組みと、ほかの 10 ファイルが効かない理由は分かっていない(推定: yosys の内部の名前付けや処理の順序)。
- **勧める決まり(6 章の案 A + C):** デザインごとに読み込むソースを明示した一覧にし、作ったときの条件を記録する。

## 1. 結果の一覧

実行した環境: Linux。yowasp-yosys 0.70.0.0.post1259、yowasp-nextpnr-himbaechel-gowin 0.11.1.0.post826、Apicula 0.32、yowasp-runtime 1.96、wasmtime 47.0.1。種は、特に書いていないものは 1。

| # | 条件 | sha256 |
| --- | --- | --- |
| 1〜3 | main 4011740。出力先を run1、run2、深いパスの run3 に変え、run3 では TMPDIR も変えた | `f12bfd3e986589d5…`(3 回一致) |
| 4 | main、`--seed 2` | `401b6054…` |
| 5 | df998b8 を `git archive` で取り出して作る | `3a2b9bec62534c24…`(**同梱と一致**) |
| 6 | 5 のソース(`.v` と `.cst`)を CRLF にする | `3a2b9bec…` |
| 7 | b277972 を取り出して Linux で作る | `71498371…`(Windows で作った記録 `report_p0_windows.md` と一致) |
| 8 | main から、df998b8 のあとに増えた rtl の 12 ファイルを除く | `3a2b9bec…` |
| 9 | 8 に加えて、`dvp_frontend.v` を df998b8 の版に戻す | `3a2b9bec…` |
| 10 | 8 に、ほかの 10 ファイルを 1 つずつ足す | どれも `3a2b9bec…` |
| 11 | 8 に `cam_fb.v` だけを足す | `f12bfd3e…` |
| 12 | 8 に `clk_meter.v` だけを足す | `c8e4904a…` |
| 13 | 8 の読み込む順番だけを逆にする | `560efa74…` |
| 14 | 9K が使う 7 モジュールと `top.v` だけを読ませる(2 回) | `b50b8018…`(2 回一致) |
| 15、16 | 14 に cam_fb を足す / さらに clk_meter も足す | `fae81067…` / `db2a668f…` |

- 10 で足した 10 ファイル: bus_cdc、fb_display、frame_ring、hdmi_testpat、hyperram_ctrl、pwm_timer、spi_master、tmds_encoder、uflash_reader、video_timing。
- 14 の 7 モジュール: base_soc、uartbone_bridge、uart_rx、uart_tx、base_regs、sysinfo、regbus_gpio。インスタンスを grep で拾って決めた。
- 8〜12 は、main を `git archive` で取り出してファイルを抜いたもので、`build_base.py` を実行した結果。13〜16 は、`build_gowin` にソースの一覧を直接渡して作った結果。

## 2. 同じ PC で繰り返して作る
```
uv sync --extra build
uv run python tools/build_base.py --board tangnano9k --out build-31/run1   # run2 も同じ
TMPDIR=$PWD/build-31/tmp2 uv run python tools/build_base.py --board tangnano9k --out build-31/a/very/deep/out_dir_name_x/run3
```
- 3 回とも `f12bfd3e…`。1 回は約 5 秒。
- `--out` のパスは道具に届かない。`build_base.py` は一時フォルダの中で作り、できた `.fs` を `--out` へコピーするだけ。道具に届くのは、ソースの絶対パスと一時フォルダ。パスが成果物に入らないことの根拠は次のとおり。
  - run3 では TMPDIR を変えた。
  - 別の作業ツリー(実験 A2 の `build-a2/bb-before`)の値も `f12bfd3e…` で、この作業ツリーの値と同じ。
  - 深さの違う取り出し先(`build-31/src-*`)でも、期待どおりの値になった。
  - `.fs` にはパスが入らない(3 章)。

## 3. 同梱と作り直しの `.fs` の違い
- 行数は、どちらも 728 行。0 と 1 以外の行(コメントなど)は無い。道具の版や日時は `.fs` に入っていない。
- 違う行は 714 行(98%)、違うビットは 143,059。同じなのは先頭の 5 行だけ。
- 10 等分した各区間に、違う行が 63〜73 行ずつある。配置配線の結果そのものの違いである。

## 4. 違いの出どころの候補
- **道具の版: 原因ではない。** df998b8 と今の main で、`pyproject.toml` の `==` 固定と、`uv.lock` の版(yowasp-runtime 1.96、wasmtime 47.0.1、Apicula 0.32)は同じ。df998b8 から今の道具で作ると一致する。
- **Apicula:** nextpnr のホイールが `Requires-Dist: Apicula==0.32` で固定している。別の依存ではない。
- **Dependabot:** `yowasp-*` を除外している。Dependabot のコミット(#18〜#20)は pytest、libusb-package、uv_build だけ。
- **種: 原因ではない。** 既定は 1(`build_base.py` と `build_gowin` の両方)。74464db のメッセージに「deterministic, seed 1」とある。種を 2 にすると変わる(表の 4)が、同梱も作り直しも種 1。
- **OS: 原因ではない。** Windows で作った b277972 の値 `71498371…` が Linux でも一致した。df998b8 をどの OS で作ったかの記録は無い。
- **入力の改行: 原因ではない。** CRLF でも同じ(表の 6)。
- **パス: 原因ではない。** 2 章のとおり。issue #12 の修正(668f005)のあとのコードでも、表の 8 で同梱と一致する。
- **ソース: 原因。** df998b8 のあとの rtl の変更(a3c1120〜daa5fb7)は、9K が使うモジュールには触れていない。触れたのは dvp_frontend の変更と 12 ファイルの追加だけ。それでも `sorted(glob("*.v"))`(`tools/build_base.py`)で全部読むので、出力が変わる。
- 合成の比較(組 8 と、組 8 + cam_fb を `build_base.py` と同じ順番で読ませたもの): `top` のセル数は 781 と 815。名前の違うセルが 324 個あり、LUT と MUX の割り当てが違う。cam_fb を一覧の後ろに置くと、`top` は組 8 と同じになり、`.fs` も `3a2b9bec…`。違いは、セルライブラリの `$specify$N` などの番号だけだった。
- `cam_fb.v` と `clk_meter.v` に `` `define ``、`` `include ``、`` `default_nettype `` は無い。プリプロセッサの設定が漏れているわけではない。

## 5. 同梱を作ったときの条件の再現
- **9K:**
  - 条件: df998b8 のソースと `build_base.py`、種 1、今と同じ `uv.lock`。過去の版の道具を取得する問題は無かった。
  - 再現: `git archive df998b8 | tar -x -C build-31/src-df998b8` → そこで `uv sync --extra build` → `TMPDIR=<作業ツリー>/build-31/tmp uv run python tools/build_base.py --board tangnano9k --out ../old-df998b8` で `3a2b9bec…`。古いコミットは issue #12 の修正の前なので、念のため TMPDIR を作業ツリーの中にした(必要だったかは試していない)。
  - 10d2337 と ba54d18(どちらも 11-05)で、「main から作った値」は 2 回変わった。
- **4K(base、camera、camstream):**
  - 道具は oss-cad-suite 2026-10-22 と、Apicula 0.35 にパッチを当てた写し、それから作り直した chipdb(`tools/p0/gwjtag4k/README.md`)。種は 1。
  - 最後に作ったコミットは、base が df998b8、camera が df27a5d、camstream が c2c6514。
  - パッチを当てた Apicula と chipdb はリポジトリに無いので、特定できない。
  - 同じ glob を使うので、今の main から作ると合わない可能性が高い(推定)。OSS、OVL、CHIPDB が無いので試していない。
- **20K:**
  - 5316cbc で作った。道具は oss-cad-suite 2026-11-15(Yosys 0.71+34、nextpnr 5e2718b6)、pack は apycula==0.35 を PYTHONPATH=OVL で上書きしたもの。CHIPDB は oss-cad-suite のもの。種は 1。
  - OVL に使った Apicula の版の記録は無い。
  - 5316cbc のあと `gateware/` は変わっていないので、上の原因は当てはまらない。
  - 作り直しは試していない。

## 6. 作り直しの決まりの案
- **A: ソースの明示的な一覧。** `DESIGNS` に、読み込む `.v` を順番どおりに書く。
  - 良い点: 原因を構造的に断つ。rtl にファイルが増えても `.fs` は変わらない(表の 14 は 2 回一致。一覧に無いファイルは読まれない)。
  - 弱い点: 一覧の手入れが要る。足し忘れは yosys のエラーで分かる。一覧を変えると `.fs` も変わる(表の 15、16)が、そのことは差分で見える。
- **B: glob のままで、CI で作り直して sha256 を比べる。**
  - 良い点: 原因が何でも、ずれを見つけられる。
  - 弱い点: 無関係なファイルを足すたびに落ち、そのたびに同梱の作り直しと実機の確認が要る。CI で作れるのは 9K だけ。
- **C: 作ったときの条件の記録。** ソースのコミット、道具の版(oss-cad-suite の日付、OVL と chipdb の sha256 も)、種、OS、コマンドを、同梱のデザインの横に書く。
  - 良い点: 4K と 20K のように、道具をリポジトリで固定できない場合でも、何を揃えればよいかが分かる。
  - 弱い点: 記録だけでは、ずれは防げない。
- **勧める案: A を主にして、C を併用する。** B は、A のあとに 9K だけの安全網として足す価値がある。
  - 道具の版の固定と Dependabot の除外は、今のままでよい。
  - 種は 1 に固定する。
  - 作る環境は問わない(Windows と Linux で同じになることを確かめた)。
  - A を入れると 9K の値が変わる(`b50b8018…`)ので、sysinfo 1.1 での作り直し(issue #32)と同時に入れる。

## 7. 確かめられなかったこと
- cam_fb と clk_meter だけが効く理由と、yosys の中のどの処理が順番に依存しているか。
- 4K と 20K の作り直し。
- df998b8 を作った OS(結果には影響しない)。
- yowasp-runtime(`~=1.12`)と wasmtime の版を変えたときの影響。これらは `uv.lock` でしか固定されていない。
- `pip install nanopynq[build]`(lock を使わない導入)で作った場合に一致するか。
- 作り直した `.fs` が実機で動くか。

## 8. 範囲の外で気づいたこと
- `tools/p0/repro_build.py` も同じ glob を使っている。
- `tests/test_bundled_designs.py` は、manifest と同梱のファイルが合うかを見るだけで、作り直して比べてはいない。このずれを見つけられない。
- `nanopynq build`(issue #27)で「同じ入力から同じ `.fs`」を約束するなら、「入力」には、読み込むファイルの組と順番が含まれる。

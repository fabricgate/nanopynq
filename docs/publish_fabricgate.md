# nanopynq のデザインを FabricGate に公開する手順(2026-11-20)

## 結論と要約

- `nanopynq build` の出力(`.fs` と `.npq`)から、`fabricgate build --npq` で FabricGate のパッケージを作り、`fabricgate push` で登録する。
- FabricGate は配布と完全性の確認(ダイジェスト)だけを担い、`.npq` の中身は解釈しない。意味の解釈とデザインの照合は nanopynq が行う。
- 登録したデザインは、`fabricgate pull` で取得したフォルダを `Overlay(フォルダ)` に渡すか、`Overlay("fabricgate://<namespace>/<design>:<version>", board=...)` で使う(README の「Designs from FabricGate」)。
- `.npq` を扱える fabricgate は、PyPI の 0.7.0 から(2026-11-20。0.6.0 以前は不可)。`nanopynq[fabricgate]` は `fabricgate>=0.7` を入れる。
- 検証用の registry で、登録(`push`)、取得(`pull`、`verify`)、FabricGate の Web のパネルからの実機の操作まで通した(2026-11-20)。本番の registry への登録と、registry から取得したデザインを `Overlay` で使うことは、まだ確かめていない(最後の節)。

## 0. 前提

- **fabricgate の CLI は、`.npq` に対応した版(0.7.0 以降)を使う。** 次のどちらか。
  - CLI だけを使うなら、PyPI の版を使う。
    ```
    alias fg='uvx fabricgate@0.7.0'
    ```
  - nanopynq を `nanopynq[fabricgate]` で入れた環境なら、`fabricgate` コマンドが入っている(0.7.0 以降)。
  - 以下では `fg` と書く。
- **宛先の registry は、毎回 `--registry` で明示する。** 省くと `FG_REGISTRY`、次に `~/.fabricgate/config.yaml` の `registry` が使われ、どちらも無ければ本番の registry に送る。
  ```
  REG=<registry の API の URL。末尾は /api/v1>
  ```
- **namespace** は、登録する人が書き込める namespace を使う。以下では `<ns>` と書く。
- registry の側が、`.npq` を持つ nanopynq の成果物を受け付ける版であること。

## 1. 成果物を用意する

自分のデザインなら、`nanopynq build` で作る(README の「Building your own gateware」)。

```
uv run nanopynq build examples/tangnano9k_pwm      # → examples/tangnano9k_pwm/dist/{pwm.fs,pwm.npq,build.json}
```

同梱の base デザインなら、そのフォルダをそのまま使う(`.npq` を持つものに限る。2026-11-20 の時点では、9K と 20K の base と 20K の sdram)。

```
cp -r src/nanopynq/data/designs/tangnano9k-base /tmp/base-src     # base.fs, base.npq, build.json
```

ビルドは再現する。同じソースと `build.json` に記録された版のツールなら、`.fs` と `.npq` はバイト単位で同じになる。

## 2. パッケージを作る

`--npq` に `.npq` を渡す。`.npq` が名指す `.fs` は、同じフォルダから読まれる。対話で、デザイン名・版(Enter で `--version` の値)・説明を聞かれる。

```
fg build examples/tangnano9k_pwm/dist --npq examples/tangnano9k_pwm/dist/pwm.npq \
  --namespace <ns> --version 1.0.0 --tags nanopynq,tangnano9k,gowin,pwm --output /tmp/pwm-pkg
#   Design name: <ns>/tangnano9k-pwm
#   Description: PWM LED example for the Tang Nano 9K, built with nanopynq build.
```

できるもの:

```
pwm-pkg/fabricgate-index.yaml
pwm-pkg/tangnano9k/nanopynq/manifest.yaml     # runtime: nanopynq、artifacts.bitstream(.fs)と artifacts.metadata(.npq)
pwm-pkg/tangnano9k/nanopynq/pwm.fs
pwm-pkg/tangnano9k/nanopynq/pwm.npq
```

- プラットフォームは `<board>/nanopynq`。`<board>` は `.npq` の `board`。
- `fabricgate-index.yaml` に `license`(SPDX)を入れるなら、ここで手で足す。
- `README.md` をパッケージのフォルダ(`fabricgate-index.yaml` の隣)に置くと、`push` が registry に送り、デザインのページに出る。`fabricgate build` は README を写さないので、手で置く。サンプルの README は `examples/<名前>/README.md`。送るのは fabricgate/fabricgate#192 を入れた CLI から(0.7.0 は送らない)。
- デザイン名・版・説明・タグは、登録すると変えにくい。本番の前に決める。

## 3. 登録する

registry に書き込む操作なので、namespace の持ち主が行う。

```
fg --registry $REG login
fg --registry $REG push /tmp/pwm-pkg
```

`push` には試しに流す手段(dry run)が無い。宛先を取り違えないよう、先に同じ `--registry` で読むだけの操作(`fg --registry $REG search <語>` など)を流し、思った registry の中身が返ることを確かめてから `push` する。

## 4. 確かめる

取得して、フォルダを `Overlay` に渡す。

```
fg --registry $REG pull <ns>/tangnano9k-pwm:1.0.0 --platform tangnano9k/nanopynq --output /tmp/pwm-pulled
sha256sum /tmp/pwm-pulled/pwm.fs /tmp/pwm-pulled/pwm.npq    # 手順 1 の dist/ のものと同じ
```

```python
from nanopynq import Overlay
ol = Overlay("/tmp/pwm-pulled")    # FabricGate の manifest.yaml は読まず、pwm.npq を読む
```

`fabricgate://` でも確かめる(`nanopynq[fabricgate]` が要る)。宛先は fabricgate の CLI と同じ設定(`FG_REGISTRY`、または `~/.fabricgate/config.yaml` の `registry`)から決まる。

```
FG_REGISTRY=$REG python -c 'from nanopynq import Overlay; Overlay("fabricgate://<ns>/tangnano9k-pwm:1.0.0", board="tangnano9k")'
```

1 回目は取得して `~/.cache/nanopynq/fabricgate/<registry>/<ns>/tangnano9k-pwm/1.0.0/tangnano9k/` に置く(`XDG_CACHE_HOME` があればその下)。`<registry>` は registry の URL をフォルダ名にしたもの(ホスト・ポート・パス。例: `registry.fabricgate.dev_api_v1`)。2 回目からは registry に問い合わせず、そのフォルダを使う。取り直すときは、そのフォルダを消す。

## 5. 確かめたこと・確かめていないこと

- 確かめた(手元、通信なし)
  - 手順 2 のパッケージの作成(2026-11-19)
  - fabricgate の取得の処理(commit `42a4e07`)を偽の registry につないで取得し、フォルダに `manifest.yaml`、`.fs`、`.npq` が同じ階層に並ぶこと。そのフォルダを nanopynq が `.npq` として読めること(2026-11-20)
  - `fabricgate://` の取得・キャッシュ・エラーの処理(偽の SDK を使うテスト。`tests/test_fabricgate.py`)
- 確かめた(検証用の registry、2026-11-20)
  - 同梱の `tangnano9k-base` を、PyPI の fabricgate 0.7.0 で手順 2 と 3 のとおりに登録した(プラットフォーム `tangnano9k/nanopynq`)。registry の版の詳細に `base.fs` と `base.npq` が載り、sha256 は同梱のものと同じ
  - 手順 4 の `pull` と `fg verify` を、ログインしていないまっさらな環境で流した。取得した `base.fs` と `base.npq` の sha256 は同梱のものと同じ
  - FabricGate の Web のデザインのページの操作パネルで、実機(Tang Nano 9K、Windows、Chromium 系のブラウザ)につないだ。LED、ボタン、レジスタの読み書きが動いた(オーナーの報告)。部品は照合が通ったあとにしか作られないので、ボードの回路の識別値は `.npq` と同じ `0xabf78d8c` だった
- 確かめていない
  - 本番の registry への登録(nanopynq のデザインは、本番にまだ無い)
  - 手順 4 の、registry から取得したフォルダを `Overlay` に渡すことと、実際の registry からの `fabricgate://`
  - 自分でビルドしたデザイン(`examples/tangnano9k_pwm` など)の登録。登録したのは同梱の base だけ

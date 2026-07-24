# SETUP — 取得・生成スクリプトの動かし方

このリポジトリを自分でフォーク／セットアップして、Danbooruタグ一覧を
自前で取得・自動更新したい人向けのドキュメントです。生成されたファイルを
使うだけの方は [README.md](README.md) を参照してください。

## 中身

```
fetch_danbooru_tags.py         Danbooru APIから作者/作品名/キャラクター/一般/メタの
                                タグ+エイリアスをカテゴリ別に取得し、日本語訳CSVを
                                マージしてCSV/JSON/ComfyUI用txtを書き出す
.github/workflows/update-tags.yml   週1回自動実行するGitHub Actions
dist/                           実行結果の出力先（下記）
```

`dist/` の出力ファイル：

| ファイル | 内容 |
|---|---|
| `danbooru.csv` / `tags.json` | 全カテゴリまとめ（a1111互換CSV／このツール用JSON） |
| `danbooru-general.csv` / `.json` | 一般タグ（category 0） |
| `danbooru-artists.csv` / `.json` | 作者タグ（category 1） |
| `danbooru-copyrights.csv` / `.json` | 作品名タグ（category 3） |
| `danbooru-characters.csv` / `.json` | キャラクタータグ（category 4） |
| `danbooru-meta.csv` / `.json` | メタタグ（category 5） |
| `danbooru-comfyui.txt` | ComfyUI-Custom-Scripts の `autocomplete.txt` 互換（`tag,count`・アンダースコア保持） |
| `meta.json` | 生成日時・カテゴリ別件数などの要約 |

作者・作品名・キャラクタータグは1タグあたりの投稿数が一般タグより少ない
傾向があるため、それぞれ個別のしきい値・取得ページ数上限を持っています
（既定値は `fetch_danbooru_tags.py --help` を参照。`--min-count-characters` の
ように上書き可能）。マイナーな版権・キャラも一般タグと同じ基準で切り捨てると
大量に漏れてしまうため、この分離が「作者・作品名・キャラクター・その他への
分類取得」の主眼です。

依存ライブラリなし（標準ライブラリのみ）で動きますが、`pip install certifi`
しておくと、OS側の証明書ストアの状態に依存せず安定します（後述）。
Python 3.9+ で動作します。

## 「certificate has expired」エラーが出たら

Danbooru自体の証明書が期限切れということはまずありません（Let's Encryptで
自動更新されています）。ほぼ確実にローカル環境側の問題です。

1. PCの時計・日付が正しいか確認する（一番多い原因）。
2. `pip install certifi` してから再実行する。このスクリプトはcertifiが
   入っていれば自動的にそれを使う（Windowsのローカル証明書ストアが古い/
   壊れているケースを回避できる）。
3. それでも直らない場合、常駐のウイルス対策ソフトや社内・VPNのプロキシが
   HTTPS通信を横取りしていないか確認する。

## 手元で試す

```bash
python3 fetch_danbooru_tags.py --out-dir dist
```

これだけで作者・作品名・キャラクター・一般・メタの5カテゴリを既定のしきい値で
まとめて取得します。一部だけで良い場合は絞り込めます：

```bash
# キャラクターと作品名だけ、キャラは投稿数5以上まで拾う
python3 fetch_danbooru_tags.py --out-dir dist \
  --categories characters,copyrights --min-count-characters 5
```

- `--max-pages-<category>`（例：`--max-pages-characters`）× `limit=1000` が
  そのカテゴリの取得件数上限です。Danbooruのタグ一覧APIはoffsetがある程度
  深くなるとエラーを返すため、無理にページを増やしすぎないようにしています。
- `--min-count-<category>` 未満の使用数タグは間引きます。
- 日本語訳を混ぜたい場合：

```bash
python3 fetch_danbooru_tags.py --out-dir dist \
  --translation-csv https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-jp.csv
```

  `<英語タグ/エイリアス>,<日本語>` の2列CSVならどれでも読めます
  （boorutan/booru-japanese-tag の danbooru-jp.csv、himamon/ComfyUIJapaneseTagAutoCompleteCSV
  の統合版などが実例としてGitHub上にあります）。ローカルファイルのパスでも可。

出力される `dist/tags.json`（または `dist/danbooru-characters.json` などカテゴリ別ファイル）は
「タグ台帳」の設定モーダル→②タグ自動補完の辞書→「候補リストをJSONから追加」で
そのまま読み込めます。カテゴリ別ファイルを1つずつ順番に読み込ませても、
最終的に同じ辞書にマージされます。`dist/danbooru.csv` は
a1111-sd-webui-tagcomplete 等のbooruタグ補完拡張とも互換の4列フォーマット、
`dist/danbooru-comfyui.txt` は ComfyUI-Custom-Scripts の `autocomplete.txt` に
そのまま差し替えて使えます（「タグ台帳」側でも `tag,count` 形式として
自動判別して読み込めます）。

## 自動更新にする

1. このフォルダをGitHubリポジトリにpush。
2. （任意）Settings → Secrets and variables → Actions → **Variables**タブ（Secretsではない）→
   New repository variable で `TRANSLATION_CSV_URL` を追加し、使いたい翻訳CSVのraw URLを
   値として入れる（例：`https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-jp.csv`）。
   ワークフローがこの値をそのまま `--translation-csv` に渡します。未設定でもエラーには
   ならず、単に日本語訳なしで出力されるだけです。
3. Settings → Actions → General → Workflow permissions を
   "Read and write permissions" にしておく（`dist/` への自動コミットに必要）。
4. あとは毎週月曜（cronは `.github/workflows/update-tags.yml` で調整可）に
   自動実行され、Danbooruから再取得 → `dist/`以下を再生成 → 差分があれば自動コミット・push、
   という流れが無人で回ります。Actionsタブの「Run workflow」ボタンから手動実行もできます。

## Hugging Face Datasetsへの配布（任意）

GitHubのdist/フォルダをそのまま参照してもらう形でも十分ですが、
「タグ辞書だけ」を独立した資産として配りたい場合はHF Datasetsも便利です。
ワークフローYAML内にコメントアウトで手順を書いてあります。事前に
HF上でdataset repoを作り、write権限のトークンを `HF_TOKEN` として
Secretsに登録すれば、`huggingface_hub` 経由で `dist/` の中身を
そのままpushできます。

## できないこと・注意点

- 私（Claude）自身がこのcronジョブを継続的に代行実行することはできません。
  実行主体は自分のGitHubリポジトリ（＝自分のGitHub Actions実行時間）です。
  他のプロジェクト同様、自分でホストする形になります。
- Danbooru APIには明確なレート制限値が公開されていないため、本スクリプトは
  リクエスト間に1秒スリープを入れる程度に留めています。極端に頻度を
  上げるcron設定（毎時など）は避けてください。週1回程度で十分タグ・
  カウントの変化は追従できます。
- 5カテゴリまとめて取得する分、以前より実行時間が伸びます（既定値のフル取得で
  数分〜十数分程度が目安）。GitHub Actions側は `timeout-minutes: 45` を設定
  済みですが、`--max-pages-*` を絞ればもっと短くできます。
- 日本語訳はDanbooru自体には存在しないため、コミュニティ製の翻訳CSVに
  依存します。訳が古い/一部機械翻訳である点は元データの性質上ご了承ください。

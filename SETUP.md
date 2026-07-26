# SETUP — 取得・生成スクリプトの動かし方

このリポジトリを自分でフォーク／セットアップして、Danbooruタグ一覧を
自前で取得・自動更新したい人向けのドキュメントです。生成されたファイルを
使うだけの方は [README.md](README.md) を参照してください。

## 中身

```
fetch_danbooru_tags.py              Danbooru APIからタグ+エイリアス+wikiの別名を取得し、
                                    日本語訳CSVをマージしてCSV/JSON/txtを書き出す
.github/workflows/update-tags.yml   週1回自動実行するGitHub Actions
dist/                               実行結果の出力先
```

`dist/` の出力ファイル：

| ファイル | 内容 |
|---|---|
| `danbooru.csv` | 全カテゴリ4列（a1111-sd-webui-tagcomplete 互換） |
| `danbooru-ja.csv` | 全カテゴリ5列（4列＋日本語）※ `--emit-merged-ja` 指定時のみ |
| `danbooru-jp.csv` | 全カテゴリ2列（タグ,日本語／訳のあるものだけ） |
| `tags.json` | 全カテゴリJSON（`ja` フィールドあり） |
| `danbooru-<category>.csv` / `.json` / `-ja.csv` / `-jp.csv` | カテゴリ別 |
| `danbooru-comfyui.txt` | ComfyUI-Custom-Scripts の `autocomplete.txt` 互換 |
| `meta.json` | 生成日時・件数・日本語の取得元内訳 |

カテゴリは general(0) / artists(1) / copyrights(3) / characters(4) / meta(5) です。
作者・作品名・キャラクタータグは1タグあたりの投稿数が一般タグより少ない傾向が
あるため、それぞれ個別のしきい値・取得ページ数上限を持っています。マイナーな
版権・キャラを一般タグと同じ基準で切り捨てると大量に漏れるためです。

依存ライブラリなし（標準ライブラリのみ）で動きますが、`pip install certifi`
しておくと、OS側の証明書ストアの状態に依存せず安定します。Python 3.9+ で動作します。

## 日本語訳の2つの供給源

Danbooruに翻訳APIはありません。代わりに次の2つを使います。

**1. Danbooru wikiの `other_names`（`--wiki-names`）**

各タグのwikiページには、タイトル下にバブルで並ぶ別名リストがあります。実質的に
pixivのタグで、キャラ・作品・絵師については人手で入力された日本語名が入っています。
これが最も質の高い供給源です。wikiページを全件walkするので数分かかります。

`other_names` には中国語・韓国語・ローマ字の別名も同居しています
（例：`uchi_no_hime-sama_ga_ichiban_kawaii` は `ウチの姫さまがいちばんカワイイ`
と `我家公主最可爱` の両方を持つ）。中国語も同じ漢字を使うため、
**かな（ひらがな・カタカナ）を含む候補を優先**し、かなが1つも無い場合だけ
漢字のみの候補にフォールバックしています。

**2. コミュニティ製の翻訳CSV（`--translation-csv`）**

`<英語タグ/エイリアス>,<日本語>` の2列CSVを読みます。wikiに載っていない
一般タグを埋める用途です。カンマ区切りで複数指定でき、**先に書いたものが優先**
されるので、手動整備の小さいファイルを機械翻訳の大きいファイルより前に置きます。

```
--translation-csv "curated-jp.csv,https://.../danbooru-machine-jp.csv"
```

既定の優先順位は **wiki > CSV** です。`--prefer-csv-names` で反転できます。

> boorutan/booru-japanese-tag の `danbooru-jp.csv` は手動訳のみで**427件**しか
> ありません。全体を埋めたい場合は同リポジトリの `danbooru-machine-jp.csv`
> （約10万件・Google翻訳ベース）を併用してください。

## 手元で試す

```bash
python3 fetch_danbooru_tags.py --out-dir dist --wiki-names --emit-merged-ja \
  --translation-csv "https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-jp.csv,https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-machine-jp.csv"
```

処理は次の順に進みます。リクエスト間に1秒スリープするため、合計15〜25分程度です。

| 段階 | ログ | 目安 |
|---|---|---|
| エイリアス取得 | `fetching aliases page N...` | 約30秒 |
| wiki別名取得 | `wiki query OK:` → `fetching wiki other_names page N...` | 数分 |
| 翻訳CSV読込 | `loaded N translations in total` | 数秒 |
| タグ本体取得 | `fetching <category> tags page N...` | 5〜10分 |

主なオプション：

```
--wiki-names              wikiのother_namesを取得して日本語欄に使う
--emit-merged-ja          danbooru-ja.csv（5列）を追加出力する
--prefer-csv-names        翻訳CSVをwikiより優先する
--skip-aliases            エイリアス取得を省略（動作確認を急ぐとき）
--categories characters,copyrights     取得するカテゴリを絞る
--min-count-<category>    その投稿数未満のタグを間引く
--max-pages-<category>    取得ページ数の上限（×1000件）
--max-pages-wiki          wikiページの walk 上限（既定400＝40万件）
--retries                 HTTPリトライ回数（既定7）
--request-interval        リクエスト間隔の秒数（既定1.0）
--debug-wiki <タグ名>      1タグ分のwiki応答を表示して終了
```

## うまくいかないときの切り分け

**日本語がほとんど入らない**

`dist/meta.json` の `ja_source_counts` を見てください。

- `wiki` が0に近い → wiki取得が空振りしています。`--debug-wiki hatsune_miku`
  で単体の応答を確認してください。APIの応答形式が変わっている可能性があります。
- `csv` が0に近い → `--translation-csv` のURLかパスが間違っています。
  ログの `loaded N translations in total` が0になっていないか確認してください。

**途中で止まる／件数が想定より少ない**

ログのページ番号を確認してください。`fetched other_names for 1,145 wiki pages`
のように極端に少ない場合は、ページングが早期に打ち切られています
（20万件前後が正常）。5,000件を下回ると警告が出ます。

**「certificate has expired」**

Danbooru側の証明書ではなく、ほぼローカル環境の問題です。
(1) PCの時計・日付を確認、(2) `pip install certifi` して再実行、
(3) ウイルス対策ソフトや社内プロキシのHTTPS横取りを確認、の順に試してください。

**HTTP 520 / IncompleteRead などで落ちる**

Danbooru前段のCloudflareの一時的な不調です。指数バックオフで自動リトライ
しますが、頻発する場合は `--retries 12 --request-interval 2.0` を試してください。

## 自動更新にする

1. このフォルダをGitHubリポジトリにpush。
2. Settings → Secrets and variables → Actions → **Variables**タブ（Secretsではない）→
   New repository variable で `TRANSLATION_CSV_URL` を追加。推奨値：

   ```
   https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-jp.csv,https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-machine-jp.csv
   ```

   未設定でもエラーにはならず、wiki由来の日本語だけが入ります。
3. Settings → Actions → General → Workflow permissions を
   "Read and write permissions" にする（`dist/` への自動コミットに必要）。
4. 毎週月曜に自動実行され、再取得 → `dist/` 再生成 → 差分があれば自動コミット・push
   という流れが無人で回ります。Actionsタブの「Run workflow」から手動実行もできます。

ワークフローには **Sanity check** ステップが入っています。タグ件数が10万件を
下回る、日本語の割合が40%を下回る、`--wiki-names` を付けたのにwiki由来が1万件
未満、のいずれかに該当するとコミット前に失敗させます。過去に、翻訳ソースの
取り違えやページングの不具合で日本語がほぼ空のまま「正常終了」したことがあり、
壊れたデータが公開されるのを防ぐためのものです。

## リポジトリサイズについて

`--emit-merged-ja` を付けると `-ja.csv` 系が増え、`dist/` は合計30MB前後に
なります（`danbooru-ja.csv` 単体で約7MB）。毎週コミットされるので、
gitの差分圧縮が効くとはいえ履歴は着実に増えます。気になる場合は
`--categories` で対象を絞るか、`--emit-merged-ja` を外して
`danbooru.csv` + `danbooru-jp.csv` の2本立てで運用してください。

## Hugging Face Datasetsへの配布（任意）

GitHubのdist/フォルダをそのまま参照してもらう形でも十分ですが、
「タグ辞書だけ」を独立した資産として配りたい場合はHF Datasetsも便利です。
ワークフローYAML内にコメントアウトで手順を書いてあります。事前に
HF上でdataset repoを作り、write権限のトークンを `HF_TOKEN` として
Secretsに登録すれば、`huggingface_hub` 経由で `dist/` の中身をpushできます。

## できないこと・注意点

- Danbooru APIには明確なレート制限値が公開されていないため、本スクリプトは
  リクエスト間に1秒スリープを入れる程度に留めています。極端に頻度を上げる
  cron設定（毎時など）は避けてください。週1回で十分追従できます。
- 日本語訳のうち翻訳CSV由来の分は機械翻訳を含みます。元データの性質上、
  不自然な訳や誤訳が残る点はご了承ください。

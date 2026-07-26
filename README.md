# danbooru-tags-ja（仮）

Danbooruのタグ一覧を**作者／作品名／キャラクター／一般／メタ**のカテゴリ別に、
日本語訳付きで、毎週自動更新して置いておくリポジトリです。

AIイラスト生成のプロンプトを書くときのタグ補完・タグ辞書として、
NovelAI用のタグ管理ツールや、Stable Diffusion系のWebUI拡張、ComfyUIなど、
お好きなツールにそのまま読み込ませて使ってください。

## まずはこれだけ

`dist/` フォルダの中身を必要な分だけダウンロードすれば使えます。自分でPythonを
動かす必要はありません。**まず1つだけ選ぶなら `dist/danbooru-ja.csv` です。**
タグ・カテゴリ・投稿数・エイリアス・日本語訳が1ファイルにまとまっています。

| ファイル | 内容 |
|---|---|
| `dist/danbooru-ja.csv` | **全部入り5列CSV**（タグ／カテゴリ／投稿数／エイリアス／日本語） |
| `dist/danbooru.csv` | 全カテゴリまとめ（a1111-sd-webui-tagcomplete 等と互換の4列CSV） |
| `dist/danbooru-jp.csv` | 日本語訳だけの2列CSV（tagcompleteの翻訳スロット用） |
| `dist/tags.json` | 全カテゴリまとめ（JSON） |
| `dist/danbooru-general.*` | 一般タグのみ（髪型・表情・構図など） |
| `dist/danbooru-artists.*` | 作者タグのみ |
| `dist/danbooru-copyrights.*` | 作品名タグのみ |
| `dist/danbooru-characters.*` | キャラクタータグのみ |
| `dist/danbooru-meta.*` | メタタグのみ（`commentary_request` など） |
| `dist/danbooru-comfyui.txt` | ComfyUI-Custom-Scripts の `autocomplete.txt` にそのまま差し替え可能 |
| `dist/meta.json` | 最終更新日時・カテゴリ別件数（データの鮮度確認用） |

カテゴリ別ファイルは `.csv`（4列）／`.json`／`-ja.csv`（5列）／`-jp.csv`（2列）の
4種類が出ています。カテゴリ番号はDanbooru本家と同じで、
0=一般／1=作者／3=作品名／4=キャラクター／5=メタです。

各フォーマットの列は次のとおりです。

```
danbooru.csv       タグ,カテゴリ番号,投稿数,"エイリアス"
danbooru-ja.csv    タグ,カテゴリ番号,投稿数,"エイリアス",日本語
danbooru-jp.csv    タグ,日本語                       ← 訳のあるタグのみ
tags.json          [{"t":"タグ","ja":"日本語","c":番号,"cnt":投稿数,"a":["エイリアス"]}, ...]
```

4列を期待するツールに5列CSVを渡しても、余分な列は読み飛ばされるだけで壊れません。

## 日本語訳について

Danbooruに翻訳APIはありませんが、**各タグのwikiページの `other_names`**
（wikiタイトル下に並ぶ別名。実質pixivタグ）に、Danbooru編集者が手で入力した
日本語名が入っています。キャラ・作品・絵師はこれを第一候補として使い、
足りない分をコミュニティ製の翻訳CSVで補っています。

直近の生成での網羅率：

| カテゴリ | 日本語つき | 割合 |
|---|---|---|
| 一般 | 24,873 / 36,107 | 68.9% |
| 作者 | 28,804 / 50,000 | 57.6% |
| 作品名 | 14,809 / 19,348 | 76.5% |
| キャラクター | 57,212 / 80,000 | 71.5% |
| メタ | 339 / 584 | 58.0% |
| **合計** | **126,037 / 186,039** | **67.7%** |

wiki由来の訳は人手なので信頼できます（`vivienne (uchihime)` → `ヴィヴィアンヌ`）。
一方、wikiに載っていないタグを埋めている翻訳CSVは機械翻訳を含むため、
不自然な訳や誤訳が混じります。最新の内訳は `dist/meta.json` の
`ja_source_counts`（`wiki` / `csv` / `none`）で確認できます。

## ツール別の使い方

- **NovelAI用のタグ管理ツール（「タグ台帳」など）**：`dist/danbooru-ja.csv` を
  1つ読み込むだけで、候補・投稿数・日本語訳がすべてそろいます。
- **a1111-sd-webui-tagcomplete（Stable Diffusion WebUI拡張）**：`dist/danbooru.csv` を
  拡張の `tags/` フォルダに置いて Tag Source に指定。日本語表示も使うなら
  `dist/danbooru-jp.csv` を翻訳ファイルとして併せて指定します。
- **ComfyUI-Custom-Scripts**：`dist/danbooru-comfyui.txt` を
  `ComfyUI/custom_nodes/ComfyUI-Custom-Scripts/user/autocomplete.txt` として置き換える。
- **自作ツール・その他**：`dist/tags.json` か `dist/danbooru-ja.csv` を読めばOK。

## 更新頻度

GitHub Actionsで毎週自動的に再取得・再生成しています（頻度はリポジトリの
`.github/workflows/update-tags.yml` 参照）。最新の更新日時とカテゴリ別件数は
`dist/meta.json` で確認できます。手動更新のタイミングによってはズレることもあるので、
厳密な鮮度が必要な場合はそちらを見てください。

## データの出どころ・注意点

- タグ本体とwikiの別名は [Danbooru](https://danbooru.donmai.us) の公開APIから
  取得しています。このリポジトリはDanbooru本家とは無関係の非公式プロジェクトで、
  内容の正確さや完全性は保証しません。
- Danbooruは成人向け作品も扱う画像掲示板のため、収録されるタグにも
  R-18表現に関連するものが含まれます。用途に応じてフィルタリングしてください。
- 翻訳CSV由来の訳には機械翻訳が含まれます。`other_names` には中国語・韓国語の
  別名も混在するため、かな文字を含む候補を優先して日本語を選び分けていますが、
  漢字だけの名前では取り違えが起きる可能性が残ります。
- タグ件数・カテゴリ分けはあくまで生成時点のDanbooruの状態のスナップショットです。

## 自分でも動かしたい／改造したい場合

取得・生成スクリプトの使い方、GitHub Actionsの設定、証明書エラーの対処法などは
[SETUP.md](SETUP.md) にまとめています。

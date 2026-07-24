# danbooru-tags-ja（仮）

Danbooruのタグ一覧を**作者／作品名／キャラクター／一般／メタ**のカテゴリ別に、
日本語訳付きで、毎週自動更新して置いておくリポジトリです。

AIイラスト生成のプロンプトを書くときのタグ補完・タグ辞書として、
NovelAI用のタグ管理ツールや、Stable Diffusion系のWebUI拡張、ComfyUIなど、
お好きなツールにそのまま読み込ませて使ってください。

## まずはこれだけ

`dist/` フォルダの中身を必要な分だけダウンロードすれば使えます。自分でPythonを
動かす必要はありません。

| ファイル | 内容 |
|---|---|
| `dist/danbooru.csv` | 全カテゴリまとめ（a1111-sd-webui-tagcomplete 等と互換の4列CSV） |
| `dist/tags.json` | 全カテゴリまとめ（JSON） |
| `dist/danbooru-general.csv` / `.json` | 一般タグのみ（髪型・表情・構図など） |
| `dist/danbooru-artists.csv` / `.json` | 作者タグのみ |
| `dist/danbooru-copyrights.csv` / `.json` | 作品名タグのみ |
| `dist/danbooru-characters.csv` / `.json` | キャラクタータグのみ |
| `dist/danbooru-meta.csv` / `.json` | メタタグのみ（`commentary_request` など） |
| `dist/danbooru-comfyui.txt` | ComfyUI-Custom-Scripts の `autocomplete.txt` にそのまま差し替え可能 |
| `dist/meta.json` | 最終更新日時・カテゴリ別件数（データの鮮度確認用） |

CSVの列は `タグ,カテゴリ番号,投稿数,"エイリアス"`、JSONは
`[{"t":"タグ","ja":"日本語訳","c":カテゴリ番号,"cnt":投稿数,"a":["エイリアス"]}, ...]`
という形式です（`ja`・`a` は無い場合は省略されます）。カテゴリ番号は
Danbooru本家と同じで、0=一般／1=作者／3=作品名／4=キャラクター／5=メタです。

## ツール別の使い方

- **NovelAI用のタグ管理ツール（「タグ台帳」など）**：設定画面の「タグ自動補完の辞書」から
  `tags.json`（または欲しいカテゴリの `.json` だけ）を読み込む。対応しているツールなら
  `danbooru.csv` でも可。
- **a1111-sd-webui-tagcomplete（Stable Diffusion WebUI拡張）**：`dist/danbooru.csv` を
  拡張の `tags/` フォルダに好きな名前で置いて、設定の Tag Source に指定する。
- **ComfyUI-Custom-Scripts**：`dist/danbooru-comfyui.txt` を
  `ComfyUI/custom_nodes/ComfyUI-Custom-Scripts/user/autocomplete.txt` として置き換える。
- **自作ツール・その他**：`dist/tags.json` を読めばOK。カテゴリ別ファイルだけ使うことも、
  全部まとめて使うことも可能です。

## 更新頻度

GitHub Actionsで毎週自動的に再取得・再生成しています（頻度はリポジトリの
`.github/workflows/update-tags.yml` 参照）。最新の更新日時とカテゴリ別件数は
`dist/meta.json` で確認できます。手動更新のタイミングによってはズレることもあるので、
厳密な鮮度が必要な場合はそちらを見てください。

## データの出どころ・注意点

- タグ本体は [Danbooru](https://danbooru.donmai.us) の公開APIから取得しています。
  このリポジトリはDanbooru本家とは無関係の非公式プロジェクトで、内容の正確さや
  完全性は保証しません。
- Danbooruは成人向け作品も扱う画像掲示板のため、収録されるタグにも
  R-18表現に関連するものが含まれます。用途に応じてフィルタリングしてください。
- 日本語訳は、翻訳CSVを設定している場合のみコミュニティ製の翻訳データを
  マージしています。訳が古い・一部機械翻訳である可能性がある点はご了承ください
  （どの翻訳ソースを使っているかはリポジトリの設定によります）。
- タグ件数・カテゴリ分けはあくまで生成時点のDanbooruの状態のスナップショットです。

## 自分でも動かしたい／改造したい場合

取得・生成スクリプトの使い方、GitHub Actionsの設定、証明書エラーの対処法などは
[SETUP.md](SETUP.md) にまとめています。

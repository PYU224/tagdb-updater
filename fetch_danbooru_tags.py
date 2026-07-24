#!/usr/bin/env python3
"""
fetch_danbooru_tags.py

Danbooruのタグ一覧（+エイリアス）を「作者／作品名／キャラクター／一般／メタ」の
カテゴリ別に取得し、それぞれ・および全部まとめた形で書き出すスクリプト。

出力（--out-dir 配下）：
  danbooru.csv / tags.json              全カテゴリまとめ（a1111互換CSV / このツール用JSON）
  danbooru-general.csv / .json          一般タグ（category 0）
  danbooru-artists.csv / .json          作者タグ（category 1）
  danbooru-copyrights.csv / .json       作品名タグ（category 3）
  danbooru-characters.csv / .json       キャラクタータグ（category 4）
  danbooru-meta.csv / .json             メタタグ（category 5）
  danbooru-comfyui.txt                  ComfyUI-Custom-Scripts の autocomplete.txt 互換（tag,count・アンダースコア保持）
  meta.json                             生成日時・件数などの要約

想定運用：GitHub Actions で週1回ぐらい実行し、差分があれば自動コミット
（.github/workflows/update-tags.yml を参照）。HuggingFace Datasetsに
そのままpushしても良い（README参照）。

日本語訳は Danbooru API には無いので、別途 boorutan/booru-japanese-tag の
danbooru-jp.csv 等（<English tag/alias>,<Japanese> の2列CSV）をローカルに
置くか --translation-csv でURL指定してマージする。

カテゴリ別のしきい値について：
作者・作品名・キャラクタータグは一般タグに比べて1タグあたりの投稿数が
少ない傾向があるため、一般タグと同じ足切りライン(post_count>=30)を使うと
マイナーな版権・キャラが大量に漏れてしまう。そのためカテゴリごとに
デフォルトのしきい値・取得ページ数上限を分けている（--min-count-* で調整可）。

注意：
- Danbooru APIには明確なレート制限の公式値はないが、コミュニティの
  慣習として "数req/秒" 程度に抑えるのがマナーとされる。このスクリプトは
  リクエスト間に REQUEST_INTERVAL 秒のスリープを入れている。
- タグ一覧の取得は offset(page番号)ベースのページネーションだが、
  Danbooruはoffsetがある程度大きくなると "You cannot go beyond page 1000"
  的なエラーを返す実装になっている。そのため各カテゴリごとに MAX_PAGES を
  超えないようにしている。
"""

import argparse
import csv
import io
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    # certifi not installed: fall back to whatever the platform provides.
    # On some Windows setups the local/system certificate store can be stale
    # (or a clock/proxy/antivirus issue causes "certificate has expired"
    # errors even though the server's cert is fine). If you hit that,
    # `pip install certifi` and re-run — this script will then use it
    # automatically.
    SSL_CONTEXT = ssl.create_default_context()

DANBOORU_BASE = "https://danbooru.donmai.us"
USER_AGENT = "tagdb-updater/1.0 (personal tag-list fetch script; contact via GitHub repo issues)"
REQUEST_INTERVAL = 1.0  # seconds between requests, be polite
PAGE_LIMIT = 1000       # Danbooru's practical max "limit" per page

# Danbooru tag category numbers (used by Danbooru itself and by
# a1111-sd-webui-tagcomplete's danbooru.csv): 0=general, 1=artist, 3=copyright, 4=character, 5=meta
CATEGORY_NAMES = {0: "general", 1: "artists", 3: "copyrights", 4: "characters", 5: "meta"}

# Per-category defaults. Artist/copyright/character tags individually have far fewer posts
# than general tags, so a uniform threshold would silently drop most minor series/characters.
DEFAULT_MIN_COUNT = {0: 30, 1: 20, 3: 10, 4: 10, 5: 30}
DEFAULT_MAX_PAGES = {0: 60, 1: 40, 3: 30, 4: 50, 5: 20}


def http_get_json(url, retries=5):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"  429 rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e) and attempt == 0:
                print(
                    "  SSL certificate verification failed. Danbooru's own certificate is "
                    "valid, so this is almost always local: (1) check your PC's clock/date "
                    "is correct, (2) `pip install certifi` and re-run so this script uses "
                    "an up-to-date CA bundle instead of the OS store, (3) check for "
                    "antivirus/corporate-proxy TLS inspection.",
                    file=sys.stderr,
                )
            print(f"  network error ({e}), retrying...", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"failed to fetch after {retries} retries: {url}")


def fetch_tags(category=None, max_pages=60, min_count=30):
    """Fetch tags ordered by post count, descending, paginated. If category is given
    (0/1/3/4/5), restricts to that Danbooru tag category."""
    tags = []
    for page in range(1, max_pages + 1):
        url = (
            f"{DANBOORU_BASE}/tags.json"
            f"?search[order]=count&search[post_count_gteq]={min_count}"
            f"&limit={PAGE_LIMIT}&page={page}"
        )
        if category is not None:
            url += f"&search[category]={category}"
        label = CATEGORY_NAMES.get(category, "all") if category is not None else "all"
        print(f"fetching {label} tags page {page}...", file=sys.stderr)
        try:
            batch = http_get_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 410 or e.code == 422:
                # Danbooru refuses pages beyond its offset window; stop here.
                print(f"  stopping pagination at page {page} ({e})", file=sys.stderr)
                break
            raise
        if not batch:
            break
        tags.extend(batch)
        time.sleep(REQUEST_INTERVAL)
        if len(batch) < PAGE_LIMIT:
            break  # last page
    return tags


def fetch_aliases(max_pages=30):
    """Fetch active tag aliases: antecedent_name -> consequent_name (alias -> canonical tag)."""
    aliases = {}  # canonical tag name -> set of alias names
    for page in range(1, max_pages + 1):
        url = (
            f"{DANBOORU_BASE}/tag_aliases.json"
            f"?search[status]=active&limit={PAGE_LIMIT}&page={page}"
        )
        print(f"fetching aliases page {page}...", file=sys.stderr)
        try:
            batch = http_get_json(url)
        except urllib.error.HTTPError as e:
            if e.code in (410, 422):
                break
            raise
        if not batch:
            break
        for row in batch:
            canonical = row.get("consequent_name")
            alias = row.get("antecedent_name")
            if not canonical or not alias:
                continue
            aliases.setdefault(canonical, set()).add(alias)
        time.sleep(REQUEST_INTERVAL)
        if len(batch) < PAGE_LIMIT:
            break
    return aliases


def load_translation_csv(path_or_url):
    """
    2-column translation CSV: <English tag/alias>,<Japanese>
    (format used by boorutan/booru-japanese-tag's danbooru-jp.csv and similar files
    for the DominikDoom/a1111-sd-webui-tagcomplete extension's translation slot).
    Returns dict: lowercased english tag/alias -> japanese text.
    """
    if not path_or_url:
        return {}
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        req = urllib.request.Request(path_or_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
            text = resp.read().decode("utf-8")
    else:
        text = Path(path_or_url).read_text(encoding="utf-8")
    out = {}
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 2:
            continue
        eng, ja = row[0].strip(), row[1].strip()
        if eng and ja:
            out[eng.lower().replace("_", " ")] = ja
    return out


def build_dataset(tags, alias_map, translations):
    dataset = []
    for t in tags:
        name = (t.get("name") or "").replace("_", " ")
        if not name:
            continue
        category = t.get("category", 0)
        count = t.get("post_count", 0)
        aliases = sorted(a.replace("_", " ") for a in alias_map.get(t.get("name"), []))
        ja = translations.get(name.lower(), "")
        if not ja:
            for a in aliases:
                if a.lower() in translations:
                    ja = translations[a.lower()]
                    break
        dataset.append({"t": name, "ja": ja, "c": category, "cnt": count, "a": aliases})
    return dataset


def write_csv(dataset, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in dataset:
            w.writerow([row["t"], row["c"], row["cnt"], ",".join(row["a"])])


def write_json(dataset, path):
    slim = [
        {k: v for k, v in row.items() if not (k == "ja" and not v) and not (k == "a" and not v)}
        for row in dataset
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, separators=(",", ":"))


def write_comfyui_txt(dataset, path):
    """ComfyUI-Custom-Scripts (pythongosssss) autocomplete.txt format: `tag,count` per line.
    Unlike the other outputs here, underscores are kept as-is — ComfyUI's autocomplete does not
    convert them to spaces the way NovelAI-style tools do."""
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        for row in dataset:
            f.write(f"{row['t'].replace(' ', '_')},{row['cnt']}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="dist", help="output directory")
    ap.add_argument(
        "--categories",
        default="general,artists,copyrights,characters,meta",
        help="comma-separated subset of categories to fetch (default: all 5)",
    )
    for cat_id, name in CATEGORY_NAMES.items():
        ap.add_argument(
            f"--min-count-{name}", type=int, default=DEFAULT_MIN_COUNT[cat_id],
            help=f"minimum post_count for {name} tags (default: {DEFAULT_MIN_COUNT[cat_id]})",
        )
        ap.add_argument(
            f"--max-pages-{name}", type=int, default=DEFAULT_MAX_PAGES[cat_id],
            help=f"max pages (x{PAGE_LIMIT}) to fetch for {name} (default: {DEFAULT_MAX_PAGES[cat_id]})",
        )
    ap.add_argument(
        "--translation-csv",
        default="",
        help="path or URL to a 2-column <tag>,<japanese> translation CSV to merge in",
    )
    ap.add_argument(
        "--skip-aliases", action="store_true", help="skip fetching tag_aliases.json (faster)"
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    name_to_id = {v: k for k, v in CATEGORY_NAMES.items()}
    wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in name_to_id]
    if unknown:
        raise SystemExit(f"unknown category name(s): {unknown}; choose from {sorted(name_to_id)}")

    alias_map = {} if args.skip_aliases else fetch_aliases()
    print(f"fetched aliases for {len(alias_map)} tags", file=sys.stderr)

    translations = load_translation_csv(args.translation_csv)
    print(f"loaded {len(translations)} translations", file=sys.stderr)

    all_dataset = []
    counts_by_category = {}
    for name in wanted:
        cat_id = name_to_id[name]
        min_count = getattr(args, f"min_count_{name}")
        max_pages = getattr(args, f"max_pages_{name}")
        tags = fetch_tags(category=cat_id, max_pages=max_pages, min_count=min_count)
        print(f"fetched {len(tags)} {name} tags", file=sys.stderr)
        dataset = build_dataset(tags, alias_map, translations)
        dataset.sort(key=lambda r: r["cnt"], reverse=True)
        counts_by_category[name] = len(dataset)
        all_dataset.extend(dataset)
        write_csv(dataset, out_dir / f"danbooru-{name}.csv")
        write_json(dataset, out_dir / f"danbooru-{name}.json")

    all_dataset.sort(key=lambda r: r["cnt"], reverse=True)
    write_csv(all_dataset, out_dir / "danbooru.csv")
    write_json(all_dataset, out_dir / "tags.json")
    write_comfyui_txt(all_dataset, out_dir / "danbooru-comfyui.txt")

    meta = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tag_count_total": len(all_dataset),
        "translated_count_total": sum(1 for r in all_dataset if r["ja"]),
        "by_category": counts_by_category,
    }
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"done: {len(all_dataset)} tags written to {out_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()

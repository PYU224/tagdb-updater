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
  danbooru-jp.csv                       日本語訳のみの2列CSV（tag,日本語／訳のあるタグだけ）
  danbooru-<category>-jp.csv            上記のカテゴリ別版
  meta.json                             生成日時・件数などの要約

日本語訳付きの一覧が欲しい場合：
  - .json 系（tags.json / danbooru-*.json）には元々 "ja" フィールドが入っている。
  - .csv 系は a1111-sd-webui-tagcomplete の danbooru.csv 形式（4列）を崩さないため
    訳を含めない。代わりに tagcomplete の翻訳スロットと同じ2列形式の
    danbooru-jp.csv を別ファイルとして出力する（danbooru.csv と併せて読み込む想定）。
  - 1ファイルに全部入った5列CSV（tag,category,count,"aliases",日本語）が欲しい場合は
    --emit-merged-ja を付けると danbooru-ja.csv が追加で出力される。
    リポジトリサイズが毎週その分増えるため既定ではオフ。

想定運用：GitHub Actions で週1回ぐらい実行し、差分があれば自動コミット
（.github/workflows/update-tags.yml を参照）。HuggingFace Datasetsに
そのままpushしても良い（README参照）。

日本語について：
Danbooruに「翻訳API」は無いが、各タグのwikiページには other_names（wikiタイトル下に
小さなバブルで並ぶ別名。実質pixivタグ）があり、キャラ・作品・絵師タグについては
ここに人手で入力された日本語名が入っている。--wiki-names を付けるとこれを取得して
日本語欄に使う（/wiki_pages.json をid順カーソルで全走査、数分かかる）。
一般タグは other_names が無いことも多いので、--translation-csv で
boorutan/booru-japanese-tag の danbooru-machine-jp.csv 等（<English>,<Japanese> の
2列CSV）を併用して埋める。既定では wiki > CSV の優先順位（--prefer-csv-names で反転）。

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
import http.client
import re
import io
import json
import random
import ssl
import sys
import time
import urllib.error
import urllib.parse
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
DEFAULT_MAX_PAGES = {0: 60, 1: 50, 3: 40, 4: 80, 5: 20}


# Retried, with exponential backoff. Danbooru sits behind Cloudflare, so besides the ordinary
# 5xx codes we also see the Cloudflare-specific 520-527 family ("unknown error", "connection
# timed out", "origin unreachable"). Those fire intermittently on long paginated runs and mean
# "the edge could not reach the origin right now" — not "stop". Treating any 5xx as retryable
# is what keeps a 40-minute crawl from dying an hour in on one bad response.
RETRYABLE_STATUS = {408, 425, 429}


DEFAULT_RETRIES = 7


def http_get_json(url, retries=None):
    retries = DEFAULT_RETRIES if retries is None else retries
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in RETRYABLE_STATUS and e.code < 500:
                raise  # 404/410/422 etc. are meaningful to the caller (end of pagination)
            if attempt == retries - 1:
                hint = ""
                if 520 <= e.code <= 527:
                    hint = (
                        " (a Cloudflare edge error in front of Danbooru — usually transient;"
                        " re-run, or raise --retries / --request-interval)"
                    )
                raise RuntimeError(f"giving up after {retries} attempts, HTTP {e.code}{hint}: {url}")
            wait = min(90.0, 3.0 * (2 ** attempt)) + random.uniform(0, 2)
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if retry_after:
                try:
                    wait = max(wait, float(retry_after))
                except (TypeError, ValueError):
                    pass
            print(
                f"  HTTP {e.code}, retry {attempt + 1}/{retries} in {wait:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
            # Deliberately broad. urllib leaks a surprising variety of transport failures on a
            # long crawl: http.client.IncompleteRead when Cloudflare truncates a response
            # mid-stream, ssl.SSLEOFError on a dropped TLS session, socket.gaierror on a DNS
            # blip. None of them are subclasses of URLError, so naming individual types meant a
            # 40-minute run could still die on one bad packet. OSError covers URLError,
            # ConnectionError, TimeoutError, ssl.SSLError and socket errors; HTTPException covers
            # the rest. HTTPError is handled above, and it is caught first because it is itself
            # an OSError subclass and carries a status code worth acting on.
            if "CERTIFICATE_VERIFY_FAILED" in str(e) and attempt == 0:
                print(
                    "  SSL certificate verification failed. Danbooru's own certificate is "
                    "valid, so this is almost always local: (1) check your PC's clock/date "
                    "is correct, (2) `pip install certifi` and re-run so this script uses "
                    "an up-to-date CA bundle instead of the OS store, (3) check for "
                    "antivirus/corporate-proxy TLS inspection.",
                    file=sys.stderr,
                )
            if attempt == retries - 1:
                raise RuntimeError(
                    f"giving up after {retries} attempts ({type(e).__name__}: {e}): {url}"
                )
            wait = min(90.0, 3.0 * (2 ** attempt)) + random.uniform(0, 2)
            print(
                f"  {type(e).__name__}: {e} — retry {attempt + 1}/{retries} in {wait:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
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


def read_text_source(path_or_url):
    """Read a local path or an http(s) URL as UTF-8 text (BOM stripped)."""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        req = urllib.request.Request(path_or_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
            text = resp.read().decode("utf-8-sig")
    else:
        text = Path(path_or_url).read_text(encoding="utf-8-sig")
    return text


# Kana / CJK ideographs / prolonged sound mark. Used to pick the Japanese entry out of a
# wiki page's other_names, which also contain romaji, Korean, Chinese and so on.
JA_CHARS = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\u3005\u30FC]")
# Hiragana + katakana only. Used to tell Japanese apart from Chinese, which shares the kanji.
KANA_CHARS = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")


# Tried in order. If the first page of a variant comes back empty or without any other_names,
# the next one is tried. Danbooru has changed search parameter names before, and a silently
# ignored or rejected parameter used to leave us with an empty dict and no explanation — the
# whole point of --wiki-names quietly doing nothing.
# Tried in order until one returns rows that actually carry other_names. Danbooru has changed
# search parameter names before, and a silently ignored or rejected parameter used to leave us
# with an empty dict and no explanation.
#
# The unfiltered form is deliberately first. search[other_names_present]=true looked like the
# obvious optimisation, but in practice it returned barely a thousand rows and then dried up,
# so we walk every wiki page and do the "has other_names" test here instead. Same request count
# either way, and no dependence on a parameter whose exact semantics we cannot verify.
WIKI_QUERY_VARIANTS = [
    "only=id,title,other_names",
    "search[other_names_present]=true&only=id,title,other_names",
    "",
]


def fetch_wiki_other_names(max_pages=400, verbose=True):
    """
    Danbooru has no translation API, but every tag can have a wiki page, and wiki pages carry an
    `other_names` list — the alternate names shown as bubbles under the wiki title. For Japanese
    works these are in practice the pixiv tags, i.e. the real Japanese name of the
    character/series/artist, entered by hand by Danbooru editors. Far better for character and
    copyright tags than any machine translation.

    Numbered pagination, matching fetch_tags/fetch_aliases. An earlier version used id cursors
    (page=b<id>), which quietly stopped after two pages and returned ~1k of the ~200k wiki pages —
    enough to look like it had worked.
    Returns dict: tag name (underscored, as Danbooru stores it) -> list of other names.
    """
    out = {}
    chosen = None
    scanned = 0
    for page in range(1, max_pages + 1):
        batch = None
        for variant in (WIKI_QUERY_VARIANTS if chosen is None else [chosen]):
            url = f"{DANBOORU_BASE}/wiki_pages.json?limit={PAGE_LIMIT}&page={page}"
            if variant:
                url += "&" + variant
            try:
                batch = http_get_json(url)
            except urllib.error.HTTPError as e:
                if e.code in (410, 422):
                    if chosen is not None:
                        batch = []          # genuine end of pagination
                        break
                    print(f"  wiki query rejected (HTTP {e.code}), trying another form...", file=sys.stderr)
                    batch = None
                    continue
                raise
            if chosen is None:
                usable = sum(1 for r in (batch or []) if r.get("other_names"))
                if not batch or not usable:
                    print(
                        f"  wiki query returned {len(batch or [])} rows / {usable} with"
                        f" other_names — trying another form...", file=sys.stderr,
                    )
                    batch = None
                    continue
                chosen = variant
                print(f"  wiki query OK: /wiki_pages.json?{variant or '(no filter)'}", file=sys.stderr)
            break

        if batch is None:
            print(
                "  ERROR: none of the wiki_pages.json query forms returned usable other_names.\n"
                "  Run with --debug-wiki <tag> to see the raw response for a single tag.",
                file=sys.stderr,
            )
            return out
        if not batch:
            break
        scanned += len(batch)
        for row in batch:
            title = row.get("title")
            names = row.get("other_names") or []
            if title and names:
                out[title] = names
        if verbose and (page <= 3 or page % 20 == 0):
            print(
                f"fetching wiki other_names page {page}... "
                f"({scanned:,} scanned, {len(out):,} with names)", file=sys.stderr,
            )
        time.sleep(REQUEST_INTERVAL)
        if len(batch) < PAGE_LIMIT:
            break
    else:
        print(
            f"  NOTE: stopped at the --max-pages-wiki limit ({max_pages}). Raise it if the count"
            f" below looks short.", file=sys.stderr,
        )
    # ~200k wiki pages exist and a large share carry other_names. Anything in the low thousands
    # means pagination died early rather than the data being small.
    if 0 < len(out) < 5000:
        print(
            f"  WARNING: only {len(out):,} wiki pages with other_names were collected, which is"
            f" far fewer than expected. Pagination probably stopped early — please report the"
            f" page numbers logged above.", file=sys.stderr,
        )
    return out


def debug_wiki(tag):
    """Print the raw wiki_pages.json response for one tag, plus what we would extract from it.
    A 30-second check instead of re-running the whole crawl."""
    name = tag.strip().replace(" ", "_")
    url = f"{DANBOORU_BASE}/wiki_pages.json?search[title]={urllib.parse.quote(name)}&limit=5"
    print(f"GET {url}\n", file=sys.stderr)
    rows = http_get_json(url)
    if not rows:
        print("no wiki page found for that tag.", file=sys.stderr)
        return
    for r in rows:
        print(json.dumps({k: r.get(k) for k in ("id", "title", "other_names")}, ensure_ascii=False, indent=2))
        print("  -> would use:", repr(pick_japanese_name(r.get("other_names"))), file=sys.stderr)


def pick_japanese_name(names):
    """
    Pick the Japanese entry from a wiki page's other_names.

    Prefer a candidate containing kana. other_names routinely also holds the Chinese and Korean
    names (uchi_no_hime-sama_ga_ichiban_kawaii carries 我家公主最可愛 alongside the Japanese
    titles), and Chinese is written in the same ideographs, so "contains CJK" alone picks the
    wrong language whenever the Chinese entry happens to come first. Kana is the one script only
    Japanese uses. Kanji-only candidates are kept as a fallback for names that genuinely have no
    kana, which is why we do two passes instead of just filtering.
    """
    ideograph_only = ""
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        if KANA_CHARS.search(n):
            return n
        if not ideograph_only and JA_CHARS.search(n):
            ideograph_only = n
    return ideograph_only


def load_translation_csv(path_or_url):
    """
    2-column translation CSV: <English tag/alias>,<Japanese>
    (format used by boorutan/booru-japanese-tag and by the translation slot of the
    DominikDoom/a1111-sd-webui-tagcomplete extension).
    Returns dict: lowercased english tag/alias (underscores -> spaces) -> japanese text.
    """
    if not path_or_url:
        return {}
    text = read_text_source(path_or_url)
    out = {}
    for row in csv.reader(io.StringIO(text)):
        # Some files carry extra columns (e.g. a "use as alias" flag). Only the first two matter.
        if len(row) < 2:
            continue
        eng, ja = row[0].strip(), row[1].strip()
        if not eng or not ja:
            continue
        # A header row like "tag,translation" would otherwise become a bogus entry.
        if eng.lower() in ("tag", "name", "english") and not any(ord(c) > 0x2E80 for c in ja):
            continue
        out[eng.lower().replace("_", " ")] = ja
    return out


def load_translations(sources):
    """
    Merge several translation CSVs. `sources` is a comma-separated string of paths/URLs.
    Earlier entries win, so a small hand-curated file can be layered over a large
    machine-translated one:
        --translation-csv "curated-jp.csv,danbooru-machine-jp.csv"
    Returns (merged dict, per-source stats list).
    """
    merged = {}
    stats = []
    for raw in (sources or "").split(","):
        src = raw.strip()
        if not src:
            continue
        try:
            one = load_translation_csv(src)
        except Exception as e:  # a bad URL should not kill an otherwise good run
            print(f"  WARNING: could not load translations from {src}: {e}", file=sys.stderr)
            stats.append({"source": src, "entries": 0, "error": str(e)})
            continue
        added = 0
        for k, v in one.items():
            if k not in merged:      # first source listed has priority
                merged[k] = v
                added += 1
        stats.append({"source": src, "entries": len(one), "newly_added": added})
        print(f"  translations: {len(one):,} from {src} ({added:,} new)", file=sys.stderr)
    return merged, stats


def build_dataset(tags, alias_map, translations, wiki_names=None, prefer_csv=False):
    """
    Resolve the Japanese text for each tag. Two independent sources:
      - wiki_names: Danbooru wiki `other_names` (human-entered, excellent for characters/series)
      - translations: the --translation-csv files (good for general/描写 tags)
    Wiki names win by default because a hand-entered pixiv name beats a machine translation;
    --prefer-csv-names flips that if you have a curated CSV you trust more.
    """
    wiki_names = wiki_names or {}
    dataset = []
    stats = {"wiki": 0, "csv": 0, "none": 0}

    def from_csv(name, aliases):
        ja = translations.get(name.lower(), "")
        if ja:
            return ja
        for a in aliases:
            if a.lower() in translations:
                return translations[a.lower()]
        return ""

    def from_wiki(raw_name, raw_aliases):
        ja = pick_japanese_name(wiki_names.get(raw_name))
        if ja:
            return ja
        for a in raw_aliases:
            ja = pick_japanese_name(wiki_names.get(a))
            if ja:
                return ja
        return ""

    for t in tags:
        raw_name = t.get("name") or ""
        name = raw_name.replace("_", " ")
        if not name:
            continue
        category = t.get("category", 0)
        count = t.get("post_count", 0)
        raw_aliases = sorted(alias_map.get(raw_name, []))
        aliases = [a.replace("_", " ") for a in raw_aliases]

        order = ("csv", "wiki") if prefer_csv else ("wiki", "csv")
        ja, src = "", "none"
        for which in order:
            ja = from_wiki(raw_name, raw_aliases) if which == "wiki" else from_csv(name, aliases)
            if ja:
                src = which
                break
        stats[src] += 1
        dataset.append({"t": name, "ja": ja, "c": category, "cnt": count, "a": aliases})
    return dataset, stats


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


def write_translation_csv(dataset, path):
    """
    2-column `tag,japanese` CSV containing only the tags that actually have a translation.
    This is the same shape as the translation files a1111-sd-webui-tagcomplete expects, so it can
    be dropped straight into its translation slot alongside danbooru.csv — and it is also one of
    the formats the タグ台帳 tool imports. Kept as a separate file rather than a 5th column on
    danbooru.csv so the existing 4-column tagcomplete format stays byte-compatible.
    Returns the number of rows written.
    """
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in dataset:
            if not row["ja"]:
                continue
            w.writerow([row["t"], row["ja"]])
            n += 1
    return n


def write_csv_with_ja(dataset, path):
    """
    5-column `tag,category,count,"aliases",japanese` — everything in one file, for when juggling
    two files is more annoying than the extra repo size. Off by default (--emit-merged-ja).
    Readers that only know the 4-column format ignore the trailing column.
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in dataset:
            w.writerow([row["t"], row["c"], row["cnt"], ",".join(row["a"]), row["ja"]])


def write_comfyui_txt(dataset, path):
    """ComfyUI-Custom-Scripts (pythongosssss) autocomplete.txt format: `tag,count` per line.
    Unlike the other outputs here, underscores are kept as-is — ComfyUI's autocomplete does not
    convert them to spaces the way NovelAI-style tools do."""
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        for row in dataset:
            f.write(f"{row['t'].replace(' ', '_')},{row['cnt']}\n")


def main():
    global REQUEST_INTERVAL, DEFAULT_RETRIES
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
        help=(
            "path(s) or URL(s) to 2-column <tag>,<japanese> translation CSVs to merge in. "
            "Comma-separate several; the first one listed wins on conflicts, so put a "
            "hand-curated file before a machine-translated one."
        ),
    )
    ap.add_argument(
        "--debug-wiki", metavar="TAG", default="",
        help="print the raw wiki_pages.json response for one tag and exit (no crawl)",
    )
    ap.add_argument(
        "--retries", type=int, default=7,
        help="HTTP retry attempts per request (default: 7). Raise if Danbooru/Cloudflare is flaky.",
    )
    ap.add_argument(
        "--request-interval", type=float, default=REQUEST_INTERVAL,
        help=f"seconds to sleep between requests (default: {REQUEST_INTERVAL}). Raise to be gentler.",
    )
    ap.add_argument(
        "--wiki-names",
        action="store_true",
        help=(
            "also fetch Danbooru wiki other_names and use them as the Japanese text. "
            "Adds a few minutes to the run but gives real Japanese names for characters, "
            "series and artists instead of machine translations."
        ),
    )
    ap.add_argument(
        "--max-pages-wiki", type=int, default=400,
        help=f"max wiki_pages pages (x{PAGE_LIMIT}) to walk when --wiki-names is set",
    )
    ap.add_argument(
        "--prefer-csv-names",
        action="store_true",
        help="let --translation-csv win over wiki other_names (default: wiki wins)",
    )
    ap.add_argument(
        "--emit-merged-ja",
        action="store_true",
        help="also write danbooru-ja.csv (tag,category,count,aliases,japanese in one file)",
    )
    ap.add_argument(
        "--skip-aliases", action="store_true", help="skip fetching tag_aliases.json (faster)"
    )
    args = ap.parse_args()

    REQUEST_INTERVAL = max(0.0, args.request_interval)
    DEFAULT_RETRIES = max(1, args.retries)

    if args.debug_wiki:
        debug_wiki(args.debug_wiki)
        return

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    name_to_id = {v: k for k, v in CATEGORY_NAMES.items()}
    wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in name_to_id]
    if unknown:
        raise SystemExit(f"unknown category name(s): {unknown}; choose from {sorted(name_to_id)}")

    alias_map = {} if args.skip_aliases else fetch_aliases()
    print(f"fetched aliases for {len(alias_map)} tags", file=sys.stderr)

    wiki_names = fetch_wiki_other_names(max_pages=args.max_pages_wiki) if args.wiki_names else {}
    if args.wiki_names:
        print(f"fetched other_names for {len(wiki_names):,} wiki pages", file=sys.stderr)
        if not wiki_names:
            print(
                "  WARNING: --wiki-names collected nothing, so every Japanese string will come\n"
                "  from --translation-csv. Check the messages above, or run:\n"
                "    python fetch_danbooru_tags.py --debug-wiki hatsune_miku",
                file=sys.stderr,
            )

    translations, translation_sources = load_translations(args.translation_csv)
    print(f"loaded {len(translations):,} translations in total", file=sys.stderr)
    if args.translation_csv and not translations:
        print(
            "  WARNING: a translation source was given but nothing was loaded. "
            "Check the URL/path and that the file really is a 2-column <tag>,<japanese> CSV.",
            file=sys.stderr,
        )

    all_dataset = []
    counts_by_category = {}
    translated_by_category = {}
    ja_source_stats = {}
    # Fetch everything first, write nothing until every category has succeeded. A crash partway
    # through (a Cloudflare blip, a network drop) used to leave dist/ holding some freshly
    # written categories next to stale ones from the previous run — an inconsistent set that
    # still looks valid.
    fetched = []
    for name in wanted:
        cat_id = name_to_id[name]
        min_count = getattr(args, f"min_count_{name}")
        max_pages = getattr(args, f"max_pages_{name}")
        tags = fetch_tags(category=cat_id, max_pages=max_pages, min_count=min_count)
        print(f"fetched {len(tags)} {name} tags", file=sys.stderr)
        dataset, src_stats = build_dataset(
            tags, alias_map, translations, wiki_names, prefer_csv=args.prefer_csv_names
        )
        for k, v in src_stats.items():
            ja_source_stats[k] = ja_source_stats.get(k, 0) + v
        dataset.sort(key=lambda r: r["cnt"], reverse=True)
        fetched.append((name, dataset))

    print("all categories fetched; writing files...", file=sys.stderr)
    for name, dataset in fetched:
        counts_by_category[name] = len(dataset)
        all_dataset.extend(dataset)
        write_csv(dataset, out_dir / f"danbooru-{name}.csv")
        write_json(dataset, out_dir / f"danbooru-{name}.json")
        translated_by_category[name] = write_translation_csv(
            dataset, out_dir / f"danbooru-{name}-jp.csv"
        )
        if args.emit_merged_ja:
            write_csv_with_ja(dataset, out_dir / f"danbooru-{name}-ja.csv")

    all_dataset.sort(key=lambda r: r["cnt"], reverse=True)
    write_csv(all_dataset, out_dir / "danbooru.csv")
    write_json(all_dataset, out_dir / "tags.json")
    write_comfyui_txt(all_dataset, out_dir / "danbooru-comfyui.txt")
    translated_total = write_translation_csv(all_dataset, out_dir / "danbooru-jp.csv")
    if args.emit_merged_ja:
        write_csv_with_ja(all_dataset, out_dir / "danbooru-ja.csv")

    meta = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tag_count_total": len(all_dataset),
        "translated_count_total": translated_total,
        "translated_ratio": round(translated_total / len(all_dataset), 4) if all_dataset else 0,
        "by_category": counts_by_category,
        # Per-category coverage makes a silently-wrong translation source obvious at a glance:
        # a near-zero number here means the source file didn't match the tag set.
        "translated_by_category": translated_by_category,
        "translation_sources": translation_sources,
        # Where each Japanese string came from: Danbooru wiki other_names vs the translation CSVs.
        "ja_source_counts": ja_source_stats,
        "wiki_other_names_used": bool(args.wiki_names),
    }
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    pct = (translated_total / len(all_dataset) * 100) if all_dataset else 0
    print(
        f"done: {len(all_dataset):,} tags written to {out_dir}/ "
        f"({translated_total:,} with a Japanese translation, {pct:.1f}%)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

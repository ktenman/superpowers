#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""AKIT lexicon: local mirror + terminology lookup.

AKIT = Andmekaitse ja infoturbe leksikon (https://akit.cyber.ee), Cybernetica's
EN<->ET information-security / data-protection lexicon.

Stdlib only, so `uv run akit.py ...` needs no install step. Four commands:

  update   crawl akit.cyber.ee -> local raw mirror -> rebuild lookup index
  build    re-derive the lookup index from the raw mirror (no network)
  lookup   search the local index for a term / definition
  similar  rank terms by how closely their meaning matches a description

Data files live next to this script:
  akit_raw.jsonl.gz   raw <main> HTML per term (the "full akit, downloaded")
  akit.jsonl          clean parsed records used by `lookup`
"""

import argparse
import gzip
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from html import unescape

BASE = "https://akit.cyber.ee"
SITEMAP_URL = BASE + "/sitemap.xml"
USER_AGENT = "VVKI-AKIT-mirror/1.0 (Cybernetica terminology tooling; +https://cyber.ee)"

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(HERE, "akit_raw.jsonl.gz")
DATA_PATH = os.path.join(HERE, "akit.jsonl")


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_get(url, retries=3, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        # URLError, TimeoutError and ConnectionError are all OSError, so OSError
        # alone covers them. HTTPException adds IncompleteRead — a truncated
        # response, which is transient and was the only failure a full 16,420-page
        # crawl actually hit (5 of them, all fine on the next run).
        except (OSError, http.client.HTTPException) as e:
            last = e
            # HTTPError subclasses URLError, so a 404 would otherwise cost three
            # attempts and two sleeps. 4xx is the server's final answer; 429 and
            # 5xx are the ones worth waiting out.
            code = getattr(e, "code", None)
            if code and 400 <= code < 500 and code != 429:
                raise
            if attempt < retries - 1:  # nothing to space out after the last try
                time.sleep(1.0 * (attempt + 1))
    raise last


def parse_sitemap(xml):
    """Return list of (id, url, lastmod) for every /term/<id> entry."""
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", block)
        if not loc:
            continue
        url = loc.group(1).strip()
        # urlopen honours file:// and ftp://, so a tampered sitemap could point
        # the crawler at the local disk. Only ever fetch akit term pages.
        if not url.startswith(BASE + "/term/"):
            continue
        tid = re.search(r"/term/(\d+)", url)
        if not tid:
            continue
        lm = re.search(r"<lastmod>([^<]*)</lastmod>", block)
        out.append((int(tid.group(1)), url, lm.group(1).strip() if lm else ""))
    return out


# --------------------------------------------------------------------------- #
# HTML parsing
# --------------------------------------------------------------------------- #
def extract_main(page_html):
    m = re.search(r"<main>(.*?)</main>", page_html, re.S)
    return m.group(1) if m else ""


def strip_tags(s):
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return unescape(s)


def clean_ws(s):
    return " ".join(s.split()).strip(" =-–—•")


def parse_title(main):
    et, en = [], []
    for lang, text in re.findall(
        r'<span[^>]*\blang="(en|et)"[^>]*>(.*?)</span>', main, re.S
    ):
        flat = strip_tags(text).replace("\n", " ")
        words = [w.strip() for w in re.split(r"[;,]", flat)]
        words = [w for w in words if w]
        (et if lang == "et" else en).extend(words)
    # de-dup, preserve order
    return _dedup(et), _dedup(en)


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def parse_term(tid, url, lastmod, main):
    et, en = parse_title(main)

    _, _, body = main.partition('<div class="term-body">')

    # sources: external links (order-preserving, de-duped)
    sources = _dedup(re.findall(r'href="(https?://[^"]+)"', body))

    def term_links(segment):
        out, seen = [], set()
        for rid, name in re.findall(
            r'href="/term/(\d+)[^"]*"[^>]*>(.*?)</a>', segment, re.S
        ):
            rid = int(rid)
            nm = clean_ws(strip_tags(name))
            if rid != tid and rid not in seen and nm:
                seen.add(rid)
                out.append({"id": rid, "term": nm})
        return out

    # related: only the "vt ka" (see also) section, not inline definition links
    mrel = re.search(r"<strong>\s*vt\s*ka\s*</strong>(.*?)$", body, re.S | re.I)
    related = term_links(mrel.group(1)) if mrel else []
    # every internal link in the body (used only for alias detection)
    all_links = term_links(body)

    # The "olemus" section holds both definitions and runs until the next
    # heading. Multi-sense terms subdivide it with sense markers —
    # <strong>(1a)</strong>, <strong>(2)</strong>, <strong>(1b) atribuudistik</strong>
    # — which are NOT headings: stopping at them left every multi-sense term
    # (including #2 turvalisus) with no definition at all.
    mo = re.search(
        r"<strong>\s*olemus\s*</strong>(.*?)(?=<strong>(?!\s*\(\w{1,3}\))|$)",
        body, re.S | re.I,
    )
    if mo:
        olemus = mo.group(1)
    else:
        pre = re.split(r"<strong>", body, maxsplit=1)[0]
        olemus = pre if strip_tags(pre).strip() else body

    # English glosses are introduced either by an <em> block or by an English
    # dictionary-source label ("Wiktionary:", "Cambridge:", ... — plain text,
    # no <em>). Estonian dictionaries (ÕS, EKSS, Vikipeedia) and ISO cites are
    # NOT boundaries; their text stays in the Estonian definition.
    en_src = (
        r"Wiktionary|Wikipedia|Cambridge|Britannica|Merriam[-\s]?Webster"
        r"|Collins|Investopedia|Techopedia|Oxford|Dictionary\.com"
    )
    boundary = re.search(r"<em>|\b(?:" + en_src + r")\s*:", olemus, re.I)

    # english definition: the <em> gloss (skipping any etymology hint before
    # olemus), else the plain text following an English-source label
    em = re.search(r"<em>(.*?)</em>", olemus, re.S)
    if em:
        definition_en = clean_ws(strip_tags(em.group(1)))
    else:
        lbl = re.search(
            r"\b(?:" + en_src + r")\s*:(.*?)(?:<br\s*/?>\s*<br\s*/?>|$)",
            olemus, re.S | re.I,
        )
        definition_en = clean_ws(strip_tags(lbl.group(1))) if lbl else ""

    # estonian definition: olemus text up to that first English gloss
    chunk = olemus[: boundary.start()] if boundary else olemus
    chunk = re.sub(r'<span class="hint-marker">.*?</span>', " ", chunk, flags=re.S)
    chunk = re.sub(r'<a\s+href="https?://[^"]*"[^>]*>.*?</a>', " ", chunk, flags=re.S)
    definition_et = clean_ws(strip_tags(chunk))
    # drop a trailing dictionary-source label, optionally with a part-of-speech
    # tag ("Wiktionary:", "ÕS:", "Wiktionary, adj:", ...)
    definition_et = re.sub(
        r"[\s,;=–—-]*"
        r"(?:Wiktionary|Wikipedia|Vikipeedia|EKSS|Õ[SD]|VSL|Britannica|Cambridge)"
        r"(?:\s*,?\s*(?:adj|adv|noun|verb|pron|prep|conj|abbr|n|v)\.?)?"
        r"\s*:?\s*$",
        "",
        definition_et,
        flags=re.I,
    ).strip(" ,;=-–—")

    # pure cross-reference (e.g. "0-day  = zero day")
    alias_of = None
    body_text = strip_tags(body).strip()
    if (
        body_text.startswith("=")
        and len(all_links) == 1
        and not em
        and not re.search(r"<strong>", body, re.I)
    ):
        alias_of = all_links[0]
        definition_et = ""

    return {
        "id": tid,
        "url": url,
        "lastmod": lastmod,
        "et": et,
        "en": en,
        "definition_et": definition_et,
        "definition_en": definition_en,
        "related": related,
        "sources": sources,
        "alias_of": alias_of,
    }


# --------------------------------------------------------------------------- #
# Raw mirror I/O
# --------------------------------------------------------------------------- #
def read_jsonl(f):
    return [json.loads(line) for line in f if line.strip()]


def load_raw():
    """Return dict {id: {'url','lastmod','html'}} from the raw mirror."""
    if not os.path.exists(RAW_PATH):
        return {}
    with gzip.open(RAW_PATH, "rt", encoding="utf-8") as f:
        return {rec["id"]: rec for rec in read_jsonl(f)}


def write_atomic(path, lines, opener=open):
    """Replace path with lines, all-or-nothing and leaving no partial file."""
    tmp = path + ".tmp"
    try:
        with opener(tmp, "wt", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def by_id(records):
    return sorted(records.values(), key=lambda r: r["id"])


def write_raw(records):
    write_atomic(
        RAW_PATH,
        (json.dumps(r, ensure_ascii=False) for r in by_id(records)),
        gzip.open,
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def sitemap_is_credible(listed, mirrored):
    """A complete crawl prunes every term the sitemap omits, so a sitemap served
    truncated (partial render, outage) would delete most of the mirror. Losing
    half of it is never a real edit to the lexicon.
    """
    return listed >= 0.5 * mirrored


def fetch_term(item):
    """(tid, url, lastmod) -> (tid, url, lastmod, main_html, error)."""
    tid, url, lastmod = item
    try:
        main = extract_main(http_get(url))
        # An error page or a template change would otherwise be stored as a
        # headword-less record that lookup can never match and that update never
        # refetches, since its lastmod now looks current. Treat it as a failure
        # so the previous copy survives and the next run retries.
        if not main.strip():
            return tid, url, lastmod, None, "no <main> in page"
        return tid, url, lastmod, main, None
    except Exception as e:  # noqa: BLE001 - keep crawling on any single failure
        return tid, url, lastmod, None, str(e)


def cmd_update(args):
    print(f"[akit] fetching sitemap {SITEMAP_URL}", file=sys.stderr)
    entries = parse_sitemap(http_get(SITEMAP_URL))
    if not entries:
        sys.exit("[akit] sitemap listed no /term/ URLs; refusing to rewrite the mirror")
    # Only a complete crawl may prune: a partial one has no opinion about the
    # terms it never listed, and dropping them would destroy the mirror.
    complete_crawl = not args.limit
    if args.limit:
        entries = entries[: args.limit]
    print(f"[akit] {len(entries)} term URLs", file=sys.stderr)

    existing = load_raw()
    if complete_crawl and not sitemap_is_credible(len(entries), len(existing)):
        sys.exit(
            f"[akit] sitemap lists {len(entries)} terms but {len(existing)} are "
            "mirrored; refusing to prune. Re-run when the site is healthy."
        )

    todo = []
    for tid, url, lastmod in entries:
        old = existing.get(tid)
        if args.force or old is None or old.get("lastmod", "") != lastmod:
            todo.append((tid, url, lastmod))
    print(
        f"[akit] {len(todo)} to fetch, {len(entries) - len(todo)} unchanged",
        file=sys.stderr,
    )

    if complete_crawl:
        records = {tid: existing[tid] for tid, _, _ in entries if tid in existing}
    else:
        records = dict(existing)
    done = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_term, it) for it in todo]
        for fut in as_completed(futures):
            tid, url, lastmod, main, err = fut.result()
            if err is not None:
                failed += 1
                if failed <= 20:
                    print(f"[akit] FAIL {tid}: {err}", file=sys.stderr)
            else:
                records[tid] = {
                    "id": tid,
                    "url": url,
                    "lastmod": lastmod,
                    "html": main,
                }
            done += 1
            if done % 500 == 0:
                print(f"[akit] fetched {done}/{len(todo)}", file=sys.stderr)

    write_raw(records)
    print(
        f"[akit] raw mirror written: {len(records)} terms, {failed} failed -> {RAW_PATH}",
        file=sys.stderr,
    )
    build_index()


def build_index():
    raw = load_raw()
    write_atomic(
        DATA_PATH,
        (
            json.dumps(
                parse_term(r["id"], r["url"], r.get("lastmod", ""), r["html"] or ""),
                ensure_ascii=False,
            )
            for r in by_id(raw)
        ),
    )
    print(f"[akit] index built: {len(raw)} terms -> {DATA_PATH}", file=sys.stderr)


def cmd_build(args):
    if not os.path.exists(RAW_PATH):
        sys.exit("[akit] no raw mirror; run `uv run akit.py update` first")
    build_index()


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #
_FOLD = str.maketrans(
    {
        "ä": "a", "ö": "o", "ü": "u", "õ": "o", "š": "s", "ž": "z",
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "à": "a", "è": "e", "ñ": "n", "ç": "c",
    }
)


FUZZY_MIN = 0.72  # difflib ratio below this is noise, not a misspelling


def norm(s):
    return (s or "").lower().strip()


def fold(s):
    return norm(s).translate(_FOLD)


def load_index():
    if not os.path.exists(DATA_PATH):
        sys.exit(f"[akit] no index at {DATA_PATH}; run `uv run akit.py update` first")
    with open(DATA_PATH, encoding="utf-8") as f:
        return read_jsonl(f)


def score_item(it, q, qf, direction):
    # --et / --en narrow the search to one language by emptying the other list
    ets = [] if direction == "en" else [norm(x) for x in it["et"]]
    ens = [] if direction == "et" else [norm(x) for x in it["en"]]
    head = ets + ens
    headf = [fold(h) for h in head]

    if q in ets:
        return 100, "ET headword"
    if q in ens:
        return 99, "EN headword"
    if qf in headf:
        return 94, "headword (ignoring diacritics)"
    if any(h.startswith(q) for h in head):
        return 80, "headword prefix"
    if any(hf.startswith(qf) for hf in headf):
        return 76, "headword prefix (folded)"
    if any(q in h for h in head):
        return 64, "in headword"
    if q and (q in norm(it.get("definition_et", "")) or q in norm(it.get("definition_en", ""))):
        return 45, "in definition"
    # ratio() <= 2*min(len)/sum(len); skipping headwords whose ceiling already
    # misses FUZZY_MIN avoids ~half the O(n·m) matches on a full-corpus scan
    best = max(
        (
            SequenceMatcher(None, qf, hf).ratio()
            for hf in headf
            if 2 * min(len(qf), len(hf)) >= FUZZY_MIN * (len(qf) + len(hf))
        ),
        default=0.0,
    )
    if best >= FUZZY_MIN:
        return int(20 + best * 30), f"fuzzy match ({best:.0%})"
    return 0, ""


def search(items, query, limit, direction=None):
    q, qf = norm(query), fold(query)
    if not q:  # every headword prefix-matches "", which would score 5 arbitrary hits at 80
        return []
    scored = []
    for it in items:
        s, why = score_item(it, q, qf, direction)
        if s > 0:
            scored.append((s, it, why))
    scored.sort(key=lambda t: (-t[0], t[1]["id"]))
    return scored[:limit]


# --------------------------------------------------------------------------- #
# Similarity search (description -> term, by meaning)
#
# `lookup` matches the query against headwords/definitions as substrings; it is
# the right tool when you already know (roughly) the word. `similar` answers the
# other question -- "I can describe the concept but don't know its name" -- by
# ranking every term on how much vocabulary it shares with the description.
#
# Model: TF-IDF cosine over each term's et + en + definition_et + definition_en.
# Pure stdlib (math + collections), and built on the fly from the loaded index
# so no data-file migration or rebuild is needed -- one pass over ~16k short
# records is well under a second.
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Bilingual (ET + EN) function words -- stored folded, since tokens are folded.
# They carry no concept signal; dropping them keeps short headword-only records
# from ranking on a bare "is"/"on"/"the" and cleans up the reported matches.
_STOPWORDS = frozenset(
    fold(w)
    for w in (
        "a an and or the of to in into on at by for from with without "
        "is are be am was were been being it its this that these those "
        "who whom whose which what not no nor may can could will would shall should must "
        "such other than then when where how also see "
        "ja või ning ega ka et kui siis nii aga kuid vaid nagu "
        "kes mis mille see need seda selle sel selles "
        "on ei ole olla pole võib saab tuleb peab mitte "
        "kõik oma ta tema nende kus millal kuidas vt"
    ).split()
)


def tokenize(text):
    """Fold diacritics, lowercase, split into alphanumeric tokens."""
    return _TOKEN_RE.findall(fold(text))


def doc_text(it):
    """The bag-of-words source for a term: both headwords and both definitions."""
    return " ".join(
        it.get("et", [])
        + it.get("en", [])
        + [it.get("definition_et") or "", it.get("definition_en") or ""]
    )


def tfidf_vec(tokens, idf):
    """Log-scaled term frequency weighted by IDF. Both sides of the cosine must
    be weighted the same way, so document and query vectors share this."""
    return {
        t: (1.0 + math.log(c)) * idf[t]
        for t, c in Counter(tokens).items()
        if t in idf
    }


def l2(vec):
    return math.sqrt(sum(w * w for w in vec.values())) or 1.0


def build_tfidf(items):
    """Return (idf, vecs, norms): the IDF map, one L2-weighted TF-IDF vector per
    item (token -> weight), and each vector's Euclidean norm."""
    docs = [tokenize(doc_text(it)) for it in items]
    df = Counter()
    for toks in docs:
        df.update(set(toks))
    n = len(items) or 1
    idf = {
        t: math.log((n + 1) / (c + 1)) + 1.0
        for t, c in df.items()
        if len(t) > 1 and t not in _STOPWORDS
    }

    vecs = [tfidf_vec(toks, idf) for toks in docs]
    return idf, vecs, [l2(v) for v in vecs]


def similar(items, query, limit):
    """Rank items by cosine similarity of the query to each term's text.

    Returns [(score, item, matched_tokens)] sorted best-first, where score is a
    0..1 cosine and matched_tokens are the query words that drove the match.
    """
    idf, vecs, norms = build_tfidf(items)
    qvec = tfidf_vec(tokenize(query), idf)
    if not qvec:
        return []
    qnorm = l2(qvec)

    out = []
    for it, vec, vnorm in zip(items, vecs, norms):
        if it.get("alias_of"):  # a bare redirect ("0-day = zero day"); rank its target instead
            continue
        common = qvec.keys() & vec.keys()
        if not common:
            continue
        dot = sum(qvec[t] * vec[t] for t in common)
        score = dot / (qnorm * vnorm)
        matched = sorted(common, key=lambda t: qvec[t] * vec[t], reverse=True)
        out.append((score, it, matched[:5]))
    out.sort(key=lambda t: (-t[0], t[1]["id"]))
    return out[:limit]


def fmt_human(it, why):
    et = ", ".join(it["et"]) or "—"
    en = ", ".join(it["en"]) or "—"
    lines = [f"● {et}   [EN: {en}]   (#{it['id']}, {why})", f"  {it['url']}"]
    if it.get("alias_of"):
        a = it["alias_of"]
        lines.append(f"  → vt {a['term']} (#{a['id']})")
    if it.get("definition_et"):
        lines.append(f"  ET: {it['definition_et']}")
    if it.get("definition_en"):
        lines.append(f"  EN: {it['definition_en']}")
    if it.get("related"):
        lines.append("  vt ka: " + ", ".join(r["term"] for r in it["related"][:8]))
    if it.get("sources"):
        lines.append(f"  allikaid: {len(it['sources'])}")
    return "\n".join(lines)


def dump_json(rows):
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_lookup(args):
    items = load_index()
    direction = "en" if args.en else "et" if args.et else None
    hits = search(items, args.query, direction=direction, limit=args.n)
    if args.json:
        dump_json([{"score": s, "why": w, **it} for s, it, w in hits])
        return
    if not hits:
        print(f"(ei leidnud vastet: {args.query!r})")
        return
    print("\n\n".join(fmt_human(it, why) for _, it, why in hits))


def cmd_similar(args):
    items = load_index()
    hits = similar(items, args.query, limit=args.n)
    if args.json:
        dump_json([{"score": round(s, 4), "matched": m, **it} for s, it, m in hits])
        return
    if not hits:
        print(f"(ei leidnud sarnast: {args.query!r})")
        return
    # in place of a match reason, show the cosine + the words that drove it
    print("\n\n".join(
        fmt_human(it, f"sarnasus {s:.0%}" + (f" · {', '.join(m)}" if m else ""))
        for s, it, m in hits
    ))


# --------------------------------------------------------------------------- #
def positive(s):
    """argparse type: reject `-n 0` / `-n -1`, which slice away real hits."""
    n = int(s)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def build_parser():
    p = argparse.ArgumentParser(prog="akit", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("update", help="crawl akit.cyber.ee and rebuild the index")
    up.add_argument("--workers", type=int, default=8)
    up.add_argument("--limit", type=int, default=0, help="fetch only first N (testing)")
    up.add_argument("--force", action="store_true", help="refetch even if lastmod unchanged")
    up.set_defaults(func=cmd_update)

    bd = sub.add_parser("build", help="re-derive index from the raw mirror (no network)")
    bd.set_defaults(func=cmd_build)

    # shared by both query commands
    qry = argparse.ArgumentParser(add_help=False)
    qry.add_argument("--json", action="store_true")
    qry.add_argument("-n", type=positive, default=5, help="max results")

    lk = sub.add_parser("lookup", parents=[qry], help="search the local index")
    lk.add_argument("query")
    lang = lk.add_mutually_exclusive_group()
    lang.add_argument("--en", action="store_true", help="input is English (find Estonian)")
    lang.add_argument("--et", action="store_true", help="input is Estonian")
    lk.set_defaults(func=cmd_lookup)

    sm = sub.add_parser(
        "similar", parents=[qry],
        help="rank terms by how closely their meaning matches a description",
    )
    sm.add_argument("query", help="a phrase or description (English or Estonian)")
    sm.set_defaults(func=cmd_similar)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

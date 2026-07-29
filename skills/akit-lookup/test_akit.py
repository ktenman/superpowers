#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tests for akit.py. Run standalone (`uv run test_akit.py`) or under pytest.

The fixtures are SYNTHETIC: real AKIT markup structure, invented content. AKIT
text is (c) Cybernetica AS and is deliberately not committed to this repo (see
DESIGN.md), and the parser only cares about the markup shape anyway. Each
fixture below mirrors a page layout observed in a live crawl.
"""

import contextlib
import http.client
import os
import sys
import tempfile

import akit

URL = "https://akit.cyber.ee/term/7"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

# Two headwords per language, a hint marker, a sense-subdivided olemus, an
# English dictionary gloss, an ISO cite, external + internal links, "vt ka".
MAIN_MULTI = """
            <h1 class="term-title">
    <span lang="en" data-lang="Inglise">
      widget security (1), widget safety, Widget Security (1)
</span>  <br>
    <span lang="et" data-lang="Eesti">
      vidinaturvalisus; vidinaturva-
</span></h1>
<div class="term-body">
    <p><span class="hint-marker">6:</span> mitte vidinaturbe-
<br/>
<br/><strong>olemus</strong>
<br/><strong>(1a)</strong> vidina <span class="hint-marker">6:</span> kaitstus teadaolevate <a href="/term/93">ohtude</a> vastu <a href="https://example.net/spec">https://example.net/spec</a>
<br/>Wiktionary:
<br/><em>the state of a widget being protected
<br/>Second line of the gloss.</em>
<br/><a href="https://example.org/widget">https://example.org/widget</a>
<br/>
<br/>ISO 12345:
<br/>vidina omadus, mida moodab <a href="/term/512-vidina-turvatase">vidina turvatase</a>
<br/><a href="https://example.org/widget">https://example.org/widget</a>
<br/>
<br/><strong>(1b)</strong> luhivorm liitsonades
<br/>
<br/><strong>vt ka</strong>
<br/>- <a href="/term/10220">vidina turvameede</a>
<br/>- <a href="/term/2814">vidina turvarisk</a>
<br/>- <a href="/term/7">vidinaturvalisus</a>
</p>
</div>
"""

# Same sense subdivision but no English gloss, so the Estonian definition has
# to span every sense marker. This is the regression guard for the bug where
# <strong>(1a)</strong> ended the olemus section and multi-sense terms (#2
# turvalisus, #510 identiteet, #7631 aspekt, #13237 assembler) parsed with no
# definition at all.
MAIN_SENSES = """
            <h1 class="term-title">
    <span lang="et" data-lang="Eesti">
      vidinaaspekt
</span></h1>
<div class="term-body">
    <p><strong>olemus</strong>
<br/><strong>(1a)</strong> esimene tahendus
<br/><strong>(1b)</strong> teine tahendus
<br/><strong>(1c) alaliik</strong> kolmas tahendus
<br/>
<br/><strong>vt ka</strong>
<br/>- <a href="/term/99">muu vidin</a>
</p>
</div>
"""

# A pure cross-reference stub: body is "= <link>" and nothing else.
MAIN_ALIAS = """
            <h1 class="term-title">
    <span lang="en" data-lang="Inglise">
      widget plaintext (1)
</span>
</h1>
<div class="term-body">
    <p>= <a href="/term/120">widget cleartext</a></p>

</div>
"""

# No olemus heading at all: the whole body is the definition. Contains a single
# internal link, which must NOT be mistaken for a cross-reference.
MAIN_MINIMAL = """
            <h1 class="term-title">
    <span lang="en" data-lang="Inglise">
      exbi-widget
</span>
</h1>
<div class="term-body">
    <p>a <a href="/term/4208">binary widget prefix</a></p>

</div>
"""

# Estonian dictionary label: its text belongs to the Estonian definition, but a
# dangling label at the very end is noise and gets stripped.
MAIN_ET_SOURCE = """
            <h1 class="term-title">
    <span lang="et" data-lang="Eesti">
      vidinaparool
</span></h1>
<div class="term-body">
    <p><strong>olemus</strong>
<br/>OS: salajane sone vidina tuvastamiseks
<br/>Vikipeedia:
</p>
</div>
"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://akit.cyber.ee/term/2</loc><lastmod>2024-05-28T07:35:58Z</lastmod></url>
<url><loc>https://akit.cyber.ee/term/512-vidina-turvatase</loc><lastmod>2020-01-02</lastmod></url>
<url><loc>https://akit.cyber.ee/term/8</loc></url>
<url><loc>https://akit.cyber.ee/about</loc><lastmod>2020-01-02</lastmod></url>
<url><loc>file:///term/1</loc><lastmod>2020-01-02</lastmod></url>
<url><loc>https://evil.example/term/1</loc><lastmod>2020-01-02</lastmod></url>
<url><loc>http://akit.cyber.ee/term/3</loc><lastmod>2020-01-02</lastmod></url>
</urlset>
"""


def item(tid, et, en, det="", den="", alias=None):
    return {
        "id": tid, "url": "", "lastmod": "", "et": et, "en": en,
        "definition_et": det, "definition_en": den,
        "related": [], "sources": [], "alias_of": alias,
    }


ITEMS = [
    item(1, ["vidinaturvalisus"], ["widget security"],
         "vidina kaitstus teadaolevate ohtude vastu", "widget protection"),
    item(2, ["küberturvalisus"], ["cyber security"], "küberruumi turvalisus"),
    item(3, ["parool"], ["password"], "salajane sõne kasutaja tuvastamiseks",
         "secret string"),
    item(4, [], ["widget plaintext"], alias={"id": 1, "term": "vidinaturvalisus"}),
]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def test_headwords():
    t = akit.parse_term(7, URL, "2026-01-01T00:00:00Z", MAIN_MULTI)
    # both separators split, sense suffix kept as a homonym disambiguator, and
    # a case-variant repeat of an earlier headword collapses
    assert t["en"] == ["widget security (1)", "widget safety"], t["en"]
    assert t["et"] == ["vidinaturvalisus", "vidinaturva-"], t["et"]
    assert (t["id"], t["url"], t["lastmod"]) == (7, URL, "2026-01-01T00:00:00Z")


def test_definitions():
    t = akit.parse_term(7, URL, "", MAIN_MULTI)
    assert t["definition_et"] == "(1a) vidina kaitstus teadaolevate ohtude vastu", \
        t["definition_et"]
    assert t["definition_en"] == (
        "the state of a widget being protected Second line of the gloss."
    ), t["definition_en"]
    # the English gloss ends the Estonian definition, so the ISO cite after it
    # is not part of either
    assert "12345" not in t["definition_et"]
    # internal link text is kept; external links and hint markers are dropped
    # whole, including the ones sitting inside the Estonian text
    assert "ohtude" in t["definition_et"]
    assert "example.net" not in t["definition_et"]
    assert "6:" not in t["definition_et"]


def test_sense_markers_do_not_end_the_olemus_section():
    # Regression: <strong>(1a)</strong> used to terminate olemus, leaving every
    # multi-sense term with definition_et == definition_en == "".
    t = akit.parse_term(11, URL, "", MAIN_SENSES)
    assert t["definition_et"] == (
        "(1a) esimene tahendus (1b) teine tahendus (1c) alaliik kolmas tahendus"
    ), t["definition_et"]
    # ...but a real heading still does end it
    assert "vt ka" not in t["definition_et"]
    assert "muu vidin" not in t["definition_et"]


def test_related_and_sources():
    t = akit.parse_term(7, URL, "", MAIN_MULTI)
    # only the "vt ka" section, and never a self-reference (/term/7)
    assert t["related"] == [
        {"id": 10220, "term": "vidina turvameede"},
        {"id": 2814, "term": "vidina turvarisk"},
    ], t["related"]
    # every external URL on the page, in document order, cited twice or not
    assert t["sources"] == [
        "https://example.net/spec",
        "https://example.org/widget",
    ], t["sources"]


def test_alias_stub():
    t = akit.parse_term(5, URL, "", MAIN_ALIAS)
    assert t["alias_of"] == {"id": 120, "term": "widget cleartext"}, t["alias_of"]
    assert t["definition_et"] == "" and t["definition_en"] == ""
    assert t["en"] == ["widget plaintext (1)"] and t["et"] == []


def test_body_without_olemus_is_the_definition():
    t = akit.parse_term(5651, URL, "", MAIN_MINIMAL)
    assert t["definition_et"] == "a binary widget prefix", t["definition_et"]
    # one internal link is not enough to make it a cross-reference
    assert t["alias_of"] is None


def test_estonian_source_labels():
    t = akit.parse_term(12, URL, "", MAIN_ET_SOURCE)
    # an Estonian dictionary is not an English-gloss boundary: its text stays
    assert t["definition_et"] == "OS: salajane sone vidina tuvastamiseks", \
        t["definition_et"]
    # ...while the dangling trailing label is dropped
    assert not t["definition_et"].endswith("Vikipeedia:")
    assert t["definition_en"] == ""


def test_missing_main_yields_an_unfindable_record():
    assert akit.extract_main("<html><body>error page</body></html>") == ""
    t = akit.parse_term(9, URL, "2026-01-01", "")
    assert t["et"] == [] and t["en"] == []
    assert t["definition_et"] == "" and t["definition_en"] == ""
    # It can never match anything, which is why fetch_term rejects it below.
    assert akit.score_item(t, "widget", "widget", None) == (0, "")


def test_fetch_term_rejects_a_page_without_main():
    item = (7, URL, "2026-01-01")
    original = akit.http_get
    try:
        akit.http_get = lambda url, **kw: "<html><body>503 try later</body></html>"
        tid, url, lastmod, main, err = akit.fetch_term(item)
        # reported as a failure, so cmd_update keeps the previous copy and the
        # unchanged lastmod makes the next run retry it
        assert (main, err) == (None, "no <main> in page"), (main, err)
        assert (tid, url, lastmod) == item

        akit.http_get = lambda url, **kw: "<html><main> real content </main></html>"
        assert akit.fetch_term(item)[3] == " real content "

        def boom(url, **kw):
            raise OSError("connection reset")

        akit.http_get = boom
        assert akit.fetch_term(item)[4] == "connection reset"
    finally:
        akit.http_get = original


def attempts_for(exc):
    """How many times http_get calls urlopen before it gives up on exc."""
    calls = []

    def boom(req, timeout=None):
        calls.append(1)
        raise exc

    saved = (akit.urllib.request.urlopen, akit.time.sleep)
    akit.urllib.request.urlopen = boom
    akit.time.sleep = lambda s: None  # no real backoff during the test
    try:
        try:
            akit.http_get(URL)
        except Exception:
            pass
        return len(calls)
    finally:
        akit.urllib.request.urlopen, akit.time.sleep = saved


def test_http_get_does_not_retry_a_permanent_client_error():
    def http_error(code):
        return akit.urllib.error.HTTPError(URL, code, "nope", {}, None)

    assert attempts_for(http_error(404)) == 1
    assert attempts_for(http_error(410)) == 1
    # rate limiting and server faults are transient, so those still get retried
    assert attempts_for(http_error(429)) == 3
    assert attempts_for(http_error(503)) == 3
    assert attempts_for(OSError("connection reset")) == 3
    # a truncated response is the failure a real full crawl hits; retrying it is
    # the whole point, and HTTPException is not an OSError
    assert attempts_for(http.client.IncompleteRead(b"partial")) == 3


# --------------------------------------------------------------------------- #
# Sitemap
# --------------------------------------------------------------------------- #
def test_parse_sitemap_only_accepts_akit_term_pages():
    assert akit.parse_sitemap(SITEMAP) == [
        (2, "https://akit.cyber.ee/term/2", "2024-05-28T07:35:58Z"),
        (512, "https://akit.cyber.ee/term/512-vidina-turvatase", "2020-01-02"),
        (8, "https://akit.cyber.ee/term/8", ""),
    ]
    # Dropped above: /about (not a term), file:// and evil.example (urlopen
    # would happily fetch both), and plain http:// (BASE is https). If AKIT ever
    # moves off https this test is why the crawl suddenly finds nothing.


def test_a_truncated_sitemap_may_not_prune_the_mirror():
    assert akit.sitemap_is_credible(16420, 16420)
    assert akit.sitemap_is_credible(16000, 16420)  # ordinary churn
    assert akit.sitemap_is_credible(0, 0)  # first ever crawl
    assert not akit.sitemap_is_credible(12, 16420)  # site half down
    assert not akit.sitemap_is_credible(8000, 16420)  # exactly-half is not enough


def aborts_update(argv, sitemap, mirrored, expect):
    """Run cmd_update with the mirror stubbed out; assert it exits, unwritten."""
    def refuse(*a, **kw):
        raise AssertionError("update must abort before touching the mirror")

    saved = (akit.http_get, akit.load_raw, akit.write_raw, akit.build_index)
    try:
        akit.http_get = lambda url, **kw: sitemap
        akit.load_raw = lambda: {i: {} for i in range(mirrored)}
        akit.write_raw = akit.build_index = refuse
        with quiet_stderr():
            try:
                akit.cmd_update(akit.build_parser().parse_args(argv))
            except SystemExit as e:
                assert expect in str(e), e
                return
        raise AssertionError(f"expected {expect!r}, got a completed crawl")
    finally:
        akit.http_get, akit.load_raw, akit.write_raw, akit.build_index = saved


def test_update_aborts_before_writing_when_the_sitemap_looks_wrong():
    # 3 usable term URLs must not prune a 100-term mirror
    aborts_update(["update"], SITEMAP, 100, "refusing to prune")
    # a sitemap with no term URLs at all would empty the mirror outright
    empty = "<urlset><url><loc>https://akit.cyber.ee/about</loc></url></urlset>"
    aborts_update(["update"], empty, 100, "refusing to rewrite")
    aborts_update(["update"], empty, 0, "refusing to rewrite")


def test_partial_crawl_merges_instead_of_pruning():
    tmp = tempfile.mkdtemp()
    saved = (akit.RAW_PATH, akit.DATA_PATH, akit.http_get)
    try:
        akit.RAW_PATH = os.path.join(tmp, "raw.jsonl.gz")
        akit.DATA_PATH = os.path.join(tmp, "index.jsonl")
        # a mirror holding four terms the sitemap below never lists -- enough
        # that sitemap_is_credible(1, 4) is false, so this also pins that the
        # prune guard is scoped to complete crawls
        akit.write_raw({
            i: {"id": i, "url": f"{akit.BASE}/term/{i}", "lastmod": "2020-01-01",
                "html": MAIN_MINIMAL}
            for i in (900, 901, 902, 903)
        })
        akit.http_get = lambda url, **kw: (
            SITEMAP if url == akit.SITEMAP_URL else f"<main>{MAIN_ALIAS}</main>"
        )
        with quiet_stderr():
            akit.cmd_update(akit.build_parser().parse_args(["update", "--limit", "1"]))
        # --limit has no opinion about terms it never listed, so they survive
        kept = [2, 900, 901, 902, 903]
        assert sorted(akit.load_raw()) == kept, sorted(akit.load_raw())
        assert [r["id"] for r in akit.load_index()] == kept
    finally:
        akit.RAW_PATH, akit.DATA_PATH, akit.http_get = saved


def test_a_failed_fetch_keeps_the_previous_copy():
    tmp = tempfile.mkdtemp()
    saved = (akit.RAW_PATH, akit.DATA_PATH, akit.http_get)
    try:
        akit.RAW_PATH = os.path.join(tmp, "raw.jsonl.gz")
        akit.DATA_PATH = os.path.join(tmp, "index.jsonl")
        # stale lastmod, so the sitemap entry for #2 lands in the refetch list
        akit.write_raw({2: {"id": 2, "url": f"{akit.BASE}/term/2",
                            "lastmod": "2020-01-01", "html": MAIN_MINIMAL}})

        def flaky(url, **kw):
            if url == akit.SITEMAP_URL:
                return SITEMAP
            raise OSError("connection reset")

        akit.http_get = flaky
        with quiet_stderr():
            akit.cmd_update(akit.build_parser().parse_args(["update", "--limit", "1"]))
        kept = akit.load_raw()[2]
        assert kept["html"] == MAIN_MINIMAL
        # the stale lastmod survives too, so the next run retries the fetch
        assert kept["lastmod"] == "2020-01-01"
    finally:
        akit.RAW_PATH, akit.DATA_PATH, akit.http_get = saved


# --------------------------------------------------------------------------- #
# Lookup scoring
# --------------------------------------------------------------------------- #
def score(it, q, direction=None):
    return akit.score_item(it, akit.norm(q), akit.fold(q), direction)


def test_scoring_tiers():
    one, two, three = ITEMS[0], ITEMS[1], ITEMS[2]
    assert score(three, "parool") == (100, "ET headword")
    assert score(three, "password") == (99, "EN headword")
    assert score(two, "kuberturvalisus")[0] == 94
    assert score(three, "paro")[0] == 80
    assert score(two, "kuberturva")[0] == 76
    assert score(one, "turvalisus")[0] == 64
    assert score(one, "kaitstus")[0] == 45
    assert score(one, "protection")[0] == 45
    s, why = score(three, "pasword")
    assert 20 < s < 50 and why.startswith("fuzzy"), (s, why)
    assert score(three, "zzzznothing") == (0, "")


def test_search_ordering_and_empty_query():
    hits = akit.search(ITEMS, "turvalisus", limit=5)
    assert [it["id"] for _, it, _ in hits] == [1, 2], hits
    # every headword prefix-matches "", so an empty query must return nothing
    assert akit.search(ITEMS, "", limit=5) == []
    assert akit.search(ITEMS, "   ", limit=5) == []


def test_equal_scores_break_by_id_not_by_index():
    # all three are tier-64 "in headword" for this query; the lowest id wins
    # regardless of where it sits in the index file
    late = item(0, ["küberturvalisus"], [])
    hits = akit.search(ITEMS + [late], "turvalisus", limit=5)
    assert {s for s, _, _ in hits} == {64}, hits
    assert [it["id"] for _, it, _ in hits] == [0, 1, 2], hits


def test_language_flags_restrict_rather_than_reorder():
    # --et means "my query is Estonian": English headwords stop matching
    assert score(ITEMS[2], "password", "et") == (0, "")
    assert score(ITEMS[2], "password", None) == (99, "EN headword")
    assert score(ITEMS[2], "parool", "en") == (0, "")
    assert score(ITEMS[2], "parool", "et") == (100, "ET headword")


@contextlib.contextmanager
def quiet_stderr():
    with open(os.devnull, "w") as devnull, contextlib.redirect_stderr(devnull):
        yield


def rejects(argv):
    """True if the CLI refuses argv (argparse exits 2 after printing usage)."""
    with quiet_stderr():
        try:
            akit.build_parser().parse_args(argv)
        except SystemExit:
            return True
    return False


def test_n_must_be_positive():
    assert akit.positive("3") == 3
    assert akit.build_parser().parse_args(["lookup", "vidin", "-n", "3"]).n == 3
    # `-n 0` / `-n -1` reach scored[:n] and silently slice real hits away, so the
    # parser has to reject them -- not just `positive` in isolation.
    for bad in ("0", "-1"):
        assert rejects(["lookup", "vidin", "-n", bad]), f"-n {bad} was accepted"
        assert rejects(["similar", "vidin", "-n", bad]), f"similar -n {bad}"


def test_language_flags_are_mutually_exclusive():
    args = akit.build_parser().parse_args(["lookup", "vidin", "--et"])
    assert (args.et, args.en) == (True, False)
    assert rejects(["lookup", "vidin", "--et", "--en"])


# --------------------------------------------------------------------------- #
# Similarity
# --------------------------------------------------------------------------- #
def test_similar_ranks_on_definition_vocabulary():
    hits = akit.similar(ITEMS, "kaitstus teadaolevate ohtude vastu", 5)
    assert hits, "expected the definition words to match"
    assert hits[0][1]["id"] == 1, [(h[1]["id"], round(h[0], 3)) for h in hits]
    assert 0 < hits[0][0] <= 1.0
    assert hits[0][2], "expected the matched tokens to be reported"
    # identical text scores identically; the lowest id wins so output is stable
    twins = [item(20, ["vidin lunavara"], []), item(10, ["vidin lunavara"], [])]
    assert [it["id"] for _, it, _ in akit.similar(twins, "vidin lunavara", 5)] == [10, 20]


def test_idf_discounts_words_that_appear_everywhere():
    corpus = [item(i, ["vidin"], [], "vidin on seade") for i in range(1, 6)]
    corpus.append(item(9, ["lunavara"], [], "vidin mis nouab lunaraha"))
    idf, _, _ = akit.build_tfidf(corpus)
    # "vidin" is in every record and carries almost no signal; "lunavara" is in
    # one. Without the IDF factor a query would score them the same.
    assert idf["lunavara"] > idf["vidin"], (idf["lunavara"], idf["vidin"])
    vec = akit.tfidf_vec(akit.tokenize("vidin lunavara"), idf)
    assert vec["lunavara"] > vec["vidin"], vec
    assert akit.similar(corpus, "vidin lunavara", 3)[0][1]["id"] == 9


def test_similar_skips_alias_stubs():
    hits = akit.similar(ITEMS, "widget plaintext", 5)
    assert 4 not in [it["id"] for _, it, _ in hits], "alias stub should not rank"


def test_similar_ignores_contentless_queries():
    assert akit.similar(ITEMS, "", 5) == []
    assert akit.similar(ITEMS, "the of and is on ei ole", 5) == []


# --------------------------------------------------------------------------- #
# Atomic writes
# --------------------------------------------------------------------------- #
def test_write_atomic_is_all_or_nothing():
    path = os.path.join(tempfile.mkdtemp(), "index.jsonl")
    akit.write_atomic(path, ["first", "second"])
    with open(path, encoding="utf-8") as f:
        assert f.read() == "first\nsecond\n"

    def half_a_file():
        yield "partial"
        raise RuntimeError("disk full")

    try:
        akit.write_atomic(path, half_a_file())
    except RuntimeError:
        pass
    else:
        raise AssertionError("the failure should have propagated")
    assert not os.path.exists(path + ".tmp"), "left a partial file behind"
    with open(path, encoding="utf-8") as f:
        assert f.read() == "first\nsecond\n", "clobbered the previous index"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            # SystemExit too: an over-eager abort in cmd_update is a failure,
            # not a reason to stop the run with a bare traceback
            except (Exception, SystemExit) as e:
                failures += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{failures} failed")
    sys.exit(1 if failures else 0)

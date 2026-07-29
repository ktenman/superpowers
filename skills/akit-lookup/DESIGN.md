# AKIT Lookup — design notes

Purpose: download the full AKIT lexicon (akit.cyber.ee) locally and look up the
correct Estonian information-security term, for VVKI documentation work.

## Key decisions

**Zero dependencies, run via uv.** Stdlib only (`urllib`, `re`, `html`, `gzip`,
`json`, `difflib`, `concurrent.futures`). PEP 723 inline metadata (`requires-python
= ">=3.10"`) lets `uv run akit.py` provision the interpreter with no install step,
no lockfile and no venv to manage — a full uv *tool* (as `ai-checker` uses) would
add a pyproject and an install step to buy nothing, since there are no deps to
resolve and the data files must sit beside the script either way.

**Data is generated, never committed.** AKIT content is © Cybernetica AS, so the
mirror is not redistributed with the repo; both data files are gitignored and each
user runs `update` once. This also keeps `skills/` small — `scripts/package-codex-plugin.sh`
copies the directory wholesale into every packaged plugin.

**Server-rendered scrape, no API.** AKIT term pages render their content in
`<main>…</main>` server-side; there is no public JSON API. The parser extracts
only `<main>` (the same content is duplicated in `<dialog>` loading elements and
a huge alphabetical sidebar — those must be ignored).

**Two-file architecture: raw mirror + derived index.**
- `akit_raw.jsonl.gz` stores the raw `<main>` HTML per term.
- `akit.jsonl` is the parsed, clean index.

This separation means parser fixes only require `build` (offline, instant), not a
re-crawl. The raw mirror is the durable "download of the full AKIT"; the index is
disposable and regenerable.

**Incremental crawl via sitemap `<lastmod>`.** `update` diffs each term's
`lastmod` against the existing mirror and fetches only what changed. Cold crawl
16,420 pages with 8 concurrent workers, measured at ~20 min; a warm refresh of
five stale pages took seconds.

**Retries only cover transient failures.** Three attempts with linear backoff on
`OSError` and `http.client.HTTPException`; a 4xx other than 429 is the server's
final answer and is reported at once. `HTTPException` is there because the only
error a real 16,420-page crawl hit was `IncompleteRead` — a truncated response,
which is not an `OSError` and so was previously not retried at all.

**Only a complete crawl may prune.** A full `update` rewrites the mirror from the
sitemap, dropping terms AKIT has retired. A partial one (`--limit`) must not: it
has no opinion about terms it never listed, so it merges into the existing mirror
instead of replacing it. A full crawl whose sitemap lists fewer than half the
mirrored terms aborts before writing anything — losing half the lexicon is an
outage or a truncated render, never a real edit. Failed fetches retain their
previous copy, and a page that yields no `<main>` counts as a failure rather than
being stored as a headword-less record that `update` would never refetch. Both
files are replaced atomically, so an interrupted run leaves the previous copy
intact. The mirror only ever loses a term on a successful, complete crawl that no
longer lists it.

## Parsing model (per term page)

- **Headwords**: every `<span lang="en">` / `<span lang="et">` in `<main>` — in
  practice these only occur in the `<h1 class="term-title">`, so the parser does
  not bother anchoring to the heading. Split on both `,` and `;` (AKIT uses both
  as separators). Sense suffixes like `(1)`/`(2)` are kept — they are homonym
  disambiguators. Worth re-checking after any AKIT template change: a `lang=`
  span appearing inside a definition would be misread as a headword.
- **Estonian definition**: the `olemus` section, truncated at the first `<em>`
  (the English gloss). Inline `/term/` links keep their anchor text; external
  `http(s)` links and trailing dictionary-source labels (`Wiktionary:`, `ÕS:`, …)
  are stripped. The section runs to the next `<strong>` heading but **not** to a
  `<strong>(1a)</strong>`-style sense marker: those subdivide the section rather
  than ending it, and stopping at them leaves every multi-sense term (#2
  `turvalisus` among them) with no definition in either language.
- **English definition**: the first `<em>…</em>` block.
- **Related** (`related[]`): only links inside the `vt ka` (see also) section —
  NOT inline definition links, which are grammatically inflected and noisy.
- **alias_of**: set when the body is a pure cross-reference (`= <a>other term</a>`
  with no olemus / `<em>` / `<strong>`), e.g. `0-day → zero day`.
- **sources[]**: all external URLs cited on the page.

## Lookup scoring (tiered, diacritic-folded)

exact ET/EN headword → folded-exact → prefix → folded-prefix → substring →
in-definition → fuzzy (`difflib` ratio ≥ 0.72). `--en`/`--et` restrict headword
matching to that language outright (the in-definition tier still reads both).
Estonian diacritics (ä ö ü õ š ž) fold to ASCII so misspellings and keyboard-lazy
queries still match.

## Validated against samples

- #12906 `e-identiteet, eID` ↔ `electronic identity` (multi-headword + vt ka)
- #7 `29100` (ISO standard, no vt ka)
- #3315 `0-day` → alias of `zero day` (pure cross-reference)

`test_akit.py` covers the parser, the scoring tiers, `similar`'s weighting and
the crawl's write paths — stdlib `assert`s, no framework, runs under `uv run
test_akit.py` or pytest. Its fixtures are synthetic markup (real structure,
invented content) because AKIT prose is © Cybernetica and cannot be committed; do
not paste real `<main>` HTML in. Each test was checked by seeding the matching
defect into `akit.py` and confirming the suite fails.

Corpus-wide sanity check over all 16,420 parsed records: 14 have a headword
longer than six words, and all 14 are genuine long official names (ministry
agencies, ISO mechanism names) rather than definition text leaking into the
headword. 22% carry no Estonian definition and 25% no English one (2,564 are
pure `alias_of` stubs) — which is why `similar` has headword-only signal for a
large slice of the lexicon.

The sense-marker rule above was worth 926 Estonian and 902 English definitions
when the mirror was re-parsed: before it, those figures were 27% and 30%. Nothing
else moved — no definition was lost and no other field changed across all 16,420
records, which is the check to repeat after any parser edit (`build` is offline,
so it costs nothing).

## Known gaps

- **Regex, not a parser.** `xml.etree.ElementTree` and `html.parser` are both
  stdlib and would be sturdier than the regexes in `parse_sitemap` /
  `parse_term`; the zero-dependency rule does not force regex here.
- **A cold crawl can still lose a page or two.** Retries make it rare, but
  `update` reports `N failed` and simply omits those terms; the next run refetches
  them because they are missing from the mirror.

---
name: akit-lookup
description: "Use when you need the correct Estonian information-security / data-protection term (or its English equivalent) — translating a term EN↔ET, checking the canonical Estonian word for an infosec concept, or verifying terminology in Estonian technical documents. Backed by a local mirror of AKIT (akit.cyber.ee), Cybernetica's Andmekaitse ja infoturbe leksikon."
---

# AKIT Lookup

**Core principle:** Query a local, offline mirror of AKIT (Cybernetica's English↔Estonian information-security lexicon) to find the *canonical* Estonian term for a concept, instead of guessing a translation.

## When to Use

- You are writing or editing Estonian technical prose and need the accepted term for an infosec / data-protection / IT concept (e.g. "what does AKIT call *replay attack*?").
- You have an English term and want the Estonian equivalent, or vice-versa.
- You know roughly what the term is *about* but not its exact form — use `similar` (see below) to get a ranked shortlist from a phrase, then confirm with `lookup`.
- You want to confirm a term you already used is the one AKIT sanctions (and see its synonyms / related terms).
- Especially for VVKI documentation: AKIT is authored by Cybernetica (same company), so its terminology is the house standard.

This is a **terminology** tool, not a general dictionary. It shines on security/privacy/IT vocabulary sourced from ISO/IEC, ISACA, and EU data-protection texts.

## First Run: Build the Mirror

**The lexicon data is NOT in the repo** — AKIT content is © Cybernetica AS and is not redistributed here. Build your own local mirror once:

```bash
cd <this-skill-dir>
uv run akit.py update            # 16,420 pages, ~20 min, then the index builds itself
```

This writes `akit_raw.jsonl.gz` and `akit.jsonl` next to the script (both gitignored). Every command below fails with `no index at …; run uv run akit.py update first` until you do. Re-run `update` every few months; it refetches only pages whose `<lastmod>` changed.

## The Tool

`akit.py` — a single-file, **zero-dependency** Python 3 script. It carries PEP 723 inline metadata, so `uv run` provisions the interpreter and needs no install step or venv.

```bash
cd <this-skill-dir>            # or use an absolute path to akit.py
uv run akit.py lookup "<query>"
```

### Lookup (the common case)

```bash
uv run akit.py lookup "electronic identity"     # EN or ET, auto-detected
uv run akit.py lookup "e-identiteet" --et        # match Estonian headwords only
uv run akit.py lookup "replay attack" --en       # match English headwords only
uv run akit.py lookup "autentimine" -n 10        # up to 10 hits
uv run akit.py lookup "vahetusrünne" --json      # machine-readable for post-processing
```

Each hit prints: the Estonian headword(s), the English headword(s), the term id/URL on akit.cyber.ee, the Estonian and English definitions, and the "vt ka" (see also) related terms. `--json` emits the full records (including `sources` and `alias_of`).

Matching is tiered and diacritic-tolerant: exact headword → prefix → substring → in-definition → fuzzy (for misspellings). So `"e-identiteet"`, `"eidentiteet"`, and `"electronic identity"` all reach term #12906.

### Search by description (when you don't know the word)

`lookup` needs (roughly) the right word. `similar` widens the net: it ranks every term by how much vocabulary your phrase shares with the term's headwords **and** definitions (TF-IDF cosine, still zero-dependency and fully offline).

```bash
uv run akit.py similar "denial of service attack"                   # → aeglustusrünne, hajus ummistusrünne
uv run akit.py similar "tarkvara mis nouab lunaraha"                # → lunavara (diacritics optional)
uv run akit.py similar "tarkvara mis nouab lunaraha" -n 10 --json   # wider shortlist, machine-readable
```

Each hit shows the usual term block plus `sarnasus NN% · <the query words that drove the match>`. Read it as a ranked shortlist, not a single answer — then `lookup` the winner to confirm.

**It is a term-family finder, not semantic search.** It matches *words*, so it lands well when your phrase already uses terminology-ish vocabulary, and badly when you paraphrase around it. Measured on the current mirror:

| Query | Result |
|-------|--------|
| `denial of service attack` | ✅ `aeglustusrünne` 43%, `hajus ummistusrünne` 41% — right family |
| `tarkvara mis nouab lunaraha` | ✅ `lunavara` 24%, rank 1 |
| `malware that encrypts files and demands payment` | ❌ `malicious software` (#7381, no Estonian headword at all); `lunavara` is not in the top 25 |

That third row is the failure mode to internalize: AKIT's English gloss for `lunavara` says "locking … files" (never "encrypt"), and its Estonian text has `krüpteerimise` / `lunaraha` inflected — so not one query word lands, and a confident-looking wrong term takes the top slot.

- **Prefer Estonian, in base forms.** 25% of terms have no English definition at all, so the Estonian text is the richer target. Diacritics are optional (`nouab` finds `nõuab`), but **matching is by whole word, not by stem** — `krüptogrammiks` will not match `krüptogramm`.
- **Compound terms drift to their head noun — go through English instead.** `similar "kahefaktoriline autentimine"` returns `seadme autentimine` (node authentication) at 52%, because only `autentimine` matched. The real answer is `kaksikautentimine` (#9), and `lookup "two-factor authentication"` finds it exactly. This is the skill's whole point: `kahefaktoriline` is a calque that appears **nowhere** in AKIT, so when your Estonian phrasing drifts, look the English term up rather than refining the Estonian guess.
- **If the top hit looks generic, it probably is.** A parent term ("malware", "attack", "processing") winning usually means none of your words reached the specific term. Retry with different vocabulary rather than trusting rank 1.
- **Scores are relative**, not confidence — 20% can be exactly right. Function words are ignored, and pure `alias_of` redirect stubs are skipped (their target ranks instead).

### Refreshing the mirror

```bash
uv run akit.py update            # re-crawl akit.cyber.ee, then rebuild the index
uv run akit.py build             # rebuild the index from the raw mirror, NO network
```

`update` reads AKIT's `sitemap.xml`, fetches only pages whose `<lastmod>` changed since the last mirror (8 concurrent workers, polite retries), rewrites the raw mirror, and rebuilds the index. A full cold crawl is 16,420 pages (~20 min). If it ends with `N failed`, just run it again — those terms are missing from the mirror, so the next run refetches only them, in seconds. Re-run it every few months to stay current. `build` is instant and offline — use it after editing the parser.

Terms AKIT has retired are pruned only by a full crawl. `--limit N` merges into the existing mirror instead of replacing it, so it is safe for testing. If a full crawl finds the sitemap listing fewer than half the terms you already have, it refuses to prune and exits — that is a site problem, so re-run it later rather than working around it.

## Data Files (generated, gitignored)

Created by `update` in this skill directory. Neither is committed — see First Run above.

| File | Role |
|------|------|
| `akit_raw.jsonl.gz` | Raw `<main>` HTML per term (~4.3 MB) — the "full AKIT, downloaded". Lets `build` re-parse without re-crawling. |
| `akit.jsonl` | The clean, parsed index that `lookup` reads (~10 MB, 16,420 records). One JSON record per term. |

Record shape: `{id, url, lastmod, et[], en[], definition_et, definition_en, related[{id,term}], sources[], alias_of}`. `alias_of` is set for pure cross-reference stubs (e.g. `0-day → zero day`).

## Interpretation

- **Trust the headword, sanity-check the definition.** The EN↔ET headword mapping is reliable. Definitions are scraped as-is from AKIT and may include ISO/Wiktionary phrasing — read them, don't paste blindly.
- **Sense numbers** like `audit trail (1)` / `audit trail (2)` are AKIT's homonym disambiguation — pick the sense that fits your context.
- **Follow "vt ka"** to neighbouring terms when the first hit is close but not exact.
- **No hit?** The query may be too specific or a multiword phrase — retry with the head noun alone, or the English term if you searched Estonian (and vice-versa). If you're not sure of the word at all, switch to `similar "<a sentence describing it>"`.

## Notes

- Fully offline once the mirror exists — only `update` touches the network. Fits the VVKI *vallasrežiim* (disconnected-operation) theme.
- AKIT content © Cybernetica AS. The mirror you build is for terminology reference during Cybernetica/Riigikantselei documentation work — keep it local; do not commit or redistribute the corpus.

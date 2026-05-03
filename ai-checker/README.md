# ai-checker

Multi-engine AI text detection — RoBERTa-large + Desklib DeBERTa-v3 + GPT-2
perplexity + QuillBot + 37 pattern rules — combined into per-sentence risk
tiers (HIGH / MED / LOW) and a doc-level AI/human verdict.

## Install

```bash
uv tool install --editable /path/to/ai-checker
```

The `ai-checker` CLI is then on `PATH`. First run downloads the three local
models (~2.4 GB) into `~/.cache/huggingface/`.

## Usage

```bash
ai-checker file.md                       # all engines, full output
ai-checker file.md --no-quillbot         # offline (no network)
ai-checker file.md --json                # machine-readable to stdout
ai-checker file.md --no-all              # hide LOW-risk, show MED/HIGH only
ai-checker file.md --no-quillbot --no-gpt2  # fast offline
ai-checker --help                        # full options
```

A copy of the per-sentence results is also written to
`<tempdir>/ai-checker-results-<pid>.json` for post-processing.

## Architecture

`main.py` is a single-file module with three model-backed engines (each exposes
`score(text)` and `score_batch(texts)`), a regex `pattern_score`, and a
`combined_risk` tier function. `analyze(text, engines)` is the library entry
point; `main()` is the CLI.

## Tests

```bash
uv sync --extra dev
uv run pytest -q
```

Tests cover the pure-Python paths (`pattern_score`, `combined_risk`,
`doc_predict`, `_chunk_by_sentences`, CLI parser). Model code is exercised by
the `ai-checker` end-to-end run.

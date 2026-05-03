---
name: ai-checker
description: "Use when the user wants to detect whether text was AI-generated, run an AI detector on a document, audit for AI patterns, or verify human authorship"
---

# AI Checker

**Core principle:** Run independent detectors over the text, combine their signals into a per-sentence risk tier (HIGH / MED / LOW), and report what reads as AI-generated.

## When to Use

The user wants to:

- Check if a document, draft, or report was written by AI
- Audit a deliverable for AI-flavored sentences before submission
- Locate AI-generated passages inside a longer human-written doc
- Compare originality across two pieces of text

## Bundled Tool

`ai-checker` is a uv tool at the root of this repo (sibling to `skills/`).

| Path | Role |
|------|------|
| `ai-checker/main.py` | Single-file source, all engines |
| `ai-checker/pyproject.toml` | Hatchling build, `ai-checker = "main:main"` entry point |
| `ai-checker/uv.lock` | Pinned dep versions |

Installed as a uv tool from the source directory in editable mode — once installed, edits to `main.py` are picked up live. The Workflow below auto-installs on first use if `ai-checker` isn't already on PATH, so no separate setup step is required.

Manual install (if you prefer to set it up ahead of time):

```bash
uv tool install --editable <superpowers-root>/ai-checker
```

`<superpowers-root>` is the directory two levels above this `SKILL.md` (resolve `../../ai-checker` from `skills/ai-checker/SKILL.md`).

Do not fall back to `python main.py` — torch and transformers won't be in an arbitrary project environment.

Reinstall is only required when `pyproject.toml` changes (new dependency, version bump, entry-point rename). Code changes to `main.py` take effect on the next invocation.

## Engines

Patterns run unconditionally. Four engines run by default; opt out with `--no-*`:

| Flag | Engine | What it sees |
|------|--------|--------------|
| `--no-roberta` | RoBERTa (`roberta-large-openai-detector`) | GPT-2-era text patterns |
| `--no-desklib` | Desklib DeBERTa-v3-large | Modern LLM output |
| `--no-gpt2` | GPT-2 perplexity | Token predictability |
| `--no-quillbot` | QuillBot API (network) | Their AI/AI-paraphrased classifier |

First run downloads RoBERTa (~500 MB), Desklib (~1.4 GB), GPT-2 (~500 MB) into `~/.cache/huggingface/`. Subsequent runs are cache-only.

## Invocation

```bash
ai-checker file.md                      # all engines, full output
ai-checker file.md --no-quillbot        # offline (no network)
ai-checker file.md --json               # machine-readable to stdout
ai-checker file.md --no-all             # hide LOW-risk, show MED/HIGH only
ai-checker file.md --no-quillbot --no-gpt2   # fast offline (~3x quicker)
```

Every run also writes `/tmp/ai-checker-results.json` regardless of `--json`. Read that file for post-processing rather than re-parsing stdout.

## Output Format

Per-sentence rows:

```
RISK   Rob   DL   G2   Pat  QB             SENTENCE
HIGH   78%   82%   16%  3   AI       91%   The framework establishes the criteria... <<<< FLAG
MED    52%   48%    9%  2   HUMAN    18%   For each phase, the team verifies... << warn
```

Followed by a summary line with HIGH / MED / LOW counts and engine averages.

## Interpretation

| Pattern | Read |
|---------|------|
| Single HIGH in a long doc | Likely a quoted/templated sentence — note, don't conclude |
| Many HIGHs clustered | AI-generated paragraph |
| Mostly MED, few HIGH | Human text edited or paraphrased by AI |
| Mostly LOW, low engine avgs | Human-written |
| QuillBot type `AI-PARAPHRASED` | Strongest single signal of LLM rewrite |

When reporting findings, quote the flagged sentences with their `pat_hits` so the user can verify, rather than just citing percentages.

## Performance

| Engines on | M-series Mac (MPS) | CPU |
|------------|--------------------|-----|
| All four | ~1–3 s/sentence | ~5–10 s/sentence |
| `--no-quillbot --no-gpt2` | ~0.5 s/sentence | ~2 s/sentence |
| RoBERTa only | ~0.2 s/sentence | ~1 s/sentence |

For a 200-sentence document with all engines, expect 5–10 minutes wall clock plus model downloads on first run. Quote the wait estimate to the user before kicking off long runs.

## Workflow

1. **Pre-flight health check** (one-time install if needed). Run ai-checker with no args and confirm it prints its usage banner — this proves it's on PATH *and* the venv loads (torch + transformers import without error). If the check fails, install editable and retry:

   ```bash
   ai-checker 2>&1 | head -1 | grep -q "^Usage:" \
     || { uv tool install --editable <superpowers-root>/ai-checker \
          && ai-checker 2>&1 | head -1 | grep -q "^Usage:"; }
   ```

   `<superpowers-root>` is the directory two levels above this `SKILL.md`. After the first successful run, the smoke test is a ~3 s no-op (torch import dominates). The `--editable` flag means future edits to `ai-checker/main.py` are picked up without reinstalling. If the post-install smoke test still fails, stop and report the error to the user — don't proceed to step 2.

2. Confirm the input file path and ask if speed > thoroughness (offer `--no-quillbot --no-gpt2` if speed wins)
3. Run `ai-checker <path>` with the chosen flags
4. Parse `/tmp/ai-checker-results.json` for the structured view
5. Report: total sentences, HIGH count, MED count, top 5 most suspicious sentences with their `pat_hits`
6. Give a verdict (`likely AI` / `mixed / paraphrased` / `likely human`) tied to the heuristics above — don't just dump numbers

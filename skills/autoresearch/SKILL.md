---
name: autoresearch
description: "Use when the user wants to autonomously optimize a measurable metric through iterative code experiments"
---

# Autoresearch

## Overview

One-shot optimization rarely works. Guessing at improvements without measurement wastes time.

**Core principle:** The ratchet pattern -- modify code, measure metric, keep improvements, discard failures, repeat autonomously. Progress only moves forward.

## When to Use

- User wants autonomous experiments to improve a measurable metric
- Overnight optimization loops (user may be asleep)
- Iterative code changes where each attempt is measured against a baseline

## Companion Modules

This skill has companion files in this directory. Load them on demand, not upfront:

| Module | When to read |
|--------|-------------|
| `strategy-engine.md` | At experiment 1, re-read every 10 experiments or after 3 consecutive failures |
| `parallel-runner.md` | Only when parallelism > 1 |
| `resilience.md` | Before any long autonomous run, or when context feels large |
| `multi-metric.md` | Only when setup declares secondary metrics |

## Setup Phase

Collect parameters through conversation before starting:

| Parameter | What it defines | Example |
|-----------|----------------|---------|
| **Metric** | Name + direction (lower/higher is better) | `val_bpb`, lower is better |
| **Mutable files** | Files the agent may edit | `train.py` |
| **Read-only files** | Files to read for context but never modify | `prepare.py` |
| **Run command** | How to execute one experiment | `uv run train.py` |
| **Extract command** | Shell command that outputs a single numeric value | `grep "^val_bpb:" run.log \| awk '{print $2}'` |
| **Time budget** | Expected wall-clock duration per experiment (kill at 2x) | 10 min |
| **Secondary metrics** | *(optional)* Additional metrics with constraints | `memory_gb < 32, latency_ms` |
| **Parallelism** | *(optional)* Max concurrent experiments, default 1 | `3` |

**Steps:**

1. Ask user what to optimize, collect the parameters above
2. Read all mutable and read-only files for context
3. Agree on a run tag (date-based). If branch `autoresearch/<tag>` exists, pick a different tag
4. Create branch from current main
5. Run baseline. If baseline crashes, debug and fix before proceeding
6. Initialize `results.tsv` with header and baseline row
7. Create `autoresearch-state.json` checkpoint:
   ```json
   {
     "schema_version": 2,
     "branch": "autoresearch/<tag>",
     "baseline_commit": "<hash>",
     "last_kept_commit": "<hash>",
     "params": { ... },
     "experiment_count": 0,
     "strategy_notes": []
   }
   ```
8. If secondary metrics declared, read `multi-metric.md`
9. Read `strategy-engine.md` for experiment planning guidance
10. Confirm setup summary, then enter the experiment loop

**Shortcut:** If user references a known config like `autoresearch-mlx/program.md`, infer parameters from it.

## Experiment Loop

1. Read current state (mutable files + `results.tsv` + `autoresearch-state.json`)
2. Consult `strategy-engine.md` categories to pick next experiment. Tag the description: `[param]`, `[arch]`, `[simplify]`, `[combo]`, or `[radical]`
3. Check `results.tsv` for prior attempts with the same tag + similar parameter — skip repeats
4. **If parallelism > 1**: read `parallel-runner.md`, dispatch batch, collect results, apply best-of-batch
5. **If parallelism == 1** (default):
   a. Apply ONE focused change to mutable files
   b. `git add <mutable files> && git commit -m "experiment: [tag] <description>"`
   c. Run: `<run command> > run.log 2>&1` (redirect all output, never flood context)
   d. Extract primary metric: `<extract command>`
   e. Extract secondary metrics (if declared)
   f. Empty output = crash. `tail -n 50 run.log`, fix if trivial, else log crash and move on
6. Check hard constraints on secondary metrics — any violation = auto-discard
7. Record result in `results.tsv`
8. If metric **improved** (and constraints pass):
   - `git add results.tsv autoresearch-state.json && git commit --amend --no-edit`
   - Update `autoresearch-state.json`: set `last_kept_commit`, increment `experiment_count`
9. If metric **equal or worse** (or constraint violation):
   - a. Note the last kept commit hash from `autoresearch-state.json`
   - b. `git add results.tsv autoresearch-state.json && git commit --amend --no-edit` (saves discard record)
   - c. `git stash -- results.tsv autoresearch-state.json` (preserve tracking files across reset)
   - d. `git reset --hard <last kept commit>`
   - e. `git stash pop` (restore tracking files with all rows including the discard)
   - f. `git add results.tsv autoresearch-state.json && git commit --amend --no-edit`
   - g. Increment `experiment_count` in `autoresearch-state.json`
10. Every 10 experiments: append strategy notes to `autoresearch-state.json` (what worked, what didn't, what to try next)
11. **REPEAT** -- never stop, never ask

## Compaction Recovery

After any context compression, BEFORE proposing the next experiment:

1. Re-read `results.tsv` to reconstruct experiment history
2. Re-read `autoresearch-state.json` for strategy context and parameters
3. Re-read current mutable files to see present code state
4. Continue the loop from where you left off

## Resume Protocol

When a user says "resume autoresearch" in a new session:

1. Look for `autoresearch-state.json` in the working directory
2. If found, read it + `results.tsv`
3. Confirm: "Found autoresearch state on branch `[branch]`, [N] experiments run, best metric [X]. Resume?"
4. If yes: checkout the branch, verify last kept commit exists, re-enter the loop
5. If not found: start fresh setup

## Results Tracking

TSV format. Category tags in descriptions enable anti-repeat logic:

```
commit	metric	status	description
a1b2c3d	2.667	keep	[param] baseline
d4e5f6g	2.588	keep	[param] halve batch size
h7i8j9k	2.590	discard	[arch] add extra layer
```

If secondary metrics are declared, extra columns go between `metric` and `status`.

## Constraints

- Only edit mutable files declared in setup
- No new dependencies without user approval
- Never use `git add -A` -- only add declared mutable files + tracking files
- Always redirect run output to `run.log`

## Simplicity Criterion

Simpler is better at equal performance. Removing complexity while maintaining the same metric = a win. Prefer deletions over additions when results are equivalent.

## Timeout and Crash Handling

- Kill experiments that exceed 2x the time budget
- Trivial crashes (typos, import errors): fix immediately
- Broken ideas that crash: log with `crash` status and move on
- 3+ consecutive crashes: re-read `strategy-engine.md`, re-read all code, switch to a different experiment category

## Autonomy

Never stop. Never ask. The user may be asleep.

If out of ideas:
- Re-read all mutable and read-only files
- Re-read `strategy-engine.md` for category rotation guidance
- Review full results history for patterns
- Combine near-miss improvements (`[combo]` category)
- Try radical or unconventional changes (`[radical]` category)

## Related Skills

- **superpowers:using-git-worktrees** -- Isolate experiment work from main workspace
- **superpowers:verification-before-completion** -- Verify results before claiming success

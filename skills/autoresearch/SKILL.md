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

## Setup Phase

Collect 6 parameters through conversation before starting:

| Parameter | What it defines | Example |
|-----------|----------------|---------|
| **Metric** | Name + direction (lower/higher is better) | `val_bpb`, lower is better |
| **Mutable files** | Files the agent may edit | `train.py` |
| **Read-only files** | Files to read for context but never modify | `prepare.py` |
| **Run command** | How to execute one experiment | `uv run train.py` |
| **Extract command** | Shell command that outputs a single numeric value | `grep "^val_bpb:" run.log \| awk '{print $2}'` |
| **Time budget** | Expected wall-clock duration per experiment (kill at 2x) | 7 min |

**Steps:**

1. Ask user what to optimize, collect the 6 parameters
2. Read all mutable and read-only files for context
3. Agree on a run tag (date-based). If branch `autoresearch/<tag>` exists, pick a different tag
4. Create branch from current main
5. Run baseline. If baseline crashes, debug and fix before proceeding
6. Initialize `results.tsv` with header and baseline row
7. Confirm setup summary, then enter the experiment loop

**Shortcut:** If user references a known config like `autoresearch-mlx/program.md`, infer parameters from it.

## Experiment Loop

Repeat indefinitely:

1. Read current state (mutable files + results history)
2. Propose ONE focused change
3. `git add <mutable files> && git commit -m "experiment: <description>"`
4. Run: `<run command> > run.log 2>&1` (redirect all output, never flood context)
5. Extract metric: `<extract command>`
6. Empty output = crash. `tail -n 50 run.log`, fix if trivial, else log crash and move on
7. Record result in `results.tsv`
8. If metric **improved**:
   - `git add results.tsv && git commit --amend --no-edit`
9. If metric **equal or worse**:
   - a. Note the last kept commit hash from `results.tsv`
   - b. `git add results.tsv && git commit --amend --no-edit` (saves discard record)
   - c. `git stash -- results.tsv` (preserve the updated TSV across reset)
   - d. `git reset --hard <last kept commit>`
   - e. `git stash pop` (restore results.tsv with all rows including the discard)
   - f. `git add results.tsv && git commit --amend --no-edit` (update the kept commit with full history)
10. REPEAT -- never stop, never ask

## Results Tracking

TSV format with 4 core columns:

```
commit	metric	status	description
```

Optional extra columns for secondary metrics go between `metric` and `status`. Crashes use `crash` status.

## Constraints

- Only edit mutable files declared in setup
- No new dependencies without user approval
- Never use `git add -A` -- only add declared mutable files
- Always redirect run output to `run.log`

## Simplicity Criterion

Simpler is better at equal performance. Removing complexity while maintaining the same metric = a win. Prefer deletions over additions when results are equivalent.

## Timeout and Crash Handling

- Kill experiments that exceed 2x the time budget
- Trivial crashes (typos, import errors): fix immediately
- Broken ideas that crash: log with `crash` status and move on
- 3+ consecutive crashes: pause the loop, re-read all code, reassess strategy

## Autonomy

Never stop. Never ask. The user may be asleep.

If out of ideas:
- Re-read all mutable and read-only files
- Review full results history for patterns
- Combine near-miss improvements
- Try radical or unconventional changes

## Related Skills

- **superpowers:using-git-worktrees** -- Isolate experiment work from main workspace
- **superpowers:verification-before-completion** -- Verify results before claiming success

---
name: autoresearch
description: "Use when the user wants to autonomously optimize a measurable metric through iterative code experiments"
---

# Autoresearch

**Core principle:** The ratchet pattern -- modify code, measure metric, keep improvements, discard failures, repeat autonomously. Progress only moves forward.

## Companion Modules

Load on demand, not upfront:

| Module | When to read |
|--------|-------------|
| `strategy-engine.md` | At experiment 1, re-read every 10 experiments or after 5 consecutive discards |
| `parallel-runner.md` | Only when parallelism > 1 |
| `resilience.md` | Before any long autonomous run, or after context compression |
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
7. Create `autoresearch-state.json` with fields: `schema_version`, `branch`, `baseline_commit`, `last_kept_commit`, `params` (all 8 parameters), `experiment_count: 0`, `strategy_notes: []`
8. Confirm setup summary, then enter the experiment loop

**Shortcut:** If user references a known config like `autoresearch-mlx/program.md`, infer parameters from it.

## Experiment Loop

1. Read current state (mutable files + `results.tsv` + `autoresearch-state.json`)
2. Consult `strategy-engine.md` categories to pick next experiment. Tag: `[param]`, `[arch]`, `[simplify]`, `[combo]`, or `[radical]`
3. Check `results.tsv` for prior attempts with the same tag + similar parameter -- skip repeats
4. **If parallelism > 1**: read `parallel-runner.md`, dispatch batch, collect results, apply best-of-batch
5. **If parallelism == 1** (default):
   a. Apply ONE focused change to mutable files
   b. `git add <mutable files> && git commit -m "experiment: [tag] <description>"`
   c. Run: `timeout $((TIME_BUDGET * 120)) <run command> > run.log 2>&1` (kill at 2x budget)
   d. Extract primary metric: `<extract command>`
   e. Extract secondary metrics (if declared)
   f. Empty output = crash. `tail -n 50 run.log`, fix if trivial (one attempt only), else log crash and move on
6. Check hard constraints on secondary metrics -- any violation = auto-discard
7. Record result in `results.tsv`
8. If metric **improved** (and constraints pass):
   - Update `autoresearch-state.json`: set `last_kept_commit`, increment `experiment_count`
   - `git add results.tsv autoresearch-state.json && git commit --amend --no-edit`
9. If metric **equal or worse** (or constraint violation):
   - a. Note `last_kept_commit` from `autoresearch-state.json`
   - b. Increment `experiment_count` in `autoresearch-state.json`
   - c. `git stash -- results.tsv autoresearch-state.json`
   - d. `git reset --hard <last kept commit>`
   - e. `git stash pop`
   - f. `git add results.tsv autoresearch-state.json && git commit --amend --no-edit`
10. Every 10 experiments: append strategy notes to `autoresearch-state.json` (see `strategy-engine.md`)
11. **REPEAT** -- never stop, never ask

## Compaction and Resume

After context compression: re-read `autoresearch-state.json`, `results.tsv`, and mutable files before continuing. See `resilience.md` for full recovery procedure.

To resume in a new session: follow the Manual Resume protocol in `resilience.md`.

## Results Tracking

TSV format with category-tagged descriptions:

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

## Timeout and Crash Handling

- Wrap run command with `timeout` at 2x the time budget in seconds
- Trivial crashes (typos, import errors): one fix attempt, then log crash
- Broken ideas that crash: log with `crash` status and move on
- 3+ consecutive crashes: follow crash protocol in `strategy-engine.md`

## Autonomy

Never stop. Never ask. The user may be asleep.

If out of ideas: follow plateau detection in `strategy-engine.md`.

# Autoresearch v2 Design: Strategy, Parallelism, Resilience, Multi-Metric

> **Supersedes** `2026-03-30-autoresearch-skill-design.md` for all new modules. The core ratchet pattern from v1 remains unchanged — v2 adds modules around it.

## Problem

The current autoresearch skill (v1) works but has significant limitations:

1. **No strategic memory** — each experiment is proposed in isolation, leading to repetitive or aimless experimentation after many iterations
2. **Single-threaded** — experiments run sequentially even when the run command is fast enough to batch
3. **Fragile across compaction** — the model loses experiment context when auto-compaction fires, with no explicit recovery protocol
4. **Single metric** — no way to track or constrain secondary metrics (memory, latency, code size)
5. **No cross-session resume** — if the session ends, all loop state is lost

## Solution

Evolve autoresearch from a single SKILL.md into a modular skill with four companion reference files. The main SKILL.md stays the entry point and orchestration loop. Companion modules are loaded on demand to keep context lean.

## Module Structure

```
skills/autoresearch/
  SKILL.md                — Setup phase + orchestration loop (streamlined)
  strategy-engine.md      — Experiment planning, pattern recognition, anti-repeat logic
  parallel-runner.md      — Worktree-based batch dispatch with self-contained worker prompts
  resilience.md           — Within-session checkpointing, compaction survival, manual resume
  multi-metric.md         — Constraint-based optimization, secondary metric tracking
```

### Loading Strategy

SKILL.md always loads. Other modules are read on demand:

| Module | When to load |
|--------|-------------|
| `strategy-engine.md` | At experiment 1, then re-read every 10 experiments or after 3 consecutive failures |
| `parallel-runner.md` | Only when parallelism > 1 (user opt-in or auto-detected for fast experiments) |
| `resilience.md` | When context usage exceeds 50%, or before any long autonomous run |
| `multi-metric.md` | Only when setup declares 2+ metrics |

This pattern is validated against Claude Code's skill system: disk-based skills receive `Base directory for this skill: <absolute-path>` and can Read companion files on demand. Other superpowers skills (brainstorming, debugging, subagent-driven-development) already use this pattern.

## Setup Phase (Revised)

Setup collects **8 parameters** — the original 6 plus 2 new optional ones:

| Parameter | What it defines | Example |
|-----------|----------------|---------|
| **Metric** | Name + direction (lower/higher is better) | `val_bpb`, lower is better |
| **Mutable files** | Files the agent may edit | `train.py` |
| **Read-only files** | Files to read for context but never modify | `prepare.py` |
| **Run command** | How to execute one experiment | `uv run train.py` |
| **Extract command** | Shell command that outputs a single numeric value | `grep "^val_bpb:" run.log \| awk '{print $2}'` |
| **Time budget** | Expected wall-clock duration per experiment (kill at 2x) | 10 min |
| **Secondary metrics** | *(optional)* Additional metrics with optional constraints | `memory_gb < 32, latency_ms` |
| **Parallelism** | *(optional)* Max concurrent experiments, default 1 | `3` |

Setup steps (unchanged from v1, plus checkpoint creation):

1. Ask the user what they want to optimize and collect parameters
2. Read all mutable and read-only files for context
3. Agree on a run tag (date-based). If branch `autoresearch/<tag>` exists, pick a different tag
4. Create branch from current main
5. Run baseline. If baseline crashes, debug and fix before proceeding
6. Initialize `results.tsv` with header and baseline row
7. Create `autoresearch-state.json` checkpoint file
8. Confirm setup summary, then enter the experiment loop

Shortcut: if user references a known config like `autoresearch-mlx/program.md`, infer parameters from it.

### Checkpoint File

Created alongside `results.tsv` during setup:

```json
{
  "schema_version": 2,
  "branch": "autoresearch/2026-04-01",
  "baseline_commit": "abc123",
  "last_kept_commit": "abc123",
  "params": {
    "metric": "val_bpb",
    "direction": "lower",
    "mutable_files": ["train.py"],
    "readonly_files": ["prepare.py"],
    "run_command": "uv run train.py",
    "extract_command": "grep '^val_bpb:' run.log | awk '{print $2}'",
    "time_budget_min": 10,
    "secondary_metrics": [],
    "parallelism": 1
  },
  "experiment_count": 0,
  "strategy_notes": []
}
```

This file is the resume anchor — if a user starts a new session and says "resume autoresearch", the skill reads this file and picks up where it left off.

## Strategy Engine (`strategy-engine.md`)

### Experiment Categories

Experiments are proposed from categories tried in rotation, not randomly:

1. **`[param]` Numeric parameter sweeps** — systematic variation of numeric values, thresholds, or configuration constants
2. **`[arch]` Structural changes** — add/remove/swap components, algorithms, data structures, or processing stages
3. **`[simplify]` Simplification** — delete code, reduce complexity while maintaining metric
4. **`[combo]` Combination** — merge two near-miss improvements that individually didn't beat baseline
5. **`[radical]` Radical** — try something unconventional when incremental changes plateau

### Anti-Repeat Logic

Before proposing an experiment, check `results.tsv` for prior attempts at the same change. Each experiment description must include a category tag from the five categories:

```
[param] halve batch size
[arch] remove attention layer
[simplify] delete unused normalization
[combo] merge reduced-depth + higher-lr
[radical] switch optimizer to SGD
```

The anti-repeat check filters by category + key parameter name, not free-text similarity. This is robust across compaction boundaries where the model may lose nuanced context about what was tried.

### Plateau Detection

If the last 5 experiments are all `discard`:

1. Re-read all mutable + read-only files from scratch
2. Switch to a different category (e.g., if stuck on hyperparameters, try architectural)
3. Consider reverting to an earlier kept state and branching differently
4. Re-read `strategy-engine.md` for fresh approach inspiration

### Strategy Notes

After each batch of 10 experiments, append a short strategy summary to `autoresearch-state.json`:

- What categories have been tried
- Which approaches showed promise (near-misses)
- What to try next
- Any patterns observed (e.g., "smaller models consistently outperform larger ones here")

These survive compaction since they're on disk.

## Parallel Runner (`parallel-runner.md`)

### When Parallelism Activates

- User sets `parallelism > 1` during setup, OR
- Experiments are fast (< 2 minutes each) and the skill auto-suggests batching

### Batch Dispatch Cycle

1. Orchestrator reads current state (`results.tsv` + mutable files)
2. Strategy engine proposes N experiments (one per worker slot)
3. For each experiment, orchestrator builds a **self-contained worker prompt**:
   ```
   You are an autoresearch worker. Your ONLY job:
   1. Apply this specific code change: [exact diff description]
   2. Run: [run command] > run.log 2>&1
   3. Extract metric: [extract command]
   4. Report: "RESULT: metric=[value] status=[keep/discard/crash] desc=[what you did]"
   Do NOT propose new experiments. Do NOT modify anything beyond the described change.
   Mutable files: [list with full paths]
   Current best metric: [value]
   ```
4. Dispatch all N workers: `Agent(isolation: "worktree", run_in_background: true)`
5. Wait for all notifications (Claude Code batches these)
6. Parse results from each worker's final message
7. **Best-of-batch**: keep only the single best improvement (if any beat current best)
8. Apply the winning change to the main branch, update `results.tsv` with all rows (including discards)
9. Repeat from step 1

### Why Best-of-Batch, Not Keep-All

Parallel experiments diverge from the same base commit. Two independent code changes cannot be safely merged — they may conflict or interact in unexpected ways. Pick the single winner, discard the rest, then the next batch starts from the new best.

### Worker Design Constraints

Workers must be completely self-contained because non-fork sub-agents in Claude Code receive only the prompt, not the parent's conversation context. Every worker prompt must include:

- The exact code change to apply (not "try something interesting")
- All file paths (absolute)
- The run and extract commands
- The current best metric value for comparison
- Clear reporting format

### Worker Failure Handling

- Worker crashes or times out → result is `crash`, orchestrator continues with other workers
- All N workers crash → fall back to sequential mode for one debugging iteration
- Worker reports nonsensical metric (NaN, negative where impossible) → treat as crash

## Resilience (`resilience.md`)

### Within-Session Checkpointing

`autoresearch-state.json` is updated after every experiment:

- `last_kept_commit` — updated on each `keep`
- `experiment_count` — incremented every iteration
- `strategy_notes` — appended every 10 experiments

`results.tsv` remains the metric source of truth (one row per experiment, always on disk).

### Compaction Survival

Verified against Claude Code source: after auto-compaction (~187K tokens), the runtime re-attaches invoked skill content via `createSkillAttachmentIfNeeded()`. The model retains awareness that autoresearch is active.

Post-compaction recovery instruction (added to SKILL.md):

> After any context compression, BEFORE proposing the next experiment:
> 1. Re-read `results.tsv` to reconstruct experiment history
> 2. Re-read `autoresearch-state.json` for strategy context
> 3. Re-read current mutable files to see present code state
> 4. Continue the loop from where you left off

### Manual Resume Protocol

When a user starts a new session and says "resume autoresearch":

1. Look for `autoresearch-state.json` in the working directory
2. If found, read it + `results.tsv`
3. Confirm with user: "Found autoresearch state on branch `[branch]`, [N] experiments run, best metric [X]. Resume?"
4. If yes: checkout the branch, verify last kept commit exists, re-enter the loop
5. If state file not found: start fresh setup

Cross-session resume is NOT automatic. Durable crons in Claude Code fire into existing sessions only and cannot spawn new ones. The user must manually start a new session and request resume.

### Graceful Degradation

If something goes wrong mid-loop (git state corrupted, branch deleted, unexpected files):

1. Read `autoresearch-state.json` for `last_kept_commit`
2. Read `results.tsv` for full experiment history
3. Verify that commit exists: `git cat-file -t <hash>`
4. If it exists: `git stash -- results.tsv autoresearch-state.json`, then `git reset --hard <hash>`, then `git stash pop` to restore tracking files
5. If the commit doesn't exist: alert the user — this requires manual intervention
6. If tracking files are also missing: reconstruct from `git log --oneline` on the autoresearch branch, create fresh `results.tsv` from commit messages, and continue

## Multi-Metric (`multi-metric.md`)

### Setup

User declares secondary metrics with optional constraints during the setup phase:

```
Secondary metrics: memory_gb < 32, latency_p99
```

- `memory_gb < 32` = **hard constraint** — violating this auto-discards regardless of primary metric improvement
- `latency_p99` = **tracked only** — informational, shown in results but doesn't drive keep/discard

Each secondary metric requires its own extract command, collected during setup.

### Results.tsv Expansion

Secondary columns go between the primary metric and status columns:

```
commit	val_bpb	memory_gb	latency_p99	status	description
a1b2c3d	2.667	26.9	45.2	keep	baseline
d4e5f6g	2.550	33.1	42.0	discard	constraint: memory_gb > 32
h7i8j9k	2.520	25.0	44.8	keep	reduce depth to 4
```

### Extended Keep/Discard Logic

1. **Check hard constraints first** — any violation = `discard` with reason in description
2. **If constraints pass** — check primary metric as before (improved = keep, else discard)
3. **Pareto note** — if an experiment significantly improves a secondary metric while being equal on primary, add a `pareto-candidate` tag to the description for future reference by the strategy engine

### Scope Limitation

This module does NOT implement full Pareto optimization. It adds constraint checking and richer tracking. The primary metric still drives keep/discard decisions. This keeps the decision logic simple and predictable.

## Experiment Loop (Revised)

The core loop in SKILL.md is updated to integrate all modules:

1. Read current state (mutable files + `results.tsv` + `autoresearch-state.json`)
2. Consult strategy engine for next experiment(s)
3. **If parallelism > 1**: read `parallel-runner.md`, dispatch batch, collect results, apply best
4. **If parallelism == 1**: apply change, commit, run, extract (same as v1)
5. Extract all metrics (primary + secondary)
6. Check constraints (if multi-metric)
7. Keep/discard decision
8. Update `results.tsv` and `autoresearch-state.json`
9. Every 10 experiments: update strategy notes
10. **REPEAT** — never stop, never ask

## What This Skill Does NOT Do

- Does not hardcode any domain (ML, performance, build times, etc.)
- Does not include hyperparameter tables or experiment idea lists
- Does not promise automatic cross-session resume (manual only)
- Does not implement full Pareto optimization (constraint-based only)
- Does not merge parallel experiment results (best-of-batch only)

## Testing

The skill is markdown instructions — it cannot be unit tested. Validation:

1. Invoke the skill and verify setup collects all 8 parameters (6 required + 2 optional)
2. Run sequential experiments on `autoresearch-mlx/` — verify the loop, strategy rotation, and plateau detection
3. Run with `parallelism: 2` — verify workers dispatch to worktrees and best-of-batch works
4. Run until compaction fires — verify post-compaction recovery reads state from disk
5. End a session, start a new one, say "resume autoresearch" — verify manual resume reads checkpoint
6. Declare a hard constraint on a secondary metric — verify constraint violations are auto-discarded
7. Try on a non-ML problem (e.g., optimizing a benchmark script) — verify domain-agnosticism

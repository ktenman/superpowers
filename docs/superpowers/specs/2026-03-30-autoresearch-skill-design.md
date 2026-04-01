# Autoresearch Skill Design

## Problem

The autonomous experiment ratchet pattern — loop through changes, measure a metric, keep improvements, discard failures — is powerful but has no reusable skill. Users must manually set up the loop each time, and existing implementations (like autoresearch-mlx) hardcode domain-specific details.

## Solution

A generic `superpowers:autoresearch` skill that applies the experiment ratchet to any problem. The skill is parametric: on invocation, the agent works with the user to define what to measure, what to modify, and how to run experiments. The loop itself is domain-agnostic.

## Skill Structure

```
skills/autoresearch/
  SKILL.md          # The skill definition
```

Bundled example (already in repo):
```
autoresearch-mlx/   # Ready-to-use MLX experiment target
```

## SKILL.md Design

### Frontmatter

```yaml
name: autoresearch
description: "Use when the user wants to autonomously optimize a measurable metric through iterative code experiments"
```

### Setup Phase

When invoked, the agent collects 6 parameters through conversation with the user:

| Parameter | What it defines | Example |
|-----------|----------------|---------|
| **Metric** | Name + direction (lower/higher is better) | `val_bpb`, lower is better |
| **Mutable files** | Files the agent may edit | `train.py` |
| **Read-only files** | Files to read for context but never modify | `prepare.py` |
| **Run command** | How to execute one experiment | `uv run train.py` |
| **Extract command** | Shell command that outputs a single numeric value | `grep "^val_bpb:" run.log \| awk '{print $2}'` |
| **Time budget** | Expected wall-clock duration per experiment (kill at 2x) | 7 min |

Steps:
1. Ask the user what they want to optimize and collect the 6 parameters
2. Read all mutable and read-only files for context
3. Agree on a run tag (e.g. date-based). If branch `autoresearch/<tag>` already exists, pick a different tag.
4. Create the branch from current main
5. Run baseline experiment. If the baseline crashes, debug and fix before proceeding — there is no loop without a working baseline.
6. Initialize `results.tsv` with header and baseline entry
7. Confirm setup, then enter the loop

If the user says "run autoresearch on autoresearch-mlx" or similar, the agent can infer the parameters from `autoresearch-mlx/program.md` instead of asking.

### Experiment Loop

The core ratchet, identical for every domain:

1. Read current state (mutable files + results history)
2. Propose ONE focused change to the mutable files
3. `git add <mutable files> && git commit -m "experiment: <description>"`
4. Run: `<run command> > run.log 2>&1` (always redirect, never flood context)
5. Extract metric: `<extract command>`
6. If empty output → crash. Read `tail -n 50 run.log`, attempt fix if trivial, else log as crash and move on.
7. Record result in `results.tsv`
8. If metric **improved** → `git add results.tsv && git commit --amend --no-edit` (advance branch)
9. If metric **equal or worse** → record discard, then `git reset --hard <previous kept commit>` (always verify the target hash from `results.tsv` before resetting)
10. **REPEAT** — never stop, never ask the user if you should continue

### Results Tracking

Tab-separated `results.tsv`. The core columns are fixed; domains may add extra columns after `metric` (e.g. `memory_gb` for ML experiments):

```
commit	metric	status	description
a1b2c3d	2.667000	keep	baseline
d4e5f6g	2.588904	keep	halve batch size
h7i8j9k	2.590000	discard	try larger model
```

Core columns:
1. Git commit hash (short, 7 chars)
2. Primary metric value. For crashes, use the `crash` status to identify them (metric value is irrelevant for crashed runs — use `0` or leave empty).
3. Status: `keep`, `discard`, or `crash`
4. Short description of what the experiment tried

Optional extra columns (between metric and status) may be added during setup if the domain has secondary metrics worth tracking (e.g. `memory_gb`, `throughput`).

### Constraints

- Only modify files declared as mutable — never touch read-only files
- No new dependencies unless the user explicitly allows it
- Never use `git add -A` — always stage specific files
- Redirect all run output to `run.log` — never let it flood agent context

### Simplicity Criterion

Applies universally regardless of domain:
- All else equal, simpler is better
- Removing code for equal/better results is a great outcome
- Small improvement + ugly complexity = probably not worth it
- Small improvement from deleting code = definitely keep

### Timeout and Crash Handling

- If a run exceeds 2x the time budget, kill it and treat as failure
- Crashes from trivial bugs (typo, missing import): fix and re-run
- Crashes from fundamentally broken ideas: log as crash, move on
- After 3+ consecutive crashes, pause and re-read the code before continuing

### Autonomy

Once the loop begins:
- Do NOT pause to ask the user if you should continue
- Do NOT ask "should I keep going?" or "is this a good stopping point?"
- The user may be asleep or away — they expect experiments to run indefinitely
- If running out of ideas: re-read the code, review results history, try combining near-misses, try radical changes
- Loop runs until the user interrupts

### Bundled Example

The repo includes `autoresearch-mlx/` as a ready-to-use experiment target for ML training on Apple Silicon. When the user asks to run autoresearch on MLX training, the agent can read `autoresearch-mlx/program.md` to auto-configure the setup parameters. The skill does not depend on this directory existing — it is purely a convenience.

### Related Skills

- `superpowers:using-git-worktrees` — for isolating experiment branches
- `superpowers:verification-before-completion` — for verifying final results before reporting

## What This Skill Does NOT Do

- Does not hardcode any domain (ML, performance, etc.)
- Does not hardcode file names, metrics, or run commands
- Does not include hyperparameter tables or experiment idea lists (the agent derives these from reading the actual code)
- Does not duplicate content from domain-specific instruction files like `program.md`

## Testing

The skill is a markdown instruction file — it cannot be unit tested. Validation:
- Invoke the skill and verify the setup phase collects all 6 parameters
- Run a few experiment cycles on `autoresearch-mlx/` to verify the loop works end-to-end
- Try on a non-ML problem (e.g. optimizing a benchmark) to confirm domain-agnosticism

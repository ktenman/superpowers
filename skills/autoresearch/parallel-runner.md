# Parallel Runner

Guide for running multiple experiments concurrently using worktree-isolated sub-agents.

**Only read this file when parallelism > 1.**

## When to Use

- User set `parallelism > 1` during setup
- Experiments are fast (< 2 minutes each) and you suggest batching to the user

## Batch Dispatch Cycle

### Step 1: Prepare experiments

Read current state (`results.tsv` + mutable files + `autoresearch-state.json`). Use the strategy engine to propose N distinct experiments (one per worker slot). Each experiment must be different — don't send the same change to multiple workers.

### Step 2: Build worker prompts

Each worker gets a **completely self-contained prompt**. Workers have NO access to your conversation context — they start fresh with only what you give them.

Template:

```
You are an autoresearch experiment worker. Follow these instructions exactly.

## Your experiment
Apply this code change: [EXACT description of what to change, including specific file paths, line numbers or code patterns to find, and the new values/code]

## Files you may edit
[List of absolute paths to mutable files]

## Steps
1. Read the mutable files listed above
2. Apply the described change — nothing more, nothing less
3. Run: [run command] > run.log 2>&1
4. Extract the metric: [extract command]
5. If the extract command returns empty, read the last 50 lines of run.log

## Report format
End your response with EXACTLY this format (one line):
RESULT: metric=[numeric value or CRASH] desc=[tag] [short description]

## Constraints
- Do NOT propose different experiments — only apply the described change
- Do NOT modify files not listed above
- Redirect ALL run output to run.log
```

### Step 3: Dispatch

Send all N workers in a single message using parallel Agent tool calls:

```
Agent(
  description: "Experiment: [short desc]",
  prompt: [worker prompt from step 2],
  isolation: "worktree",
  run_in_background: true
)
```

All workers launch simultaneously in isolated worktrees.

### Step 4: Collect results

Wait for all task notifications. Parse the `RESULT:` line from each worker's final message.

If a worker's response doesn't contain a valid `RESULT:` line, treat it as a crash.

### Step 5: Best-of-batch selection

1. Parse `RESULT:` lines from all workers. Missing or unparseable = crash.
2. Compare all reported metrics against current best
3. If none beat current best: record all as discards in `results.tsv`
4. If one or more beat current best: the best metric value wins

### Step 6: Apply the winner

If there's a winner:
1. Read the winning worker's worktree to see exactly what changed (worktree persists if worker made changes)
2. Apply the same change to your main branch mutable files
3. `git add <mutable files> && git commit -m "experiment: [desc from worker]"`
4. Record as `keep` in `results.tsv`, update `autoresearch-state.json`

If the worktree was cleaned up, reconstruct the change from the worker's description.

Record ALL experiments (winners and losers) in `results.tsv` for anti-repeat tracking.

### Step 7: Repeat

Go back to step 1 with the new state.

## Failure Handling

- **Some workers crash:** Continue with results from others. Record crashes in `results.tsv`.
- **All workers crash:** Fall back to sequential mode (parallelism = 1) for one experiment. Debug the crash, then resume parallel mode.
- **Worker returns NaN or nonsensical metric:** Treat as crash.
- **Worker modifies wrong files:** Treat as crash, don't apply changes.

## When to Fall Back to Sequential

- All N workers crashed in the same batch
- 3+ consecutive batches produced zero `keep` results (parallel overhead isn't paying off)
- The experiment domain requires sequential dependency (each change builds on the previous)

When falling back, set parallelism to 1 in `autoresearch-state.json` and continue with the normal loop in SKILL.md.

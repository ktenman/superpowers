# Resilience

Guide for surviving context compression, session interruptions, and unexpected failures.

## Checkpoint File: `autoresearch-state.json`

Source of truth for loop state. Updated per the experiment loop in SKILL.md. Strategy notes format defined in `strategy-engine.md`.

Always stage both tracking files in git operations:
```bash
git add results.tsv autoresearch-state.json
git stash -- results.tsv autoresearch-state.json  # before hard resets
```

## Context Compression Recovery

When you notice the conversation has been compressed (earlier messages are summarized or missing), do this IMMEDIATELY before proposing the next experiment:

1. **Read `autoresearch-state.json`** — this tells you:
   - Which branch you're on
   - What the last kept commit was
   - How many experiments have been run
   - Strategy notes from previous batches
   - All setup parameters (metric, files, commands, time budget)

2. **Read `results.tsv`** — this tells you:
   - Every experiment tried (including discards and crashes)
   - The current best metric value
   - What categories and approaches have been explored

3. **Read all mutable files** — to see the current code state

4. **Verify git state:**
   ```bash
   git branch --show-current
   git rev-parse HEAD
   ```
   Confirm you're on the autoresearch branch and HEAD matches `last_kept_commit`.

5. **Continue the loop** — you now have everything needed to propose the next experiment.

## Manual Resume (New Session)

When a user starts a new session and says "resume autoresearch":

1. Look for `autoresearch-state.json` in the current directory
2. If not found, check common locations: project root, `autoresearch-mlx/`
3. If found:
   - Read the checkpoint file
   - Read `results.tsv`
   - Show the user: branch name, experiment count, best metric value
   - Ask: "Resume from here?"
4. If confirmed:
   - `git checkout <branch from checkpoint>`
   - Verify: `git rev-parse HEAD` matches `last_kept_commit`
   - If mismatch: `git reset --hard <last_kept_commit>` (after stashing tracking files)
   - Read mutable files, read `strategy-engine.md`, re-enter the loop
5. If not found: tell the user no checkpoint exists, start fresh setup

## Graceful Degradation

### Git state is wrong (HEAD doesn't match checkpoint)

```bash
git stash -- results.tsv autoresearch-state.json
git reset --hard <last_kept_commit from checkpoint>
git stash pop
git add results.tsv autoresearch-state.json
git commit --amend --no-edit
```

### Branch is missing

1. Check if the commit still exists: `git cat-file -t <last_kept_commit>`
2. If yes: create a new branch at that commit and continue
   ```bash
   git checkout -b autoresearch/<new-tag> <last_kept_commit>
   ```
3. If no: alert the user — the experiment history is gone and cannot be reconstructed

### Tracking files are missing but branch exists

1. Reconstruct from git history:
   ```bash
   git log --oneline
   ```
2. Create a fresh `results.tsv` from commit messages (they contain experiment descriptions)
3. Create a minimal `autoresearch-state.json` with:
   - Branch: current branch name
   - `last_kept_commit`: current HEAD
   - `experiment_count`: number of commits on branch
   - `strategy_notes`: empty (lost)
4. Continue the loop — you'll rebuild strategy knowledge as you run more experiments

### Run command or extract command fails unexpectedly

1. Check if the environment changed (missing dependency, moved file)
2. Read `autoresearch-state.json` params to confirm the commands
3. Try running the command manually to see the error
4. If fixable: fix and continue
5. If not fixable: alert the user with the error details

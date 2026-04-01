# Autoresearch Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic `superpowers:autoresearch` skill that implements an autonomous experiment ratchet for optimizing any measurable metric.

**Architecture:** Single SKILL.md file in `skills/autoresearch/` following existing superpowers skill conventions. The skill is parametric — all domain-specific details are collected during setup, not hardcoded.

**Tech Stack:** Markdown with YAML frontmatter (same as all other superpowers skills).

---

### Task 1: Create the autoresearch skill directory and SKILL.md

**Files:**
- Create: `skills/autoresearch/SKILL.md`

**Reference:** Spec at `docs/superpowers/specs/2026-03-30-autoresearch-skill-design.md`

- [ ] **Step 1: Create skill directory**

```bash
mkdir -p skills/autoresearch
```

- [ ] **Step 2: Write SKILL.md**

Create `skills/autoresearch/SKILL.md` with the following content. The file has three sections: frontmatter, overview/setup, and the experiment loop.

Frontmatter:
```yaml
---
name: autoresearch
description: "Use when the user wants to autonomously optimize a measurable metric through iterative code experiments"
---
```

Overview section must include:
- Core principle: one sentence explaining the ratchet pattern (modify, measure, keep/discard)
- When to Use: trigger conditions (user wants autonomous experiments, overnight optimization, metric improvement)

Setup Phase section must include:
- The 6-parameter table from the spec (metric, mutable files, read-only files, run command, extract command, time budget)
- The 7 setup steps from the spec
- The shortcut: if user references a known config like `autoresearch-mlx/program.md`, infer parameters from it

Experiment Loop section must include:
- The 10-step ratchet loop from the spec (read state, propose change, commit, run, extract, handle crash, record, keep/discard, repeat)
- Results tracking: TSV format with core 4 columns + optional extras
- Constraints: only mutable files, no new deps, no `git add -A`, redirect output
- Simplicity criterion
- Timeout/crash handling (kill at 2x budget, 3+ consecutive crashes = pause and re-read)
- Autonomy: never stop, never ask, loop until interrupted

Related Skills section:
- `superpowers:using-git-worktrees`
- `superpowers:verification-before-completion`

Keep the entire file concise — aim for ~100 lines. Do NOT duplicate content that exists in domain-specific files like `program.md`. Do NOT include hyperparameter tables or experiment idea lists.

- [ ] **Step 3: Verify skill follows conventions**

Check that the file:
- Has YAML frontmatter with `name` and `description`
- Description starts with "Use when"
- Has `## Overview` with a core principle
- Has `## When to Use`
- Follows the structure of existing skills like `skills/systematic-debugging/SKILL.md`

- [ ] **Step 4: Commit**

```bash
git add skills/autoresearch/SKILL.md
git commit -m "Add autoresearch skill: generic autonomous experiment ratchet"
```

### Task 2: Clean up the old local skill file

**Files:**
- Remove: `~/.claude/skills/autoresearch.md`
- Modify: `~/.claude/skills/SKILL.md` (remove autoresearch entry)

- [ ] **Step 1: Remove the local autoresearch skill**

```bash
rm ~/.claude/skills/autoresearch.md
```

- [ ] **Step 2: Remove autoresearch entry from SKILL.md index**

Edit `~/.claude/skills/SKILL.md` to remove the autoresearch section (lines starting from `## autoresearch` through `See autoresearch.md for full details.`).

- [ ] **Step 3: Verify local cleanup**

```bash
cat ~/.claude/skills/SKILL.md
```

Confirm only `ai-checker` entry remains.

### Task 3: Update the PR

- [ ] **Step 1: Stage and amend the existing commit or create new commit**

```bash
git add skills/autoresearch/SKILL.md
git commit -m "Add autoresearch skill: generic autonomous experiment ratchet"
```

- [ ] **Step 2: Push to the fork**

```bash
git push
```

- [ ] **Step 3: Verify the PR includes both the skill and the bundled example**

```bash
gh pr view 1 --repo ktenman/superpowers
```

Confirm the PR now has:
- `autoresearch-mlx/` (the bundled example)
- `skills/autoresearch/SKILL.md` (the generic skill)

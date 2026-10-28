# The Simplify Pass

Part of superpowers:subagent-driven-development. The implementer reported
DONE.

One simplifier subagent per task, between the implementer's report and the
task review. It cuts what the task did not need and commits. The task review
that follows is what vets its diff.

The simplifier writes to the worktree, so it reads the code directly — it gets
BASE and HEAD, not a review package. The package is generated once, in
SKILL.md's step 4, after the simplifier has committed, so it spans the
implementation and the simplification as one diff.

- Statuses: **SIMPLIFIED** (a commit the reviewer will see), **NO_CHANGES**
  (the diff was already minimal), **BLOCKED** (the suite was red on arrival
  and reverting the cuts does not fix it — that is an implementer problem;
  route it as one).
- Ledger: `Task <N>: simplified (<net line change>, commit <sha7>)`, or
  `Task <N>: simplify — no changes`.
- The pass never runs inside the fix loop: a simplifier and a fixer taking
  turns on the same code is how an addressed finding comes back.

**Model:** judgment work over one small diff — mid-tier, never above the
reviewer that follows it.

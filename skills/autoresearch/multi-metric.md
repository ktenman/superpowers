# Multi-Metric

Guide for tracking and constraining secondary metrics alongside the primary optimization target.

**Only read this file when secondary metrics are declared during setup.**

## Setup

During parameter collection, the user declares secondary metrics in this format:

```
Secondary metrics: memory_gb < 32, latency_p99
```

Parse each entry as either:
- **Constrained:** `name < value` or `name > value` — hard limit, violations auto-discard
- **Tracked:** `name` alone — recorded in results but doesn't affect keep/discard

For each secondary metric, collect an extract command:

| Secondary metric | Constraint | Extract command |
|-----------------|------------|-----------------|
| `memory_gb` | `< 32` | `grep "peak_memory:" run.log \| awk '{print $2}'` |
| `latency_p99` | *(none)* | `grep "p99:" run.log \| awk '{print $2}'` |

Store these in `autoresearch-state.json` under `params.secondary_metrics`:

```json
"secondary_metrics": [
  {
    "name": "memory_gb",
    "extract_command": "grep 'peak_memory:' run.log | awk '{print $2}'",
    "constraint": "< 32"
  },
  {
    "name": "latency_p99",
    "extract_command": "grep 'p99:' run.log | awk '{print $2}'",
    "constraint": null
  }
]
```

## Results.tsv Format

Secondary metric columns go between the primary metric and the status column:

```
commit	val_bpb	memory_gb	latency_p99	status	description
a1b2c3d	2.667	26.9	45.2	keep	[param] baseline
d4e5f6g	2.550	33.1	42.0	discard	[param] larger model — constraint: memory_gb > 32
h7i8j9k	2.520	25.0	44.8	keep	[arch] reduce depth to 4
```

The header row must list all metric columns in order. Don't change column order mid-run.

## Extraction

After each experiment run, extract ALL metrics:

1. Primary metric: `<primary extract command>`
2. For each secondary metric: `<secondary extract command>`
3. If a secondary extract command fails (empty output), record `N/A` for that metric — `N/A` passes all constraints (benefit of doubt). Don't treat it as a crash unless the primary also failed

## Keep/Discard Decision (Extended)

The decision follows this order:

### 1. Check hard constraints

For each constrained secondary metric:
- Parse the constraint (e.g., `< 32`)
- Compare the extracted value against the constraint
- If ANY constraint is violated: **auto-discard**, regardless of primary metric
- Include the violation in the description: `constraint: memory_gb (33.1) > 32`

### 2. Check primary metric

If all constraints pass:
- Compare primary metric against current best (same as single-metric mode)
- Improved = `keep`, equal/worse = `discard`

### 3. Pareto note (informational)

If the experiment is being discarded on primary metric BUT significantly improved a secondary metric:
- Add `pareto-candidate` to the description
- Example: `discard [arch] wider layers — pareto-candidate: latency_p99 improved 45→30`
- The strategy engine can reference pareto-candidates when looking for `[combo]` opportunities

## Constraint Syntax

Supported operators: `<`, `>`, `<=`, `>=` followed by a numeric threshold. If the user gives an ambiguous constraint (e.g., "memory should stay reasonable"), ask for a specific number.

## Strategy Interaction

The strategy engine should consider secondary metrics when planning:

- If a `[param]` change consistently violates a constraint, note it in strategy notes and avoid that parameter axis
- `pareto-candidate` entries in results.tsv suggest the experiment was valuable on a different axis — consider combining it with something that improves the primary metric via `[combo]`
- When writing strategy notes every 10 experiments, include a line about constraint health: "memory_gb: all within constraint" or "memory_gb: 3/10 experiments violated, avoiding large-model changes"

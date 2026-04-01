# Strategy Engine

Guide for planning experiments systematically instead of randomly.

## Experiment Categories

Propose experiments from these categories in rotation. Tag every experiment description with its category.

### `[param]` Numeric Parameter Sweeps

Systematically vary numeric values, thresholds, or configuration constants found in the mutable files.

- Identify all tunable numbers in the code (sizes, rates, counts, thresholds)
- Try halving, doubling, or order-of-magnitude changes
- When a direction shows promise (e.g., smaller batch size helps), explore that axis further
- Don't fine-tune — find the right ballpark first

### `[arch]` Structural Changes

Add, remove, or swap components, algorithms, data structures, or processing stages.

- Look at the overall structure of the mutable code
- Try removing components that might be unnecessary
- Try swapping algorithms (e.g., different sort, different data structure)
- Try reordering processing stages
- Keep changes focused — one structural change per experiment

### `[simplify]` Simplification

Delete code or reduce complexity while maintaining the metric.

- Look for dead code, unused branches, over-engineered abstractions
- Try removing features that don't contribute to the metric
- Simpler code that achieves the same metric = a win worth keeping
- This category is especially valuable after a series of `[arch]` experiments that added complexity

### `[combo]` Combination

Merge two near-miss improvements that individually didn't beat baseline.

- Review `results.tsv` for experiments that were close to improving
- Apply two complementary near-miss changes together
- Only combine changes from different categories (e.g., a `[param]` near-miss + a `[simplify]` near-miss)
- Don't combine changes that modify the same code region

### `[radical]` Radical

Try something unconventional when incremental changes plateau.

- Rewrite a significant portion of the mutable code from a different angle
- Try an approach that contradicts current assumptions
- Use this category when the other four have been exhausted
- High risk, high reward — expect more crashes and discards

## Category Rotation

Don't cycle through categories mechanically. Use this priority:

1. **Start with `[param]`** — fastest to try, establishes what's tunable
2. **Move to `[arch]`** — once you understand the parameter landscape
3. **Periodically `[simplify]`** — every 5-10 experiments, look for complexity to remove
4. **Use `[combo]`** — when you have 3+ near-miss results to combine
5. **Use `[radical]`** — when the last 5+ experiments are all `discard`

## Anti-Repeat Protocol

Before proposing an experiment:

1. Read `results.tsv` descriptions
2. Filter by the category tag you're about to use
3. Check if the specific parameter or component you plan to change has been tried before
4. If it has: pick a different target or different category
5. If all obvious targets in a category are exhausted: switch category

Example — if `results.tsv` contains:
```
[param] halve batch size → keep
[param] double learning rate → discard
[param] halve learning rate → discard
```

Do NOT propose `[param] reduce learning rate by 25%` — the learning rate axis has been explored. Try a different parameter or switch to `[arch]`.

## Plateau Detection

**Trigger:** 5 consecutive `discard` results.

**Response:**
1. Re-read ALL mutable and read-only files from scratch (don't rely on memory)
2. Re-read this file (`strategy-engine.md`) for fresh perspective
3. Review the full `results.tsv` — look for patterns:
   - Which categories produced the most `keep` results?
   - Are there near-misses that could be combined?
   - Is there a consistent direction (smaller is better? simpler is better?)
4. Switch to a category you haven't tried recently
5. If all categories feel exhausted, use `[radical]`

**Trigger:** 3 consecutive `crash` results.

**Response:**
1. Stop proposing new experiments
2. Re-read all mutable files carefully
3. Check if a recent `keep` introduced fragility
4. Fix the root cause of crashes before continuing
5. Consider reverting to the previous `keep` state if the current code is unstable

## Strategy Notes

Every 10 experiments, write a brief summary to `autoresearch-state.json` `strategy_notes` array:

```json
{
  "at_experiment": 10,
  "summary": "[param] exhausted for learning rates and batch sizes. [arch] depth reduction was the biggest win. Next: try [simplify] to remove unused gating, then [combo] depth-reduction + batch-size."
}
```

These notes survive context compression and help you resume intelligently.

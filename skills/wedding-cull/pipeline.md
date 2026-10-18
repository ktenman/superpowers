# Wedding cull: full delivery pipeline

From a rated shoot to a delivery that fits the contract, plus a backup bench, portfolio picks and
Lightroom work queues. Paths are relative to this skill's directory: prefix them with its absolute
path, because the user's folder may have its own `scripts/`. Run every `.py` through `uv run`
(PEP 723 headers pull the dependencies); each documents its arguments in `--help`. WORKDIR is the
RAW folder's work folder, the absolute path step 1 prints. Pass it absolute: the batch files store
paths exactly as given.

The vision passes are `workflows/*.js` scripts for the Workflow tool (`scriptPath` + `args`).
They fan out one agent per ~12-frame batch (screening 515 frames took 43 agents), so tell the
user the scale and get a go-ahead first. The Workflow tool also needs their explicit opt-in to
multi-agent orchestration (e.g. "use a workflow"); without it, dispatch the script's prompt per
batch with the Agent tool. Each script's header comment gives its `args` shape;
`wedding` is one line of context for the vision agents (couple, place, date, camera bodies and
their file prefixes).

## Cull-specific rules (on top of SKILL.md's hard rules and Lightroom round trip)

1. **Contract first.** Read the booking contract before curating: delivery count floor AND
   ceiling, mandatory coverage buckets, preview deadline, portfolio cap / client veto.
   Scene-balance every cut against the mandatory buckets.
2. **Two-camera clock sync.** The cull reads one RAW folder holding every card, the one Lightroom
   imported them into. File names are the frame IDs, so the bodies need different file-name prefixes; ask the user if two share one.
   NEVER interleave bodies by EXIF time without verifying sync on a
   moment both cameras shot (first kiss, first dance): VIEW the candidate pairs. Scene-note
   labels can be premise errors (a "rings" frame that's really the ring-bearer waiting
   pre-ceremony). Measure the offset, apply it as a per-prefix constant
   (`chrono_merge.py --offset IMG_=-568`), and confirm the anchor pair lands on the same
   corrected second. (One job's second body ran 9m28s ahead.)
3. **Honest measurement:**
   - Laplacian sharpness = *relative flag* (same pipeline/res only), never a verdict.
   - Exposure clip measured on 8-bit previews *understates* RAW headroom: flag only.
   - Blink: faces < 80px = `"unknown"`, never a guessed number.
   - Never claim critical focus is confirmed from a preview/decode; flag it for the
     photographer's 100% review (`flag100` fields).

## Steps

Phases: ORIENT (read contract, inventory files, map ratings) → MEASURE (1–4) → CURATE (5–6) →
VALIDATE (7–8) → EXTEND (9–10) → OUTPUT (11–12).
**Pause for user approval before OUTPUT: it writes sidecars and folders.**

1. `uv run photo.py previews RAWDIR`: oriented 1600px preview JPEGs in WORKDIR/previews; prints WORKDIR.
2. `exiftool -j RAWDIR > WORKDIR/exif.json`
3. `uv run photo.py models`, then `uv run scripts/blink.py --previews WORKDIR/previews --out WORKDIR/faces.json`
4. `uv run scripts/metrics.py --workdir WORKDIR` → `metrics.csv/json` (sharpness + soft flag,
   clip, dHash near-dupe clusters, time runs, ratings from the sidecars in exif.json).
5. `uv run scripts/mkbatches.py --metrics WORKDIR/metrics.json --previews WORKDIR/previews
   --outdir WORKDIR/batches --paths-out WORKDIR/batch_paths.json`: scene/time-coherent batch
   manifests (~12 frames); the workflows' `batches` arg is the list in batch_paths.json.
6. **Vision screen**: `workflows/curate-screen.js`, one Sonnet agent per batch views every
   preview and returns keep/maybe/drop + scene + reason + crop/grade direction + flag100.
   Aim ~25–50% over the delivery ceiling as candidates.
7. **Verify flagged**: decode suspects at 2560px (`uv run photo.py decode RAWDIR ID...` →
   WORKDIR/verify), then `workflows/verify-flagged.js`: per-frame agent returns
   eyes/focus/verdict (pass/hold/fail). *hold* = no visible defect but unprovable (profile
   face, sunglasses) → KEEP. *fail* = real defect → demote + scene-matched swap from
   alternates; visually verify every swap-in.
8. **Finalize**: `workflows/finalize.js` locks the delivery at the contract ceiling (step 10
   splits it at the floor into must-have and good-to-have), coverage map
   vs mandatory buckets, portfolio ≤ cap (balanced across the day, mix of orientations),
   preview set. Portfolio picks must all be verify-pass.
9. **Backup bench**: `workflows/buffer-screen.js` on held-back 5★ + un-screened 4★: screen
   (A/B/C) → scene-balanced shortlist → independent skeptic verify. Expect ~30% downgrades, so
   shortlist ~1.4× the bench; while the bench is still short it verifies the next-best screened
   frames, up to the shortlist size again (count those agents in the go-ahead).
10. **Tiers + edit actions**: `workflows/tier-edit-actions.js` (score 0–100 within scene
    batches, `must_moment` flag, edit_actions crop/color/retouch/none with direction notes) →
    `uv run scripts/aggregate_tiers.py --tier1-size N --force-tier1 <portfolio ids>`
    (largest-remainder scene quotas; must_moments and portfolio pinned to tier-1).
11. **Organize**: `uv run scripts/organize.py` → `1_must_have_N/`, `2_good_to_have_N/`,
    `3_backup_N/`, `edit_crop/`, `edit_color/`, `edit_retouch/`, `edit_clean/`; each holds
    preview copies + `manifest.csv` (RAW paths + notes), usable as a Lightroom work queue.
    `--backup` takes buffer-screen's result (on every run once the backup folder exists).
    **The photographer culls in these folders: that is user input.** A preview deleted from a
    tier or backup folder or `edit_clean` = rejected, out of every list; from another `edit_*`
    queue = that edit done (drop it from edit_actions) or rejected: ask which; dragged to
    another tier folder = moved to that list. Before any rerun, diff each folder's files
    against its manifest.csv and apply the changes to the tier/backup JSONs. organize.py and
    chrono_merge.py rebuild from scratch, and refuse, listing every conflict, until the input
    matches what the photographer left.
    For client-facing "one camera" ordering: `uv run scripts/chrono_merge.py` → one folder of
    sequence-renamed copies (`<Name>-001.jpg`…) in corrected chronological order +
    manifest.csv with the id↔seq↔RAW map (apply rule 2 first). For a photographer triage pool
    (delivery + bench, per-image edit direction columns + EDITS.md):
    `uv run scripts/build_pool.py` → pool json → chrono_merge on it. Sequence names shift on
    every rebuild: the manifest is the id map, and user deletions from these folders are
    permanent rejects (dropped_user).
12. **XMP write-back**: first apply the photographer's deletions from step 11's folders (the same
    diff), or rejected frames get tagged. Then one Lightroom keyword per list, with photo.py's backup
    and rating guard: `uv run photo.py keyword RAWDIR TIERS.json tier1_must_have cull/must_have`, the
    same with `tier2_good_to_have cull/good_to_have`, and `keyword RAWDIR BENCH.json backup_50 cull/backup`
    (TIERS.json = aggregate_tiers.py's `--out`, BENCH.json = buffer-screen's result). `label` in place
    of `keyword`, with a colour in place of the keyword, overwrites the culling app's colour label
    instead: only if the user explicitly accepts that.

## What made the vision passes reliable

- Batches are scene-grouped, so scores are *within-scene relative*; agents are told to spread
  scores, not cluster at 80.
- Every screen has an independent adversarial verify stage; verifiers judge fresh "as a
  skeptic" and get the screen notes only as hints.
- Structured output via JSON schema on every agent, no text parsing.
- Aggregate from the workflow's `journal.jsonl` or task `.output` (`result.results`); a
  missing journal line can still be present in the output.
- Vision verdicts at 1600–2560px can be wrong about *content* too (a "kiss" that is actually
  a circle dance): the verify pass re-reads the premise, not just the pixels.

## Deliverable structure that worked

150 must-have (contract floor, scene-balanced) + 50 good-to-have (to ceiling) + 50 backup bench
(not delivered; swap stock) + portfolio ≤10 with a preview-5 subset. Every report includes a
"measured vs verify-at-100%" caveats section listing exactly what was NOT confirmed and what
the photographer must check.

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Split a locked delivery into tier-1 (must-have) / tier-2 (good-to-have).

Inputs: the delivered frame list (id+scene) and per-frame rank verdicts
(score 0-100, must_moment bool) from the tier-edit-actions workflow.
Tier-1 is scene-balanced: each scene gets a quota proportional to its share
of the delivery (largest-remainder rounding), must_moment frames are forced
into tier-1 first, then slots fill best-score-first.
Scores are batch-relative vision judgments, NOT absolute quality metrics --
they order frames, they don't certify them.
"""
import argparse, json


def quotas(scene_counts, total):
    # largest-remainder proportional rounding that sums exactly to `total`
    n = sum(scene_counts.values())
    raw = {s: c * total / n for s, c in scene_counts.items()}
    q = {s: int(v) for s, v in raw.items()}
    for s, _ in sorted(raw.items(), key=lambda kv: -(kv[1] - int(kv[1])))[: total - sum(q.values())]:
        q[s] += 1
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, help="json: list of {id, scene, ...} (the locked delivery)")
    ap.add_argument("--frames-key", default=None, help="if the json is an object, key holding the list (e.g. 'delivered')")
    ap.add_argument("--verdicts", required=True, help="json: list of {id, score, must_moment, edit_actions, ...}")
    ap.add_argument("--tier1-size", type=int, required=True)
    ap.add_argument("--force-tier1", default="", help="comma-separated ids that must land in tier-1 (e.g. portfolio/preview picks)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    forced = set(filter(None, a.force_tier1.split(",")))

    frames = json.load(open(a.frames))
    if a.frames_key:
        frames = frames[a.frames_key]
    scene = {e["id"]: e["scene"] for e in frames}
    V = {v["id"]: v for v in json.load(open(a.verdicts))}
    missing = [i for i in scene if i not in V]
    if missing:
        raise SystemExit(f"no verdict for {len(missing)} frames: {missing[:5]}")

    from collections import Counter, defaultdict
    q = quotas(Counter(scene.values()), a.tier1_size)

    by = defaultdict(list)
    for i, s in scene.items():
        by[s].append(V[i])
    def pinned(v):
        return v.get("must_moment") or v["id"] in forced

    tier1, tier2 = [], []
    for s, items in by.items():
        # pinned frames first (must_moment or --force-tier1), then best-score-first up to quota
        items.sort(key=lambda v: (not pinned(v), -v["score"]))
        k = q[s]
        # a scene's pinned frames can exceed its quota; they still all go to tier-1
        k = max(k, sum(1 for v in items if pinned(v)))
        tier1 += [dict(v, scene=s) for v in items[:k]]
        tier2 += [dict(v, scene=s) for v in items[k:]]
    # if pinned frames pushed tier1 over size, demote the weakest non-pinned frames
    if len(tier1) > a.tier1_size:
        tier1.sort(key=lambda v: (pinned(v), v["score"]))
        while len(tier1) > a.tier1_size and not pinned(tier1[0]):
            tier2.append(tier1.pop(0))

    out = {
        "tier1_must_have": sorted(tier1, key=lambda v: -v["score"]),
        "tier2_good_to_have": sorted(tier2, key=lambda v: -v["score"]),
        "quotas": q,
        "counts": {"tier1": len(tier1), "tier2": len(tier2)},
    }
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"tier1={len(tier1)} tier2={len(tier2)} quotas={q}")


if __name__ == "__main__":
    main()

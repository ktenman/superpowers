#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Compose a flat frame list for chrono_merge.py: the locked delivery plus
optional spare candidates (backup bench, extras), each entry carrying
tier + edit direction so the merged folder is self-describing.

Output entries: {id, scene, tier, edit_actions, edit_note, check100}.
tier = must_have | good_to_have (delivered) | bench | extra (candidates).
"""
import argparse, json


def norm100(v):
    if not v or v == "none": return ""
    return v if isinstance(v, str) else "confirm eyes/critical focus at 100%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delivered", required=True, help="delivered_final.json")
    ap.add_argument("--tiers", required=True, help="tiers.json (edit notes + tier)")
    ap.add_argument("--backup", default=None, help="backup_final.json — bench candidates")
    ap.add_argument("--extras", default=None, help="group_extras.json — extras candidates")
    ap.add_argument("--extras-top", type=int, default=0, help="take N best extras by score")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    t = json.load(open(a.tiers))
    tv = {v["id"]: (tier, v) for tier, vs in (("must_have", t["tier1_must_have"]),
                                              ("good_to_have", t["tier2_good_to_have"])) for v in vs}
    delivered = json.load(open(a.delivered))["delivered"]
    dropped = {e["id"] for e in json.load(open(a.delivered)).get("dropped_user") or []}

    def edit_of(v):
        acts = [x for x in v.get("edit_actions", []) if x != "none"]
        notes = [(k.upper(), v.get(f"{k}_note", "")) for k in ("crop", "color", "retouch") if k in acts]
        texts = [n for _, n in notes if n]
        if not acts:
            return "", "preset only — no active work"
        if texts and len(set(texts)) == 1:
            return "+".join(acts), texts[0]
        return "+".join(acts), " | ".join(f"{k}: {n}" for k, n in notes if n) or "see edit queue"

    pool = []
    for e in delivered:
        tier, v = tv[e["id"]]
        acts, note = edit_of(v)
        pool.append({"id": e["id"], "scene": e["scene"], "tier": tier,
                     "edit_actions": acts, "edit_note": note, "check100": norm100(e.get("flag100"))})

    if a.backup:
        b = json.load(open(a.backup))
        for v in b["backup_50"]:
            if v["id"] in dropped: continue
            pool.append({"id": v["id"], "scene": v["scene"], "tier": "bench",
                         "edit_actions": "", "edit_note": v.get("note", ""),
                         "check100": norm100(v.get("flag100"))})

    if a.extras and a.extras_top:
        g = json.load(open(a.extras))
        gone = set(g.get("promoted_to_delivery", [])) | dropped
        res = {r["id"]: r for r in g["results"]}
        cands = sorted((res[i] for i in g["keeps"] if i not in gone),
                       key=lambda r: (-r["score"], r["id"]))[:a.extras_top]
        for r in cands:
            pool.append({"id": r["id"], "scene": "group", "tier": "extra",
                         "edit_actions": "", "edit_note": f"[{r['category']}] {r.get('note','')}",
                         "check100": norm100(r.get("flag100"))})

    ids = [f["id"] for f in pool]
    assert len(ids) == len(set(ids)) and not set(ids) & dropped
    json.dump({"frames": pool}, open(a.out, "w"), indent=1)
    print(f"{len(pool)} frames -> {a.out} (delivered {len(delivered)}, candidates {len(pool)-len(delivered)})")


if __name__ == "__main__":
    main()

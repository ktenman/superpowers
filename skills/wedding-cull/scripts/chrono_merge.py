#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Merge a finished delivery into ONE folder in true chronological order.

Multi-camera shoots rarely share a clock to the second. NEVER interleave by
EXIF time without verifying sync on a moment both bodies shot (first kiss,
first dance): view the frames, measure the offset, pass it per filename
prefix, e.g. --offset IMG_=-568 (R5 clock 9m28s ahead -> subtract 568s).

Copies preview JPEGs (never RAWs, never moves) renamed <name>-001.jpg,
<name>-002.jpg, ... so nothing in the filename betrays which body shot what.
manifest.csv keeps the full map: seq, new name, original id, corrected time,
scene, tier, edit direction, RAW path — use it to batch-rename the edited
exports. If frame entries carry tier/edit_actions/edit_note/check100 (see
build_pool.py) those are used directly and an EDITS.md digest is written.
"""
import argparse, csv, datetime, json, os, shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, help="json: list of {id, scene, ...} (the locked delivery)")
    ap.add_argument("--frames-key", default=None, help="if the json is an object, key holding the list")
    ap.add_argument("--metrics", required=True, help="metrics.json (capture epoch per id)")
    ap.add_argument("--tiers", default=None, help="tiers.json, adds a tier column to the manifest")
    ap.add_argument("--previews", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--name", default="wedding", help="filename stem, e.g. Bride-Groom")
    ap.add_argument("--offset", action="append", default=[],
                    help="PREFIX=SECONDS added to matching ids' epochs; repeatable")
    ap.add_argument("--rawdir", required=True)
    ap.add_argument("--raw-ext", default=".CR3")
    a = ap.parse_args()

    offs = [(p, float(s)) for p, s in (o.split("=", 1) for o in a.offset)]
    M = {m["id"]: m for m in json.load(open(a.metrics))}
    frames = json.load(open(a.frames))
    if a.frames_key:
        frames = frames[a.frames_key]
    tier = {}
    if a.tiers:
        t = json.load(open(a.tiers))
        tier = {v["id"]: "must_have" for v in t["tier1_must_have"]}
        tier |= {v["id"]: "good_to_have" for v in t["tier2_good_to_have"]}

    def corrected(i):  # metrics' epoch already holds the sub-second part
        return M[i]["epoch"] + next((s for p, s in offs if i.startswith(p)), 0)

    frames = sorted(frames, key=lambda f: (corrected(f["id"]), f["id"]))
    pad = max(3, len(str(len(frames))))

    # rebuild from scratch, same contract as organize.py -- but only over this script's own output, and never
    # over the photographer's cull: a copy deleted from it is a reject, so it must be gone from --frames first,
    # and files it didn't write must be moved out
    man = os.path.join(a.outdir, "manifest.csv")
    if os.path.exists(man):
        rows = list(csv.DictReader(open(man)))
        have = {f for f in os.listdir(a.outdir) if not f.startswith(".")} - {"manifest.csv", "EDITS.md"}
        back = sorted({r["id"] for r in rows if r["new_name"] not in have} & {f["id"] for f in frames})
        extra = sorted(have - {r["new_name"] for r in rows})  # e.g. edited exports saved next to the copies
        if back or extra:  # reported together, so a renamed copy shows up as one of each
            raise SystemExit(f"{a.outdir}: deleted but still in --frames: {' '.join(back) or '-'}; "
                             f"not in its manifest.csv: {' '.join(extra) or '-'}\n"
                             "drop the deleted frames from the input (dropped_user) and move the other files out "
                             "before rebuilding")
        shutil.rmtree(a.outdir)
    elif os.path.isdir(a.outdir) and any(not f.startswith(".") for f in os.listdir(a.outdir)):
        raise SystemExit(f"{a.outdir} holds files but no manifest.csv, so it is not a chrono_merge "
                         "output: pass a new --outdir")
    os.makedirs(a.outdir, exist_ok=True)
    cols = ["seq", "new_name", "id", "time_corrected", "scene", "tier",
            "edit_actions", "edit_note", "check100", "raw_path"]
    edits_md = ["# Edit directions — one line per image, in folder order",
                "", "Direction in words only — grade with your own presets. "
                "`⚠100%` = confirm at full resolution before final edit. "
                "`[bench]` = candidate, NOT in the locked delivery.", ""]
    with open(os.path.join(a.outdir, "manifest.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for n, f in enumerate(frames, 1):
            i = f["id"]
            new = f"{a.name}-{n:0{pad}d}.jpg"
            tr = f.get("tier") or tier.get(i, "")
            shutil.copy2(os.path.join(a.previews, i + ".jpg"), os.path.join(a.outdir, new))
            w.writerow({
                "seq": n, "new_name": new, "id": i,
                "time_corrected": datetime.datetime.fromtimestamp(corrected(i)).strftime("%H:%M:%S"),
                "scene": f.get("scene", ""), "tier": tr,
                "edit_actions": f.get("edit_actions", ""), "edit_note": f.get("edit_note", ""),
                "check100": f.get("check100", ""),
                "raw_path": os.path.join(a.rawdir, i + a.raw_ext),
            })
            mark = " [bench]" if tr == "bench" else ""
            line = f"- **{new[:-4]}**{mark} ({i} · {f.get('scene','')}) — {f.get('edit_actions') or 'clean'}: {f.get('edit_note','')}"
            if f.get("check100"):
                line += f" ⚠100%: {f['check100']}"
            edits_md.append(line)
    if any(f.get("edit_note") for f in frames):
        open(os.path.join(a.outdir, "EDITS.md"), "w").write("\n".join(edits_md) + "\n")
    print(f"{len(frames)} frames -> {a.outdir} ({a.name}-{1:0{pad}d}.jpg ... {a.name}-{len(frames):0{pad}d}.jpg)")


if __name__ == "__main__":
    main()

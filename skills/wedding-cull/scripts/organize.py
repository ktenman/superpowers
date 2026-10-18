#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Build the physical sorting directories for a finished cull.

Copies PREVIEW JPEGs (never RAW originals, never moves anything) into:
  <outdir>/1_must_have_<n>/     tier-1 delivery
  <outdir>/2_good_to_have_<n>/  tier-2 delivery
  <outdir>/3_backup_<n>/        backup bench (not delivered unless a swap is needed)
  <outdir>/edit_crop/           frames needing re-crop / straighten / composition fix
  <outdir>/edit_color/          frames needing corrective color/exposure beyond the preset
  <outdir>/edit_retouch/        frames needing cleanup (objects, skin, distractions)
  <outdir>/edit_clean/          preset-only frames, no active work
A frame appears in ONE tier folder and EVERY edit folder that applies.
Each folder gets a manifest.csv pointing at the RAW originals plus the
per-frame notes, so the folder works as a Lightroom work queue.
"""
import argparse, csv, json, os, shutil


def write_folder(outdir, name, rows, previews, rawdir, raw_ext, extra_cols):
    d = os.path.join(outdir, name)
    # rebuild from scratch so reruns after a swap don't leave stale previews behind
    # (only ever removes the folders this script itself creates -- preview copies + manifest)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    cols = ["id", "scene", "score", "raw_path"] + extra_cols
    with open(os.path.join(d, "manifest.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            src = os.path.join(previews, r["id"] + ".jpg")
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(d, r["id"] + ".jpg"))
            w.writerow({c: r.get(c, "") for c in cols})
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", required=True, help="tiers.json from aggregate_tiers.py")
    ap.add_argument("--backup", default=None, help="backup_final.json (optional bench)")
    ap.add_argument("--previews", required=True)
    ap.add_argument("--rawdir", required=True, help="directory holding the RAW originals (read-only, only referenced in manifests)")
    ap.add_argument("--raw-ext", default=".CR3")
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    t = json.load(open(a.tiers))
    rp = lambda i: os.path.join(a.rawdir, i + a.raw_ext)
    note_cols = ["must_moment", "edit_actions", "crop_note", "color_note", "retouch_note", "why"]

    def rows_of(vs):
        return [dict(v, raw_path=rp(v["id"]),
                     edit_actions="+".join(v.get("edit_actions", []))) for v in vs]

    t1, t2 = rows_of(t["tier1_must_have"]), rows_of(t["tier2_good_to_have"])
    n1 = write_folder(a.outdir, f"1_must_have_{len(t1)}", t1, a.previews, a.rawdir, a.raw_ext, note_cols)
    n2 = write_folder(a.outdir, f"2_good_to_have_{len(t2)}", t2, a.previews, a.rawdir, a.raw_ext, note_cols)
    print(f"tier folders: {n1} + {n2}")

    if a.backup:
        b = json.load(open(a.backup))
        bench = [dict(v, raw_path=rp(v["id"]), score="") for v in b["backup_50"]]
        nb = write_folder(a.outdir, f"3_backup_{len(bench)}", bench, a.previews, a.rawdir, a.raw_ext,
                          ["grade", "dup_risk", "flag100", "note", "v_note"])
        print(f"backup folder: {nb}")

    # edit-action queues over the delivered tiers (tier1+tier2)
    allv = t1 + t2
    for action, folder in (("crop", "edit_crop"), ("color", "edit_color"), ("retouch", "edit_retouch")):
        sub = [v for v in allv if action in v["edit_actions"].split("+")]
        write_folder(a.outdir, folder, sub, a.previews, a.rawdir, a.raw_ext, note_cols)
        print(f"{folder}: {len(sub)}")
    clean = [v for v in allv if v["edit_actions"] in ("none", "")]
    write_folder(a.outdir, "edit_clean", clean, a.previews, a.rawdir, a.raw_ext, note_cols)
    print(f"edit_clean: {len(clean)}")


if __name__ == "__main__":
    main()

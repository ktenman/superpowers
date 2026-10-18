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
import argparse, csv, glob, json, os, re, shutil, sys


def earlier(outdir, name):
    """This folder's earlier builds (a tier folder's name carries its count: any 1_must_have_<n>)."""
    same = re.escape(name.rstrip("0123456789")) + r"\d*"
    return [os.path.dirname(d) for d in glob.glob(os.path.join(glob.escape(outdir), "*", ""))
            if re.fullmatch(same, os.path.basename(os.path.dirname(d)))]


def conflicts(group, old, previews):
    """The photographer's cull of one group of folders: every file they deleted, added or dragged between the
    group's folders must sit where the new input puts it, or the rebuild would undo that."""
    want, left, touched, errs = {}, {}, set(), []
    for name, rows, _ in group:
        kind = name.rstrip("0123456789_")
        for r in rows: want.setdefault(r["id"], set()).add(kind)
        if len(old[name]) > 1:  # earlier versions left the old count's folder behind: which one is being culled?
            errs.append(f"{' and '.join(old[name])}: two builds of one folder, move out the one not being culled")
            continue
        for o in old[name]:
            man = os.path.join(o, "manifest.csv")
            if not os.path.exists(man):
                errs.append(f"{o} has lost its manifest.csv, so what was deleted from it can't be told"); continue
            ids = {r["id"] for r in csv.DictReader(open(man))}
            have = {f.removesuffix(".jpg") for f in os.listdir(o) if not f.startswith(".")} - {"manifest.csv"}
            for i in have: left.setdefault(i, set()).add(kind)
            touched |= (have - ids) | {i for i in ids - have if os.path.exists(os.path.join(previews, i + ".jpg"))}
    show = lambda s: " and ".join(sorted(s)) or "no folder"
    return errs + [f"{i}: left in {show(left.get(i, ()))}, the input puts it in {show(want.get(i, ()))}"
                   for i in sorted(touched) if left.get(i, set()) != want.get(i, set())]


def write_folder(outdir, name, rows, previews, extra_cols, old):
    # rebuild from scratch so reruns after a swap don't leave stale previews behind
    # (only ever removes the folders this script itself creates -- preview copies + manifest)
    for o in old: shutil.rmtree(o)
    d = os.path.join(outdir, name)
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
    folders = [(f"1_must_have_{len(t1)}", t1, note_cols), (f"2_good_to_have_{len(t2)}", t2, note_cols)]
    if a.backup:
        bench = [dict(v, raw_path=rp(v["id"]), score="") for v in json.load(open(a.backup))["backup_50"]]
        folders.append((f"3_backup_{len(bench)}", bench, ["grade", "dup_risk", "flag100", "note", "v_note"]))

    # edit-action queues over the delivered tiers (tier1+tier2)
    allv = t1 + t2
    for action, folder in (("crop", "edit_crop"), ("color", "edit_color"), ("retouch", "edit_retouch")):
        folders.append((folder, [v for v in allv if action in v["edit_actions"].split("+")], note_cols))
    folders.append(("edit_clean", [v for v in allv if v["edit_actions"] in ("none", "")], note_cols))

    # every folder checked before any is rebuilt, every conflict reported at once; the tier and backup
    # folders are one group (a preview dragged between them is a tier change), each edit queue its own
    if not a.backup and earlier(a.outdir, "3_backup_"):
        sys.exit(f"{a.outdir} has a backup folder: pass the bench with --backup, so the cull is checked against it")
    old = {name: earlier(a.outdir, name) for name, _, _ in folders}
    groups = [[f for f in folders if f[0][0].isdigit()]] + [[f] for f in folders if not f[0][0].isdigit()]
    errs = [e for g in groups for e in conflicts(g, old, a.previews)]
    if errs:
        sys.exit("\n".join(errs) + "\napply the photographer's changes to the tier/backup JSONs: a preview deleted "
                 "from a tier/backup folder or edit_clean = rejected, from another edit queue = that edit done or "
                 "rejected (ask), dragged to another tier folder = moved there; move out any file that isn't a preview")
    for name, rows, cols in folders:
        write_folder(a.outdir, name, rows, a.previews, cols, old[name])
        print(f"{name}: {len(rows)}")


if __name__ == "__main__":
    main()

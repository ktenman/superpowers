#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Write cull results into XMP sidecars — additively and reversibly.

NEVER touches RAW files. NEVER touches xmp:Rating (the culling app's rating
survives). Before editing any sidecar, an untouched copy goes to <backup-dir>.

Two mechanisms, choose per run:
  --keyword TAG   append TAG to dc:subject (Lightroom keyword). Purely
                  additive — nothing existing is overwritten. DEFAULT choice.
  --label TEXT    set xmp:Label. Overwrites the culling app's color label
                  (that color is redundant with xmp:Rating, but it IS a
                  overwrite — the backup copy is the undo).
Frames come from a JSON file: either a list of ids, or an object with --ids-key.

Example (tier-1 delivery as LR keyword):
  uv run xmp_writeback.py --xmpdir RAWDIR --frames tiers.json --ids-key tier1_must_have \
      --keyword "cull/must_have" --backup-dir WORKDIR/xmp_backup_<date>
"""
import argparse, json, os, re, shutil, sys


def load_ids(path, key):
    data = json.load(open(path))
    if key:
        data = data[key]
    return [(e["id"] if isinstance(e, dict) else e) for e in data]


def add_keyword(text, tag):
    if re.search(rf"<rdf:li>{re.escape(tag)}</rdf:li>", text):
        return text  # idempotent
    if "<dc:subject>" in text:
        return text.replace("<rdf:Bag>", f"<rdf:Bag><rdf:li>{tag}</rdf:li>", 1)
    bag = (f"<dc:subject><rdf:Bag><rdf:li>{tag}</rdf:li></rdf:Bag></dc:subject>")
    # inject into the first rdf:Description block
    m = re.search(r"(<rdf:Description[^>]*>)", text)
    if not m:
        raise ValueError("no rdf:Description")
    return text[: m.end()] + bag + text[m.end():]


def set_label(text, label):
    if 'xmp:Label="' in text:
        return re.sub(r'xmp:Label="[^"]*"', f'xmp:Label="{label}"', text)
    m = re.search(r"(<rdf:Description)", text)
    return text[: m.end()] + f' xmp:Label="{label}"' + text[m.end():]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xmpdir", required=True)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--ids-key", default=None)
    ap.add_argument("--keyword", default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--backup-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.keyword and not a.label:
        sys.exit("nothing to do: pass --keyword and/or --label")

    ids = load_ids(a.frames, a.ids_key)
    os.makedirs(a.backup_dir, exist_ok=True)
    done = skipped = 0
    for i in ids:
        p = os.path.join(a.xmpdir, i + ".xmp")
        if not os.path.exists(p):
            print(f"MISSING sidecar: {i}", file=sys.stderr)
            skipped += 1
            continue
        text = orig = open(p, encoding="utf-8", errors="ignore").read()
        if a.keyword:
            text = add_keyword(text, a.keyword)
        if a.label:
            text = set_label(text, a.label)
        if text == orig:
            skipped += 1
            continue
        if a.dry_run:
            print(f"would write {i}")
        else:
            b = os.path.join(a.backup_dir, i + ".xmp")
            if not os.path.exists(b):  # keep the FIRST backup, don't overwrite it on re-runs
                shutil.copy2(p, b)
            open(p, "w", encoding="utf-8").write(text)
        done += 1
    print(f"written={done} unchanged/missing={skipped} backup={a.backup_dir}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python", "numpy"]
# ///
"""How far a look moved each frame from the camera's own JPEG, and which frames it moved too far.

  look.py ASSHOT_DIR LOOK_DIR SHEET.jpg

Per frame: median L*, near-black share (L* < 10), clipped share (L* > 97), face L* (confident YuNet faces) and
colour strength (90th-percentile chroma; shown, never flagged: no threshold told one shoot's approved frames from
those the photographer wanted calmer). Prints the flagged frames and the medians over all frames, and writes review
sheet(s), flagged frames first: camera JPEG left, look right. Measure before crops: a crop moves the numbers.
"""
import os, sys
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2, numpy as np
from autocrop import COMPOSE, detector, save

# flag past these, look minus camera JPEG. One shoot: the full-strength preset the photographer called "too dark,
# too much edit" measured median L* -3.1, near-black +6.1 points (43 of 60 frames flagged); the look they approved
# +2.7 and -2.1 (3 flagged, one of which they had lifted +0.15 EV by hand).
LIMITS = (("L", -3, "darker"), ("black", 5, "shadows crushed"), ("face", -3, "faces darker"), ("clip", 1, "highlights clipped"))

def stats(img):
    lab = cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_BGR2Lab)
    L = lab[..., 0]
    fl, fw = [], []
    for f in detector(img.shape[1], img.shape[0])(img):
        if f[14] < COMPOSE or f[3] < 30: continue
        p = L[max(int(f[1] + .3 * f[3]), 0):max(int(f[1] + .8 * f[3]), 0),  # inner box: skin, not hair
              max(int(f[0] + .25 * f[2]), 0):max(int(f[0] + .75 * f[2]), 0)]
        if p.size: fl.append(float(np.median(p))); fw.append(f[2] * f[3])
    return {"L": float(np.median(L)), "black": float((L < 10).mean() * 100), "clip": float((L > 97).mean() * 100),
            "C": float(np.percentile(np.hypot(lab[..., 1], lab[..., 2]), 90)),
            "face": float(np.average(fl, weights=fw)) if fl else None}

def main(before, after, out):
    rows = []
    for f in sorted(os.listdir(after)):
        b, a = cv2.imread(os.path.join(before, f)), cv2.imread(os.path.join(after, f))
        if b is None or a is None: print(f"{f}: missing camera JPEG or look", file=sys.stderr); continue
        sb, sa = stats(b), stats(a)
        d = {"L": sa["L"] - sb["L"], "black": sa["black"] - sb["black"], "clip": sa["clip"] - sb["clip"],
             "colour": (sa["C"] / max(sb["C"], 1) - 1) * 100,
             "face": None if None in (sa["face"], sb["face"]) else sa["face"] - sb["face"]}
        flags = [name for k, lim, name in LIMITS if d[k] is not None and (d[k] < lim if lim < 0 else d[k] > lim)]
        rows.append((os.path.splitext(f)[0], d, flags, b, a))
    if not rows: sys.exit("nothing to measure")
    fmt = lambda d: (f"L* {d['L']:+5.1f}  near-black {d['black']:+5.1f}  clipped {d['clip']:+4.1f}  colour {d['colour']:+4.0f}%"
                     + ("" if d["face"] is None else f"  faces {d['face']:+5.1f}"))
    for i, d, flags, _, _ in rows:
        if flags: print(f"{i}  {fmt(d)}  <- {', '.join(flags)}")
    med = {k: float(np.median(v)) if (v := [r[1][k] for r in rows if r[1][k] is not None]) else None for k in rows[0][1]}
    print(f"median   {fmt(med)}   ({sum(bool(r[2]) for r in rows)} of {len(rows)} flagged; vs the camera's JPEGs)")
    tiles = []
    for i, d, flags, b, a in sorted(rows, key=lambda r: not r[2]):
        b, a = (cv2.resize(m, (round(m.shape[1] * 400 / m.shape[0]), 400), interpolation=cv2.INTER_AREA) for m in (b, a))
        t = np.hstack([b, np.full((400, 8, 3), 255, np.uint8), a])
        t = np.vstack([np.full((52, t.shape[1], 3), 255, np.uint8), t])
        for k, s in enumerate((f"{i}  {', '.join(flags) or 'ok'}", fmt(d))):  # shrink to fit narrow tiles
            sc = min(0.5, 0.5 * (t.shape[1] - 12) / cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0])
            cv2.putText(t, s, (6, 20 + 24 * k), cv2.FONT_HERSHEY_SIMPLEX, sc, (0, 0, 200) if flags and not k else (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(t)
    save(tiles, out)

if __name__ == "__main__":
    if len(sys.argv) != 4: sys.exit(__doc__)
    main(*sys.argv[1:])

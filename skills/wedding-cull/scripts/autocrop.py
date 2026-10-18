#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python", "numpy"]
# ///
"""Rule-of-thirds crop proposals -> Camera Raw crop + Upright=Level in the XMP sidecars.

Faces (YuNet) on the oriented previews decide the crop: the eye line goes on the upper third line,
a single subject on the vertical third that leaves room where the face is turned (else the nearer
third). An axis keeps the photographer's composition when reaching its third would cut more than
--min-keep of the frame (e.g. a deliberately centered portrait). Aspect ratio is kept.
Straightening is not measured here: Upright=Level (crs 3) makes Camera Raw compute it at render
time -- rotation + fill-zoom only, no perspective warp (verified in Photoshop 27.8).

  propose --previews DIR --rawdir DIR --out proposals.json   prints ids, writes only the json
  write   --proposals proposals.json --xmpdir DIR             prints ids; back DIR up first!
  sheet   --proposals proposals.json --before DIR --after DIR --out sheet.jpg
"""
import argparse, json, os, subprocess, sys
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2, numpy as np

T = 1 / 3
COMPOSE = 0.85  # YuNet score a face needs to steer the crop; every detection is still protected from cuts
# (tuning set: frontal faces 0.87-0.94; a log end 0.81 and a wall photo panel 0.67 steered crops
#  wrong; a real face in profile scored 0.62 -- so score must never decide what may be cut)
YUNET = os.path.expanduser("~/.cache/wedding-cull/yunet.onnx")  # fetched by `photo.py models`

def fit(p, t):
    """Largest crop (fraction of the axis) that puts position p at fraction t of the crop."""
    return min(p / t, (1 - p) / (1 - t))

def to_sensor(x, y, o):
    """Display-normalized point -> unrotated-sensor-normalized point (Camera Raw crop space)."""
    return {1: (x, y), 3: (1 - x, 1 - y), 6: (y, 1 - x), 8: (1 - y, x)}[o]

def detector(W, H):
    if not os.path.exists(YUNET): sys.exit(f"no {YUNET} - run: uv run photo.py models")
    d = cv2.FaceDetectorYN.create(YUNET, "", (W, H), 0.6, 0.3, 5000)
    return lambda img: [] if (f := d.detect(img)[1]) is None else f.tolist()

def subject(faces, H):
    """Main faces (confident, not background) and their eye line as a fraction of H."""
    conf = [f for f in faces if f[14] >= COMPOSE]
    if not conf: return [], None
    big = max(f[2] * f[3] for f in conf)
    sig = [f for f in conf if f[2] * f[3] >= 0.25 * big]
    return sig, float(np.mean([(f[5] + f[7]) / 2 for f in sig])) / H

def crop_for(faces, W, H, min_keep):
    """faces: YuNet rows [x,y,w,h, reye xy, leye xy, nose xy, mouth xy*2, score] -> (crop|None, why)."""
    sig, ey = subject(faces, H)
    if not sig: return None, "no face - straighten only"
    if max(f[3] for f in sig) < 0.04 * H: return None, "faces too small - straighten only"
    gx0, gx1 = min(f[0] for f in sig), max(f[0] + f[2] for f in sig)
    sx = (gx0 + gx1) / 2 / W
    tx = None                                              # None = keep the composition on that axis
    if len(sig) == 1:
        f = sig[0]; yaw = (f[8] - (f[4] + f[6]) / 2) / max(abs(f[6] - f[4]), 1)  # nose vs eyes: + = faces right
        tx = T if yaw > 0.2 else 2 * T if yaw < -0.2 else (T if sx < 0.5 else 2 * T)
    elif len(sig) == 2 and gx1 - gx0 < W / 3:              # a close pair moves as one; groups keep their x
        tx = T if sx < 0.5 else 2 * T
    ty = T
    s_x = fit(sx, tx) if tx else 1.0
    s_y = fit(ey, ty)
    if s_x < min_keep: tx, s_x = None, 1.0
    if s_y < min_keep: ty, s_y = None, 1.0
    if tx is None and ty is None: return None, "thirds would cut too much - kept as composed"
    s = min(s_x, s_y)
    if s > 0.97: return None, "already on thirds"
    x0 = min(max(sx - tx * s if tx else sx * (1 - s), 0), 1 - s)
    y0 = min(max(ey - ty * s if ty else ey * (1 - s), 0), 1 - s)
    crop = (x0, y0, x0 + s, y0 + s)
    for f in faces:  # never cut through a face (incl. hair/chin margin): fully inside or fully outside
        fx0, fy0 = max(f[0] - .1 * f[2], 0) / W, max(f[1] - .25 * f[3], 0) / H
        fx1, fy1 = min(f[0] + 1.1 * f[2], W) / W, min(f[1] + 1.1 * f[3], H) / H
        inside = fx0 >= crop[0] and fy0 >= crop[1] and fx1 <= crop[2] and fy1 <= crop[3]
        outside = fx1 <= crop[0] or fx0 >= crop[2] or fy1 <= crop[1] or fy0 >= crop[3]
        if not (inside or outside): return None, "crop would cut a face - straighten only"
    where = ["eyes on upper third" if ty else "", f"subject on {'left' if tx == T else 'right'} third" if tx else ""]
    return [round(v, 5) for v in crop], f"crop {s:.0%}: " + ", ".join(w for w in where if w)

def turned(b, f):
    """Degrees the render is rotated vs the original (ORB matches + similarity fit); None if unsure."""
    orb, g = cv2.ORB_create(3000), lambda m: cv2.cvtColor(m, cv2.COLOR_BGR2GRAY)
    (kb, db), (kf, df) = orb.detectAndCompute(g(b), None), orb.detectAndCompute(g(f), None)
    if db is None or df is None: return None
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(db, df)
    if len(m) < 30: return None
    M, inl = cv2.estimateAffinePartial2D(np.float32([kb[x.queryIdx].pt for x in m]),
                                         np.float32([kf[x.trainIdx].pt for x in m]))
    return None if M is None or inl.sum() < 30 else float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))

def propose(a):
    rows = json.loads(subprocess.check_output(["exiftool", "-j", "-n", "-Orientation", "-Rating", "-HasCrop",
                                               "-PerspectiveUpright", "-ext", "CR3", "-ext", "xmp", a.rawdir]))
    stem = lambda d: os.path.splitext(os.path.basename(d["SourceFile"]))[0]
    raw = {stem(d): d for d in rows if d["SourceFile"].lower().endswith(".cr3")}
    xmp = {stem(d): d for d in rows if d["SourceFile"].lower().endswith(".xmp")}
    out = {}
    for i in sorted(set(raw) & set(xmp)):
        x = xmp[i]
        if x.get("Rating", 0) < a.min_rating: continue
        if str(x.get("HasCrop")).lower() in ("true", "1") or x.get("PerspectiveUpright", 0):
            print(f"{i}: already cropped/straightened by hand - left alone", file=sys.stderr); continue
        img = cv2.imread(os.path.join(a.previews, i + ".jpg"))
        if img is None: print(f"{i}: no preview - skipped", file=sys.stderr); continue
        H, W = img.shape[:2]
        crop, why = crop_for(detector(W, H)(img), W, H, a.min_keep)
        out[i] = {"orient": raw[i].get("Orientation", 1), "crop": crop, "why": why}
        print(i)
    json.dump(out, open(a.out, "w"), indent=1)

def write(a):
    lines = []
    for i, p in json.load(open(a.proposals)).items():
        tags = ["-XMP-crs:PerspectiveUpright=Level"]
        if p["crop"]:
            (l, t), (r, b) = to_sensor(*p["crop"][:2], p["orient"]), to_sensor(*p["crop"][2:], p["orient"])
            tags += ["-XMP-crs:HasCrop=True", "-XMP-crs:CropAngle=0"] + [f"-XMP-crs:{k}={v:.6f}" for k, v in (
                ("CropLeft", min(l, r)), ("CropRight", max(l, r)), ("CropTop", min(t, b)), ("CropBottom", max(t, b)))]
        lines += ["-q", "-overwrite_original", *tags, os.path.join(a.xmpdir, i + ".xmp"), "-execute"]
        print(i)
    subprocess.run(["exiftool", "-@", "-"], input="\n".join(lines) + "\n", text=True, check=True)

def sheet(a):
    tiles = []
    for i, p in sorted(json.load(open(a.proposals)).items()):
        b, f = cv2.imread(os.path.join(a.before, i + ".jpg")), cv2.imread(os.path.join(a.after, i + ".jpg"))
        if b is None or f is None: print(f"{i}: missing before/after", file=sys.stderr); continue
        meas = []
        if p["crop"]:  # check: where did the eye line actually land in Camera Raw's render? (target 0.33)
            _, ey = subject(detector(f.shape[1], f.shape[0])(f), f.shape[0])
            if ey is not None: meas.append(f"eye line {ey:.2f}")
        r = turned(b, f)
        meas.append("turned ?" if r is None else f"turned {abs(r):.1f} deg")
        b, f = (cv2.resize(m, (round(m.shape[1] * 400 / m.shape[0]), 400), interpolation=cv2.INTER_AREA) for m in (b, f))
        h, w = f.shape[:2]
        for k in (1, 2):  # thirds grid on the result
            cv2.line(f, (w * k // 3, 0), (w * k // 3, h), (255, 255, 255), 1)
            cv2.line(f, (0, h * k // 3), (w, h * k // 3), (255, 255, 255), 1)
        t = np.hstack([b, np.full((h, 8, 3), 255, np.uint8), f])
        t = np.vstack([np.full((52, t.shape[1], 3), 255, np.uint8), t])
        for k, s in enumerate((f"{i}  {p['why']}", "rendered: " + ", ".join(meas))):  # shrink to fit narrow tiles
            sc = min(0.5, 0.5 * (t.shape[1] - 12) / cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0])
            cv2.putText(t, s, (6, 20 + 24 * k), cv2.FONT_HERSHEY_SIMPLEX, sc, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(t)
    Wm = max(t.shape[1] for t in tiles)
    tiles = [np.pad(t, ((0, 10), (0, Wm - t.shape[1] + 10), (0, 0)), constant_values=255) for t in tiles]
    if len(tiles) % 2: tiles.append(np.full_like(tiles[0], 255))
    cv2.imwrite(a.out, np.vstack([np.hstack(tiles[k:k + 2]) for k in range(0, len(tiles), 2)]),
                [cv2.IMWRITE_JPEG_QUALITY, 85])

def selftest():
    assert abs(fit(0.5, T) - 0.75) < 1e-9 and abs(fit(0.4, T) - 0.9) < 1e-9
    assert to_sensor(0.2, 0.3, 8) == (0.7, 0.2) and to_sensor(0.2, 0.3, 6) == (0.3, 0.8)
    face = lambda cx, cy, s, nose=0.0, score=0.9: [cx - s / 2, cy - s / 2, s, s, cx - s / 4, cy - s / 8, cx + s / 4,
                                                   cy - s / 8, cx + nose * s / 2, cy + s / 8, 0, 0, 0, 0, score]
    crop, _ = crop_for([face(680, 420, 120)], 1500, 1000, 0.8)  # eyes at y=405 (0.405 H), left of center
    s = crop[2] - crop[0]; eyes = (405 / 1000 - crop[1]) / s; subj = (680 / 1500 - crop[0]) / s
    assert abs(eyes - T) < 1e-3 and abs(subj - T) < 1e-3, (eyes, subj)
    assert crop_for([face(680, 420, 120), face(1300, 500, 70, score=0.65)], 1500, 1000, 0.8)[0] == crop  # junk: no steer
    assert crop_for([face(750, 300, 120)], 1500, 1000, 0.8)[1].endswith("upper third")  # centered: x kept
    assert crop_for([face(680, 420, 120), face(270, 500, 40, score=0.62)], 1500, 1000, 0.8)[1].startswith("crop would cut")  # profile: protected
    assert "subject" not in crop_for([face(x, 400, 80) for x in (600, 700, 800)], 1500, 1000, 0.8)[1]  # group: x kept
    assert crop_for([], 1500, 1000, 0.8)[0] is None
    print("selftest ok")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["propose", "write", "sheet", "selftest"])
    ap.add_argument("--previews"); ap.add_argument("--rawdir"); ap.add_argument("--proposals")
    ap.add_argument("--xmpdir"); ap.add_argument("--before"); ap.add_argument("--after"); ap.add_argument("--out")
    ap.add_argument("--min-rating", type=int, default=4)
    ap.add_argument("--min-keep", type=float, default=0.8, help="smallest crop allowed, as fraction of width/height")
    a = ap.parse_args()
    {"propose": propose, "write": write, "sheet": sheet, "selftest": lambda _: selftest()}[a.cmd](a)

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
Straightening is not set here: Upright=Level (crs 3) makes Camera Raw compute it at render
time -- rotation + fill-zoom only, no perspective warp (verified in Photoshop 27.8). `level` then
keeps it only on frames where that rotation measurably levels the as-shot frame.

  propose --previews DIR --rawdir DIR --out proposals.json   prints ids, writes only the json
  write   --proposals proposals.json --xmpdir DIR             prints ids; back DIR up first!
  level   --proposals proposals.json --before DIR --after DIR
          before = the camera's own JPEGs; sets "level" per frame, prints the ids to re-render (crop, no Level)
  sheet   --proposals proposals.json --before DIR --after DIR --out sheet.jpg
          prints the files written: sheet.jpg, or sheet-1.jpg, sheet-2.jpg ... past PAGE frames
"""
import argparse, json, os, subprocess, sys, tempfile
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2, numpy as np

T = 1 / 3
COMPOSE = 0.85  # YuNet score a face needs to steer the crop; every detection is still protected from cuts
# (tuning set: frontal faces 0.87-0.94; a log end 0.81 and a wall photo panel 0.67 steered crops
#  wrong; a real face in profile scored 0.62 -- so score must never decide what may be cut)
YUNET = os.path.expanduser("~/.cache/wedding-cull/yunet.onnx")  # fetched by `photo.py models`
PAGE = 50  # frames per sheet file: a JPEG can't be taller than 65,535 px, about 280 frames

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

def roll(img):
    """Camera roll in degrees from the long near-vertical lines; None below 4 lines. Pitch makes true verticals
    lean in proportion to their distance from the centre column, so fit lean(x) = k*(x - 0.5) + roll."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    segs = cv2.createLineSegmentDetector().detect(g)[0]
    v = []
    for x1, y1, x2, y2 in ([] if segs is None else segs.reshape(-1, 4)):
        n, a = np.hypot(x2 - x1, y2 - y1), (np.degrees(np.arctan2(x2 - x1, y2 - y1)) + 90) % 180 - 90  # 0 = vertical
        if n > .08 * h and abs(a) < 15: v.append(((x1 + x2) / 2 / w - .5, a, n))
    if len(v) < 4: return None
    x, y, wt = (np.array(c) for c in zip(*v))
    keep = np.ones(len(v), bool)
    for _ in range(4):  # length-weighted least squares, dropping lines that aren't the scene's verticals
        sw = np.sqrt(wt[keep])
        k, r = np.linalg.lstsq(np.vstack([x[keep], np.ones(keep.sum())]).T * sw[:, None], y[keep] * sw, rcond=None)[0]
        res = np.abs(y - (k * x + r))
        new = res < max(1.0, 2.5 * np.median(res[keep]))
        if (new == keep).all() or new.sum() < 4: break
        keep = new
    return float(r)

def keep_level(r, t):
    """Level stays only if its visible turn t moves the as-shot roll r at least 0.3 deg closer to level.
    (one shoot: this kept all 9 frames Level visibly fixed and dropped all 7 the photographer undid --
    converging verticals, slanted screens, a car interior, a night scene with no true level)"""
    return None not in (r, t) and abs(t) >= 0.3 and abs(r - t) <= abs(r) - 0.3

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
        if not (p["crop"] or p.get("level", True)): continue  # left as shot
        tags = ["-XMP-crs:PerspectiveUpright=Level"] if p.get("level", True) else []
        if p["crop"]:
            (l, t), (r, b) = to_sensor(*p["crop"][:2], p["orient"]), to_sensor(*p["crop"][2:], p["orient"])
            tags += ["-XMP-crs:HasCrop=True", "-XMP-crs:CropAngle=0"] + [f"-XMP-crs:{k}={v:.6f}" for k, v in (
                ("CropLeft", min(l, r)), ("CropRight", max(l, r)), ("CropTop", min(t, b)), ("CropBottom", max(t, b)))]
        lines += ["-q", "-overwrite_original", *tags, os.path.join(a.xmpdir, i + ".xmp"), "-execute"]
        print(i)
    if lines:  # with no arguments exiftool prints its manual, which apply would read as ids
        subprocess.run(["exiftool", "-@", "-"], input="\n".join(lines) + "\n", text=True, check=True)

def level(a):
    props, redo = json.load(open(a.proposals)), []
    for i, p in props.items():
        b, f = cv2.imread(os.path.join(a.before, i + ".jpg")), cv2.imread(os.path.join(a.after, i + ".jpg"))
        if b is None or f is None: sys.exit(f"{i}: missing before/after")
        r, t = roll(b), turned(b, f)
        p["level"] = keep_level(r, t)
        if p["level"]: continue
        p["why"] += f" - not straightened: as shot {'?' if r is None else f'{r:+.1f}'} deg, Level turned {'?' if t is None else f'{t:+.1f}'} deg"
        if p["crop"]: redo.append(i)
    json.dump(props, open(a.proposals, "w"), indent=1)
    if redo: print("\n".join(redo))  # an empty line would read as one blank id

def sheet(a):
    tiles = []
    for i, p in sorted(json.load(open(a.proposals)).items()):
        if not (p["crop"] or p.get("level", True)): continue  # left as shot: nothing to review
        b, f = cv2.imread(os.path.join(a.before, i + ".jpg")), cv2.imread(os.path.join(a.after, i + ".jpg"))
        if b is None or f is None: print(f"{i}: missing before/after", file=sys.stderr); continue
        meas = []
        if p["crop"]:  # check: where did the eye line actually land in Camera Raw's render? (target 0.33)
            _, ey = subject(detector(f.shape[1], f.shape[0])(f), f.shape[0])
            if ey is not None: meas.append(f"eye line {ey:.2f}")
        r = turned(b, f)
        meas.append("turned ?" if r is None else f"turned {abs(r):.1f} deg")
        if p["crop"]:  # dim what the crop cuts: names, logos, slides and hands at the edge are easy to miss
            H, W = b.shape[:2]
            x0, y0, x1, y1 = (round(v * s) for v, s in zip(p["crop"], (W, H, W, H)))
            dim = (b * 0.35).astype(np.uint8)
            dim[y0:y1, x0:x1] = b[y0:y1, x0:x1]
            b = dim
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
    save(tiles, a.out)

def save(tiles, path):
    """Same-height tiles two per row into PAGE-frame JPEG pages; prints each file written."""
    if not tiles: return
    Wm = max(t.shape[1] for t in tiles)
    tiles = [np.pad(t, ((0, 10), (0, Wm - t.shape[1] + 10), (0, 0)), constant_values=255) for t in tiles]
    if len(tiles) % 2: tiles.append(np.full_like(tiles[0], 255))
    rows = [np.hstack(tiles[k:k + 2]) for k in range(0, len(tiles), 2)]
    pages = [rows[k:k + PAGE // 2] for k in range(0, len(rows), PAGE // 2)]
    stem, ext = os.path.splitext(path)
    for n, page in enumerate(pages, 1):
        out = path if len(pages) == 1 else f"{stem}-{n}{ext}"
        if not cv2.imwrite(out, np.vstack(page), [cv2.IMWRITE_JPEG_QUALITY, 85]): sys.exit(f"could not write {out}")
        print(out)

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
    rng, img = np.random.default_rng(1), np.full((1000, 1500, 3), 128, np.uint8)  # a scene of upright blocks
    for _ in range(60):
        x, y, w, h = rng.integers(0, 1400), rng.integers(0, 900), rng.integers(20, 100), rng.integers(90, 300)
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), [int(c) for c in rng.integers(0, 255, 3)], -1)
    tilted = cv2.warpAffine(img, cv2.getRotationMatrix2D((750, 500), 2, 1.1), (1500, 1000), borderValue=(128, 128, 128))
    r0, r1, t = roll(img), roll(tilted), turned(img, tilted)
    assert abs(r0) < 0.2 and abs(abs(t) - 2) < 0.2 and abs(r1 - (r0 - t)) < 0.3, (r0, r1, t)  # the sign keep_level relies on
    assert keep_level(r1, turned(tilted, img)) and not keep_level(r0, t)  # levelling the tilted copy helps; tilting the level one doesn't
    with tempfile.TemporaryDirectory() as d:  # nothing to re-render or write: no output, which photo.py would read as ids
        cli = lambda *c: subprocess.run([sys.executable, __file__, *c, "--proposals", f"{d}/p.json"],
                                        capture_output=True, text=True, check=True).stdout
        os.mkdir(f"{d}/b"); os.mkdir(f"{d}/a"); cv2.imwrite(f"{d}/b/x.jpg", tilted); cv2.imwrite(f"{d}/a/x.jpg", img)
        json.dump({"x": {"crop": None, "why": ""}}, open(f"{d}/p.json", "w"))
        assert cli("level", "--before", f"{d}/b", "--after", f"{d}/a") == "" and json.load(open(f"{d}/p.json"))["x"]["level"]
        json.dump({"x": {"crop": None, "level": False}}, open(f"{d}/p.json", "w"))
        o = cli("write", "--xmpdir", d)
        assert o == "", o[:200]
    print("selftest ok")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["propose", "write", "level", "sheet", "selftest"])
    ap.add_argument("--previews"); ap.add_argument("--rawdir"); ap.add_argument("--proposals")
    ap.add_argument("--xmpdir"); ap.add_argument("--before"); ap.add_argument("--after"); ap.add_argument("--out")
    ap.add_argument("--min-rating", type=int, default=4)
    ap.add_argument("--min-keep", type=float, default=0.8, help="smallest crop allowed, as fraction of width/height")
    a = ap.parse_args()
    {"propose": propose, "write": write, "level": level, "sheet": sheet, "selftest": lambda _: selftest()}[a.cmd](a)

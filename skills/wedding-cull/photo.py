#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""One entry point for finishing culled Canon RAWs: `uv run photo.py JOB ...`, from any folder.
RAWs are never touched: jobs write only XMP sidecars (backed up first, ratings/labels checked after)
or render JPGs through Photoshop/Camera Raw.

  preset   RAWDIR PRESET.xmp [MIN]  look preset + lens correction on sidecars rated >= MIN (default 4)
  crop     RAWDIR [MIN]             thirds crop + straighten proposals -> review sheet, writes nothing
  apply    RAWDIR OUTDIR            write the reviewed proposals, export those frames as JPGs
  export   RAWDIR OUTDIR [MIN]      JPGs of every CR3 rated >= MIN, rendered from its sidecar
  previews RAWDIR                   1600px oriented JPEG of every CR3 into previews/ (crop runs this too)
  decode   RAWDIR ID...             2560px oriented JPEGs of single frames, for the verify pass
  keyword  RAWDIR FRAMES KEY WORD   cull write-back: Lightroom keyword WORD on the frames in FRAMES.json[KEY]
  label    RAWDIR FRAMES KEY COLOR  the same as a colour label, overwriting the culling app's
  models                            fetch the face models (crop runs this too; scripts/blink.py needs them)
  selftest                          preset, write-back, backup and rating guard on synthetic sidecars

A RAW folder's work files live in ~/Downloads/wedding-cull/<folder>-<6 hex of its full path>/:
previews/, verify/, proposals.json, the review sheet(s) and xmp_backup_<YYYY-MM-DD>/. Jobs print it.
JPGs: 5088px long edge, Photoshop quality 11, sRGB.
"""
import argparse, hashlib, json, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from os import cpu_count
from pathlib import Path

S = Path(__file__).resolve().parent / "scripts"
AC = ("uv", "run", "-q", S / "autocrop.py")
JPG = 5088, 11  # long edge px, Photoshop JPEG quality
MODELS = Path.home() / ".cache/wedding-cull"
# preset bookkeeping, not develop settings: never copied, and not expected in the sidecars afterwards
META = ["PresetType", "Cluster", "UUID", "SupportsAmount", "SupportsColor", "SupportsMonochrome", "SupportsHDR",
        "SupportsSceneReferred", "SupportsOutputReferred", "CameraModelRestriction", "Copyright", "ContactInfo",
        "Name", "ShortName", "Group"]
# ponytail: exiftool silently drops crs tags it doesn't know; these are copied by hand.
# Extend the list if preset reports others missing.
BY_HAND = ["ColorVariance", "CurveRefineSaturation"]

def run(*cmd, **kw):  # a failing tool stops the job
    return subprocess.run([str(c) for c in cmd], check=True, text=True, **kw)

def out(*cmd):
    return run(*cmd, stdout=subprocess.PIPE).stdout

def workdir(raw):  # keyed by the full path: same-named folders (two cards' 100EOSR5) never share files
    return Path.home() / "Downloads/wedding-cull" / f"{raw.name}-{hashlib.sha1(str(raw).encode()).hexdigest()[:6]}"

def models():  # fetched once, checksum-pinned
    MODELS.mkdir(parents=True, exist_ok=True)
    for name, sha, url in (
            ("yunet.onnx", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
             "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
            ("face_landmarker.task", "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
             "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task")):
        f = MODELS / name
        if not f.exists():
            run("curl", "-fsSL", "-o", f"{f}.part", url)
            Path(f"{f}.part").rename(f)
        if hashlib.sha256(f.read_bytes()).hexdigest() != sha:
            f.unlink()
            sys.exit(f"{name}: checksum mismatch, removed")

def rated(raw, n):  # sidecars rated >= n
    r = subprocess.run(["exiftool", "-q", "-if", f"$XMP:Rating >= {n}", "-p", "$Directory/$FileName", "-ext", "xmp", raw],
                       stdout=subprocess.PIPE, text=True)
    if r.returncode not in (0, 2): sys.exit(f"exiftool failed reading {raw}")  # 2 = no sidecar passed -if
    return [Path(p) for p in r.stdout.splitlines()]

def existing(fs, what):  # the files that exist; each missing one is named
    for f in fs:
        if not f.exists(): print(f"skip {f.stem}: no {what}")
    return [f for f in fs if f.exists()]

def marks(raw, keep):  # every sidecar's file name and the tags in keep
    return sorted(out("exiftool", "-q", "-T", "-FileName", *(f"-{t}" for t in keep), "-ext", "xmp", raw).splitlines())

def guarded(raw, work, write, keep=("Rating", "Label")):
    """Back every sidecar up (the day's first copy is kept), write, then check no rating or label moved."""
    b = work / f"xmp_backup_{date.today()}"
    b.mkdir(parents=True, exist_ok=True)
    before = marks(raw, keep)
    for name in (m.split("\t")[0] for m in before):  # the sidecars exiftool sees: every one a job can write
        if not (b / name).exists(): shutil.copy2(raw / name, b)
    print(f"backup: {b}")
    try: return write()
    finally:
        if marks(raw, keep) != before: sys.exit(f"RATING/LABEL CHANGED - restore the sidecars from {b}")

def preset(raw, work, look, n):
    files = rated(raw, n)
    if not files: sys.exit(f"no sidecars rated >= {n}")
    tags = lambda s: set(re.findall(r"crs:[A-Za-z0-9]+", s))
    want = tags(look.read_text()) - {f"crs:{t}" for t in META}  # every setting, none of the preset's bookkeeping
    # read by exiftool: a preset saved by exiftool (a copy without some tags) has them as elements, not attributes
    by_hand = {t: v for t, v in zip(BY_HAND, out("exiftool", "-T", "-n", *(f"-{t}" for t in BY_HAND), look)
                                    .rstrip("\n").split("\t")) if v not in ("-", "")}
    def write():
        run("exiftool", "-q", "-overwrite_original", "-tagsFromFile", look, "-XMP-crs:all", *[f"--{t}" for t in META],
            "-XMP-crs:LensProfileEnable=1", "-XMP-crs:LensProfileSetup=LensDefaults", "-XMP-crs:AutoLateralCA=1", *files)
        for f in files:
            x = f.read_bytes().decode()
            for t, v in by_hand.items():
                if f"crs:{t}" not in x:
                    x = x.replace("<crs:AutoLateralCA>", f"<crs:{t}>{v}</crs:{t}>\n  <crs:AutoLateralCA>", 1)
            f.write_bytes(x.encode())
            miss = sorted(want - tags(x))  # check: every setting landed
            if miss: sys.exit(f"MISSING in {f}: {' '.join(miss)}")
    guarded(raw, work, write)
    print(f"ok: {len(files)} sidecars updated")

def tag(raw, work, frames, key, value, label):
    """Cull write-back: keyword (added to dc:subject) or colour label on the sidecars of the frames in FRAMES[KEY]."""
    files = existing([raw / f"{v['id']}.xmp" for v in json.loads(frames.read_text())[key]], "sidecar")
    if not files: sys.exit("no sidecars to write")
    # removing the keyword before adding it keeps a rerun from listing it twice
    tags = [f"-XMP-xmp:Label={value}"] if label else [f"-XMP-dc:Subject-={value}", f"-XMP-dc:Subject+={value}"]
    guarded(raw, work, lambda: run("exiftool", "-q", "-overwrite_original", *tags, *files),
            ("Rating",) if label else ("Rating", "Label"))
    print(f"ok: {len(files)} sidecars updated")

def orient(raw, dest, size, quality, ids=None):
    """RAW -> oriented JPEG per id, resumable. sips leaves a portrait CR3 as landscape pixels plus an
    orientation tag; magick -auto-orient bakes it into the pixels (hard-won: NEVER -rotate)."""
    if ids is None: ids = [f.stem for f in sorted(raw.iterdir()) if f.suffix.lower() == ".cr3"]
    dest.mkdir(parents=True, exist_ok=True)
    def one(i):
        src, dst = raw / f"{i}.CR3", dest / f"{i}.jpg"
        if dst.exists() and dst.stat().st_size: return None
        if not src.exists(): return f"{i} (no CR3)"
        with tempfile.TemporaryDirectory() as t:
            ok = not subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(size), src, "--out", f"{t}/x.jpg"],
                                    capture_output=True).returncode and \
                 not subprocess.run(["magick", f"{t}/x.jpg", "-auto-orient", "-resize", f"{size}x{size}>",
                                     "-quality", str(quality), dst], capture_output=True).returncode
        if not ok: dst.unlink(missing_ok=True)
        return None if ok else i
    with ThreadPoolExecutor(cpu_count()) as ex:
        failed = [f for f in ex.map(one, ids) if f]
    print(f"{len(ids) - len(failed)} oriented JPEGs in {dest}" + (f"; FAILED: {', '.join(failed)}" if failed else ""))

def render(dest, size, quality, raws):
    """Photoshop renders each RAW through Camera Raw with its sidecar (develop, crop, Upright) -> sRGB <id>.jpg.
    The script text goes inline: `do javascript <file alias>` fails with error 8800. Addressed by bundle id,
    because the app name carries the release year."""
    if not raws: return
    dest.mkdir(parents=True, exist_ok=True)
    r = out("osascript", "-e", "on run argv", "-e", "with timeout of 7200 seconds", "-e",
            'tell application id "com.adobe.Photoshop" to do javascript (read POSIX file (item 1 of argv)) with arguments (rest of argv)',
            "-e", "end timeout", "-e", "end run", S / "ps_render.jsx", dest, size, quality, *raws).strip()
    print(r)
    if "FAIL" in r: sys.exit("some frames did not render")

def previews(raw, work, ids=None):  # one size for the cache that crop, the cull's metrics and its screens share
    orient(raw, work / "previews", 1600, 88, ids)

def clone(src, dst):  # APFS clone: instant and takes no space; a plain copy where cloning can't work
    if subprocess.run(["cp", "-c", src, dst], stderr=subprocess.DEVNULL).returncode: shutil.copy(src, dst)

def crop(raw, work, n):
    models()
    raws = existing([x.with_suffix(".CR3") for x in rated(raw, n)], "CR3")
    previews(raw, work, [r.stem for r in raws])  # all that propose reads
    props = work / "proposals.json"
    ids = out(*AC, "propose", "--previews", work / "previews", "--rawdir", raw, "--min-rating", n, "--out", props).splitlines()
    if not ids: print("nothing to propose"); return
    # stage RAW clones + edited sidecars and render them with the real engine: the sheet shows what apply writes
    stage, after = work / "stage", work / "after"  # a symlinked CR3 would save the copy, but Photoshop refuses to open one
    for d in (stage, after): shutil.rmtree(d, ignore_errors=True)  # a killed run's stage too
    stage.mkdir()
    try:
        for i in ids:
            clone(raw / f"{i}.CR3", stage); shutil.copy(raw / f"{i}.xmp", stage)
        run(*AC, "write", "--proposals", props, "--xmpdir", stage, stdout=subprocess.DEVNULL)
        render(after, 1600, 8, [stage / f"{i}.CR3" for i in ids])
    finally: shutil.rmtree(stage)  # even when a render fails: across volumes, clones are full copies
    for f in work.glob("sheet*.jpg"): f.unlink()  # a rerun with fewer pages leaves none behind
    sheets = out(*AC, "sheet", "--proposals", props, "--before", work / "previews", "--after", after,
                 "--out", work / "sheet.jpg").splitlines()
    print(f"\nreview: {'  '.join(sheets)}\n(left = as shot, right = proposed result with thirds grid)")

def apply(raw, work, dest):
    props = work / "proposals.json"
    if not props.exists(): sys.exit(f"no proposals for {raw}: run crop first")
    ids = guarded(raw, work, lambda: out(*AC, "write", "--proposals", props, "--xmpdir", raw).splitlines())
    render(dest, *JPG, [raw / f"{i}.CR3" for i in ids])
    print(f"\nok: {len(ids)} sidecars updated, JPGs in {dest}")

def export(raw, dest, n):
    raws = existing([x.with_suffix(".CR3") for x in rated(raw, n)], "CR3")
    render(dest, *JPG, raws)
    print(f"\nok: {len(raws)} JPGs in {dest}")

def selftest():
    xmp = lambda attrs: ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                         f'<rdf:Description rdf:about="" {attrs}/></rdf:RDF></x:xmpmeta>\n')
    rating = lambda n: f'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="{n}" xmp:Label="Blue"'
    with tempfile.TemporaryDirectory() as t:
        raw, work, look = Path(t) / "raw", Path(t) / "work", Path(t) / "look.xmp"
        raw.mkdir()
        (raw / "a.xmp").write_text(xmp(rating(5))); (raw / "b.xmp").write_text(xmp(rating(3)))
        (raw / "c.XMP").write_text(xmp(rating(5)))  # written too, so it must be in the backup
        look.write_text(xmp('xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" crs:PresetType="Normal" '
                            'crs:Contrast2012="+20" crs:ColorVariance="7"'))
        orig = {f.name: f.read_bytes() for f in raw.iterdir()}
        preset(raw, work, look, 4); preset(raw, work, look, 4)  # a rerun changes nothing and keeps the first backup
        a = (raw / "a.xmp").read_text()
        assert "crs:Contrast2012" in a and "crs:LensProfileEnable" in a and "PresetType" not in a, a
        assert a.count("<crs:ColorVariance>7</crs:ColorVariance>") == 1, a
        assert (raw / "b.xmp").read_bytes() == orig["b.xmp"]  # rated 3: untouched
        assert {f.name: f.read_bytes() for f in (work / f"xmp_backup_{date.today()}").iterdir()} == orig
        el, copy = Path(t) / "el", Path(t) / "copy.xmp"  # a preset copy saved by exiftool has elements, not attributes
        el.mkdir(); (el / "d.xmp").write_text(xmp(rating(5)))
        run("exiftool", "-q", "-o", copy, "-XMP-crs:PresetType=", look)
        preset(el, work, copy, 4)
        assert "<crs:ColorVariance>7</crs:ColorVariance>" in (el / "d.xmp").read_text()
        frames = Path(t) / "tiers.json"
        frames.write_text('{"tier1_must_have": [{"id": "a"}, {"id": "gone"}]}')
        for _ in range(2): tag(raw, work, frames, "tier1_must_have", "cull/must_have", False)  # rerun: listed once
        tag(raw, work, frames, "tier1_must_have", "Red", True)  # label may move, the rating may not
        a = (raw / "a.xmp").read_text()
        assert a.count("cull/must_have") == 1 and "<xmp:Label>Red</xmp:Label>" in a, a
        try: guarded(raw, work, lambda: run("exiftool", "-q", "-overwrite_original", "-XMP-xmp:Rating=1", raw / "a.xmp"))
        except SystemExit as e: assert "RATING/LABEL CHANGED" in str(e)
        else: raise AssertionError("rating change not caught")
    assert workdir(Path("/a/100EOSR5")) != workdir(Path("/b/100EOSR5"))
    print("selftest ok")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    jobs = ap.add_subparsers(dest="job", required=True)
    for job, args in (("preset", "rawdir look min"), ("crop", "rawdir min"), ("apply", "rawdir outdir"),
                      ("export", "rawdir outdir min"), ("previews", "rawdir"), ("decode", "rawdir ids"),
                      ("keyword", "rawdir frames key value"), ("label", "rawdir frames key value"),
                      ("models", ""), ("selftest", "")):
        p = jobs.add_parser(job)
        for arg in args.split():
            if arg == "min": p.add_argument("min", type=int, nargs="?", default=4, help="lowest rating (default 4)")
            elif arg == "ids": p.add_argument("ids", nargs="+")
            elif arg in ("key", "value"): p.add_argument(arg)
            else: p.add_argument(arg, type=Path)
    a = ap.parse_args()
    if a.job == "models": models(); print(f"ok: models in {MODELS}"); sys.exit()
    if a.job == "selftest": selftest(); sys.exit()
    raw = a.rawdir.resolve()
    if not raw.is_dir(): sys.exit(f"not a folder: {a.rawdir}")
    work = workdir(raw)
    dest = a.outdir.resolve() if "outdir" in a else None  # absolute: Photoshop would resolve a relative one elsewhere
    if a.job == "preset": preset(raw, work, a.look, a.min)
    elif a.job == "crop": crop(raw, work, a.min)
    elif a.job == "apply": apply(raw, work, dest)
    elif a.job == "export": export(raw, dest, a.min)
    elif a.job == "previews": previews(raw, work)
    elif a.job == "decode": orient(raw, work / "verify", 2560, 90, a.ids)
    elif a.job in ("keyword", "label"): tag(raw, work, a.frames, a.key, a.value, a.job == "label")
    if a.job != "export": print(f"work folder: {work}")

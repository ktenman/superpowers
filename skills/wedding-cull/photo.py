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
  previews RAWDIR                   1600px oriented JPEG of every CR3 for the cull (crop makes its own)
  decode   RAWDIR ID...             2560px oriented JPEGs of single frames, for the verify pass
  models                            fetch the face models for scripts/blink.py (crop fetches its own)
  selftest                          preset, backup and rating guard on synthetic sidecars

A RAW folder's work files live in ~/Downloads/wedding-cull/<folder>-<6 hex of its full path>/:
previews/, verify/, proposals.json, sheet.jpg and xmp_backup_<date>/. Jobs print it.
JPGs: 5088px long edge, Photoshop quality 11, sRGB.
"""
import argparse, hashlib, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from os import cpu_count
from pathlib import Path

S = Path(__file__).resolve().parent / "scripts"
MODELS = Path.home() / ".cache/wedding-cull"
PHOTOSHOP = "Adobe Photoshop 2026"  # ponytail: hardcoded; change it when the year in the app name changes
# preset bookkeeping, not develop settings: never copied, and not expected in the sidecars afterwards
META = ["PresetType", "Cluster", "UUID", "SupportsAmount", "SupportsColor", "SupportsMonochrome", "SupportsHDR",
        "SupportsSceneReferred", "SupportsOutputReferred", "CameraModelRestriction", "Copyright", "ContactInfo",
        "Name", "ShortName", "Group"]
NOT_EXPECTED = re.compile(r"PresetType|Cluster|UUID|Supports|CameraModelRestriction|Copyright|ContactInfo|Name$|Group")
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

def marks(raw):  # every sidecar's rating and colour label
    return sorted(out("exiftool", "-q", "-T", "-FileName", "-Rating", "-Label", "-ext", "xmp", raw).splitlines())

def guarded(raw, work, write):
    """Back every sidecar up (the day's first copy is kept), write, then check no rating or label moved."""
    b = work / f"xmp_backup_{date.today()}"
    b.mkdir(parents=True, exist_ok=True)
    for x in raw.glob("*.xmp"):
        if not (b / x.name).exists(): shutil.copy2(x, b)
    before = marks(raw)
    print(f"backup: {b}")
    try: return write()
    finally:
        if marks(raw) != before: sys.exit(f"RATING/LABEL CHANGED - restore the sidecars from {b}")

def preset(raw, work, look, n):
    files = rated(raw, n)
    if not files: sys.exit(f"no sidecars rated >= {n}")
    p = look.read_text()
    tags = lambda s: set(re.findall(r"crs:[A-Za-z0-9]+", s))
    def write():
        run("exiftool", "-q", "-overwrite_original", "-tagsFromFile", look, "-XMP-crs:all", *[f"--{t}" for t in META],
            "-XMP-crs:LensProfileEnable=1", "-XMP-crs:LensProfileSetup=LensDefaults", "-XMP-crs:AutoLateralCA=1", *files)
        for f in files:
            x = f.read_bytes().decode()
            for t in BY_HAND:
                v = re.search(f'crs:{t}="([^"]*)"', p)
                if v and v[1] and f"crs:{t}" not in x:
                    x = x.replace("<crs:AutoLateralCA>", f"<crs:{t}>{v[1]}</crs:{t}>\n  <crs:AutoLateralCA>", 1)
            f.write_bytes(x.encode())
            miss = sorted(t for t in tags(p) - tags(x) if not NOT_EXPECTED.search(t))  # check: every setting landed
            if miss: sys.exit(f"MISSING in {f}: {' '.join(miss)}")
    guarded(raw, work, write)
    print(f"ok: {len(files)} sidecars updated")

def orient(raw, dest, size, quality, ids=None):
    """RAW -> oriented JPEG per id, resumable. sips leaves a portrait CR3 as landscape pixels plus an
    orientation tag; magick -auto-orient bakes it into the pixels (hard-won: NEVER -rotate)."""
    ids = ids or [f.stem for f in sorted(raw.glob("*.CR3"))]
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
    The script text goes inline: `do javascript <file alias>` fails with error 8800."""
    if not raws: return
    dest.mkdir(parents=True, exist_ok=True)
    r = out("osascript", "-e", "on run argv", "-e", "with timeout of 7200 seconds", "-e",
            f'tell application "{PHOTOSHOP}" to do javascript (read POSIX file (item 1 of argv)) with arguments (rest of argv)',
            "-e", "end timeout", "-e", "end run", S / "ps_render.jsx", dest, size, quality, *raws).strip()
    print(r)
    if "FAIL" in r: sys.exit("some frames did not render")

def clone(src, dst):  # APFS clone: instant and takes no space; a plain copy where cloning can't work
    if subprocess.run(["cp", "-c", src, dst], stderr=subprocess.DEVNULL).returncode: shutil.copy(src, dst)

def crop(raw, work, n):
    models()
    orient(raw, work / "previews", 1600, 88)
    ac, props = ("uv", "run", "-q", S / "autocrop.py"), work / "proposals.json"
    ids = out(*ac, "propose", "--previews", work / "previews", "--rawdir", raw, "--min-rating", n, "--out", props).splitlines()
    if not ids: print("nothing to propose"); return
    # stage RAW clones + edited sidecars and render them with the real engine: the sheet shows what apply writes
    stage, after = work / "stage", work / "after"
    shutil.rmtree(stage, ignore_errors=True); shutil.rmtree(after, ignore_errors=True); stage.mkdir()
    for i in ids:
        clone(raw / f"{i}.CR3", stage); shutil.copy(raw / f"{i}.xmp", stage)
    run(*ac, "write", "--proposals", props, "--xmpdir", stage, stdout=subprocess.DEVNULL)
    render(after, 1600, 8, [stage / f"{i}.CR3" for i in ids])
    run(*ac, "sheet", "--proposals", props, "--before", work / "previews", "--after", after, "--out", work / "sheet.jpg")
    shutil.rmtree(stage)
    print(f"\nreview: {work / 'sheet.jpg'}  (left = as shot, right = proposed result with thirds grid)")

def apply(raw, work, dest):
    props = work / "proposals.json"
    if not props.exists(): sys.exit(f"no proposals for {raw}: run crop first")
    ids = guarded(raw, work, lambda: out("uv", "run", "-q", S / "autocrop.py", "write", "--proposals", props,
                                         "--xmpdir", raw).splitlines())
    render(dest, 5088, 11, [raw / f"{i}.CR3" for i in ids])
    print(f"\nok: {len(ids)} sidecars updated, JPGs in {dest}")

def export(raw, dest, n):
    raws = [x.with_suffix(".CR3") for x in rated(raw, n)]
    for r in raws:
        if not r.exists(): print(f"skip {r.stem}: no CR3")
    raws = [r for r in raws if r.exists()]
    render(dest, 5088, 11, raws)
    print(f"\nok: {len(raws)} JPGs in {dest}")

def selftest():
    xmp = lambda attrs: ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                         f'<rdf:Description rdf:about="" {attrs}/></rdf:RDF></x:xmpmeta>\n')
    rating = lambda n: f'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="{n}" xmp:Label="Blue"'
    with tempfile.TemporaryDirectory() as t:
        raw, work, look = Path(t) / "raw", Path(t) / "work", Path(t) / "look.xmp"
        raw.mkdir()
        (raw / "a.xmp").write_text(xmp(rating(5))); (raw / "b.xmp").write_text(xmp(rating(3)))
        look.write_text(xmp('xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" crs:PresetType="Normal" '
                            'crs:Contrast2012="+20" crs:ColorVariance="7"'))
        orig = {f.name: f.read_bytes() for f in raw.iterdir()}
        preset(raw, work, look, 4); preset(raw, work, look, 4)  # a rerun changes nothing and keeps the first backup
        a = (raw / "a.xmp").read_text()
        assert "crs:Contrast2012" in a and "crs:LensProfileEnable" in a and "PresetType" not in a, a
        assert a.count("<crs:ColorVariance>7</crs:ColorVariance>") == 1, a
        assert (raw / "b.xmp").read_bytes() == orig["b.xmp"]  # rated 3: untouched
        assert {f.name: f.read_bytes() for f in (work / f"xmp_backup_{date.today()}").iterdir()} == orig
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
                      ("models", ""), ("selftest", "")):
        p = jobs.add_parser(job)
        for arg in args.split():
            if arg == "min": p.add_argument("min", type=int, nargs="?", default=4, help="lowest rating (default 4)")
            elif arg == "ids": p.add_argument("ids", nargs="+")
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
    elif a.job == "previews": orient(raw, work / "previews", 1600, 88)
    elif a.job == "decode": orient(raw, work / "verify", 2560, 90, a.ids)
    if a.job != "export": print(f"work folder: {work}")

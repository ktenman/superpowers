#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "opencv-python",
#   "numpy",
# ]
# ///
"""Phase 1 measurement. Emits metrics.csv + metrics.json.
Every value here is COMPUTED from the preview/EXIF/XMP -- no aesthetic scores, no guesses.
Sharpness = Laplacian variance (relative flag for 100% check, NOT a verdict).
Exposure clip is measured on the 8-bit preview -> UNDER-states real RAW headroom; treat as a flag.
"""
import os, glob, json, csv, argparse
from datetime import datetime
import numpy as np, cv2

ap=argparse.ArgumentParser(description="Phase 1 measurement -> metrics.csv + metrics.json")
ap.add_argument("--workdir",required=True,help="dir containing exif.json, faces.json, previews/; metrics.csv/json written here")
args=ap.parse_args()
W=args.workdir; PREV=f"{W}/previews"

def dhash(gray, s=8):
    r=cv2.resize(gray,(s+1,s),interpolation=cv2.INTER_AREA)
    diff=r[:,1:]>r[:,:-1]
    bits=0
    for b in diff.flatten(): bits=(bits<<1)|int(b)
    return bits
def ham(a,b): return (a^b).bit_count()

def epoch_of(dt, subsec):
    try:
        base=datetime.strptime(dt,"%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:
        return None
    ss=0.0
    if subsec not in (None,""):
        s=str(subsec)
        try: ss=int(s)/(10**len(s))
        except Exception: ss=0.0
    return base+ss

def main():
    exif={}; xmp={}
    for e in json.load(open(f"{W}/exif.json")):  # exiftool -j RAWDIR: the RAWs, and the sidecars with the ratings
        idn,ext=os.path.splitext(os.path.basename(e["SourceFile"]))
        (xmp if ext.lower()==".xmp" else exif)[idn]=e
    faces=json.load(open(f"{W}/faces.json")) if os.path.exists(f"{W}/faces.json") else {}

    rows=[]
    files=sorted(glob.glob(f"{PREV}/*.jpg"))
    for k,f in enumerate(files):
        idn=os.path.splitext(os.path.basename(f))[0]
        e=exif.get(idn,{})
        img=cv2.imread(f)
        if img is None: continue
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        H,Wd=gray.shape
        sharp_whole=float(cv2.Laplacian(gray,cv2.CV_64F).var())
        # exposure on luminance
        med=float(np.median(gray))
        clip_hi=float((gray>=250).mean()*100); clip_lo=float((gray<=5).mean()*100)
        dh=dhash(gray)
        # face region sharpness from largest face bbox
        fj=faces.get(idn,{}); ff=fj.get("faces",[])
        sharp_face=None; face_area=None; nf=fj.get("n_faces",0)
        if ff:
            b=ff[0]["bbox"]; x,y,ww,hh=b
            x=max(0,x);y=max(0,y);ww=max(1,min(ww,Wd-x));hh=max(1,min(hh,H-y))
            crop=gray[y:y+hh,x:x+ww]
            if crop.size>0: sharp_face=float(cv2.Laplacian(crop,cv2.CV_64F).var())
            face_area=ff[0]["area_frac"]
        xm=xmp.get(idn,{})
        ori=e.get("Orientation",""); portrait="Rotate" in str(ori)
        foc=e.get("FocalLength","");
        try: foc=float(str(foc).replace("mm","").strip())
        except: foc=None
        ep=epoch_of(e.get("DateTimeOriginal",""), e.get("SubSecTimeOriginal"))
        rows.append(dict(id=idn,camera=e.get("Model"),datetime=e.get("DateTimeOriginal"),
            subsec=e.get("SubSecTimeOriginal"),epoch=ep,orientation="portrait" if portrait else "landscape",
            shutter=e.get("ShutterSpeed"),aperture=e.get("Aperture"),iso=e.get("ISO"),focal_mm=foc,
            lens=e.get("LensModel"),as_rating=xm.get("Rating"),as_label=xm.get("Label"),
            sharp_whole=round(sharp_whole,1),sharp_face=round(sharp_face,1) if sharp_face is not None else None,
            face_area_frac=face_area,n_faces=nf,
            eyes_flag=fj.get("primary_flag"),eyes_blink=fj.get("blink_primary"),
            exp_median=round(med,1),clip_hi_pct=round(clip_hi,2),clip_lo_pct=round(clip_lo,2),
            dhash=dh))
        if k%200==0: print(f"  metrics {k}/{len(files)}")

    # ---- clustering: time-sorted union-find on (dHash near + time-window) ----
    n0=len(rows); rows=[r for r in rows if r["epoch"] is not None]
    s=sorted(r["sharp_whole"] for r in rows)
    for r in rows: r["soft"]=r["sharp_whole"]<s[len(s)//10]  # bottom 10% of the shoot, as curate-screen.js tells its agents
    rows.sort(key=lambda r:r["epoch"])
    n=len(rows); par=list(range(n))
    def find(a):
        while par[a]!=a: par[a]=par[par[a]]; a=par[a]
        return a
    def uni(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb: par[rb]=ra
    TIME_W=8.0; HAM_T=10
    for i in range(n):
        ti=rows[i]["epoch"]; di=rows[i]["dhash"]
        j=i+1
        while j<n and rows[j]["epoch"]-ti<=TIME_W:
            if ham(di,rows[j]["dhash"])<=HAM_T: uni(i,j)
            j+=1
    # dupe group ids
    gid={};
    for i in range(n):
        r=find(i); gid.setdefault(r,len(gid))
    for i in range(n): rows[i]["dupe_group_id"]=gid[find(i)]
    from collections import Counter
    gsz=Counter(r["dupe_group_id"] for r in rows)
    for r in rows: r["dupe_group_size"]=gsz[r["dupe_group_id"]]
    # time-run ids (gap>3s => new run)
    run=0; prev=None
    for r in rows:
        if prev is not None and r["epoch"]-prev>3.0: run+=1
        r["time_run_id"]=run; prev=r["epoch"]

    # dhash to hex string for csv readability
    for r in rows: r["dhash"]=format(r["dhash"],"016x")

    cols=["id","camera","datetime","subsec","epoch","orientation","shutter","aperture","iso",
          "focal_mm","lens","as_rating","as_label","sharp_whole","soft","sharp_face","face_area_frac",
          "n_faces","eyes_flag","eyes_blink","exp_median","clip_hi_pct","clip_lo_pct",
          "time_run_id","dupe_group_id","dupe_group_size","dhash"]
    with open(f"{W}/metrics.csv","w",newline="") as fh:
        wr=csv.DictWriter(fh,fieldnames=cols); wr.writeheader(); wr.writerows(rows)
    json.dump(rows,open(f"{W}/metrics.json","w"))
    print(f"DONE rows={len(rows)} skipped_no_capture_time={n0-len(rows)} dupe_groups={len(gid)} time_runs={run+1}")

if __name__=="__main__": main()

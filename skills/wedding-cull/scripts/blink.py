#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mediapipe",
#   "opencv-python",
#   "numpy<2",
# ]
# ///
# NOTE: mediapipe requires numpy<2 -- keep the numpy<2 pin above.
"""Face detection + eye-blink over previews.
Two-stage: YuNet detects faces (robust on small faces) -> FaceLandmarker reads eyeBlink blendshape
on each face crop >= MINPX. Blink is a FLAG-ONLY signal for 100% review, never a verdict.
Faces < MINPX get state 'unknown' (too small to judge honestly -> no fabricated number).
Output faces.json { id:{n_faces,faces:[...],primary_flag,blink_primary} }.
"""
import os, glob, json, sys, argparse
import cv2, numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mtp
from mediapipe.tasks.python import vision

TARGET=320        # upscale face crop to ~this so landmarker lands well

def state_of(b):
    if b is None: return "unknown"
    if b>0.5: return "closed"
    if b>0.3: return "squint"
    return "open"

def main():
    ap=argparse.ArgumentParser(description="Face detection + eye-blink over previews -> faces.json")
    ap.add_argument("--previews",required=True,help="dir of preview .jpg files")
    ap.add_argument("--out",required=True,help="output faces.json path")
    ap.add_argument("--yunet",default=os.path.expanduser("~/.cache/wedding-cull/yunet.onnx"),help="yunet.onnx model path (photo.py models)")
    ap.add_argument("--landmarker",default=os.path.expanduser("~/.cache/wedding-cull/face_landmarker.task"),help="face_landmarker.task model path (photo.py models)")
    ap.add_argument("--minpx",type=int,default=80,help="min max(w,h) in the preview to attempt a blink read (smaller faces get state 'unknown')")
    a=ap.parse_args()
    PREV=a.previews; OUT=a.out; YUNET=a.yunet; FLM=a.landmarker
    MINPX=a.minpx     # min max(w,h) in the preview to attempt a blink read

    files=sorted(glob.glob(os.path.join(PREV,"*.jpg")))
    if not files: print("no previews",file=sys.stderr); sys.exit(1)
    yn=cv2.FaceDetectorYN.create(YUNET,"",(320,320),0.6,0.3,5000)
    lm=vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mtp.BaseOptions(model_asset_path=FLM),
        running_mode=vision.RunningMode.IMAGE,num_faces=1,
        output_face_blendshapes=True,min_face_detection_confidence=0.3))

    def blink_of(img,b,W,H):
        x,y,w,h=b; cx,cy=x+w/2,y+h/2; s=max(w,h)*1.7
        x0,y0=int(max(0,cx-s/2)),int(max(0,cy-s/2)); x1,y1=int(min(W,cx+s/2)),int(min(H,cy+s/2))
        crop=img[y0:y1,x0:x1]
        if crop.size==0: return None
        sc=TARGET/max(crop.shape[:2])
        if sc>1: crop=cv2.resize(crop,None,fx=sc,fy=sc,interpolation=cv2.INTER_CUBIC)
        rgb=np.ascontiguousarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB))
        try: r=lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb))
        except Exception: return None
        if not r.face_blendshapes: return None
        return float(max(c.score for c in r.face_blendshapes[0] if 'Blink' in c.category_name))

    out={}
    for k,f in enumerate(files):
        idn=os.path.splitext(os.path.basename(f))[0]
        img=cv2.imread(f)
        if img is None:
            print(f"{idn}: unreadable preview",file=sys.stderr); continue
        H,W=img.shape[:2]; yn.setInputSize((W,H)); _,det=yn.detect(img)
        faces=[]
        if det is not None:
            for d in sorted(det,key=lambda b:-b[2]*b[3]):
                x,yy,w,h=[int(v) for v in d[:4]]
                if w<=0 or h<=0: continue
                area=(w*h)/(W*H)
                bl=blink_of(img,(x,yy,w,h),W,H) if max(w,h)>=MINPX else None
                faces.append({"bbox":[x,yy,w,h],"area_frac":round(area,4),
                              "blink":round(bl,3) if bl is not None else None,"state":state_of(bl)})
        top=faces[:2]
        known=[p for p in top if p["blink"] is not None]
        out[idn]={"n_faces":len(faces),
                  "faces":faces,
                  "primary_flag":(any(p["state"] in ("closed","squint") for p in known) if known else None),
                  "blink_primary":(round(max(p["blink"] for p in known),3) if known else None)}
        if k%100==0: print(f"  blink {k}/{len(files)}",file=sys.stderr)
    lm.close()
    json.dump(out,open(OUT,"w"))
    nf=sum(1 for v in out.values() if v.get("primary_flag"))
    withface=sum(1 for v in out.values() if v.get("n_faces"))
    print(f"DONE faces.json images={len(out)} with_faces={withface} primary-eye-flags={nf}")

if __name__=="__main__": main()

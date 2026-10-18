# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Pack 5-star frames into review batches (~TARGET/batch), never splitting a burst across batches."""
import json, os, argparse
from datetime import datetime
ap=argparse.ArgumentParser(description="Pack 5-star frames from metrics.json into review batches")
ap.add_argument("--metrics",required=True,help="metrics.json path")
ap.add_argument("--previews",required=True,help="previews dir (frame paths point here)")
ap.add_argument("--outdir",required=True,help="output dir for batch_NNN.json files")
ap.add_argument("--paths-out",required=True,help="output path for batch_paths.json (list of batch file paths)")
ap.add_argument("--target",type=int,default=12,help="~frames per batch")
a=ap.parse_args()
R=json.load(open(a.metrics))
PREV=a.previews
pool=[r for r in R if r["as_rating"]==5]
pool.sort(key=lambda r:r["epoch"])
def hms(e): return datetime.fromtimestamp(e).strftime("%H:%M:%S")
def frame(r):
    return {"id":r["id"],"path":f"{PREV}/{r['id']}.jpg",
        "t":hms(r["epoch"]),"burst":r["dupe_group_id"],"bn":r["dupe_group_size"],
        "sharp":r["sharp_whole"],"soft":r["soft"],
        "eyes_closed_flag":bool(r["eyes_flag"]),"blink":r["eyes_blink"],
        "hi_clip_pct":r["clip_hi_pct"],"faces":r["n_faces"],"o":r["orientation"],
        "focal":r["focal_mm"],"ap":r["aperture"],"lens":r["lens"]}
# pack ~TARGET/batch, never split a burst (dupe_group) across batches
TARGET=a.target; batches=[]; cur=[]; prevb=None
for r in pool:
    if cur and len(cur)>=TARGET and r["dupe_group_id"]!=prevb:
        batches.append(cur); cur=[]
    cur.append(frame(r)); prevb=r["dupe_group_id"]
if cur: batches.append(cur)
os.makedirs(a.outdir,exist_ok=True)
paths=[]
for i,b in enumerate(batches):
    p=f"{a.outdir}/batch_{i:03d}.json"
    json.dump({"batch_id":i,"frames":b},open(p,"w"),indent=0)
    paths.append(p)
json.dump(paths,open(a.paths_out,"w"))
print(f"5star pool={len(pool)}  batches={len(batches)}  sizes:min={min(len(b) for b in batches)} max={max(len(b) for b in batches)} avg={len(pool)/len(batches):.1f}")
print("first batch frames:",[f['id'] for f in batches[0]])

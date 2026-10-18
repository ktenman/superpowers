---
name: wedding-cull
description: Use when finishing or culling a photo shoot shot as Canon RAW (CR3 + XMP sidecars), wedding or not - applying a Lightroom/Camera Raw preset ("filter") or lens correction to the selected photos, straightening crooked or tilted photos (wrong angle, sloping horizon), cropping to the rule of thirds, exporting RAWs to JPG through Photoshop, or culling a wedding into a delivery, backup bench and portfolio
---

# Wedding cull and RAW finishing

Edits go into the XMP sidecars and render through Adobe's own engine. RAW pixels are never touched, Lightroom can still undo everything, and the JPGs come out of Photoshop/Camera Raw. Every job runs through `photo.py` next to this file; the full wedding cull is in `pipeline.md`.

## Hard rules

1. Never modify RAW originals; work files live outside the RAW folder.
2. Before writing sidecars, tell the user which photos and which settings change, and get an OK. `photo.py` backs every sidecar up first to `xmp_backup_<YYYY-MM-DD>/` in the work folder, keeping the copy from before that day's first job, and aborts if the write changed a rating or, except in `label`, a colour label (restore from that backup, which also drops that day's earlier edits). Never clobber `xmp:Rating`.
3. Copies, never moves.
4. Previews: `magick -auto-orient`, never `-rotate` (sips leaves a portrait CR3 as landscape pixels plus an orientation tag).
5. No invented numbers: no confidence %, no "focus confirmed" from a preview, edit direction in words.

## Lightroom round trip

If the photos are in a Lightroom catalog, the catalog holds the edits and a sidecar holds only what was last saved to it. Keep them in step (select the folder's photos, then the Metadata menu):

- Before a job: Save Metadata to Files, unless nothing changed in Lightroom since the last Save or Read. Unsaved edits are missing from the JPGs and lost at the next Read.
- After `preset`, `apply`, `keyword` or `label` (every job that writes sidecars), or a sidecar restored from a backup: Read Metadata from Files before anything else in Lightroom; a Save first overwrites what was written. So `apply` goes straight into `export`, and per-photo exposure/WB after `preset` fits between that Read and the Save before `crop`.
- Photos Lightroom flags as changed on disk (the culling app rated them after import): Read those before the first Save, or the Save overwrites their ratings. If they also have unsaved Lightroom edits, ask the user which to keep.

## Jobs

Run `uv run <this-skill-dir>/photo.py <job> ...` from any folder; `--help` lists the jobs. Each RAW folder gets its own work folder, `~/Downloads/wedding-cull/<folder>-<6 hex>/`, holding its previews, proposals, review sheet and sidecar backups (`xmp_backup_<YYYY-MM-DD>/`). Every job prints it; `previews RAWDIR` is a cheap way to see it again (it only fills in missing previews). The hex comes from the folder's resolved full path, so the same folder under another path (a remounted drive) gets a new one. Needs exiftool, uv, ImageMagick and Photoshop. MIN defaults to 4: "selected photos" = sidecars rated ≥ 4 (the culling app writes 5★ Green, 4★ Blue). Count them for the user before writing:
`exiftool -q -if '$XMP:Rating >= 4' -p '$FileName' -ext xmp RAWDIR | wc -l`

| The user wants | Run | Then |
|---|---|---|
| their filter/preset + lens fix on the selected photos | `preset RAWDIR PRESET.xmp [MIN]` | they read it into Lightroom and set exposure/WB per photo |
| crooked photos straightened, crops on the thirds | `crop RAWDIR [MIN]` | show the review sheet(s) it prints, collect vetoes |
| the reviewed crops | `apply RAWDIR OUTDIR` | sidecars written, JPGs of exactly those frames |
| JPGs of every selected photo | `export RAWDIR OUTDIR [MIN]` | renders every selected frame, cropped ones again too; same-name JPGs are overwritten |
| a wedding culled | read `pipeline.md` | |

- Vetoes: `proposals.json` in the work folder maps file-name stem → proposal. Set a frame's `"crop"` to `null` to keep only the straightening; delete its entry to leave it as shot. Rerunning `crop` rebuilds the file and loses the vetoes.
- Run `preset` before `crop`. `preset` copies every crs tag in the preset, so list them first: `exiftool -s -XMP-crs:all PRESET.xmp`. Two kinds need the user's say before writing, with a copy without them on offer (`exiftool -o COPY.xmp -XMP-crs:TAG= ... PRESET.xmp`): Exposure2012, WhiteBalance, ColorTemperature or Tint overwrite the user's own; HasCrop True or a PerspectiveUpright other than Off make `crop` skip every frame, because it leaves frames that already have a crop or an Upright mode alone.
- A filter pack with several .xmp and no file named: read its README and use the variant without baked-in exposure/WB.
- `preset` always turns lens correction on, which needs a profile per lens. List the lenses with `exiftool -q -q -p '$LensModel' -ext cr3 RAWDIR | sort -u`, then search inside the profiles for each: `grep -rlF 'LENS' "/Library/Application Support/Adobe/CameraRaw/LensProfiles/1.0"`. Profile file names spell lenses differently (`RF 28-70mm` for `RF28-70mm`). A lens without one gets no profile correction, and Camera Raw reports no error: tell the user which lenses have none before writing.

## How crop + straighten work (verified, don't re-derive)

- Straighten = `crs:PerspectiveUpright=Level`: Camera Raw levels the frame at render time (rotation + fill-zoom, no perspective warp). Tilt estimated from detected lines (Hough/LSD) was unreliable on real shoots.
- Crop: YuNet faces on 1600px oriented previews. Eye line on the upper third; one subject on the third it faces; a close pair moves as one; groups keep their x. Aspect kept, ≥ 80% of each side, never cuts a face. Only faces scoring ≥ 0.85 steer (log ends and wall photos scored 0.67–0.81), but every detection is protected (a real profile face scored 0.62).
- Crop values are normalized to the unrotated sensor; `to_sensor` in `scripts/autocrop.py` maps EXIF orientations 1/3/6/8.
- The review sheet is Camera Raw's render of staged sidecar copies with the proposals written in, so it shows exactly the crop and straightening `apply` adds, with the measured eye line and rotation per frame. `apply` adds them to the sidecars as they are when it runs.
- Photoshop is driven by AppleScript `do javascript` with the script text inline (a file alias fails with error 8800), addressed by bundle id, so any installed version works.

## Tell the user

- People facing away from the camera are invisible to face detection: check the sheet for cut-off bodies.
- Frames with no CR3 (PSD-only) are skipped; those export from Photoshop.
- Crops of crop-mode RAWs come out under 5088px, because export never upscales.
- Upright=Level was verified in Photoshop/Camera Raw renders, not in Lightroom itself.
- To undo only the crop, reset it in Lightroom; setting Upright to Off drops the straightening too. To undo a frame entirely, copy its sidecar back from an `xmp_backup_<YYYY-MM-DD>/`. Each holds the sidecars as they were before that day's first job (the oldest, before any job), so a restore also drops every later job and saved Lightroom edit. Either way the JPG keeps the old look until it is exported again: one frame from Lightroom (sRGB, long edge 5088 px, Don't Enlarge), or rerun `export`.

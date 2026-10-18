---
name: wedding-cull
description: Use when finishing or culling a photo shoot shot as Canon RAW (CR3 + XMP sidecars), wedding or not - applying a Lightroom/Camera Raw preset ("filter") or lens correction to the selected photos, straightening crooked or tilted photos (wrong angle, sloping horizon), cropping to the rule of thirds, exporting RAWs to JPG through Photoshop, or culling a wedding into a delivery, backup bench and portfolio
---

# Wedding cull and RAW finishing

Edits go into the XMP sidecars and render through Adobe's own engine. RAW pixels are never touched, Lightroom can still undo everything, and the JPGs come out of Photoshop/Camera Raw. Every job runs through `photo.py` next to this file; the full wedding cull is in `pipeline.md`.

## Hard rules

1. Never modify RAW originals; work files live outside the RAW folder.
2. Before writing sidecars, tell the user which photos and which settings change, and get an OK. `photo.py` backs every sidecar up first to `xmp_backup_<YYYY-MM-DD>/` in the work folder (a second run that day keeps the first copy) and aborts if the write changed a rating or colour label (restore from that backup). Never clobber `xmp:Rating`.
3. Copies, never moves.
4. Previews: `magick -auto-orient`, never `-rotate` (sips leaves a portrait CR3 as landscape pixels plus an orientation tag).
5. No invented numbers: no confidence %, no "focus confirmed" from a preview, edit direction in words.

## Lightroom round trip

If the photos are in a Lightroom catalog: Lightroom keeps edits there, and a sidecar holds only what was last saved to it. Before each job, the user selects the folder's photos → Metadata → Save Metadata to Files; after a job that wrote sidecars, Metadata → Read Metadata from Files. Lightroom edits in between (exposure/WB after `preset`) are fine once saved again before the next job; unsaved ones are missing from the JPGs and lost at the next read. Exception: photos Lightroom flags as changed on disk (the culling app rated them after import) need Read first, because Save would overwrite those ratings.

## Jobs

Run `uv run <this-skill-dir>/photo.py <job> ...` from any folder; `--help` lists the jobs. Each RAW folder gets its own work folder, `~/Downloads/wedding-cull/<folder>-<6 hex>/`, which every job prints: previews, proposals, review sheet, sidecar backups in `xmp_backup_<YYYY-MM-DD>/`. It is named after the full path, so the same folder under another path (a remounted drive) gets a new one. Needs exiftool, uv, ImageMagick and Photoshop 2026. MIN defaults to 4: "selected photos" = sidecars rated ≥ 4 (the culling app writes 5★ Green, 4★ Blue). Count them for the user before writing:
`exiftool -q -if '$XMP:Rating >= 4' -p '$FileName' -ext xmp RAWDIR | wc -l`

| The user wants | Run | Then |
|---|---|---|
| their filter/preset + lens fix on the selected photos | `preset RAWDIR PRESET.xmp [MIN]` | they read it into Lightroom and set exposure/WB per photo |
| crooked photos straightened, crops on the thirds | `crop RAWDIR [MIN]` | show the `sheet.jpg` it prints, collect vetoes |
| the reviewed crops | `apply RAWDIR OUTDIR` | sidecars written, JPGs of exactly those frames |
| JPGs of every selected photo | `export RAWDIR OUTDIR [MIN]` | renders every selected frame, cropped ones again too; same-name JPGs are overwritten |
| a wedding culled | read `pipeline.md` | |

- Vetoes: `proposals.json` in the work folder maps file-name stem → proposal. Set a frame's `"crop"` to `null` to keep only the straightening; delete its entry to leave it as shot. Rerunning `crop` rebuilds the file and loses the vetoes.
- Run `preset` before `crop`: `preset` copies every crs tag in the preset (a variant with baked-in exposure/WB overwrites the user's), and `crop` leaves frames that already have a crop or an Upright mode alone, so a preset that sets either makes `crop` skip every frame. Check first: `exiftool -n -HasCrop -PerspectiveUpright PRESET.xmp` (Upright 0 = off).
- A filter pack with several .xmp: read its README and batch-apply the variant without baked-in exposure/WB.
- `preset` always turns lens correction on, which needs a profile per lens: `exiftool -s3 -LensModel -ext cr3 RAWDIR | sort -u`, then grep each name in `ls -R "/Library/Application Support/Adobe/CameraRaw/LensProfiles/1.0"`. Without one, Camera Raw silently skips the correction.

## How crop + straighten work (verified, don't re-derive)

- Straighten = `crs:PerspectiveUpright=Level`: Camera Raw levels the frame at render time (rotation + fill-zoom, no perspective warp). Tilt estimated from detected lines (Hough/LSD) was unreliable on real shoots.
- Crop: YuNet faces on 1600px oriented previews. Eye line on the upper third; one subject on the third it faces; a close pair moves as one; groups keep their x. Aspect kept, ≥ 80% of each side, never cuts a face. Only faces scoring ≥ 0.85 steer (log ends and wall photos scored 0.67–0.81), but every detection is protected (a real profile face scored 0.62).
- Crop values are normalized to the unrotated sensor; `to_sensor` in `scripts/autocrop.py` maps EXIF orientations 1/3/6/8.
- The review sheet is rendered by Camera Raw from staged copies, so it shows exactly what `apply` writes, with the measured eye line and rotation per frame.
- Photoshop is driven by AppleScript `do javascript` with the script text inline (a file alias fails with error 8800); the app name is `PHOTOSHOP` in `photo.py`.

## Tell the user

- People facing away from the camera are invisible to face detection: check the sheet for cut-off bodies.
- Frames with no CR3 (PSD-only) are skipped; those export from Photoshop.
- Crops of crop-mode RAWs come out under 5088px, because export never upscales.
- Upright=Level was verified in Photoshop/Camera Raw renders, not in Lightroom itself.
- To undo a frame entirely, copy its sidecar back from `xmp_backup_<YYYY-MM-DD>/`; that also undoes a same-day `preset`, because the day's first backup is kept. To undo only the crop and straightening, reset Crop and set Upright to Off in Lightroom.

---
name: wedding-cull
description: Use when finishing or culling a photo shoot shot as Canon RAW (CR3 + XMP sidecars), wedding or not - applying a Lightroom/Camera Raw preset ("filter") or lens correction to the selected photos, toning down a look that came out too dark or over-edited, straightening crooked or tilted photos (wrong angle, sloping horizon), cropping to the rule of thirds, exporting RAWs to JPG through Photoshop, or culling a wedding into a delivery, backup bench and portfolio
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
- After `preset`, `apply`, `keyword` or `label` (every job that writes sidecars), or a sidecar restored from a backup: Read Metadata from Files before anything else in Lightroom; a Save first overwrites what was written. So `apply` goes straight into `export`, and per-photo exposure/WB after `preset` fits between that Read and the Save before the next job (`crop`, or `apply` in the ask-once order).
- Photos Lightroom flags as changed on disk (the culling app rated them after import): Read those before the first Save, or the Save overwrites their ratings. If they also have unsaved Lightroom edits, ask the user which to keep.

## Jobs

Run `uv run <this-skill-dir>/photo.py <job> ...` from any folder; `--help` lists the jobs. Each RAW folder gets its own work folder, `~/Downloads/wedding-cull/<folder>-<6 hex>/`, holding its previews, proposals, review sheet and sidecar backups (`xmp_backup_<YYYY-MM-DD>/`). Every job prints it; `previews RAWDIR` is a cheap way to see it again (it only fills in missing previews). The hex comes from the folder's resolved full path, so the same folder under another path (a remounted drive) gets a new one. Needs exiftool, uv, ImageMagick and Photoshop. MIN defaults to 4: "selected photos" = sidecars rated ≥ 4 (the culling app writes 5★ Green, 4★ Blue). Count them for the user before writing:
`exiftool -q -if '$XMP:Rating >= 4' -p '$FileName' -ext xmp RAWDIR | wc -l`

| The user wants | Run | Then |
|---|---|---|
| to see their filter/preset before anything is written | `look RAWDIR PRESET.xmp [MIN] [AMOUNT]` | show the sheet(s) and the frames it flags |
| their filter/preset + lens fix on the selected photos | `preset RAWDIR PRESET.xmp [MIN] [AMOUNT]` | they read it into Lightroom and set exposure/WB per photo |
| crooked photos straightened, crops on the thirds | `crop RAWDIR [MIN] [PRESET.xmp [AMOUNT]]` | show the review sheet(s) it prints, collect vetoes |
| the reviewed crops | `apply RAWDIR OUTDIR` | sidecars written, JPGs of exactly those frames |
| JPGs of every selected photo | `export RAWDIR OUTDIR [MIN]` | renders every selected frame, cropped ones again too; same-name JPGs are overwritten |
| a wedding culled | read `pipeline.md` | |

- Vetoes: `proposals.json` in the work folder maps file-name stem → proposal, with the reason in `"why"`. Set a frame's `"crop"` to `null` to keep only the straightening, its `"level"` to `false` to drop the straightening (or `true` to force it where the check left the frame as shot); delete its entry to leave it as shot. Rerunning `crop` rebuilds the file and loses the vetoes.
- Run `preset` before `crop`, or give `crop` the PRESET.xmp and AMOUNT that `preset` will get: its renders, and with them the straightening check and the sheet, need the lens correction and look `apply` will find. `preset` copies every crs tag in the preset, so list them first: `exiftool -s -XMP-crs:all PRESET.xmp`. Two kinds need the user's say before writing, with a copy without them on offer (`exiftool -o COPY.xmp -XMP-crs:TAG= ... PRESET.xmp`): Exposure2012, WhiteBalance, ColorTemperature or Tint overwrite the user's own; HasCrop True or a PerspectiveUpright other than Off make `crop` skip every frame, because it leaves frames that already have a crop or an Upright mode alone.
- A filter pack with several .xmp and no file named: read its README and use the variant without baked-in exposure/WB.
- `preset` always turns lens correction on, which needs a profile per lens. List the lenses with `exiftool -q -q -p '$LensModel' -ext cr3 RAWDIR | sort -u`, then search inside the profiles for each: `grep -rlF 'LENS' "/Library/Application Support/Adobe/CameraRaw/LensProfiles/1.0"`. Profile file names spell lenses differently (`RF 28-70mm` for `RF28-70mm`). A lens without one gets no profile correction, and Camera Raw reports no error: tell the user which lenses have none before writing.

## Gentle by default, one OK

Photographers judge an edit against what they saw on the camera, so the checks measure against the camera's own JPEG (the preview embedded in each CR3).

- `look` and `preset` apply the preset at AMOUNT 0.5, like Lightroom's Amount slider at 50, but keep its shadow lift (Shadows, Blacks and Darks raised, Contrast lowered) at full: the lift offsets the curves' shadow crush. On one shoot the full-strength preset measured median L* −3.1 and +6 points near-black against the camera's JPEGs, and the photographer called it too dark and over-edited. Everything at half was still −2.9; half with the lift kept measured +2.7 and is the look they approved. AMOUNT 1 only when the user asks for the preset at full strength.
- `look` renders the preset on staged copies and flags frames more than 3 L* darker than shot, with over 5 points more near-black, with faces more than 3 L* darker, or with over 1 point more clipped highlights. On that shoot it flagged 43 of 60 frames at full strength and 3 of 60 with the approved look, one of which the photographer had lifted by hand. Name the flagged frames and what was measured in the OK; their exposure is the photographer's call in Lightroom. Colour strength is shown, never flagged: no threshold told the approved frames from the ones they wanted calmer.
- Face detection can't see what else a crop cuts: on that shoot 5 of 21 crops cut a speaker's name, a logo, a slide or a flag. The sheet dims the part each crop removes. Before asking, have a fresh subagent review the sheet(s) and set `"crop": null` on every crop that cuts text, a logo, a slide, a flag or a hand.
- Ask once. `look` and `crop` write nothing, so run both (`crop` with the same PRESET.xmp and AMOUNT) and the crop review first, then put one OK to the user: the look and its AMOUNT, the flagged frames, and how many frames get straightened, cropped or left as shot (vetoed crops named). On the OK: `preset`, then `apply` or `export`.

## How crop + straighten work (verified, don't re-derive)

- Straighten = `crs:PerspectiveUpright=Level`: Camera Raw levels the frame at render time (rotation + fill-zoom, no perspective warp). Its estimate can be wrong: on one shoot the photographer undid it on 7 of 59 frames (converging verticals, slanted screens, a car interior, a night scene with no true level). So `crop` keeps Level only where it measurably helps. The as-shot roll comes from the long near-vertical lines in the camera's JPEG (fitted so that keystone lean cancels out), and Level's turn from matching that JPEG to the render. Level stays when it turns at least 0.3° and leaves the frame at least 0.3° closer to level. On that shoot this kept Level on 15 frames, among them all 9 it visibly fixed, and dropped all 7 the photographer undid. The rest turned less, or couldn't be measured, and stay as shot. Lines never set the angle themselves: tilt estimated from them was unreliable on real shoots. Blind spot: only verticals are read, so a frame with only a horizon stays as shot; set its `"level"` to `true` to straighten it anyway.
- Crop: YuNet faces on 1600px oriented previews. Eye line on the upper third; one subject on the third it faces; a close pair moves as one; groups keep their x. Aspect kept, ≥ 80% of each side, never cuts a face. Only faces scoring ≥ 0.85 steer (log ends and wall photos scored 0.67–0.81), but every detection is protected (a real profile face scored 0.62).
- Crop values are normalized to the unrotated sensor; `to_sensor` in `scripts/autocrop.py` maps EXIF orientations 1/3/6/8.
- The review sheet is Camera Raw's render of staged sidecar copies with the proposals (and a given preset) written in, so it shows exactly the crop and straightening `apply` adds, with the measured eye line and rotation per frame. `apply` adds them to the sidecars as they are when it runs. Frames left as shot aren't on the sheet.
- Photoshop is driven by AppleScript `do javascript` with the script text inline (a file alias fails with error 8800), addressed by bundle id, so any installed version works.

## Tell the user

- People facing away from the camera are invisible to face detection: check the sheet for cut-off bodies.
- Frames with no CR3 (PSD-only) are skipped; those export from Photoshop.
- Crops of crop-mode RAWs come out under 5088px, because export never upscales.
- Upright=Level was verified in Photoshop/Camera Raw renders, not in Lightroom itself.
- To undo only the crop, reset it in Lightroom; setting Upright to Off drops the straightening too. To undo a frame entirely, copy its sidecar back from an `xmp_backup_<YYYY-MM-DD>/`. Each holds the sidecars as they were before that day's first job (the oldest, before any job), so a restore also drops every later job and saved Lightroom edit. Either way the JPG keeps the old look until it is exported again: one frame from Lightroom (sRGB, long edge 5088 px, Don't Enlarge), or rerun `export`.

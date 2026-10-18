// Render RAWs through Camera Raw (using each file's sidecar .xmp: develop + crop) to sRGB 8-bit JPEGs.
// args: outDir, maxEdge (0 = full size, never upscales), quality (0-12), raw1, raw2, ...
var outDir = arguments[0], maxEdge = parseInt(arguments[1], 10), q = parseInt(arguments[2], 10);
var oldDialogs = app.displayDialogs, oldUnits = app.preferences.rulerUnits, ok = 0, fails = [];
app.displayDialogs = DialogModes.NO;
app.preferences.rulerUnits = Units.PIXELS;
try {
  for (var i = 3; i < arguments.length; i++) {
    var f = new File(arguments[i]), doc = null;
    try {
      doc = app.open(f);
      if (doc.bitsPerChannel != BitsPerChannelType.EIGHT) doc.bitsPerChannel = BitsPerChannelType.EIGHT;
      doc.convertProfile("sRGB IEC61966-2.1", Intent.RELATIVECOLORIMETRIC, true, true);
      var w = doc.width.value, h = doc.height.value;
      if (maxEdge > 0 && Math.max(w, h) > maxEdge)
        doc.resizeImage(w >= h ? UnitValue(maxEdge, "px") : undefined,
                        w >= h ? undefined : UnitValue(maxEdge, "px"), undefined, ResampleMethod.BICUBICSHARPER);
      var o = new JPEGSaveOptions();
      o.quality = q; o.embedColorProfile = true; o.formatOptions = FormatOptions.STANDARDBASELINE;
      doc.saveAs(new File(outDir + "/" + decodeURI(f.name).replace(/\.[^.]+$/, "") + ".jpg"), o, true, Extension.LOWERCASE);
      ok++;
    } catch (e) {
      fails.push(decodeURI(f.name) + ": " + e);
    } finally {
      // only ever close the document this script opened -- never the user's other open files
      if (doc) try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
    }
  }
} finally {
  app.displayDialogs = oldDialogs;
  app.preferences.rulerUnits = oldUnits;
}
"ok " + ok + (fails.length ? "; FAIL " + fails.join(" | ") : "");

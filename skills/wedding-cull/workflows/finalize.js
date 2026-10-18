export const meta = {
  name: 'wedding-cull-phase3',
  description: 'Phase 3: one Opus agent per scene locks the delivery cut, nominates portfolio standouts, flags full-res verification',
  phases: [{ title: 'Finalize', detail: 'one Opus editor per scene' }],
}

// args: {wedding: 'couple, place, date, cameras', batches: [per-scene manifest paths]}

const SCHEMA = {
  type: "object",
  properties: {
    scene: { type: "string" },
    deliver: { type: "array", items: { type: "string" } },
    alternates: { type: "array", items: { type: "string" } },
    portfolio_noms: { type: "array", items: {
      type: "object",
      properties: { id: { type: "string" }, why: { type: "string" } },
      required: ["id", "why"], additionalProperties: false } },
    verify_full_res: { type: "array", items: {
      type: "object",
      properties: { id: { type: "string" }, what: { type: "string" } },
      required: ["id", "what"], additionalProperties: false } },
    cut_notes: { type: "string" }
  },
  required: ["scene", "deliver", "alternates", "portfolio_noms", "verify_full_res", "cut_notes"],
  additionalProperties: false
}

function prompt(path) {
  return `You are the lead editor locking the FINAL delivery cut for ONE scene of a wedding gallery (${args.wedding}). These frames were already marked KEEP in a first-pass cull of the 5-star pool. Your job is the decisive editorial lock.

STEP 1 - Read the manifest: ${path}
It has: scene, target (exactly how many to DELIVER), n_keeps, and frames[] each with an image "path" plus measured metadata (t, burst, burst_size, sharp, soft, eyes_flag, blink, hi_clip, faces, lens, focal, ap) and the first-pass notes (p2_reason, p2_crop, p2_grade, p2_flag).

STEP 2 - Actually OPEN every frame (use Read on each "path").

STEP 3 - Produce:
1. deliver = EXACTLY \`target\` frame ids, the strongest. Cut cross-frame redundancy the first pass missed: near-identical compositions from DIFFERENT bursts (multiple altar wides, repeated venue angles, sequential same-pose portraits). Prefer eyes-open + genuine expression, clean critical focus (you can only judge gross focus at preview res), strong composition, COUPLE-centric over guests-only, emotional peak over filler. Keep genuine variety - a mix of tight/wide, angles, and distinct moments; do not deliver five versions of one beat.
2. alternates = ALL remaining keeps, best-first (swap-ready if the client vetoes a delivery pick).
3. portfolio_noms = the 0-4 frames in this scene strong enough for PUBLIC/PORTFOLIO use: technically clean, emotionally resonant, ideally just the couple. One-line "why" each. Only truly standout frames - it's fine to nominate none.
4. verify_full_res = any deliver or portfolio-nom frame whose eyes / focus / motion you cannot fully confirm at preview resolution, each with "what" to check at 100%. Be honest: flag rather than assume.
5. cut_notes = one line on what redundancy you cut.

If target >= n_keeps, deliver all and leave alternates empty. If fewer than \`target\` frames are genuinely deliverable, deliver fewer and SAY SO in cut_notes - never pad with weak frames.

RULES: use the exact ids from the manifest. No numeric scores or confidence %. Do NOT claim critical focus is confirmed. Do NOT re-grade or apply edits. Judge only what you can see.`
}

phase('Finalize')
const results = await parallel(args.batches.map((p, i) => () =>
  agent(prompt(p), {
    label: `finalize:${p.split('/').pop().replace('.json', '')}`,
    phase: 'Finalize', schema: SCHEMA, effort: 'high', agentType: 'general-purpose'
  })
))

const ok = results.filter(Boolean)
const deliver = ok.flatMap(r => r.deliver || [])
const noms = ok.flatMap(r => (r.portfolio_noms || []).map(n => ({ ...n, scene: r.scene })))
const verify = ok.flatMap(r => (r.verify_full_res || []).map(v => ({ ...v, scene: r.scene })))
const perScene = ok.map(r => ({ scene: r.scene, deliver: (r.deliver || []).length, alt: (r.alternates || []).length, noms: (r.portfolio_noms || []).length, cut: r.cut_notes }))
log(`delivered=${deliver.length} portfolio_noms=${noms.length} verify_full_res=${verify.length} scenes=${ok.length}`)
return { delivered_total: deliver.length, per_scene: perScene, portfolio_noms: noms, verify_full_res: verify, scenes: ok }

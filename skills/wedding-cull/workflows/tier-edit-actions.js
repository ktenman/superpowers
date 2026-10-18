export const meta = {
  name: 'tier-and-edit-actions',
  description: 'Rank the locked delivery into must-have + good-to-have, and tag each frame with needed edit actions (crop/color/retouch)',
  phases: [
    { title: 'Rank', detail: 'one vision agent per batch scores scene-grouped batches + tag edit actions' },
  ],
}

// args: {wedding: 'couple, place, date', batches: [scene-grouped batch paths]}

const RANK_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id','score','must_moment','edit_actions','why'],
        properties: {
          id: { type: 'string' },
          score: { type: 'number', description: '0-100 strength as a delivered wedding photo, judged WITHIN this scene batch' },
          must_moment: { type: 'boolean', description: 'true ONLY if this frame records a unique, irreplaceable moment (first kiss, ring exchange, vows, first dance, cake cut, bouquet, key family formal, signing) that no other frame in the delivery would cover' },
          edit_actions: {
            type: 'array',
            items: { type: 'string', enum: ['crop','color','retouch','none'] },
            description: 'what the photographer must actively do in edit: crop = re-crop/straighten/composition fix needed; color = corrective color/exposure work beyond a normal preset (blown sky recovery, mixed WB, heavy shadows); retouch = distraction removal / skin / object cleanup; none = clean, preset-only frame',
          },
          crop_note: { type: 'string', description: 'if crop: one-line direction in words (e.g. "straighten horizon, tighten from left"), else "none"' },
          color_note: { type: 'string', description: 'if color: one-line direction in words, no numbers, else "none"' },
          retouch_note: { type: 'string', description: 'if retouch: what to remove/fix, else "none"' },
          why: { type: 'string', description: 'one line justifying the score' },
        },
      },
    },
  },
}

const PROMPT = (path) => `You are tiering an already-locked wedding delivery (${args.wedding}). Every frame you see is ALREADY approved for delivery — your job is to rank strength WITHIN this batch (all same scene) and tag edit work, so the photographer can split "must-have" from "good-to-have" and batch the editing.

Read the JSON array at ${path}. Each element: id, scene, reason (why it was curated), crop_hint + grade_hint (earlier curation notes — treat as hints, re-judge yourself), preview (ABSOLUTE path to a ~1600px orientation-correct JPEG).

For EVERY element, use the Read tool on "preview" to VIEW it, then:
- score 0-100: emotional impact + technical quality + storytelling, relative to the other frames in THIS batch. Spread your scores — do not cluster everything at 80.
- must_moment: true only for unique irreplaceable moments (first kiss, ring exchange, vows peak, first dance, cake, bouquet toss, signing, THE family formal). A pretty portrait variant is NOT a must_moment.
- edit_actions: what actively needs doing beyond the photographer's normal preset pass:
  * crop — needs re-crop/straighten/composition fix (tilted horizon, dead space, distracting edge)
  * color — needs corrective color/exposure (blown sky to recover, mixed/artificial WB, heavy shadow lift)
  * retouch — needs cleanup (exit sign, cable, stray guest, skin blemish, stroller)
  * none — clean, preset-only
  Multiple actions allowed; use ["none"] only alone.
- crop_note / color_note / retouch_note: one line each in WORDS (never numeric edit values), "none" when not applicable.
Return one verdict per element — all of them.`

phase('Rank')
const results = await parallel(args.batches.map((p, i) => () =>
  agent(PROMPT(p), { label: `rank:tb_${String(i).padStart(2,'0')}`, phase: 'Rank', schema: RANK_SCHEMA, model: 'sonnet', effort: 'medium' })
))

const all = results.filter(Boolean).flatMap(r => r.verdicts || [])
log(`ranked ${all.length} frames`)
return { ranked: all.length, verdicts: all }

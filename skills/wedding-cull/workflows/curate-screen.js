export const meta = {
  name: 'wedding-cull-phase2',
  description: 'Phase 2: one Sonnet vision agent per 12-frame batch screens the five-star wedding frames into keep/maybe/drop with crop + grade direction + 100%-check flags',
  phases: [{ title: 'Screen', detail: 'one Sonnet vision agent per 12-frame batch', model: 'sonnet' }],
}

// args: {wedding: 'couple, place, date, cameras + file prefixes', batches: [batch manifest paths]}

const SCHEMA = {
  type: "object",
  properties: {
    decisions: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          verdict: { type: "string", enum: ["keep", "maybe", "drop"] },
          scene: { type: "string", enum: ["prep", "ceremony", "session", "group", "congratulations", "details", "party", "other"] },
          reason: { type: "string" },
          crop: { type: "string" },
          grade: { type: "string" },
          flag100: { type: "string", enum: ["focus", "eyes", "motion", "none"] }
        },
        required: ["id", "verdict", "scene", "reason", "crop", "grade", "flag100"],
        additionalProperties: false
      }
    }
  },
  required: ["decisions"],
  additionalProperties: false
}

function prompt(path) {
  return `You are the lead editor at a wedding photography studio doing the HUMAN second-pass cull. Wedding: ${args.wedding}. The culling app (an auto-culler) already rated every frame in your batch its TOP tier (5-star). Your job is the editorial pass an auto-culler cannot do: keep the genuinely strong frames, cut technical failures and near-duplicate burst redundancy.

STEP 1 - Read the manifest file: ${path}
It has a "frames" array. Each frame has:
  path = the 1600px preview JPEG to open
  t = capture time HH:MM:SS, burst = burst-cluster id, bn = burst size
  soft = TRUE if my sharpness proxy put it in the bottom 10% (a FLAG to double-check, NOT a verdict)
  eyes_closed_flag / blink = my face detector suspects closed/squinting eyes (COARSE - verify with your own eyes; unreliable on small or distant faces)
  hi_clip_pct = % highlight clip measured on the 8-bit preview (the RAW has more headroom, so a bright dress or sky here is usually recoverable - do NOT drop for this alone)
  faces, o (portrait/landscape), focal, ap, lens

STEP 2 - Actually OPEN and look at every frame's image \`path\` (use Read on each one).

STEP 3 - Judge each frame through four lenses:
  1. Technical soundness - focus, motion blur, exposure. BUT this is a 1600px preview: you can judge gross blur and motion, you CANNOT confirm critical focus. If focus looks marginal, set flag100="focus" and lean "maybe" - never hard-drop for focus you cannot confirm at this resolution.
  2. Storytelling - does it advance the day's narrative (arrival, ceremony, vows, kiss, portraits, group, congratulations, details, party)?
  3. Emotional impact - expression, eye contact, connection, a genuine moment vs a flat or posed-dead frame.
  4. Client value - would the couple treasure this / want it printed?

BURST DEDUP (the most important cut): frames sharing a \`burst\` id are near-identical. Keep the best 1-2, drop the rest; in each dropped frame's reason NAME the winning sibling id (e.g. "beaten by 196A1005"). Prefer the frame with best eyes-open + expression + focus.

VERDICTS:
  keep  = strong, deliverable as-is.
  maybe = borderline, OR needs a 100% focus/eyes check, OR a nice-but-redundant alternate worth holding as a swap candidate.
  drop  = technical failure (gross blur, motion smear, BOTH subjects' eyes shut, badly cut composition) OR clearly beaten by a burst sibling.
Across all batches we keep roughly half as candidates - be decisive but not brutal; when torn between drop and maybe, choose maybe.

FOR EACH FRAME return:
  id       - the frame id, exactly as in the manifest
  verdict  - keep / maybe / drop
  scene    - one of: prep, ceremony, session, group, congratulations, details, party, other
  reason   - 12 words max, concrete (what makes it work or fail; name the burst winner if dropped)
  crop     - a crop suggestion as ratio + direction ("4x5 tighter from left"), or "none"
  grade    - colour/tone DIRECTION IN WORDS ONLY, no numbers, no camera settings (e.g. "warm WB, lift shadows, deepen greens, tame highlights on dress"); this is direction for the human editor, not an edit you apply
  flag100  - the single most important thing to verify at 100%: "focus", "eyes", "motion", or "none"

RULES: Return a decision for EVERY frame in the manifest - same ids, none skipped. Do NOT invent numeric scores or confidence percentages. Do NOT claim focus is confirmed. Do NOT apply any edit. Judge only what you can actually see in the previews.`
}

phase('Screen')
const results = await parallel(args.batches.map((p, i) => () =>
  agent(prompt(p), {
    label: `screen:batch_${String(i).padStart(3, '0')}`,
    phase: 'Screen', schema: SCHEMA, model: 'sonnet', effort: 'medium', agentType: 'general-purpose'
  })
))

const all = results.filter(Boolean).flatMap(r => r.decisions || [])
const c = { keep: 0, maybe: 0, drop: 0 }
const scene = {}
for (const d of all) { c[d.verdict] = (c[d.verdict] || 0) + 1; scene[d.scene] = (scene[d.scene] || 0) + 1 }
const failed = results.map((r, i) => r ? null : i).filter(x => x !== null)
log(`screened ${all.length} | keep=${c.keep} maybe=${c.maybe} drop=${c.drop} | failed batches=${failed.length}`)
return { total: all.length, counts: c, by_scene: scene, failed_batches: failed, decisions: all }

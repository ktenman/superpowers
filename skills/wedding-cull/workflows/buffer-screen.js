export const meta = {
  name: 'buffer-nice-to-have',
  description: 'Screen held-back candidates (spare 5-star + un-screened 4-star) and pick a scene-balanced "nice-to-have" buffer behind the locked delivery',
  phases: [
    { title: 'Screen', detail: 'one vision agent per batch grades every candidate from previews' },
    { title: 'Verify', detail: 'independent second look at the scene-balanced shortlist' },
  ],
}

// args: {wedding, batches: [batch paths], delivery: {scene: delivered count}, bench: final buffer size,
//        shortlist: how many to verify (verify downgrades ~30%, so ~1.4x bench avoids a top-up)}

const SCENES = ['prep','ceremony','session','congratulations','group','party','details','other']

const SCREEN_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id','preview','scene','eyes','focus','grade','note'],
        properties: {
          id: { type: 'string' },
          preview: { type: 'string', description: 'echo the absolute preview path you opened' },
          scene: { type: 'string', enum: SCENES },
          subject: { type: 'string' },
          eyes: { type: 'string', enum: ['open','partial','closed','na'] },
          focus: { type: 'string', enum: ['sharp','acceptable','soft','oof'] },
          grade: { type: 'string', enum: ['A','B','C'], description: 'A=strong nice-to-have, B=ok backup, C=skip (weak/defect/redundant)' },
          dup_note: { type: 'string', description: 'near-duplicate of another frame in THIS batch, if any (id or "none")' },
          note: { type: 'string', description: 'one line; include a crop or color DIRECTION hint if obvious' },
        },
      },
    },
  },
}

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['id','confirm','eyes','focus','dup_risk','flag100','note'],
  properties: {
    id: { type: 'string' },
    confirm: { type: 'string', enum: ['keep','downgrade'], description: 'keep = worthy nice-to-have; downgrade = drop from buffer' },
    eyes: { type: 'string', enum: ['open','partial','closed','na'] },
    focus: { type: 'string', enum: ['sharp','acceptable','soft','oof'] },
    dup_risk: { type: 'string', enum: ['low','med','high'] },
    flag100: { type: 'string', description: 'what the photographer should confirm at 100% (focus/eyes/clip), or "none"' },
    note: { type: 'string' },
  },
}

const SCREEN_PROMPT = (path) => `You are culling a wedding shoot (${args.wedding}). This is a BUFFER pass: pick "nice-to-have" backups that sit BEHIND an already-locked delivery. Standard is high but slightly below hero-delivery: a solid, usable, in-focus frame with open eyes on the key subject earns a B; something genuinely lovely earns an A; anything soft on the subject, blinked, awkward, or clearly redundant is a C.

Read the JSON array at ${path}. Each element has: id, preview (ABSOLUTE path to a ~1600px orientation-correct JPEG), tier (5 = held-back 5-star, 4 = un-screened 4-star), scene (hint; "unknown" for 4-star — you must assign it).

For EVERY element: use the Read tool on its "preview" path to VIEW the image, then judge honestly.
- scene: assign from ${SCENES.join(', ')} (prep=getting-ready, session=posed couple portraits, congratulations=receiving-line/toasts, group=family/friends groupings, party=reception/dancing, details=rings/decor/still-life, other=misc/candid/kids).
- eyes: of the PRIMARY subject (couple first). Profile/back-to-camera/no-face = na, never guess.
- focus: is the primary subject critically sharp? soft/oof if not. You are at ~1600px — if you cannot be sure, say acceptable and let the note flag it.
- grade A/B/C as above. Be willing to give C's; a buffer of mediocre frames helps no one.
- dup_note: if two frames in this batch are near-identical, keep the stronger and mark the weaker's dup_note with the winner's id.
- note: one line. If an obvious crop or color/exposure direction jumps out, say it in words (never invent numbers).
Echo each preview path back in "preview". Return ONE verdict per element, all of them.`

const VERIFY_PROMPT = (id, preview) => `Independent second look for a wedding BUFFER pick. Frame ${id}. Use the Read tool to open ${preview} and judge it fresh, as a skeptic.

Confirm it is worth keeping as a nice-to-have backup behind the locked delivery. Downgrade if: the primary subject is soft/out-of-focus, a key face is blinked or mid-word, the composition is awkward, or it's clearly redundant. Keep if it's a clean, usable, pleasant frame.
- eyes: primary subject (profile/back/no-face = na).
- focus: sharp/acceptable/soft/oof on the primary subject at ~1600px.
- dup_risk: your gut on whether this likely duplicates a stronger frame elsewhere in the shoot.
- flag100: one thing the photographer should confirm at 100% before using it (focus, eyes, highlight clip), or "none". Do NOT claim critical focus is confirmed from a 1600px preview.
- note: one line.`

// ---------- Phase 1: screen all (barrier — need every verdict to rank + scene-balance globally) ----------
phase('Screen')
const batchPaths = args.batches
const screenResults = await parallel(batchPaths.map((p, i) => () =>
  agent(SCREEN_PROMPT(p), { label: `screen:bb_${String(i).padStart(2,'0')}`, phase: 'Screen', schema: SCREEN_SCHEMA, model: 'sonnet', effort: 'medium' })
))

const all = screenResults.filter(Boolean).flatMap(r => r.verdicts || [])
log(`screened ${all.length} frames`)

// drop obvious defects, dedup by id (a frame can only appear once)
const byId = {}
for (const v of all) if (v && v.id && !byId[v.id]) byId[v.id] = v
let kept = Object.values(byId).filter(v =>
  v.grade !== 'C' && v.eyes !== 'closed' && v.focus !== 'oof'
)

// score for ranking
const gradeS = { A: 30, B: 15 }
const eyeS = { open: 6, na: 4, partial: 2, closed: -100 }
const focusS = { sharp: 8, acceptable: 4, soft: -2, oof: -100 }
const score = v => (gradeS[v.grade]||0) + (eyeS[v.eyes]||0) + (focusS[v.focus]||0)
kept.sort((a,b) => score(b) - score(a))

// scene-balanced shortlist for the verify pass (targets proportional to the delivery)
const DELIV = args.delivery
const DTOT = Object.values(DELIV).reduce((a, b) => a + b, 0)
const targetFor = (n) => { const t={}; for (const s of SCENES) t[s]=Math.round((DELIV[s]||0)/DTOT*n); return t }
function sceneBalancedPick(pool, n) {
  const target = targetFor(n)
  const cnt = {}; const chosen = []; const taken = new Set()
  // pass 1: fill each scene up to its target, best-first
  for (const v of pool) {
    if (chosen.length >= n) break
    const s = v.scene
    if ((cnt[s]||0) < (target[s]||0)) { chosen.push(v); taken.add(v.id); cnt[s]=(cnt[s]||0)+1 }
  }
  // pass 2: fill remaining slots with best leftovers regardless of scene
  for (const v of pool) {
    if (chosen.length >= n) break
    if (!taken.has(v.id)) { chosen.push(v); taken.add(v.id); cnt[v.scene]=(cnt[v.scene]||0)+1 }
  }
  return chosen
}
const shortlist = sceneBalancedPick(kept, args.shortlist)
log(`verify shortlist: ${shortlist.length} (of ${kept.length} kept, ${Object.keys(byId).length} screened)`)

// ---------- Phase 2: independent verify of the shortlist ----------
phase('Verify')
const verified = await parallel(shortlist.map(v => () =>
  agent(VERIFY_PROMPT(v.id, v.preview), { label: `verify:${v.id}`, phase: 'Verify', schema: VERIFY_SCHEMA, model: 'sonnet', effort: 'medium' })
    .then(res => res ? ({ ...v, verify: res }) : null)
))

const confirmed = verified.filter(Boolean).filter(x => x.verify.confirm === 'keep')
log(`confirmed after verify: ${confirmed.length}`)

// final scene-balanced bench from confirmed (re-sort with verify signal folded in)
const dupPenalty = { low: 0, med: -6, high: -20 }
confirmed.sort((a,b) => (score(b) + (dupPenalty[b.verify.dup_risk]||0)) - (score(a) + (dupPenalty[a.verify.dup_risk]||0)))
const final50 = sceneBalancedPick(confirmed, args.bench)

const dist = {}
for (const v of final50) dist[v.scene] = (dist[v.scene]||0) + 1

return {
  screened: Object.keys(byId).length,
  kept_after_defect_drop: kept.length,
  shortlist: shortlist.length,
  confirmed: confirmed.length,
  final_count: final50.length,
  scene_dist: dist,
  buffer_50: final50.map(v => ({
    id: v.id, tier: undefined, scene: v.scene, eyes: v.eyes, focus: v.focus, grade: v.grade,
    subject: v.subject, note: v.note,
    v_eyes: v.verify.eyes, v_focus: v.verify.focus, dup_risk: v.verify.dup_risk,
    flag100: v.verify.flag100, v_note: v.verify.note,
  })),
  dropped_by_verify: verified.filter(Boolean).filter(x => x.verify.confirm === 'downgrade').map(x => ({ id: x.id, scene: x.scene, why: x.verify.note })),
}

export const meta = {
  name: 'buffer-topup-verify',
  description: 'Verify next-best buffer candidates to top up a short backup bench',
  phases: [{ title: 'Verify' }],
}

// args: [{id, preview, note, ...}] next-best screened candidates from buffer-screen

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['id','confirm','eyes','focus','dup_risk','flag100','note'],
  properties: {
    id: { type: 'string' },
    confirm: { type: 'string', enum: ['keep','downgrade'] },
    eyes: { type: 'string', enum: ['open','partial','closed','na'] },
    focus: { type: 'string', enum: ['sharp','acceptable','soft','oof'] },
    dup_risk: { type: 'string', enum: ['low','med','high'] },
    flag100: { type: 'string' },
    note: { type: 'string' },
  },
}

const VERIFY_PROMPT = (id, preview, hint) => `Independent second look for a wedding BUFFER pick. Frame ${id}. Use the Read tool to open ${preview} and judge it fresh, as a skeptic. (Screening note, treat as hint only: ${hint})

Confirm it is worth keeping as a nice-to-have backup behind the locked delivery. Downgrade if: the primary subject is soft/out-of-focus, a key face is blinked or mid-word, the composition is awkward, or it's clearly redundant. Keep if it's a clean, usable, pleasant frame.
- eyes: primary subject (profile/back/no-face = na).
- focus: sharp/acceptable/soft/oof on the primary subject at ~1600px.
- dup_risk: your gut on whether this likely duplicates a stronger frame elsewhere in the shoot.
- flag100: one thing the photographer should confirm at 100% before using it (focus, eyes, highlight clip), or "none". Do NOT claim critical focus is confirmed from a 1600px preview.
- note: one line.`

phase('Verify')
const results = await parallel(args.map(c => () =>
  agent(VERIFY_PROMPT(c.id, c.preview, c.note), { label: `verify:${c.id}`, phase: 'Verify', schema: VERIFY_SCHEMA, model: 'sonnet', effort: 'medium' })
    .then(res => res ? ({ ...c, verify: res }) : null)
))
const done = results.filter(Boolean)
return {
  kept: done.filter(x => x.verify.confirm === 'keep').map(x => ({ id: x.id, scene: x.scene, grade: x.grade, eyes: x.eyes, focus: x.focus, subject: x.subject, note: x.note, v_eyes: x.verify.eyes, v_focus: x.verify.focus, dup_risk: x.verify.dup_risk, flag100: x.verify.flag100, v_note: x.verify.note })),
  dropped: done.filter(x => x.verify.confirm === 'downgrade').map(x => ({ id: x.id, scene: x.scene, why: x.verify.note })),
}

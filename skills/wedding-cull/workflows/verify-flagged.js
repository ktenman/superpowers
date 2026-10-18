export const meta = {
  name: 'wedding-cull-verify',
  description: 'Phase 3b: verify flagged frames at 2560px (eyes open + critical focus) -> pass/hold/fail, portfolio nominees on Opus',
  phases: [{ title: 'Verify', detail: 'one agent per flagged frame at higher res' }],
}

// args: [{id, scene, what, path (2560px decode), nom (portfolio nominee)}]

const SCHEMA = {
  type: "object",
  properties: {
    id: { type: "string" },
    eyes: { type: "string", enum: ["open", "partial", "closed", "na"] },
    focus: { type: "string", enum: ["sharp", "acceptable", "soft", "oof"] },
    verdict: { type: "string", enum: ["pass", "hold", "fail"] },
    note: { type: "string" }
  },
  required: ["id", "eyes", "focus", "verdict", "note"],
  additionalProperties: false
}

function prompt(t) {
  return `You are verifying ONE wedding photo, decoded from RAW at 2560px (much sharper than the culling preview). This frame was flagged during the cull for a closer look before it's locked into the delivery/portfolio set.

Frame: ${t.id}  |  scene: ${t.scene}${t.nom ? "  |  PORTFOLIO NOMINEE" : ""}
CHECK SPECIFICALLY: ${t.what}

STEP 1 - Open the image (Read): ${t.path}
STEP 2 - Judge honestly, only what you can see at 2560px:
  eyes  = are the KEY subjects' eyes open?  open / partial / closed / na (na = no faces / detail shot)
  focus = is critical focus on the key subject good?  sharp / acceptable / soft / oof
          (You are at 2560px, not 100%. Use "acceptable" when it looks fine but true pixel-focus needs a 100% peek; reserve "soft"/"oof" for visibly missed focus.)
  verdict = pass (clean - safe to deliver${t.nom ? "/portfolio" : ""})
          / hold (deliverable but with a caveat - name it in note)
          / fail (a KEY subject's eyes are shut, or the subject is clearly out of focus / motion-blurred - should be demoted from delivery)
  note  = one concrete line (what you actually see: whose eyes, where focus landed, any flaw).

Do NOT invent numbers or confidence %. For a detail/no-face frame, set eyes=na and judge focus only. Be strict on portfolio nominees.`
}

phase('Verify')
const tasks = args
const results = await parallel(tasks.map(t => () =>
  agent(prompt(t), {
    label: `verify:${t.id}${t.nom ? '*' : ''}`,
    phase: 'Verify', schema: SCHEMA,
    model: t.nom ? undefined : 'sonnet',
    effort: t.nom ? 'high' : 'medium',
    agentType: 'general-purpose'
  })
))

const ok = results.filter(Boolean)
const fails = ok.filter(r => r.verdict === 'fail')
const holds = ok.filter(r => r.verdict === 'hold')
const passes = ok.filter(r => r.verdict === 'pass')
log(`verified=${ok.length}/${tasks.length} | pass=${passes.length} hold=${holds.length} fail=${fails.length}`)
return { verified: ok.length, results: ok, fails, holds }

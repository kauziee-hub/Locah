// "Make it look like this": a reference picture laid over a lab owner's draft, then undone.
//   node tools/certify/owner-lab/reference-check.mjs <scenario-run-dir-name> <reference image> [out dir]
// One real vision call. The draft is read back from the API before, after and after undo.
import { mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { mintToken, sessionCookies } from './session.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const API = process.env.CERTIFY_API || 'http://localhost:8020'
const WS = process.env.CERTIFY_WORKSPACE || 'http://localhost:3201'
const [run, image, outArg] = process.argv.slice(2)
const journal = JSON.parse(readFileSync(path.join(ROOT, 'certify-out/product-e2e/SCENARIOS', run, 'journal.json'), 'utf8'))
const OUT = path.resolve(ROOT, outArg || `certify-out/review/reference-${run}`)
mkdirSync(OUT, { recursive: true })
const owner = { ...journal.owner, token: mintToken(journal.owner) }
const B = journal.business_id
let failed = 0
const check = (label, ok, detail = '') => {
  if (!ok) failed++
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label}${detail ? ` — ${String(detail).slice(0, 300)}` : ''}`)
}
const headers = { Authorization: `Bearer ${owner.token}`, 'Content-Type': 'application/json' }
const theme = async () => (await (await fetch(`${API}/v1/b/${B}/website`, { headers })).json()).data.draft.theme
const design = (t) => JSON.stringify([{ ...t.dna, headline: null }, t.experience, t.composition])

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 } })
await ctx.addCookies(sessionCookies(owner))
const page = await ctx.newPage()
const shot = async (name) => {
  await page.goto(`${WS}/b/${B}/website/preview`, { waitUntil: 'networkidle', timeout: 180000 })
  await page.waitForTimeout(5000)
  await page.screenshot({ path: path.join(OUT, `${name}.png`) })
}

const before = await theme()
await shot('1-before')
const mime = /\.png$/i.test(image) ? 'image/png' : /\.webp$/i.test(image) ? 'image/webp' : 'image/jpeg'
const res = await fetch(`${API}/v1/b/${B}/website/reference-style`, {
  method: 'POST', headers, body: JSON.stringify({ image_base64: readFileSync(image).toString('base64'), mime_type: mime }),
})
const data = (await res.json()).data || {}
console.log('LOCAH:', data.reply)
console.log('mood:', (data.mood || []).join(', '), '|', data.why || '')
check('the reference was read and applied', res.status === 200 && data.matched === true, `${res.status}`)
const after = await theme()
console.log('now:', JSON.stringify({ bg: after.background_color, text: after.text_color, primary: after.primary_color, accent: after.accent_color, style: after.owner_style }))
check('colours and the owner’s style changed', after.primary_color !== before.primary_color || after.background_color !== before.background_color)
check('the site’s own composition, motion and art direction did not', design(after) === design(before))
await shot('2-matched')

const undo = await fetch(`${API}/v1/b/${B}/website/reference-style`, { method: 'POST', headers, body: JSON.stringify({ undo: true }) })
const undone = (await undo.json()).data || {}
const back = await theme()
check('undo puts the draft back exactly', undone.undone === true && JSON.stringify(back) === JSON.stringify(before),
  JSON.stringify(Object.keys(back).filter((k) => JSON.stringify(back[k]) !== JSON.stringify(before[k]))))
await shot('3-undone')
await browser.close()
console.log(`\n${failed ? failed + ' failed' : 'all passed'}. Screenshots: ${OUT}`)
process.exit(failed ? 1 : 0)

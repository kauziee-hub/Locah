// A composed section in the Website editor, driven as a lab owner: flip it,
// try another arrangement, edit a block's words, ask for it in chat — and put
// it back. Every check is read back from the API (the draft).
//   node tools/certify/owner-lab/composition-editor-check.mjs <scenario-run-dir-name> [out dir]
import { mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { mintToken, sessionCookies } from './session.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const API = process.env.CERTIFY_API || 'http://localhost:8020'
const WS = process.env.CERTIFY_WORKSPACE || 'http://localhost:3201'
const [run, outArg] = process.argv.slice(2)
const journal = JSON.parse(readFileSync(path.join(ROOT, 'certify-out/product-e2e/SCENARIOS', run, 'journal.json'), 'utf8'))
const OUT = path.resolve(ROOT, outArg || `certify-out/review/comp-editor-${run}`)
mkdirSync(OUT, { recursive: true })
const owner = { ...journal.owner, token: mintToken(journal.owner) }
const B = journal.business_id
const headers = { Authorization: `Bearer ${owner.token}`, 'Content-Type': 'application/json' }
let failed = 0
const check = (label, ok, detail = '') => {
  if (!ok) failed++
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label}${detail ? ` — ${String(detail).slice(0, 240)}` : ''}`)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const draft = async () => (await (await fetch(`${API}/v1/b/${B}/website`, { headers })).json()).data.draft
const composed = async () => {
  const d = await draft()
  for (const p of d.pages) for (const s of p.sections) if (s.section_type_id === 'composition') return { page: p, section: s }
  return null
}
const cols = (s) => s.content.items.map((b) => `${b.kind}:${b.col}/${b.span}`).join(' ')

const first = await composed()
if (!first) {
  console.log('FAIL this business has no composed section')
  process.exit(1)
}
const original = first.section.content
console.log('composition:', first.page.slug, original.role, original.recipe, cols(first.section))

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 } })
await ctx.addCookies(sessionCookies(owner))
const page = await ctx.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)))
await page.goto(`${WS}/b/${B}/website/preview`, { waitUntil: 'networkidle', timeout: 180000 })
if (first.page.slug !== 'home') {
  await page.locator('#ed-page').selectOption({ label: first.page.title })
  await sleep(1500)
}
const row = page.locator(`#ed-sec-${first.section.id}`)
await row.locator('.ed-sec__head').click()
await row.getByRole('button', { name: 'Flip sides' }).waitFor({ timeout: 30000 })
await page.screenshot({ path: path.join(OUT, '1-panel.png') })
check('the composed section opens with its arrangement controls and its blocks',
  (await row.locator('.ed-comp__block').count()) === original.items.length)

await row.getByRole('button', { name: 'Flip sides' }).click()
await sleep(2500)
const flipped = (await composed()).section
check('Flip sides mirrors the arrangement', cols(flipped) !== cols(first.section) && flipped.content.recipe === original.recipe,
  `${cols(first.section)} → ${cols(flipped)}`)

await page.locator(`#ed-sec-${first.section.id}`).getByRole('button', { name: 'Another arrangement' }).click()
await sleep(2500)
const next = (await composed()).section
check('Another arrangement changes the recipe, keeping the words', next.content.recipe !== original.recipe &&
  JSON.stringify(next.content.items.map((b) => b.title).filter(Boolean)).includes(JSON.stringify(original.items.find((b) => b.title)?.title || '').slice(1, -1)),
  `${original.recipe} → ${next.content.recipe}`)
await page.screenshot({ path: path.join(OUT, '2-another.png') })

// A block's words, edited in place.
const titled = page.locator(`#ed-sec-${first.section.id}`).locator('input[id$="-title"]').first()
const before = await titled.inputValue()
await titled.fill(`${before} (edited)`)
await titled.blur()
await sleep(2500)
const edited = (await composed()).section
check('a block’s heading can be edited in place', edited.content.items.some((b) => b.title === `${before} (edited)`))
await titled.fill(before)
await titled.blur()
await sleep(2000)

// The same by chat.
await page.getByRole('tab', { name: 'Ask LOCAH' }).click()
await page.locator('#ed-ask-box').fill('try another layout for the story')
await page.getByRole('button', { name: 'Change it' }).click()
await page.locator('.ed-ask__turn[data-who="locah"]:not([data-pending])').last().waitFor({ timeout: 60000 })
await sleep(1500)
const reply = await page.locator('.ed-ask__turn[data-who="locah"]').last().innerText()
const chatted = (await composed()).section
console.log('LOCAH:', reply)
check('asked in chat, the arrangement changes', chatted.content.recipe !== next.content.recipe || cols(chatted) !== cols(next), reply)
await page.screenshot({ path: path.join(OUT, '3-chat.png') })

// Put it back exactly as it was.
await fetch(`${API}/v1/b/${B}/website/sections/${first.section.id}`, { method: 'PATCH', headers, body: JSON.stringify({ content: original }) })
const restored = (await composed()).section
check('restored to how it was', JSON.stringify(restored.content) === JSON.stringify(original))
check('no page errors', errors.length === 0, errors.join(' | '))
await browser.close()
console.log(`\n${failed ? failed + ' failed' : 'all passed'}. Screenshots: ${OUT}`)
process.exit(failed ? 1 : 0)

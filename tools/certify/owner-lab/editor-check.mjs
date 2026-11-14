// The Website editor, driven as a lab owner: arrange, design, ask.
//   node tools/certify/owner-lab/editor-check.mjs <scenario-run-dir-name> [out dir]
// Every check is read back from the API (the draft) or from the preview frame —
// never from the control that was just clicked.
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
const OUT = path.resolve(ROOT, outArg || `certify-out/review/editor-${run}`)
mkdirSync(OUT, { recursive: true })
const owner = { ...journal.owner, token: mintToken(journal.owner) }
const B = journal.business_id
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let passed = 0
let failed = 0
const check = (label, ok, detail = '') => {
  ok ? passed++ : failed++
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label}${detail ? ` — ${String(detail).slice(0, 220)}` : ''}`)
}
async function draft() {
  const res = await fetch(`${API}/v1/b/${B}/website`, { headers: { Authorization: `Bearer ${owner.token}` } })
  return (await res.json()).data.draft
}
const home = (d) => d.pages.find((p) => p.slug === 'home')
const kinds = (d) => [...home(d).sections].sort((a, b) => a.sort_order - b.sort_order).map((s) => s.section_type_id)

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 } })
await ctx.addCookies(sessionCookies(owner))
const page = await ctx.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)))
const shot = (name) => page.screenshot({ path: path.join(OUT, `${name}.png`) })
const status = () => page.locator('.ed-status').innerText().catch(() => '')
const settle = async (re = /saved|changed|added|removed|hidden|shown|copy|back/i) => {
  await page.waitForFunction((src) => new RegExp(src, 'i').test(document.querySelector('.ed-status')?.textContent || ''), re.source, { timeout: 30000 }).catch(() => {})
  await sleep(1200)
}

const before = await draft()
const themeBefore = before.theme || {}
console.log('design before:', JSON.stringify({ dna: themeBefore.dna?.concept, display: themeBefore.dna?.display, primary: themeBefore.primary_color, sections: kinds(before) }))

await page.goto(`${WS}/b/${B}/website/preview`, { waitUntil: 'networkidle', timeout: 180000 })
await page.locator('.ed__frame iframe').waitFor({ timeout: 60000 })
await sleep(4000)
await shot('01-editor')
check('the editor shows Sections, Design and Ask LOCAH', (await page.getByRole('tab').allInnerTexts()).join('|') === 'Sections|Design|Ask LOCAH')
const rows = await page.locator('.ed-sec').count()
check('every section of the page is listed', rows === kinds(before).length, `${rows} rows / ${kinds(before).length} sections`)

// 1. click a section in the real page → it opens in the rail
const frame = page.frameLocator('.ed__frame iframe')
const second = frame.locator('[data-section-id]').nth(2)
const secondId = await second.getAttribute('data-section-id')
await second.locator(':scope > *').first().click({ position: { x: 40, y: 40 } }).catch(async () => {
  await frame.locator(`[data-section-id="${secondId}"] *`).first().click()
})
await sleep(800)
check('clicking a section in the preview opens it in the editor', (await page.locator(`#ed-sec-${secondId}`).getAttribute('data-open')) === 'true')
await shot('02-click-to-select')

// 2. move the third section up with the arrow, then drag it back down
const order0 = kinds(await draft())
const third = page.locator('.ed-sec').nth(2)
await third.getByRole('button', { name: /^Move .* up$/ }).click()
await settle(/order saved/)
const order1 = kinds(await draft())
check('Move up changes the saved order', order1[1] === order0[2] && order1[2] === order0[1], `${order0.slice(0, 4)} → ${order1.slice(0, 4)}`)
const grip = page.locator('.ed-sec').nth(1).locator('.ed-sec__grip')
const target = page.locator('.ed-sec').nth(2)
await grip.dragTo(target)
await settle(/order saved/)
const order2 = kinds(await draft())
check('dragging a section by its handle moves it', order2.join() === order0.join(), `${order1.slice(0, 4)} → ${order2.slice(0, 4)}`)
await shot('03-reordered')

// 3. hide and show from the row's menu
const row = page.locator('.ed-sec').nth(2)
const rowId = (await row.getAttribute('id')).replace('ed-sec-', '')
await row.getByRole('button', { name: /^More for/ }).click()
await row.getByRole('button', { name: 'Hide from the page' }).click()
await settle(/hidden/)
let now = home(await draft()).sections.find((s) => s.id === rowId)
check('Hide takes the section off the page without deleting it', now && now.is_visible === false)
await sleep(2500)
check('the hidden section is not in the preview', (await page.frameLocator('.ed__frame iframe').locator(`[data-section-id="${rowId}"]`).count()) === 0)
await page.locator(`#ed-sec-${rowId}`).getByRole('button', { name: /^More for/ }).click()
await page.locator(`#ed-sec-${rowId}`).getByRole('button', { name: 'Show on the page' }).click()
await settle(/shown/)
now = home(await draft()).sections.find((s) => s.id === rowId)
check('Show brings it back', now && now.is_visible === true)

// 4. add a section, then remove it
await page.getByRole('button', { name: '+ Add a section' }).click()
await page.locator('.ed-add__item').first().waitFor({ timeout: 20000 })
const offered = await page.locator('.ed-add__item strong').allInnerTexts()
console.log('can add:', offered.join(', '))
await page.locator('.ed-add__item', { hasText: /^Text/ }).first().click()
await settle(/added/)
const withText = kinds(await draft())
check('Add a section adds it to the page', withText.length === order0.length + 1 && withText.at(-1) === 'text_block', withText.slice(-3))
await shot('04-added')
const last = page.locator('.ed-sec').last()
await last.getByRole('button', { name: /^More for/ }).click()
await last.getByRole('button', { name: 'Remove…' }).click()
await last.getByRole('button', { name: 'Yes, remove it' }).click()
await settle(/removed/)
check('Remove asks first, then removes it', kinds(await draft()).length === order0.length)

// 5. Design: a ready-made pair, a lettering, a size
await page.getByRole('tab', { name: 'Design' }).click()
await page.locator('.ed-swatch').first().waitFor()
await shot('05-design')
await page.getByRole('button', { name: 'Use Maroon & gold' }).click()
await settle(/saved/)
await page.locator('.ed-font', { hasText: 'Elegant' }).click()
await settle(/lettering saved/)
await page.locator('.ed-field', { hasText: 'Heading size' }).getByRole('button', { name: 'Large', exact: true }).click()
await settle(/Heading size saved/)
const styled = (await draft()).theme
check('the pair is saved as the main and accent colours', styled.primary_color === '#7b1e2b' && styled.accent_color === '#b8860b', `${styled.primary_color} ${styled.accent_color}`)
check('the lettering and size are saved as the owner’s style', styled.owner_style?.font === 'elegant' && styled.owner_style?.heading_size === 'large', JSON.stringify(styled.owner_style))
check('the site’s design is untouched by all of it', JSON.stringify(styled.dna) === JSON.stringify(themeBefore.dna) && JSON.stringify(styled.experience) === JSON.stringify(themeBefore.experience) && JSON.stringify(styled.composition) === JSON.stringify(themeBefore.composition))
await sleep(3500)
const seen = await page.frameLocator('.ed__frame iframe').locator('[data-locah-site]').evaluate((el) => ({
  display: el.getAttribute('data-display'), heading: el.getAttribute('data-owner-heading'),
  primary: getComputedStyle(el).getPropertyValue('--site-primary').trim(),
  h1zoom: getComputedStyle(document.querySelector('h1')).zoom,
}))
check('the preview shows the new colour, lettering and size', seen.display === 'cormorant' && seen.heading === 'large' && seen.primary === '#7b1e2b' && Number(seen.h1zoom) > 1, JSON.stringify(seen))
await shot('06-design-applied')

// 6. Ask LOCAH — with slips
await page.getByRole('tab', { name: 'Ask LOCAH' }).click()
await page.locator('#ed-ask-box').fill('chnge colur to dark green and make the text biger, also rounded buttons')
await page.getByRole('button', { name: 'Change it' }).click()
await page.locator('.ed-ask__turn[data-who="locah"]:not([data-pending])').last().waitFor({ timeout: 60000 })
await sleep(1500)
const reply1 = await page.locator('.ed-ask__turn[data-who="locah"]').last().innerText()
console.log('LOCAH:', reply1)
const asked = (await draft()).theme
check('asked in words (with typos): colour, text size and corners all changed', asked.primary_color === '#1f4d2b' && asked.owner_style?.text_size === 'large' && asked.owner_style?.corners === 'round', `${asked.primary_color} ${JSON.stringify(asked.owner_style)}`)
const mv = kinds(await draft())
const menuKind = mv.find((k) => ['product_showcase', 'category_showcase'].includes(k))
await page.locator('#ed-ask-box').fill('move the menu to the bottom')
await page.getByRole('button', { name: 'Change it' }).click()
await page.waitForFunction(() => document.querySelectorAll('.ed-ask__turn[data-who="locah"]:not([data-pending])').length >= 2, null, { timeout: 60000 })
await sleep(1500)
console.log('LOCAH:', await page.locator('.ed-ask__turn[data-who="locah"]').last().innerText())
const mv2 = kinds(await draft())
check('asked to move a section: it moved', mv2.at(-1) === menuKind && mv.at(-1) !== menuKind, `${mv.slice(-3)} → ${mv2.slice(-3)}`)
await page.locator('#ed-ask-box').fill('add online payment gateway')
await page.getByRole('button', { name: 'Change it' }).click()
await page.waitForFunction(() => document.querySelectorAll('.ed-ask__turn[data-who="locah"]:not([data-pending])').length >= 3, null, { timeout: 60000 })
const reply3 = await page.locator('.ed-ask__turn[data-who="locah"]').last().innerText()
console.log('LOCAH:', reply3)
check('asked for something it cannot do: it says so and changes nothing', /did not change anything|cannot|can't/i.test(reply3) && JSON.stringify((await draft()).theme) === JSON.stringify(asked))
await shot('07-ask')

// 7. put things back: the menu where it was, the original look
await page.locator('#ed-ask-box').fill('go back to the original design')
await page.getByRole('button', { name: 'Change it' }).click()
await page.waitForFunction(() => document.querySelectorAll('.ed-ask__turn[data-who="locah"]:not([data-pending])').length >= 4, null, { timeout: 60000 })
await sleep(1000)
const reset = (await draft()).theme
check('“go back to the original design” clears the owner’s style and keeps the design', !reset.owner_style && JSON.stringify(reset.dna) === JSON.stringify(themeBefore.dna))
await fetch(`${API}/v1/b/${B}/website/theme`, { method: 'PATCH', headers: { Authorization: `Bearer ${owner.token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ theme: { primary_color: themeBefore.primary_color, accent_color: themeBefore.accent_color } }) })
const sections = [...home(await draft()).sections]
const wanted = order0.map((k) => sections.find((s) => s.section_type_id === k && !s._used && (s._used = true))).filter(Boolean)
if (wanted.length === sections.length) {
  await fetch(`${API}/v1/b/${B}/website/pages/${home(before).id}/sections/reorder`, { method: 'POST', headers: { Authorization: `Bearer ${owner.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ section_ids: wanted.map((s) => s.id) }) })
}

// 8. the Look & menu page that used to erase the design
await page.goto(`${WS}/b/${B}/website/theme`, { waitUntil: 'networkidle', timeout: 120000 })
await shot('08-look-and-menu')
check('Look & menu has no JSON box', (await page.locator('textarea').count()) === 0 && (await page.getByText(/JSON/).count()) === 0)
check('and lists the header links to rename and reorder', (await page.locator('.ed-nav__row').count()) >= 2)

check('no page errors in the editor', errors.length === 0, errors.join(' | '))
console.log(`\n${passed} passed, ${failed} failed. Screenshots: ${OUT}`)
await browser.close()
process.exit(failed ? 1 : 0)

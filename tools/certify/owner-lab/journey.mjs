#!/usr/bin/env node
// Owner Simulation Lab — one business owner, end to end, in a real browser.
//
//   node tools/certify/owner-lab/journey.mjs <scenario> <variant> [--from <step>] [--run <dir>]
//
// Against the certification stack (tools/certify/stack: API :8020, worker,
// public web :3200, Workspace :3201, auth stand-in :54331). The owner is a
// fresh test identity (session.mjs); from there every step is the product's
// own UI, clicked and typed: /start → the interview chat → "Build my website"
// → preview → publish → the Workspace. The persona's words are the same the
// API journeys use (platform_testing.certify.owners). The API is read — never
// written — to know what LOCAH is asking and to check what the UI claims
// against the database-backed state.
//
// Evidence: certify-out/product-e2e/SCENARIOS/<scenario>-<variant>/ — a
// journal.json (every step: what was done, what the UI and the API said,
// pass/fail) and numbered screenshots.
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { mintToken, newOwner, sessionCookies } from './session.mjs'
import { bookingJourney } from './booking-journey.mjs'
import { stayJourney } from './stay-journey.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const API = process.env.CERTIFY_API || 'http://localhost:8020'
const WEB = process.env.CERTIFY_WEB || 'http://localhost:3200'
const WS = process.env.CERTIFY_WORKSPACE || 'http://localhost:3201'

const argv = process.argv.slice(2)
const opt = (name, fallback) => {
  const i = argv.indexOf(`--${name}`)
  return i >= 0 ? argv[i + 1] : fallback
}
const [scenarioKey = 'meat-shop', variant = 'normal'] = argv.filter((a, i) => !a.startsWith('--') && !argv[i - 1]?.startsWith('--'))
const OUT = path.resolve(ROOT, opt('run', `certify-out/product-e2e/SCENARIOS/${scenarioKey}-${variant}`))
mkdirSync(path.join(OUT, 'shots'), { recursive: true })

const persona = JSON.parse(
  execFileSync('uv', ['run', '--no-env-file', 'python', '-m', 'platform_testing.certify.lab_owner', 'script', scenarioKey, variant], {
    cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'], env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  }).trim().split(/\r?\n/).pop(),
)

// ------------------------------------------------------------------ journal
const statePath = path.join(OUT, 'journal.json')
const journal = existsSync(statePath) && opt('from')
  ? JSON.parse(readFileSync(statePath, 'utf8'))
  : { scenario: scenarioKey, variant, started_at: new Date().toISOString(), owner: null, business_id: null, steps: [] }
let shotNo = journal.steps.reduce((n, s) => n + (s.shots?.length || 0), 0)
function save() {
  writeFileSync(statePath, JSON.stringify(journal, null, 1))
}
function step(name) {
  const entry = { name, at: new Date().toISOString(), status: 'running', notes: [], shots: [], checks: [] }
  journal.steps.push(entry)
  save()
  console.log(`\n== ${name}`)
  return {
    note(text) { entry.notes.push(text); console.log('  ·', text) },
    check(label, ok, detail = '') {
      entry.checks.push({ label, ok: Boolean(ok), detail: String(detail).slice(0, 400) })
      console.log(`  ${ok ? 'PASS' : 'FAIL'} ${label}${detail ? ` — ${String(detail).slice(0, 160)}` : ''}`)
      return Boolean(ok)
    },
    async shot(page, label, full = false) {
      const file = `shots/${String(++shotNo).padStart(2, '0')}-${label}.png`
      await page.screenshot({ path: path.join(OUT, file), fullPage: full }).catch(() => {})
      entry.shots.push(file)
    },
    done(status) {
      entry.status = status || (entry.checks.every((c) => c.ok) ? 'pass' : 'fail')
      entry.ended_at = new Date().toISOString()
      save()
      console.log(`  => ${entry.status}`)
      return entry.status
    },
  }
}

// ---------------------------------------------------------------- the owner
let owner = journal.owner
if (!owner) {
  owner = newOwner(scenarioKey.replace(/[^a-z]/g, '').slice(0, 10))
  journal.owner = { id: owner.id, email: owner.email }
  save()
} else {
  owner = { ...owner, token: mintToken(owner) }
}
async function api(method, p, body, token = owner.token) {
  const res = await fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try { data = await res.json() } catch {}
  return { status: res.status, data: data?.data ?? data }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// The question LOCAH is asking now, and this owner's answer to it.
const ALIASES = { name: ['name', 'identity'], contact: ['contact', 'phone'], offer: ['offer', 'catalogue'],
  structure: ['structure', 'catalogue', 'offer'], catalogue: ['catalogue', 'structure', 'offer'] }
const askOf = (data) => {
  const bp = data?.blueprint || {}
  const asks = bp.asks || []
  return asks.length ? String(asks[asks.length - 1]?.ask || '') : String(bp.last_asked_target || '')
}
const readyOf = (data) => {
  const state = data?.blueprint?.completion_state || {}
  return Boolean(data?.build_available || state.ready_at || ['review', 'ready'].includes(state.status))
}
function answerFor(ask) {
  for (const key of ALIASES[ask] || [ask]) if (persona.answers[key]) return persona.answers[key]
  if (ask === 'name') return `It's called ${persona.business_name}.`
  return null
}

const browser = await chromium.launch()
const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await ownerCtx.addCookies(sessionCookies(owner))
const page = await ownerCtx.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 300)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
// The business model decides the steps after the build: an order business
// (catalogue, stock, a customer order, fulfilment) or a booking business
// (services, hours, the people customers book, an appointment and its changes).
// A hotel books nights in rooms of a room type (stay-journey.mjs).
const MODEL = persona.kind === 'hotel' ? 'stay'
  : persona.modules.includes('bookings') && !persona.modules.includes('orders') ? 'booking' : 'order'
const from = opt('from', 'start')
const ORDERS = {
  order: ['start', 'interview', 'build', 'tools', 'workspace', 'catalogue', 'stock', 'publish', 'customer', 'fulfil', 'team', 'lifecycle', 'return'],
  booking: ['start', 'interview', 'build', 'tools', 'workspace', 'services', 'hours', 'providers', 'publish', 'book', 'conflicts',
    'appointment', 'guest-cancel', 'team', 'lifecycle', 'return'],
  stay: ['start', 'interview', 'build', 'tools', 'workspace', 'rooms', 'roomlist', 'publish', 'stay', 'overlap', 'arrival',
    'guest-cancel', 'return'],
}
const ORDER = ORDERS[MODEL]
const to = opt('to', ORDER[ORDER.length - 1])
if (!ORDER.includes(from) || !ORDER.includes(to)) throw new Error(`steps for a ${MODEL} business: ${ORDER.join(', ')}`)
const runs = (name) => ORDER.includes(name) && ORDER.indexOf(name) >= ORDER.indexOf(from) && ORDER.indexOf(name) <= ORDER.indexOf(to)
journal.model = MODEL

try {
  // ------------------------------------------------------------- 1. start
  if (runs('start')) {
    const s = step('start: a new owner opens LOCAH and describes the business')
    await page.goto(`${WS}/`, { waitUntil: 'networkidle', timeout: 180000 })
    s.check('a business-less owner opening the Workspace is sent to onboarding', page.url().startsWith(`${WEB}/start`), page.url())
    await s.shot(page, 'start')
    await page.locator('textarea').first().fill(persona.opening)
    s.note(`typed the opening (${persona.opening.length} chars)`)
    await page.getByRole('button', { name: /continue/i }).click()
    await page.waitForURL(/\/start\/[0-9a-f-]{36}\/interview/, { timeout: 240000 })
    journal.business_id = page.url().match(/start\/([0-9a-f-]{36})/)[1]
    s.check('Continue created the business and opened the interview', Boolean(journal.business_id), journal.business_id)
    const biz = await api('GET', `/v1/b/${journal.business_id}`)
    s.check('the business exists for this owner (API)', biz.status === 200, `status ${biz.status}`)
    await page.waitForLoadState('networkidle').catch(() => {})
    await s.shot(page, 'interview-opened')
    s.done()
  }
  const B = journal.business_id
  // A booking business's own steps (services, hours, providers, a guest's
  // appointment and what happens to it): booking-journey.mjs.
  const BK = MODEL === 'booking'
    ? bookingJourney({ browser, page, api, step, journal, B, WS, WEB, API, sleep, pageErrors })
    : null
  const ST = MODEL === 'stay'
    ? stayJourney({ browser, page, api, step, journal, B, WS, WEB, API, sleep, pageErrors })
    : null

  // --------------------------------------------------------- 2. interview
  if (runs('interview')) {
    const s = step('interview: answer what LOCAH asks, in the chat')
    if (!page.url().includes(`/start/${B}/interview`)) await page.goto(`${WEB}/start/${B}/interview`, { waitUntil: 'networkidle' })
    const answered = {}
    const said = new Set()
    for (let turn = 0; turn < 14; turn++) {
      const state = await api('GET', `/v1/b/${B}/interview`)
      const data = state.data || {}
      const ask = askOf(data)
      const last = [...(data.blueprint?.messages || [])].reverse().find((m) => m.role === 'assistant')
      s.note(`LOCAH asks [${ask || '-'}]: ${(last?.text || '').replace(/\s+/g, ' ').slice(0, 140)}`)
      if (readyOf(data) && (!ask || ask === 'free' || answered[ask] >= 1)) break
      let answer = answerFor(ask)
      if (!answer || said.has(answer)) answer = persona.fallback
      answered[ask] = (answered[ask] || 0) + 1
      said.add(answer)
      const before = Number(data.blueprint?.revision || 0)
      const box = page.getByPlaceholder(/reply in your own words|tell locah what to change/i)
      await box.fill(answer)
      await page.getByRole('button', { name: 'Send' }).click()
      s.note(`owner: ${answer.slice(0, 140)}`)
      // The UI's answer is in when the blueprint has moved on and the chat is idle.
      const t0 = Date.now()
      while (Date.now() - t0 < 180000) {
        await sleep(2500)
        const now = await api('GET', `/v1/b/${B}/interview`)
        if (Number(now.data?.blueprint?.revision || 0) > before && !(await page.locator('.ti-thinking').count())) break
      }
    }
    await s.shot(page, 'interview-done')
    const end = (await api('GET', `/v1/b/${B}/interview`)).data || {}
    s.check('the interview offers Build', readyOf(end), JSON.stringify(end.blueprint?.completion_state || {}).slice(0, 200))
    journal.interview = { turns: (end.blueprint?.messages || []).length, ready: readyOf(end) }
    s.done()
  }

  // ------------------------------------------------------------- 3. build
  if (runs('build')) {
    const s = step('build: review what LOCAH understood, leave the tools for later, Build my website')
    if (!page.url().includes(`/start/${B}/interview`)) await page.goto(`${WEB}/start/${B}/interview`, { waitUntil: 'networkidle' })
    await page.locator('.ti-bar__build, .ti-float-build').first().click()
    await page.locator('.cs-build').waitFor({ timeout: 60000 })
    await s.shot(page, 'confirm-sheet')
    const later = page.getByRole('button', { name: 'Review later' })
    if (await later.count()) {
      await later.click()
      s.note('recommended tools: "Review later" — the owner picks their own set in the Workspace')
    }
    const recommended = await page.locator('.cs-tools li strong').allInnerTexts().catch(() => [])
    journal.recommended_tools = recommended
    s.note(`recommended: ${recommended.join(', ') || '(none)'}`)
    const t0 = Date.now()
    await page.locator('.cs-build').click()
    await page.waitForURL(new RegExp(`/start/${B}/website`), { timeout: 240000 }).catch(() => {})
    s.check('Build opens the website step', page.url().includes(`/start/${B}/website`), page.url())
    let job = {}
    let bpState = ''
    while (Date.now() - t0 < 900000) {
      await sleep(8000)
      bpState = (await api('GET', `/v1/b/${B}/interview`)).data?.blueprint?.completion_state?.status || ''
      job = (await api('GET', `/v1/b/${B}/website/generation`)).data || {}
      if (bpState === 'built' && ['completed', 'fallback_used', 'failed', 'cancelled', 'superseded'].includes(job.status)) break
    }
    journal.build = { seconds: Math.round((Date.now() - t0) / 1000), state: bpState, job_status: job.status,
      fallback_reason: job.fallback_reason || null, usage: job.provider_usage ? Object.fromEntries(Object.entries(job.provider_usage).filter(([k]) => !/audit/.test(k))) : null }
    s.check('the build job finished with the AI build', job.status === 'completed', `${job.status} after ${journal.build.seconds}s`)
    await page.reload({ waitUntil: 'networkidle' })
    await s.shot(page, 'website-step')
    s.done()
  }
  // ------------------------------------------------------------- 4. tools
  if (runs('tools')) {
    const s = step('tools: continue into the Workspace, then turn on my own set of tools')
    // An interview-built site skips "Your tools": the tools wait in the
    // Workspace ("Review later" in the confirm sheet). /done hands off.
    // A resumed run starts on a blank page: the owner comes back to the website step.
    if (page.url() === 'about:blank') await page.goto(`${WEB}/start/${B}/website`, { waitUntil: 'networkidle', timeout: 120000 })
    if (page.url().startsWith(WEB)) {
      if (!page.url().includes(`/start/${B}/website`)) await page.goto(`${WEB}/start/${B}/website`, { waitUntil: 'networkidle' })
      await page.getByRole('link', { name: /continue/i }).first().click()
      await page.waitForURL(new RegExp(`/start/${B}/(done|modules)`), { timeout: 120000 })
      await s.shot(page, 'after-website-continue')
      s.note(`Continue → ${page.url().replace(WEB, '')}`)
      await page.waitForURL(new RegExp(`${WS}/b/${B}`), { timeout: 60000 }).catch(() => {})
    }
    s.check('the hand-off lands in this business Workspace', page.url().startsWith(`${WS}/b/${B}`), page.url())
    await page.waitForLoadState('networkidle').catch(() => {})
    await s.shot(page, 'workspace-first-screen')
    await page.goto(`${WS}/b/${B}/modules`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(page, 'modules-overview', true)
    journal.modules_page_text = (await page.innerText('main').catch(() => '')).replace(/\s+/g, ' ').slice(0, 2500)
    // This owner's own choice. A shop: catalogue, orders, fulfilment and stock
    // (fish sells out) — not online payments, though recommended (UPI or cash
    // at the door). A salon: services, bookings and payments as recommended
    // (the bridal advance online), plus Staff & rota for the stylists people
    // ask for by name.
    const chosen = MODEL === 'stay' ? [...persona.modules]
      : MODEL === 'booking'
      ? [...new Set(persona.modules.concat(['workforce']))]
      : [...new Set(persona.modules.concat(['inventory']))]
    journal.tools_chosen = chosen
    s.note(`recommended in the interview: ${(journal.recommended_tools || []).join(', ')}; chosen: ${chosen.join(', ')}`)
    for (const mid of chosen) {
      await page.goto(`${WS}/b/${B}/modules/${mid}`, { waitUntil: 'networkidle', timeout: 120000 })
      const on = page.getByRole('button', { name: /^turn on/i })
      if (await on.count()) {
        await on.first().click()
        await page.waitForLoadState('networkidle').catch(() => {})
        await sleep(1500)
        s.note(`${mid}: clicked "Turn on"`)
      } else {
        s.note(`${mid}: no "Turn on" (already on, or not offered): ${(await page.innerText('main')).replace(/\s+/g, ' ').slice(0, 160)}`)
      }
      await s.shot(page, `module-${mid}`)
    }
    const mods = await api('GET', `/v1/b/${B}/modules`)
    const active = (Array.isArray(mods.data) ? mods.data : []).filter((m) => m.activation_state === 'active').map((m) => m.module_id)
    journal.modules_active = active
    s.note(`active (API): ${active.join(', ')}`)
    for (const m of chosen) s.check(`chosen tool is active: ${m}`, active.includes(m))
    if (MODEL === 'order') {
      s.check('the declined recommendation stays off: payments', !active.includes('payments'))
    } else {
      // No payment provider account exists on this stack (no Razorpay/Cashfree
      // test keys): Payments may be on — cash and UPI at the salon work without
      // one — but nothing may tell the owner that customers can pay online.
      const pay = (await api('GET', `/v1/b/${B}/modules/payments/setup`)).data || {}
      journal.payments_setup = { status: pay.status, status_label: pay.status_label, remaining: pay.remaining,
        steps: (pay.steps || []).map((x) => `${x.done ? '✓' : '○'} ${x.label}`) }
      s.note(`payments setup (API): ${JSON.stringify(journal.payments_setup).slice(0, 300)}`)
      await page.goto(`${WS}/b/${B}/modules/payments`, { waitUntil: 'networkidle', timeout: 120000 })
      const said = (await page.innerText('main')).replace(/\s+/g, ' ')
      await s.shot(page, 'payments-tool-page', true)
      await page.goto(`${WS}/b/${B}/payments`, { waitUntil: 'networkidle', timeout: 120000 })
      const money = (await page.innerText('main')).replace(/\s+/g, ' ')
      await s.shot(page, 'payments-money-page', true)
      const online = money.slice(money.search(/online payments/i)).slice(0, 300)
      journal.payments_state = { tool_page: said.slice(0, 400), online_payments: online }
      s.check('the Payments money page says online payments are not switched on yet', /waiting for the payment provider|not (yet )?(connected|switched on)/i.test(online), online)
      s.check('the Payments tool page does not promise online payment while no provider is connected',
        !(/working — customers can use it/i.test(said) && /pay online/i.test(said)), said.slice(0, 260))
    }
    s.done()
  }

  // ------------------------------------------------------- 5. the home
  if (runs('workspace')) {
    const s = step('workspace home: what an owner sees with a new business and their tools on')
    await page.goto(`${WS}/b/${B}`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(page, 'workspace-home', true)
    const text = (await page.innerText('main').catch(() => page.innerText('body'))).replace(/\s+/g, ' ')
    journal.workspace_home_text = text.slice(0, 2500)
    s.check('the home has no error screen', !/not reachable|something went wrong|application error/i.test(text), text.slice(0, 160))
    const nav = await page.locator('nav a, aside a').evaluateAll((as) => as.map((a) => `${a.innerText.trim()}|${a.getAttribute('href')}`)).catch(() => [])
    journal.workspace_nav = [...new Set(nav)].slice(0, 80)
    s.note(`nav: ${journal.workspace_nav.map((n) => n.split('|')[0]).filter(Boolean).join(' · ').slice(0, 500)}`)
    s.done()
  }
  // ------------------------------------------------------- 6. catalogue
  if (MODEL === 'order' && runs('catalogue')) {
    const s = step('catalogue: bring in what I told LOCAH, check the prices, make it live, change one price')
    await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(page, 'products-empty', true)
    const fromTalk = page.getByRole('button', { name: /as drafts$/i })
    if (await fromTalk.count()) {
      s.note(`offered from the conversation: ${(await page.locator('#from-talk-h').locator('..').innerText()).replace(/\s+/g, ' ').slice(0, 300)}`)
      await fromTalk.click()
      // "Adding…" until the server has made them; the page then refreshes.
      const t0 = Date.now()
      while (Date.now() - t0 < 120000) {
        await sleep(2000)
        if (((await api('GET', `/v1/platform/businesses/${B}/products`)).data || []).length) break
      }
      await page.locator('#from-talk-h').waitFor({ state: 'detached', timeout: 60000 }).catch(() => {})
      s.note(`drafts made in ${Math.round((Date.now() - t0) / 1000)}s`)
    } else {
      s.note('no "From your conversation with LOCAH" offer on the page')
    }
    await s.shot(page, 'products-drafts', true)
    let products = (await api('GET', `/v1/platform/businesses/${B}/products`)).data || []
    journal.products_after_import = products.map((p) => ({ id: p.id, title: p.title, status: p.status, price_type: p.price_type, price: p.price_amount, unit: p.unit_of_measure }))
    s.note(`products (API): ${journal.products_after_import.map((p) => `${p.title} ${p.price ?? '-'}${p.unit ? '/' + p.unit : ''} [${p.status}]`).join('; ')}`)
    s.check('the items the owner named arrived as products', products.length >= 3, `${products.length} products`)
    const priced = journal.products_after_import.filter((p) => p.price)
    s.check('the prices the owner gave came with them', priced.length >= Math.min(3, products.length), `${priced.length}/${products.length} priced`)
    // Make each one live from its own page, the way the owner would.
    for (const p of products.slice(0, 8)) {
      await page.goto(`${WS}/b/${B}/offerings/${p.id}`, { waitUntil: 'networkidle', timeout: 120000 })
      const liveLabel = page.locator('label.bos-toggle', { hasText: /draft — only you can see it|live — shown to customers/i })
      const toggle = liveLabel.locator('input[type="checkbox"]')
      if (!(await toggle.count())) { s.note(`${p.title}: no live toggle`); continue }
      if (/curry cut/i.test(p.title) && /chicken/i.test(p.title)) {
        const price = page.locator('label').filter({ has: page.locator('span.bos-label', { hasText: /^Price/ }) }).locator('input')
        if (await price.count()) { await price.first().fill('260'); s.note(`${p.title}: price changed to 260`); journal.price_changed = { id: p.id, title: p.title, from: p.price_amount, to: 260 } }
        else s.check(`${p.title}: the price field is there to change`, false)
      }
      if (!(await toggle.isChecked())) await liveLabel.click() // the switch's track covers the box: people click the label
      await page.getByRole('button', { name: /^save$/i }).click()
      const said = await page.locator('p.bos-status').filter({ hasText: /saved|could not|error|needs/i }).first().innerText({ timeout: 30000 }).catch(() => '')
      s.note(`${p.title}: "${said.replace(/\s+/g, ' ').slice(0, 140)}"`)
      if (p === products[0]) await s.shot(page, 'product-editor', true)
    }
    products = (await api('GET', `/v1/platform/businesses/${B}/products`)).data || []
    journal.products_live = products.map((p) => ({ id: p.id, title: p.title, status: p.status, price: p.price_amount }))
    const live = products.filter((p) => p.status === 'active')
    s.check('the owner made the items live (API)', live.length >= Math.min(3, products.length), `${live.length}/${products.length} live`)
    if (journal.price_changed) {
      const changed = products.find((p) => p.id === journal.price_changed.id)
      s.check('the price change was saved (API)', Number(changed?.price_amount) === 260, `${changed?.price_amount}`)
    }
    await page.goto(`${WS}/b/${B}/offerings`, { waitUntil: 'networkidle' })
    await s.shot(page, 'products-live', true)
    s.done()
  }
  // ------------------------------------------------------------- 7. stock
  if (MODEL === 'order' && runs('stock')) {
    const s = step('stock: keep stock of what sells out, record this morning\'s arrival')
    const KEEP = [/chicken curry cut/i, /^mutton/i, /seer fish/i]
    await page.goto(`${WS}/b/${B}/inventory?view=setup`, { waitUntil: 'networkidle', timeout: 120000 })
    for (const re of KEEP) {
      const card = page.locator('ul.bos-stock-setup > li').filter({ has: page.locator('summary strong', { hasText: re }) })
      if (!(await card.count())) { s.check(`item listed in stock settings: ${re}`, false); continue }
      await card.first().locator('summary').click()
      const one = card.first()
      const keep = one.locator('label', { hasText: /Keep stock of/ }).locator('input[type="checkbox"]')
      if (!(await keep.isChecked())) await one.locator('label', { hasText: /Keep stock of/ }).click()
      await one.getByRole('button', { name: 'Save stock settings' }).click()
      await sleep(2000)
      s.note(`${re.source}: keep stock → ${(await one.locator('summary .bos-hint').innerText()).trim()}`)
    }
    await page.reload({ waitUntil: 'networkidle' })
    await s.shot(page, 'stock-settings', true)
    const products = (await api('GET', `/v1/platform/businesses/${B}/products`)).data || []
    const tracked = products.filter((p) => p.track_inventory).map((p) => p.title)
    s.check('three items keep stock (API)', tracked.length >= 3, tracked.join(', '))
    // This morning's arrival, in kilos, on the counter by weight.
    const ARRIVAL = { 'chicken curry cut': '12', mutton: '6', 'seer fish': '4' }
    await page.goto(`${WS}/b/${B}/inventory?view=weighed`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(page, 'counter-before-arrival', true)
    const itemSelect = page.locator('label', { hasText: /^\s*Item/ }).locator('select').first()
    const options = await itemSelect.locator('option').evaluateAll((os) => os.map((o) => ({ value: o.value, text: o.textContent.trim() })))
    s.note(`items on the counter form: ${options.map((o) => o.text).join(', ')}`)
    for (const [word, kg] of Object.entries(ARRIVAL)) {
      const opt = options.find((o) => o.text.toLowerCase().startsWith(word))
      if (!opt) { s.check(`"${word}" can be weighed in`, false, options.map((o) => o.text).join(', ')); continue }
      await itemSelect.selectOption(opt.value)
      await page.locator('label', { hasText: /How much \(kg\)/ }).locator('input').first().fill(kg)
      await page.getByRole('button', { name: 'Record arrival' }).click()
      const said = await page.locator('[role=status], .bos-status').filter({ hasText: /recorded|saved|added|could not|error/i }).first().innerText({ timeout: 20000 }).catch(() => '')
      s.note(`${opt.text}: ${kg} kg → "${said.replace(/\s+/g, ' ').slice(0, 120)}"`)
      await page.waitForLoadState('networkidle').catch(() => {})
    }
    await page.reload({ waitUntil: 'networkidle' })
    await s.shot(page, 'counter-after-arrival', true)
    journal.stock_counter_text = (await page.innerText('main')).replace(/\s+/g, ' ').slice(0, 1500)
    const stock = (await api('GET', `/v1/platform/businesses/${B}/stock`)).data || {}
    const rows = stock.items || stock.rows || stock.records || (Array.isArray(stock) ? stock : [])
    journal.stock_after_arrival = rows.map((r) => ({ title: r.title, on_hand: r.on_hand_text || r.quantity_on_hand })).slice(0, 20)
    s.note(`stock (API): ${journal.stock_after_arrival.map((r) => `${r.title} ${r.on_hand}`).join('; ') || JSON.stringify(stock).slice(0, 200)}`)
    s.check('the arrival is on hand (API)', journal.stock_after_arrival.some((r) => /12\s*kg/.test(String(r.on_hand))), JSON.stringify(journal.stock_after_arrival).slice(0, 300))
    s.done()
  }
  // ------------------------------- 6–7 (booking). services, hours, providers
  if (BK && runs('services')) await BK.services()
  if (BK && runs('hours')) await BK.hours()
  if (BK && runs('providers')) await BK.providers()
  if (ST && runs('rooms')) await ST.rooms()
  if (ST && runs('roomlist')) await ST.roomlist()

  // ----------------------------------------------------------- 8. publish
  if (runs('publish')) {
    const s = step('publish: preview, then put the website online')
    await page.goto(`${WS}/b/${B}/website/publish`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(page, 'publish-page')
    s.note((await page.innerText('main')).replace(/\s+/g, ' ').slice(0, 300))
    await page.getByRole('button', { name: /^publish( latest draft)?$/i }).click()
    const t0 = Date.now()
    let site = {}
    while (Date.now() - t0 < 120000) {
      await sleep(2500)
      site = (await api('GET', `/v1/b/${B}/website`)).data || {}
      if (site.website?.status === 'published' || site.status === 'published' || site.published_version_id || site.website?.published_version_id) break
    }
    await page.waitForLoadState('networkidle').catch(() => {})
    await s.shot(page, 'published')
    const biz = (await api('GET', `/v1/b/${B}`)).data || {}
    journal.slug = biz.slug
    journal.public_url = `${WEB}/${biz.slug}`
    s.note(`page now says: ${(await page.innerText('main')).replace(/\s+/g, ' ').slice(0, 300)}`)
    const before = (await (await fetch(`${API}/v1/public/websites/${biz.slug}`)).json())?.data?.capabilities || {}
    s.note(`after Publish alone, the live site can: order=${before.order} book=${before.book} catalogue=${before.catalogue}`)
    journal.capabilities_after_publish_only = before
    // "To go live for customers: 1. Website → Preview & publish 2. Marketplace →
    // Confirm & become discoverable" (the hand-off page).
    await page.goto(`${WS}/b/${B}/marketplace`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(page, 'marketplace-before')
    await page.getByRole('button', { name: /confirm & become discoverable/i }).click()
    await page.waitForLoadState('networkidle').catch(() => {})
    await sleep(2500)
    await page.reload({ waitUntil: 'networkidle' })
    await s.shot(page, 'marketplace-after')
    s.note(`marketplace now: ${(await page.innerText('main')).replace(/\s+/g, ' ').slice(0, 400)}`)
    const after = (await (await fetch(`${API}/v1/public/websites/${biz.slug}`)).json())?.data?.capabilities || {}
    journal.capabilities_live = after
    if (MODEL !== 'order') s.check('once live, the website takes bookings (public capabilities)', after.book === true, JSON.stringify(after).slice(0, 200))
    else s.check('once live, the website takes orders (public capabilities)', after.order === true, JSON.stringify(after).slice(0, 200))
    const res = await fetch(journal.public_url)
    s.check('the public website answers', res.status === 200, `${journal.public_url} → ${res.status}`)
    const html = await res.text()
    s.check('the live site carries the business name', html.includes(persona.business_name), persona.business_name)
    s.done()
  }

  // --------------------- 9–13 (booking). the guest's appointment and after
  if (BK && runs('book')) await BK.book()
  if (BK && runs('conflicts')) await BK.conflicts()
  if (BK && runs('appointment')) await BK.appointment()
  if (BK && runs('guest-cancel')) await BK.guestCancel()
  if (BK && runs('team')) await BK.team()
  if (BK && runs('lifecycle')) await BK.lifecycle()
  if (BK && runs('return')) await BK.ret(owner)
  if (ST && runs('stay')) await ST.stay()
  if (ST && runs('overlap')) await ST.overlap()
  if (ST && runs('arrival')) await ST.arrival()
  if (ST && runs('guest-cancel')) await ST.guestCancel()
  if (ST && runs('return')) await ST.ret(owner)

  // ---------------------------------------------------------- 9. customer
  if (MODEL === 'order' && runs('customer')) {
    const s = step('customer: a guest in another browser orders, pays at pickup')
    const guest = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const g = await guest.newPage()
    g.on('pageerror', (e) => pageErrors.push(`guest: ${String(e).slice(0, 300)}`))
    await g.goto(journal.public_url, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(g, 'public-home', true)
    // The range: on the home page, or the page the navigation names for it.
    // "+ Add" for a counted item; "Choose" for one sold by weight (a pack sheet).
    const addButtons = () => g.getByRole('button', { name: /^(\+\s*)?(add|choose)\b/i })
    if (!(await addButtons().count())) {
      const hrefs = await g.locator('header a, nav a').evaluateAll((as) => as.map((a) => a.getAttribute('href') || '').filter((h) => /\/(menu|shop|products|store|range|order)\b/.test(h)))
      for (const h of [...new Set(hrefs)]) {
        await g.goto(new URL(h, journal.public_url).href, { waitUntil: 'networkidle' })
        if (await addButtons().count()) break
      }
    }
    const found = await addButtons().count()
    s.check('the live items can be added', found > 0, `${found} Add buttons at ${g.url()}`)
    await s.shot(g, 'range', true)
    journal.guest_range_url = g.url()
    for (let i = 0; i < Math.min(2, found); i++) {
      const b = addButtons().nth(i)
      await b.scrollIntoViewIfNeeded()
      await b.click()
      await sleep(800)
      // A weighed item opens its pack sheet: take 500 g, add to cart.
      const sheet = g.locator('dialog.ls-sheet[open]')
      if (await sheet.count()) {
        const packs = await sheet.getByRole('radio').allInnerTexts()
        const half = sheet.getByRole('radio', { name: /^500 g/ })
        if (await half.count()) await half.click()
        s.note(`pack sheet: ${packs.map((x) => x.replace(/\s+/g, ' ')).join(' | ')} → 500 g`)
        if (i === 0) await s.shot(g, 'pack-sheet')
        await sheet.getByRole('button', { name: /add to cart/i }).click()
        await sleep(900)
      }
    }
    await s.shot(g, 'added')
    s.check('the basket bar appears', (await g.locator('.ls-basket-bar').count()) > 0)
    const slugPath = new URL(journal.public_url).pathname.replace(/\/$/, '')
    await g.goto(`${WEB}${slugPath}/checkout`, { waitUntil: 'networkidle' })
    await g.locator('form.ls-checkout__form').waitFor({ timeout: 30000 })
    const lines = await g.locator('.ls-checkout__form [aria-labelledby="basket-h"] li, .ls-checkout__line').count()
    s.check('the basket holds the items', lines > 0, `${lines} lines`)
    // Failure first: no name, no phone — the order must not go through.
    const placeBtn = g.locator('.ls-checkout__place')
    const ordersBefore = ((await api('GET', `/v1/platform/businesses/${B}/orders`)).data || []).length
    if (await placeBtn.isEnabled()) {
      await placeBtn.click()
      await sleep(2500)
      const said = (await g.locator('[role=alert]:visible, .ls-offer__error:visible').first().innerText().catch(() => '')) || (await g.locator('input:invalid').first().evaluate((e) => (e.labels?.[0]?.innerText || e.name) + ': ' + e.validationMessage).catch(() => '')) || ''
      const ordersAfter = ((await api('GET', `/v1/platform/businesses/${B}/orders`)).data || []).length
      s.check('with no name or phone, Place order does not place an order', ordersAfter === ordersBefore, `${ordersBefore} → ${ordersAfter}`)
      s.check('and says what is missing', Boolean(said.trim()), said.slice(0, 160))
      await s.shot(g, 'checkout-empty-refused', true)
    } else {
      s.note('with no details, Place order is disabled')
    }
    const modes = g.locator('[role=radiogroup]').first().locator('[role=radio]')
    const modeTexts = await modes.allInnerTexts().catch(() => [])
    const pickup = modeTexts.findIndex((m) => /pick|collect/i.test(m))
    if (pickup >= 0) await modes.nth(pickup).click()
    s.check('pickup is offered and chosen', pickup >= 0, modeTexts.join(' / '))
    await sleep(500)
    const payGroup = g.locator('[role=radiogroup]').filter({ has: g.locator('[role=radio]', { hasText: /pickup|collect|cash|deliver/i }) }).last()
    const payTexts = await payGroup.locator('[role=radio]').allInnerTexts().catch(() => [])
    const own = payTexts.findIndex((p) => /pickup|collect|cash/i.test(p))
    if (own >= 0) await payGroup.locator('[role=radio]').nth(own).click()
    s.check('paying at pickup is offered and chosen (no gateway on this business)', own >= 0, payTexts.join(' / '))
    await g.locator('input[name=name]').fill('Priya Raman')
    await g.locator('input[name=email]').fill('priya.lab@locah.test').catch(() => {})
    await g.locator('input[name=phone]').fill('+919840011223')
    await s.shot(g, 'checkout', true)
    await placeBtn.click()
    await g.getByText('Order confirmed').waitFor({ timeout: 45000 }).catch(() => {})
    const body = (await g.innerText('body')).replace(/\s+/g, ' ')
    const number = (body.match(/Order\s+([A-Z0-9-]{3,})/i) || [])[1] || ''
    journal.order_number = number
    s.check('the page says Order confirmed', /Order confirmed/i.test(body), body.slice(0, 200))
    s.check('with an order number', Boolean(number), number)
    s.check('and how to pay', /Pay when|pay at|pickup/i.test(body))
    const track = g.getByRole('link', { name: /track/i }).first()
    journal.track_url = (await track.count()) ? new URL(await track.getAttribute('href'), g.url()).href : ''
    await s.shot(g, 'confirmed', true)
    // The order is real: in the owner's list, with the customer and the lines.
    const orders = (await api('GET', `/v1/platform/businesses/${B}/orders`)).data || []
    const mine = (Array.isArray(orders) ? orders : orders.items || []).find((o) => String(o.order_number || o.number || '').includes(number) || JSON.stringify(o).includes(number))
    journal.order_id = mine?.id || ''
    s.check('the order is in the business’s orders (API)', Boolean(mine), mine ? `${mine.status} ${mine.total_amount || mine.total || ''}` : JSON.stringify(orders).slice(0, 200))
    await guest.close()
    s.done()
  }
  // ------------------------------------------------------- 10. the order
  if (MODEL === 'order' && runs('fulfil')) {
    const s = step('owner: hear about the order, accept it, get it ready, hand it over, take the cash')
    const stockBefore = ((await api('GET', `/v1/platform/businesses/${B}/stock`)).data?.items || []).map((r) => `${r.title} ${r.on_hand_text}`)
    await page.goto(`${WS}/b/${B}/notifications`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(page, 'notifications', true)
    const noteText = (await page.innerText('main')).replace(/\s+/g, ' ')
    s.check('a notification tells the owner about the new order', /new order/i.test(noteText), noteText.slice(0, 300))
    s.check('the notification names which order (number, customer or amount)', new RegExp(`${journal.order_number}|Priya|₹\s?320`, 'i').test(noteText), noteText.slice(0, 200))
    const item = page.locator('article').filter({ hasText: /new order placed/i }).filter({ hasText: new RegExp(journal.order_number || '.', 'i') }).first()
    const open = item.getByRole('link', { name: /^open$/i })
    if (await open.count()) {
      await open.first().click()
      await page.waitForURL(/\/orders\//, { timeout: 20000 }).catch(() => {})
      await page.waitForLoadState('networkidle').catch(() => {})
    }
    s.check('the notification’s Open goes to the order', page.url().includes(journal.order_id), page.url())
    if (!page.url().includes(journal.order_id)) await page.goto(`${WS}/b/${B}/orders/${journal.order_id}`, { waitUntil: 'networkidle' })
    await page.waitForLoadState('networkidle').catch(() => {})
    await s.shot(page, 'order-new', true)
    const track = journal.track_url ? await browser.newContext().then((c) => c.newPage()) : null
    const ACTIONS = /^(accept|start preparing|start|mark (as )?ready|ready for pickup|ready|mark (as )?collected|collected|hand(ed)? over|complete|mark (as )?complete|picked up)$/i
    const seen = []
    for (let i = 0; i < 7; i++) {
      const order = (await api('GET', `/v1/platform/businesses/${B}/orders/${journal.order_id}`)).data || {}
      seen.push(order.status)
      if (['completed', 'fulfilled', 'collected', 'delivered'].includes(order.status)) break
      const next = page.getByRole('button', { name: ACTIONS })
      if (!(await next.count())) { s.note(`no next action at status ${order.status}: ${(await page.getByRole('button').allInnerTexts()).join(' | ').slice(0, 300)}`); break }
      const label = (await next.first().innerText()).trim()
      await next.first().click()
      // A confirm step, when the action asks for one.
      const yes = page.getByRole('dialog').getByRole('button', { name: /^(yes|confirm|accept|ok|mark)/i })
      if (await yes.count()) await yes.first().click()
      await sleep(2500)
      await page.reload({ waitUntil: 'networkidle' })
      const after = (await api('GET', `/v1/platform/businesses/${B}/orders/${journal.order_id}`)).data || {}
      s.note(`"${label}" → ${after.status}`)
      await s.shot(page, `order-${String(after.status || i)}`)
      if (track) {
        await track.goto(journal.track_url, { waitUntil: 'networkidle' })
        const shown = (await track.innerText('body')).replace(/\s+/g, ' ')
        s.note(`  customer's tracking page: ${shown.slice(shown.search(/order/i), shown.search(/order/i) + 160)}`)
      }
    }
    journal.order_statuses = seen
    // The cash at pickup.
    const money = page.getByRole('button', { name: /record money received/i })
    if (await money.count()) {
      await money.click()
      await sleep(800)
      await s.shot(page, 'record-money')
      const amount = page.getByLabel(/amount/i)
      if (await amount.count() && !(await amount.first().inputValue())) await amount.first().fill('320')
      const save = page.getByRole('button', { name: /^(record|save|record payment|received)/i }).last()
      if (await save.count()) await save.click()
      await sleep(2500)
      await page.reload({ waitUntil: 'networkidle' })
    }
    const final = (await api('GET', `/v1/platform/businesses/${B}/orders/${journal.order_id}`)).data || {}
    journal.order_final = { status: final.status, payment_status: final.payment_status, paid: final.amount_paid ?? final.paid_amount }
    s.note(`final: ${JSON.stringify(journal.order_final)}`)
    await s.shot(page, 'order-final', true)
    s.check('the order reached its end state', ['completed', 'fulfilled', 'collected', 'delivered'].includes(final.status), `${seen.join(' → ')} → ${final.status}`)
    s.check('the cash is recorded as paid', /paid/i.test(String(final.payment_status)) && !/not|un/i.test(String(final.payment_status)), String(final.payment_status))
    const stockAfter = ((await api('GET', `/v1/platform/businesses/${B}/stock`)).data?.items || []).map((r) => `${r.title} ${r.on_hand_text}`)
    s.note(`stock before: ${stockBefore.join('; ')} | after: ${stockAfter.join('; ')}`)
    s.check('the curry cut sold came off the stock', stockBefore.join() !== stockAfter.join(), '')
    if (track) {
      await track.goto(journal.track_url, { waitUntil: 'networkidle' })
      await track.screenshot({ path: path.join(OUT, `shots/${String(++shotNo).padStart(2, '0')}-customer-tracking-final.png`), fullPage: true })
      const shown = (await track.innerText('body')).replace(/\s+/g, ' ')
      s.check('the customer sees the order as done', /collected|completed|picked up|handed|delivered|done/i.test(shown), shown.slice(0, 240))
      await track.context().close()
    }
    s.done()
  }
  // ------------------------------------------------------------- 11. team
  if (MODEL === 'order' && runs('team')) {
    const s = step('team: add a manager and a store keeper; each sees their work, and nothing they may not touch')
    const PEOPLE = [
      { role: 'manager', name: 'Murugan (lab manager)' },
      { role: 'store_keeper', name: 'Selvi (lab store keeper)' },
    ]
    journal.team = journal.team || {}
    for (const person of PEOPLE) {
      const who = newOwner(person.role.replace('_', ''), `lab-${person.role.replace('_', '')}-${Date.now().toString(36)}@locah.test`)
      journal.team[person.role] = { id: who.id, email: who.email }
      await page.goto(`${WS}/b/${B}/team/add`, { waitUntil: 'networkidle', timeout: 120000 })
      await page.locator('label', { hasText: /^\s*Name/ }).locator('input').first().fill(person.name)
      await page.locator('input[type=email]').first().fill(who.email)
      await page.locator(`input[name=role-new][value=${person.role}]`).check()
      const loc = page.locator('label', { hasText: /Primary Location/ }).locator('input[type=checkbox]')
      if ((await loc.count()) && !(await loc.isChecked())) await page.locator('label', { hasText: /Primary Location/ }).click()
      await page.getByRole('button', { name: 'Add and make a join link' }).click()
      const link = page.getByLabel('Join link')
      await link.waitFor({ timeout: 30000 })
      const url = await link.inputValue()
      s.note(`${person.role}: join link made (${url.replace(/token\/.*$|\/join\/.*/, '/join/…')})`)
      await s.shot(page, `team-${person.role}-link`)
      // Their own browser, signed in as them.
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
      await ctx.addCookies(sessionCookies(who))
      const p2 = await ctx.newPage()
      await p2.goto(url, { waitUntil: 'networkidle', timeout: 120000 })
      await s.shot(p2, `team-${person.role}-join`)
      const join = p2.getByRole('button', { name: /^join /i })
      s.check(`${person.role}: the join page offers to join this business`, (await join.count()) > 0, (await p2.innerText('body')).replace(/\s+/g, ' ').slice(0, 200))
      if (await join.count()) {
        await join.first().click()
        await p2.waitForURL(new RegExp(`/b/${B}`), { timeout: 60000 }).catch(() => {})
      }
      s.check(`${person.role}: joined and landed in the Workspace`, p2.url().includes(`/b/${B}`), p2.url())
      await p2.waitForLoadState('networkidle').catch(() => {})
      await s.shot(p2, `team-${person.role}-home`, true)
      journal.team[person.role].home = (await p2.innerText('main').catch(() => '')).replace(/\s+/g, ' ').slice(0, 600)
      const as = (m, pth, body) => api(m, pth, body, who.token)
      if (person.role === 'manager') {
        await p2.goto(`${WS}/b/${B}/orders`, { waitUntil: 'networkidle' })
        const ordersText = (await p2.innerText('main')).replace(/\s+/g, ' ')
        s.check('manager: sees the orders', new RegExp(journal.order_number || 'ORD-', 'i').test(ordersText), ordersText.slice(0, 160))
        await s.shot(p2, 'team-manager-orders', true)
        await p2.goto(`${WS}/b/${B}/modules/payments`, { waitUntil: 'networkidle' })
        s.check('manager: no "Turn on" for a tool (owner-only)', (await p2.getByRole('button', { name: /^turn on/i }).count()) === 0)
        const en = await as('POST', `/v1/b/${B}/modules/payments/enable`)
        s.check('manager: turning on a tool through the API is refused', en.status === 403, `status ${en.status}`)
        const pub = await as('POST', `/v1/b/${B}/website/publish`)
        s.check('manager: publishing the website through the API is refused', pub.status === 403, `status ${pub.status}`)
        const inv = await as('POST', `/v1/platform/businesses/${B}/team/people`, { name: 'X', email: 'x-lab@locah.test', role: 'manager', location_ids: [] })
        s.check('manager: adding people through the API is refused', inv.status === 403, `status ${inv.status}`)
      } else {
        await p2.goto(`${WS}/b/${B}/inventory`, { waitUntil: 'networkidle' })
        const stockText = (await p2.innerText('main')).replace(/\s+/g, ' ')
        s.check('store keeper: sees the stock', /kg/i.test(stockText), stockText.slice(0, 160))
        await p2.goto(`${WS}/b/${B}/orders`, { waitUntil: 'networkidle' })
        const ordersText = (await p2.innerText('main').catch(() => '')).replace(/\s+/g, ' ')
        await s.shot(p2, 'team-storekeeper-orders', true)
        s.check('store keeper: the orders page shows no orders', !new RegExp(journal.order_number || 'ORD-', 'i').test(ordersText), ordersText.slice(0, 200))
        const list = await as('GET', `/v1/platform/businesses/${B}/orders`)
        s.check('store keeper: reading orders through the API is refused', list.status === 403, `status ${list.status}`)
        const one = await as('GET', `/v1/platform/businesses/${B}/orders/${journal.order_id}`)
        s.check('store keeper: one order by its id is refused too', one.status === 403 || one.status === 404, `status ${one.status}`)
      }
      await ctx.close()
    }
    // Another business's owner cannot reach this one at all.
    const stranger = newOwner('stranger')
    const theirs = await api('GET', `/v1/platform/businesses/${B}/orders`, null, stranger.token)
    s.check('another owner cannot read this business (tenant isolation, API)', theirs.status === 403 || theirs.status === 404, `status ${theirs.status}`)
    s.done()
  }
  // -------------------------------------------------------- 12. lifecycle
  if (MODEL === 'order' && runs('lifecycle')) {
    const s = step('lifecycle: turn Orders off and on again — the website stops selling, the records stay')
    const capabilities = async () => (await (await fetch(`${API}/v1/public/websites/${journal.slug}`)).json())?.data?.capabilities || {}
    // From a known state: Orders on (an interrupted earlier run may have left it off).
    if (!((await api('GET', `/v1/b/${B}/modules`)).data || []).some((m) => m.module_id === 'orders' && m.activation_state === 'active')) {
      await page.goto(`${WS}/b/${B}/modules/orders`, { waitUntil: 'networkidle', timeout: 120000 })
      await page.getByRole('button', { name: /^turn on/i }).first().click()
      await page.waitForLoadState('networkidle').catch(() => {})
      await sleep(2500)
      s.note('Orders was off at the start; turned it on first')
    }
    const ordersBefore = ((await api('GET', `/v1/platform/businesses/${B}/orders`)).data || []).length
    await page.goto(`${WS}/b/${B}/modules/orders`, { waitUntil: 'networkidle', timeout: 120000 })
    const off = page.getByRole('button', { name: /^turn off/i })
    s.check('the Orders page offers Turn off', (await off.count()) > 0)
    await off.first().click()
    const confirm = page.getByRole('dialog').getByRole('button', { name: /^(yes|turn off|confirm)/i })
    if (await confirm.count()) await confirm.last().click()
    await page.waitForLoadState('networkidle').catch(() => {})
    await sleep(2500)
    await page.reload({ waitUntil: 'networkidle' })
    await s.shot(page, 'orders-turned-off', true)
    let mods = (await api('GET', `/v1/b/${B}/modules`)).data || []
    s.check('Orders is off (API)', !mods.some((m) => m.module_id === 'orders' && m.activation_state === 'active'))
    let caps = await capabilities()
    s.check('the live website no longer takes orders', caps.order === false, JSON.stringify(caps).slice(0, 120))
    const guest = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
    await guest.goto(`${journal.public_url}/shop`, { waitUntil: 'networkidle' })
    const buyButtons = await guest.getByRole('button', { name: /^(\+\s*)?(add|choose)\b/i }).count()
    s.check('no cart button is left on the shop page (no stale CTA)', buyButtons === 0, `${buyButtons} buttons`)
    await guest.screenshot({ path: path.join(OUT, `shots/${String(++shotNo).padStart(2, '0')}-shop-with-orders-off.png`), fullPage: false })
    s.note(`with Orders off the shop page says: ${(await guest.innerText('main')).replace(/\s+/g, ' ').slice(0, 220)}`)
    await page.goto(`${WS}/b/${B}/orders`, { waitUntil: 'networkidle' })
    s.note(`owner's Orders page while off: ${(await page.innerText('main')).replace(/\s+/g, ' ').slice(0, 220)}`)
    await s.shot(page, 'orders-page-while-off', true)
    // And on again.
    await page.goto(`${WS}/b/${B}/modules/orders`, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: /^turn on/i }).first().click()
    await page.waitForLoadState('networkidle').catch(() => {})
    await sleep(2500)
    mods = (await api('GET', `/v1/b/${B}/modules`)).data || []
    s.check('Orders is on again (API)', mods.some((m) => m.module_id === 'orders' && m.activation_state === 'active'))
    const ordersAfter = ((await api('GET', `/v1/platform/businesses/${B}/orders`)).data || []).length
    s.check('every past order is still there', ordersAfter === ordersBefore, `${ordersBefore} → ${ordersAfter}`)
    caps = await capabilities()
    s.check('the website takes orders again', caps.order === true, JSON.stringify(caps).slice(0, 120))
    await guest.context().close()
    s.done()
  }

  // ----------------------------------------------------------- 13. return
  if (MODEL === 'order' && runs('return')) {
    const s = step('return: a new session another day — find the orders, the customer and what changed')
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    await ctx.addCookies(sessionCookies({ ...owner, token: mintToken(owner) }))
    const p3 = await ctx.newPage()
    await p3.goto(`${WS}/b/${B}`, { waitUntil: 'networkidle', timeout: 120000 })
    await s.shot(p3, 'return-home', true)
    const home = (await p3.innerText('main')).replace(/\s+/g, ' ')
    journal.return_home = home.slice(0, 800)
    s.check('the home now shows real activity, not zeros', /₹\s?[1-9]/.test(home), home.slice(0, 200))
    await p3.goto(`${WS}/b/${B}/orders`, { waitUntil: 'networkidle' })
    const tabs = p3.getByRole('link', { name: /^completed/i }).or(p3.getByRole('tab', { name: /^completed/i }))
    if (await tabs.count()) { await tabs.first().click(); await p3.waitForLoadState('networkidle').catch(() => {}) }
    const done = (await p3.innerText('main')).replace(/\s+/g, ' ')
    s.check('the completed orders are found under Completed', new RegExp(journal.order_number, 'i').test(done), done.slice(0, 200))
    await s.shot(p3, 'return-orders-completed', true)
    const customers = await api('GET', `/v1/platform/businesses/${B}/customers`)
    const priya = (customers.data || []).find?.((c) => /priya/i.test(c.display_name || c.name || ''))
    if (priya) {
      await p3.goto(`${WS}/b/${B}/customers/${priya.id}`, { waitUntil: 'networkidle' })
      const hist = (await p3.innerText('main')).replace(/\s+/g, ' ')
      s.check('the customer’s page shows her orders', /ORD-/i.test(hist), hist.slice(0, 200))
      await s.shot(p3, 'return-customer', true)
    } else {
      s.check('the customer who ordered is in Customers (API)', false, JSON.stringify(customers.data).slice(0, 200))
    }
    await ctx.close()
    s.done()
  }
} catch (err) {
  const s = step('error')
  s.note(String(err?.stack || err).slice(0, 1200))
  await s.shot(page, 'error')
  s.done('error')
  process.exitCode = 1
} finally {
  journal.page_errors = pageErrors.slice(0, 40)
  journal.ended_at = new Date().toISOString()
  save()
  await browser.close()
}

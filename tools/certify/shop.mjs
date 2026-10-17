#!/usr/bin/env node
// Website Builder Certification — a customer orders on the published site,
// in a real browser, up to payment.
//
//   node tools/certify/shop.mjs <out_site_dir> <base_url> [--mobile]
//
// <base_url> is the tenant home (http://localhost:3200/<slug>). The customer
// finds the range (home, or the page the navigation names), taps "+ Add" on
// two things, opens the basket from the bar that appears, chooses pickup (or
// delivery with an address when that is all there is), chooses the
// business's own way of being paid (pay at pickup / cash on delivery — no
// gateway is connected on a local stack), fills in their details and places
// the order. Passes when the page says "Order confirmed" with an order number
// and how to pay. Screens of every step go to <out_site_dir>/shop/, the steps
// to <out_site_dir>/shop.json. Exit 0 on a confirmed order, 1 otherwise.

import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { launch } from '../acceptance/cdp.mjs'

const args = process.argv.slice(2)
const mobile = args.includes('--mobile')
const [outDir, base] = args.filter((a) => !a.startsWith('--'))
if (!outDir || !base) {
  console.error('usage: node tools/certify/shop.mjs <out_site_dir> <base_url> [--mobile]')
  process.exit(2)
}
const OUT = path.resolve(outDir)
const SHOTS = path.join(OUT, mobile ? 'shop-mobile' : 'shop')
mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const steps = []
let n = 0

function step(name, ok, detail = '') {
  steps.push({ step: name, ok: Boolean(ok), detail: String(detail).slice(0, 300) })
  console.log(`${ok ? 'ok ' : 'NO '} ${name}${ok ? '' : `  — ${String(detail).slice(0, 200)}`}`)
  return Boolean(ok)
}

const page = mobile ? await launch({ width: 390, height: 844, mobile: true }) : await launch({ width: 1440, height: 900 })
const shot = async (label) => page.shot(path.join(SHOTS, `${String(++n).padStart(2, '0')}-${label}.png`))
const addButtons = () =>
  page.eval(`[...document.querySelectorAll('button.ls-order')].filter((b) => b.offsetParent !== null && /add/i.test(b.innerText)).length`)

let confirmed = false
try {
  await page.goto(base)
  await sleep(1200)
  // The range: on the home page, or on the page the navigation names for it.
  let found = await addButtons()
  if (!found) {
    const links = await page.eval(`[...document.querySelectorAll('header a, nav a')].map((a) => a.getAttribute('href') || '')
      .filter((h) => /\\/(menu|shop|products|store|range|order)\\b/.test(h))`)
    for (const href of [...new Set(links)]) {
      await page.goto(new URL(href, base).href)
      await sleep(1200)
      found = await addButtons()
      if (found) break
    }
  }
  if (step('an Add button on the range', found > 0, `${found} found`)) {
    await shot('range')
    for (let i = 0; i < Math.min(2, found); i++) {
      await page.eval(`(() => { const b = [...document.querySelectorAll('button.ls-order')].filter((x) => x.offsetParent !== null && /add/i.test(x.innerText))[${i}]; b.scrollIntoView({ block: 'center' }); b.click(); return true })()`)
      await sleep(700)
    }
    const bar = await page.eval(`!!document.querySelector('.ls-basket-bar')`)
    step('the basket bar says it was added', bar)
    await shot('added')
    await page.goto(new URL(`${new URL(base).pathname.replace(/\/$/, '')}/checkout`, base).href)
    await page.waitFor('form.ls-checkout__form', { timeout: 20000 })
    const lines = await page.eval(`document.querySelectorAll('.ls-checkout__form [aria-labelledby="basket-h"] li, .ls-checkout__line').length`)
    step('the basket holds the items', lines > 0, `${lines} lines`)
    // How it is handed over: pickup when it is offered.
    const modes = await page.eval(`[...document.querySelectorAll('[role=radiogroup]')][0] ? [...[...document.querySelectorAll('[role=radiogroup]')][0].querySelectorAll('[role=radio]')].map((b) => b.innerText.trim()) : []`)
    const pickup = modes.find((m) => /pick|collect/i.test(m))
    if (pickup) await page.click(pickup, { byText: true })
    else if (modes.length) {
      await page.click(modes[0], { byText: true })
      await sleep(400)
      await page.type('input[name=line1]', '12, 4th Cross Street, Besant Nagar').catch(() => undefined)
      await page.type('input[name=city]', 'Chennai').catch(() => undefined)
      await page.type('input[name=postal_code]', '600090').catch(() => undefined)
    }
    step('pickup or delivery chosen', modes.length > 0, modes.join(' / '))
    await sleep(600)
    // The business's own way of being paid: never a gateway here.
    const pays = await page.eval(`(() => { const g = [...document.querySelectorAll('[role=radiogroup]')].find((x) => /pay/i.test(x.getAttribute('aria-label') || '')); return g ? [...g.querySelectorAll('[role=radio]')].map((b) => b.innerText.trim()) : [] })()`)
    const own = pays.find((p) => /pickup|collect|delivered|delivery|cash/i.test(p))
    if (own) await page.click(own, { byText: true })
    step('paying at pickup / on delivery chosen', Boolean(own), pays.join(' / '))
    await page.type('input[name=name]', 'Priya Raman')
    await page.type('input[name=email]', 'priya.certify@locah.test').catch(() => undefined)
    await page.type('input[name=phone]', '+919840011223')
    await sleep(800)
    await shot('checkout')
    const ready = await page.eval(`!document.querySelector('.ls-checkout__place')?.disabled`)
    step('Place order is ready', ready)
    await page.click('.ls-checkout__place')
    await page.waitFor('Order confirmed', { text: true, timeout: 30000 }).catch(() => undefined)
    const body = await page.eval('document.body.innerText')
    confirmed = /Order confirmed/.test(body)
    step('the page says Order confirmed', confirmed, body.slice(0, 200))
    step('with an order number', /Order\s+[A-Z0-9-]{3,}/.test(body), (body.match(/Order\s+[A-Z0-9-]{3,}/) || [''])[0])
    step('and how to pay', /Pay when|Payment received|advance|Finish the payment/i.test(body))
    step('and a way to track it', await page.eval(`[...document.querySelectorAll('a')].some((a) => /track/i.test(a.innerText))`))
    await shot('confirmed')
  }
} catch (err) {
  step('ran to the end', false, err && err.message)
  await shot('error').catch(() => undefined)
} finally {
  writeFileSync(path.join(OUT, mobile ? 'shop-mobile.json' : 'shop.json'),
    JSON.stringify({ base, mobile, ok: confirmed && steps.every((s) => s.ok), steps }, null, 1))
  await page.close()
}
process.exit(confirmed ? 0 : 1)

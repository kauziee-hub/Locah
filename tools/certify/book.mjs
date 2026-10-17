#!/usr/bin/env node
// Website Builder Certification — a customer books on the published site, in a
// real browser, up to its confirmation.
//
//   node tools/certify/book.mjs <out_site_dir> <base_url> [--mobile]
//
// Opens <base_url>/book, picks the first thing to book (a service, a class, a
// table, a room), a working day two days ahead, an open time (or dates for a
// stay), fills in their details and books. Passes when the page says it is
// confirmed (or the request was sent, for a business that confirms by hand).
// Screens to <out_site_dir>/book[-mobile]/, steps to book[-mobile].json.
// Exit 0 when booked, 1 otherwise.

import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { launch } from '../acceptance/cdp.mjs'

const args = process.argv.slice(2)
const mobile = args.includes('--mobile')
const [outDir, base] = args.filter((a) => !a.startsWith('--'))
if (!outDir || !base) {
  console.error('usage: node tools/certify/book.mjs <out_site_dir> <base_url> [--mobile]')
  process.exit(2)
}
const OUT = path.resolve(outDir)
const SHOTS = path.join(OUT, mobile ? 'book-mobile' : 'book')
mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const steps = []
let n = 0
function step(name, ok, detail = '') {
  steps.push({ step: name, ok: Boolean(ok), detail: String(detail).slice(0, 300) })
  console.log(`${ok ? 'ok ' : 'NO '} ${name}${ok ? '' : `  — ${String(detail).slice(0, 200)}`}`)
  return Boolean(ok)
}
function workday(ahead = 2) {
  const d = new Date(Date.now() + ahead * 864e5)
  while (d.getDay() === 0) d.setDate(d.getDate() + 1)
  return d.toISOString().slice(0, 10)
}
/** Set a React-controlled input by selector, the way a person types into it. */
const setValue = (page, selector, value) => page.eval(`(() => {
  const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(value)});
  el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)
const byLabel = (page, label, value) => page.eval(`(() => {
  const l = [...document.querySelectorAll('label')].find((x) => x.innerText.trim().toLowerCase().startsWith(${JSON.stringify(label.toLowerCase())}));
  const el = l && l.querySelector('input'); if (!el) return false;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(value)});
  el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)

const page = mobile ? await launch({ width: 390, height: 844, mobile: true }) : await launch({ width: 1440, height: 900 })
const shot = async (label) => page.shot(path.join(SHOTS, `${String(++n).padStart(2, '0')}-${label}.png`))
let booked = false
try {
  await page.goto(`${base.replace(/\/$/, '')}/book`)
  await sleep(1500)
  const title = await page.eval(`(document.querySelector('h1') || {}).innerText || ''`)
  if (!step('the booking page opens', /book/i.test(title), title)) throw new Error('no booking page')
  // What to book: the first choice offered (a service, a class, a table, a room).
  const choices = await page.eval(`[...document.querySelectorAll('button[aria-pressed]')].filter((b) => b.offsetParent !== null).map((b) => b.innerText.trim().slice(0, 40))`)
  if (choices.length) await page.eval(`[...document.querySelectorAll('button[aria-pressed]')].find((b) => b.offsetParent !== null).click()`)
  // A business with one thing to book (a restaurant's tables) shows it already chosen.
  const form = await page.eval(`!!document.querySelector('input[type=date]')`)
  step('something to book', choices.length > 0 || form, choices.join(' / ') || 'one choice, already chosen')
  await sleep(800)
  await shot('choose')
  const stay = await page.eval(`[...document.querySelectorAll('label')].some((l) => /check-in/i.test(l.innerText))`)
  if (stay) {
    await byLabel(page, 'Check-in', workday(3))
    await byLabel(page, 'Check-out', workday(4))
    await sleep(300)
    await page.click('Check availability', { byText: true })
    await sleep(2500)
    step('dates are open', !(await page.eval(`/not available|no room|fully booked/i.test(document.body.innerText)`)))
  } else {
    // A customer looks at the next days until one is open (a salon shut on
    // Mondays, a restaurant serving dinner only some nights).
    let slots = []
    let free = false
    const tried = []
    for (let ahead = 2; ahead < 10 && !slots.length && !free; ahead++) {
      const day = workday(ahead)
      if (tried.includes(day)) continue
      tried.push(day)
      await setValue(page, 'input[type=date]', day)
      await sleep(2500)
      // An open time: the slot buttons that appear for the day.
      slots = await page.eval(`[...document.querySelectorAll('button[aria-pressed]')].filter((b) => b.offsetParent !== null && !b.disabled && /\\d{1,2}[:.]\\d{2}|am|pm/i.test(b.innerText)).map((b) => b.innerText.trim())`)
      // Hours the business never gave: the customer asks for a time instead.
      free = !slots.length && await page.eval(`!!document.querySelector('input[type=time]')`)
    }
    if (free) {
      await setValue(page, 'input[type=time]', '11:00')
      await sleep(400)
    }
    step('hours known (slots, not a time to ask for)', !free, free ? 'the business gave no opening hours' : '')
    if (step('open times in the next week', slots.length > 0 || free, `${slots.length} on ${tried[tried.length - 1]} (tried ${tried.join(', ')})`) && slots.length) {
      const pick = slots[Math.floor(slots.length / 2)]
      await page.eval(`[...document.querySelectorAll('button[aria-pressed]')].find((b) => b.innerText.trim() === ${JSON.stringify(pick)}).click()`)
      await sleep(600)
    }
  }
  await byLabel(page, 'Name', 'Priya Raman')
  await byLabel(page, 'Email', 'priya.certify@locah.test')
  await byLabel(page, 'Phone', '+919840011223')
  await sleep(500)
  await shot('details')
  await page.eval(`document.querySelector('form button[type=submit]').click()`)
  for (let i = 0; i < 40 && !booked; i++) {
    await sleep(500)
    // innerText follows the theme's text-transform ("CONFIRMED").
    booked = await page.eval(`/Confirmed|Request sent|We have your request|You are on the waitlist/i.test(document.body.innerText)`)
  }
  const body = await page.eval('document.body.innerText')
  step('the page says it is booked', booked, body.slice(0, 240))
  await shot('booked')
} catch (err) {
  step('ran to the end', false, err && err.message)
  await shot('error').catch(() => undefined)
} finally {
  writeFileSync(path.join(OUT, mobile ? 'book-mobile.json' : 'book.json'),
    JSON.stringify({ base, mobile, ok: booked && steps.every((s) => s.ok), steps }, null, 1))
  await page.close()
}
process.exit(booked ? 0 : 1)

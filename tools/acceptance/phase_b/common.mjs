// Shared setup for Phase B browser flows against the LOCAL stack only.
import { readFileSync } from 'node:fs'
import { launch } from '../cdp.mjs'

export const API = process.env.LOCAH_API || 'http://localhost:8010'
export const WS = process.env.LOCAH_WORKSPACE || 'http://localhost:3101'
export const WEB = process.env.LOCAH_WEB || 'http://localhost:3100'
export const OUT = process.env.LOCAH_ACCEPT_OUT || 'acceptance-out'
export const session = JSON.parse(readFileSync(process.env.LOCAH_ACCEPT_SESSION || `${OUT}/session.json`, 'utf8'))

export async function api(path, { method = 'GET', body, token = session.token } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  let data
  try { data = JSON.parse(text) } catch { data = text }
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${text.slice(0, 300)}`)
  return data
}

export async function newBusiness({ name, category, sub, type = 'other', modules = [] }) {
  const r = await api('/v1/platform/businesses', {
    method: 'POST',
    body: { display_name: name, business_type: type, category_key: category, subcategory_key: sub },
  })
  const id = r.data.business.id
  for (const m of modules) await api(`/v1/b/${id}/modules/${m}/enable`, { method: 'POST' })
  return { id, slug: r.data.business.slug }
}

export async function browser({ mobile = false } = {}) {
  const page = mobile ? await launch({ width: 390, height: 844, mobile: true }) : await launch({ width: 1440, height: 900 })
  for (const origin of [WS, WEB]) await page.cookie(session.cookie_name, session.cookie, origin)
  return page
}

export function check(cond, msg, results) {
  results.push({ ok: !!cond, msg: String(msg).slice(0, 400) })
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}`)
  if (!cond) process.exitCode = 1
}

/** Click (by visible text) until `selector` appears — covers clicks that land
 *  before React has hydrated the page. */
export async function clickUntil(page, text, selector, tries = 8) {
  for (let i = 0; i < tries; i++) {
    await page.click(text, { byText: true }).catch(() => undefined)
    const shown = await page.eval(`!!document.querySelector(${JSON.stringify(selector)})`)
    if (shown) return
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`clicking "${text}" never showed ${selector}`)
}

/** Console errors, minus one known harness artifact: when a test navigates
 *  away while Next.js is still prefetching a link, the aborted fetch logs
 *  "Failed to fetch RSC payload … TypeError: Failed to fetch" (in dev, followed
 *  by its stack frames). Anything else
 *  — including a real RSC failure with a status code — still counts. */
export function realErrors(page) {
  return page.consoleErrors.filter((e) => !/Failed to fetch RSC payload .* TypeError: Failed to fetch(\n\s+at [^\n]+)*$/s.test(e))
}

/** The local auth stand-in's latest one-time code for an email (its mailbox). */
export async function mailCode(email, { tries = 20 } = {}) {
  const auth = process.env.LOCAH_AUTH || 'http://127.0.0.1:54321'
  for (let i = 0; i < tries; i++) {
    const r = await fetch(`${auth}/__mock/mail?email=${encodeURIComponent(email)}`)
    const last = (await r.json()).messages?.at(-1)
    if (last?.code) return last.code
    await new Promise((res) => setTimeout(res, 250))
  }
  throw new Error(`no code was emailed to ${email}`)
}

/** An invited person creates their login on the join page the way they really
 *  would: email, then the 6-digit code emailed to them (no password). */
export async function joinWithCode(page, email) {
  await page.waitFor('Create your login', { text: true })
  await page.type('.bos-join__form input[type=email]', email)
  await page.eval(`document.querySelector('.bos-join__form button[type=submit]').click()`)
  await page.waitFor('.bos-join__form input[autocomplete=one-time-code]')
  // A complete code checks itself — the same as typing or pasting it.
  await page.type('.bos-join__form input[autocomplete=one-time-code]', await mailCode(email))
}

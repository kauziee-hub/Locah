#!/usr/bin/env node
// Owner Simulation Lab — Workspace click/action audit (brief section 4).
//
//   node tools/certify/owner-lab/clickaudit.mjs [--journal meat-shop-normal-r3]
//        [--out certify-out/product-e2e/clickaudit] [--only <route substring>]
//        [--viewports desktop,phone] [--no-links] [--no-shots]
//   node tools/certify/owner-lab/clickaudit.mjs --links-only [--out ...] # re-GET the links of a finished audit.json
//   node tools/certify/owner-lab/clickaudit.mjs --summary [--out ...]   # markdown tables from audit.json
//
// Every route under apps/workspace/src/app/b/[businessId]/ is loaded as the
// journal's owner (a minted local session, session.mjs) at 1440x900 and at a
// 390x844 phone. Dynamic segments are resolved from links the Workspace itself
// renders (falling back to ids the journal or a read-only API GET knows).
// For each page: the document status, error boundary / not-found / gate text,
// console and page errors, failed requests; then every visible link, button,
// input and select — its accessible name as Chrome computes it (CDP
// accessibility tree), whether a button has anything wired to it (React props,
// a form to submit, a disclosure), disabled state and whether a reason is
// near it, nested interactive elements, clickable elements a keyboard cannot
// reach, tap targets under 44 px on the phone, and horizontal overflow. Every
// distinct link target is then GET-requested once (signed in, in a separate
// request context) and its status recorded.
//
// READ-ONLY: it never clicks a button except the phone navigation toggle (a
// disclosure) and presses Tab/Escape for the keyboard probe. It never submits
// a form. It never fetches third-party hosts (only localhost links are GET).
// As a hard guarantee every browser request that is not GET/HEAD/OPTIONS (a
// server action, an API write fired on mount) is aborted and recorded on the
// page as `blockedWrites` — except the auth stand-in's token refresh.
import { mkdirSync, readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, request as pwRequest } from 'playwright'
import { mintToken, sessionCookies } from './session.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const API = process.env.CERTIFY_API || 'http://localhost:8020'
const WS = process.env.CERTIFY_WORKSPACE || 'http://localhost:3201'

const argv = process.argv.slice(2)
const opt = (name, fallback) => {
  const i = argv.indexOf(`--${name}`)
  return i >= 0 ? argv[i + 1] : fallback
}
const flag = (name) => argv.includes(`--${name}`)
const OUT = path.resolve(ROOT, opt('out', 'certify-out/product-e2e/clickaudit'))
const AUDIT_JSON = path.join(OUT, 'audit.json')
mkdirSync(OUT, { recursive: true })

if (flag('summary')) {
  summary(JSON.parse(readFileSync(AUDIT_JSON, 'utf8')))
  process.exit(0)
}

const JOURNAL = opt('journal', 'meat-shop-normal-r3')
const journal = JSON.parse(readFileSync(path.join(ROOT, 'certify-out/product-e2e/SCENARIOS', JOURNAL, 'journal.json'), 'utf8'))
const B = journal.business_id
const owner = { ...journal.owner, token: mintToken(journal.owner) }
const ONLY = opt('only', '')
const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 } },
  phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1 },
}
const VPS = opt('viewports', 'desktop,phone').split(',').filter((v) => VIEWPORTS[v])
const NIL = '00000000-0000-4000-8000-000000000000'
const AUTH_PORT = process.env.CERTIFY_AUTH_PORT || '54331'

// Abort (and record) every write a page tries to make while it is audited.
async function guard(page, sink) {
  await page.route('**/*', (route) => {
    const req = route.request()
    const m = req.method()
    if (m === 'GET' || m === 'HEAD' || m === 'OPTIONS') return route.continue()
    let u
    try { u = new URL(req.url()) } catch { return route.abort('blockedbyclient') }
    if (u.port === AUTH_PORT && u.pathname.startsWith('/auth/')) return route.continue()
    const action = req.headers()['next-action']
    sink.push(`${m} ${u.host}${u.pathname.split(B).join('{B}')}${action ? ` (server action ${action.slice(0, 10)})` : ''}`)
    return route.abort('blockedbyclient')
  })
}

// Dev-mode pages compile on first hit; some poll, so "networkidle" is bounded.
async function load(page, url) {
  const resp = await page.goto(url, { waitUntil: 'load', timeout: 180000 })
  await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => {})
  return resp
}

// ------------------------------------------------------------------ routes
const APP_DIR = path.join(ROOT, 'apps/workspace/src/app/b/[businessId]')
const ROUTES = readdirSync(APP_DIR, { recursive: true })
  .map((f) => String(f).split(path.sep).join('/'))
  .filter((f) => f === 'page.tsx' || f.endsWith('/page.tsx'))
  .map((f) => (f === 'page.tsx' ? '' : f.slice(0, -'/page.tsx'.length)))
  .sort()
const STATIC = new Set(ROUTES.filter((r) => !r.includes('[')))
const DYNAMIC = ROUTES.filter((r) => r.includes('['))
const routeUrl = (concrete) => `${WS}/b/${B}${concrete ? `/${concrete}` : ''}`
const slugOf = (concrete) => (concrete || 'home').replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80)

// --------------------------------------------------------------- API reads
async function apiGet(p) {
  try {
    const res = await fetch(`${API}${p}`, { headers: { Authorization: `Bearer ${owner.token}` } })
    const body = await res.json().catch(() => null)
    return { status: res.status, data: body?.data ?? body }
  } catch (e) {
    return { status: 0, data: null, error: String(e) }
  }
}
const firstId = (data) => {
  const list = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : []
  return list[0]?.id || null
}

// ------------------------------------------------------- in-page inspection
// Runs in the page. Marks every interactive element with data-ca=<n> (so the
// CDP accessibility tree can be joined back) and returns what it can see.
function inspect() {
  const W = window.innerWidth
  const H = window.innerHeight
  const rk = (el) => Object.keys(el).find((k) => k.startsWith('__reactProps$'))
  const props = (el) => { const k = rk(el); return k ? el[k] : null }
  const HANDLERS = ['onClick', 'onMouseDown', 'onMouseUp', 'onPointerDown', 'onPointerUp', 'onTouchStart', 'onTouchEnd']
  const hasClick = (el) => { const p = props(el); return !!(p && HANDLERS.some((h) => typeof p[h] === 'function')) }
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim()
  const inClosedDetails = (el) => {
    const d = el.closest('details:not([open])')
    if (!d) return false
    const s = d.querySelector(':scope > summary')
    return !(s && s.contains(el))
  }
  const visible = (el) => {
    if (!el.getClientRects().length) return false
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true })) return false
    if (inClosedDetails(el)) return false
    return true
  }
  const CHROME = '[aria-label="Workspace navigation"], .ws-mobile-bar, .ws-mobile-scrim'
  const SEL = [
    'a[href]', 'a[role]', 'button', '[role=button]', '[role=link]', '[role=tab]', '[role=menuitem]', '[role=checkbox]',
    '[role=switch]', '[role=radio]', '[role=option]', '[role=combobox]', 'input:not([type=hidden])', 'select', 'textarea',
    'summary', '[contenteditable=""]', '[contenteditable=true]', '[tabindex]:not([tabindex="-1"])',
  ].join(',')
  const NATIVE = new Set(['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'SUMMARY', 'OPTION', 'LABEL'])
  const els = [...document.querySelectorAll(SEL)].filter(visible)
  const set = new Set(els)
  // Clickable things that are not interactive elements (a div with onClick).
  const clickables = []
  for (const el of document.body.querySelectorAll('*')) {
    if (set.has(el) || NATIVE.has(el.tagName) || el.closest('a[href],button,label,summary')) continue
    if (hasClick(el) && visible(el)) clickables.push(el)
  }
  const describe = (el) => clean((el.getAttribute('aria-describedby') || '').split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' '))
  const contextText = (el) => {
    const own = clean(el.innerText || el.value || '')
    let c = el.parentElement
    for (let i = 0; i < 3 && c; i++, c = c.parentElement) {
      const t = clean(c.innerText).replace(own, '').trim()
      if (t) return t.slice(0, 160)
    }
    return ''
  }
  const actionOf = (el) => {
    const tag = el.tagName
    if (tag === 'SUMMARY') return 'disclosure'
    if (tag === 'A' && el.getAttribute('href') != null) return 'link'
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag) && !['submit', 'button', 'reset', 'image'].includes(el.type)) return 'field'
    if (hasClick(el)) return 'click'
    let a = el.parentElement
    for (let i = 0; i < 3 && a; i++, a = a.parentElement) if (hasClick(a)) return 'click(ancestor)'
    if (el.closest('a[href]')) return 'link(ancestor)'
    if ((tag === 'BUTTON' || tag === 'INPUT') && el.form && (el.type === 'submit' || el.type === 'image')) return 'submit'
    if (tag === 'BUTTON' && el.type === 'reset' && el.form) return 'reset'
    if (el.getAttribute('popovertarget') || el.getAttribute('commandfor')) return 'popover'
    if (el.closest('label') && tag === 'INPUT') return 'label'
    const p = props(el)
    if (p && (p.onKeyDown || p.onChange || p.onFocus)) return 'other-handler'
    return 'none'
  }
  const items = els.map((el, i) => {
    el.setAttribute('data-ca', String(i))
    const r = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    const own = clean(el.innerText || '')
    const parentText = clean(el.parentElement?.innerText || '')
    return {
      i,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      type: el.getAttribute('type') || (el.tagName === 'BUTTON' ? 'submit' : ''),
      text: own.slice(0, 80),
      value: el.tagName === 'INPUT' || el.tagName === 'SELECT' ? clean(el.value).slice(0, 40) : '',
      href: el.getAttribute('href'),
      target: el.getAttribute('target') || '',
      disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
      title: el.getAttribute('title') || '',
      placeholder: el.getAttribute('placeholder') || '',
      ariaLabel: el.getAttribute('aria-label') || '',
      labelled: !!(el.labels && el.labels.length) || el.hasAttribute('aria-labelledby') || el.hasAttribute('aria-label') || !!el.getAttribute('title'),
      describedBy: describe(el),
      context: el.disabled === true || el.getAttribute('aria-disabled') === 'true' ? contextText(el) : '',
      rect: { x: Math.round(r.x), y: Math.round(r.y + window.scrollY), w: Math.round(r.width), h: Math.round(r.height) },
      onScreenX: r.right > 0 && r.left < W,
      srOnly: r.width <= 2 && r.height <= 2,
      inline: cs.display === 'inline' && parentText.length > own.length + 15,
      chrome: !!el.closest(CHROME),
      nested: !!el.parentElement?.closest('a[href],button'),
      action: actionOf(el),
      hashOk: (() => {
        const h = el.getAttribute('href')
        if (!h || !h.includes('#')) return null
        const u = new URL(h, location.href)
        if (u.pathname !== location.pathname || !u.hash || u.hash === '#') return null
        return !!document.getElementById(decodeURIComponent(u.hash.slice(1)))
      })(),
    }
  })
  const extra = clickables.map((el) => ({
    tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', cls: String(el.className || '').slice(0, 60),
    text: clean(el.innerText).slice(0, 80), chrome: !!el.closest(CHROME),
    tabbable: el.tabIndex >= 0,
  }))
  // Horizontal overflow: elements that stick out of the viewport without a
  // scrolling/clipping ancestor to hold them.
  const sw = document.documentElement.scrollWidth
  const offenders = []
  if (sw > W + 1) {
    const holds = (el) => {
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const ox = getComputedStyle(a).overflowX
        if (['auto', 'scroll', 'hidden', 'clip'].includes(ox)) return true
      }
      return false
    }
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect()
      if (r.right <= W + 1 || r.width === 0 || !visible(el)) continue
      if (holds(el)) continue
      if (offenders.some((o) => o.el.contains(el))) continue
      offenders.push({ el, right: Math.round(r.right) })
      if (offenders.length >= 8) break
    }
  }
  const main = document.querySelector('main') || document.body
  const mainText = clean(main.innerText)
  const bodyText = clean(document.body.innerText)
  const portal = document.querySelector('nextjs-portal')
  const overlay = clean(portal?.shadowRoot?.textContent || '')
  // Stat tiles showing a bare zero ("0", "₹0", "0%", "0.0") — leaf elements only,
  // with the tile's text for the reader to judge (an honest "0 orders today"
  // on a live shop is fine; a wall of zero cards on a new business is not).
  const ZERO = /^(₹\s?)?0([.,]0+)?\s?%?$/
  const zeroStats = []
  for (const el of main.querySelectorAll('strong,b,span,div,p,dd,td,output,h2,h3,h4,data')) {
    if (el.children.length || !ZERO.test(clean(el.textContent)) || !visible(el)) continue
    const tile = el.parentElement?.parentElement || el.parentElement
    zeroStats.push(clean(tile?.innerText || '').slice(0, 70))
  }
  return {
    url: location.href,
    title: document.title,
    h1: [...document.querySelectorAll('h1')].filter(visible).map((e) => clean(e.innerText)).slice(0, 4),
    headings: [...main.querySelectorAll('h1,h2,h3')].filter(visible).map((e) => clean(e.innerText).slice(0, 80)).slice(0, 25),
    markers: {
      errorBoundary: /Something went wrong on this page/.test(bodyText),
      notFound: /Not your business|This page could not be found/.test(bodyText),
      gate: (bodyText.match(/[^.]{0,60}(is switched off|isn't in your plan|You do not have access to|could not be loaded|temporarily unreachable|Could not reach)[^.]{0,60}/) || [''])[0],
      devOverlay: /Unhandled Runtime Error|Server Error|Failed to compile|Error:/.test(overlay) ? overlay.slice(0, 400) : '',
    },
    zeroMoney: (mainText.match(/₹\s?0(?![\d.,])/g) || []).length,
    zeroStats: zeroStats.slice(0, 20),
    mainText: mainText.slice(0, 3000),
    scrollWidth: sw,
    innerWidth: W,
    innerHeight: H,
    overflow: offenders.map((o) => ({
      right: o.right,
      what: `${o.el.tagName.toLowerCase()}${o.el.id ? `#${o.el.id}` : ''}${typeof o.el.className === 'string' && o.el.className ? `.${o.el.className.trim().split(/\s+/).slice(0, 3).join('.')}` : ''}`,
      text: clean(o.el.innerText).slice(0, 60),
    })),
    items,
    clickables: extra,
  }
}

// The accessible name Chrome computes for each data-ca element.
async function axNames(page) {
  const cdp = await page.context().newCDPSession(page)
  try {
    await cdp.send('DOM.enable').catch(() => {})
    await cdp.send('Accessibility.enable').catch(() => {})
    const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
    const byBackend = new Map()
    const walk = (n) => {
      const a = n.attributes || []
      for (let i = 0; i < a.length; i += 2) if (a[i] === 'data-ca') byBackend.set(n.backendNodeId, Number(a[i + 1]))
      for (const c of n.children || []) walk(c)
      for (const c of n.shadowRoots || []) walk(c)
      if (n.contentDocument) walk(n.contentDocument)
    }
    walk(root)
    const { nodes } = await cdp.send('Accessibility.getFullAXTree')
    const out = {}
    for (const n of nodes) {
      const idx = byBackend.get(n.backendDOMNodeId)
      if (idx === undefined) continue
      out[idx] = { name: String(n.name?.value ?? '').trim(), role: n.role?.value || '', ignored: !!n.ignored }
    }
    return out
  } finally {
    await cdp.detach().catch(() => {})
  }
}

// --------------------------------------------------------------- the audit
const browser = await chromium.launch()
const contexts = {}
for (const vp of VPS) {
  contexts[vp] = await browser.newContext(VIEWPORTS[vp])
  await contexts[vp].addCookies(sessionCookies(owner))
}
// --links-only: re-check the link targets of a finished audit.json (pages untouched).
const LINKS_ONLY = flag('links-only')
const prior = existsSync(AUDIT_JSON) && (ONLY || LINKS_ONLY) ? JSON.parse(readFileSync(AUDIT_JSON, 'utf8')) : null
const audit = prior || {
  started_at: new Date().toISOString(),
  journal: JOURNAL,
  business_id: B,
  owner_email: owner.email,
  workspace: WS,
  routes_total: ROUTES.length,
  pages: [],
  probes: [],
  skipped: [],
  resolved: {},
  links: {},
  drawer: null,
  keyboard: [],
}
const save = () => writeFileSync(AUDIT_JSON, JSON.stringify(audit, null, 1))
const seenHrefs = new Map() // absolute url -> first route that showed it

async function auditPage(vp, route, concrete, { probe = false } = {}) {
  const url = routeUrl(concrete)
  const page = await contexts[vp].newPage()
  const consoleErrors = []
  const pageErrors = []
  const badResponses = []
  const blockedWrites = []
  await guard(page, blockedWrites)
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text().replace(/\s+/g, ' ')
    if (/ERR_BLOCKED_BY_CLIENT/.test(t)) return // our own write guard
    consoleErrors.push(t.slice(0, 300))
  })
  page.on('pageerror', (e) => pageErrors.push(String(e).replace(/\s+/g, ' ').slice(0, 300)))
  page.on('response', (r) => {
    const t = r.request().resourceType()
    if (r.status() >= 400 && ['fetch', 'xhr', 'script', 'stylesheet', 'image', 'font'].includes(t)) badResponses.push(`${r.status()} ${t} ${r.url().split(B).join('{B}').slice(0, 160)}`)
  })
  page.on('requestfailed', (r) => {
    const f = r.failure()?.errorText || ''
    if (!/ERR_ABORTED|ERR_BLOCKED_BY_CLIENT/.test(f)) badResponses.push(`failed ${r.resourceType()} ${r.url().split(B).join('{B}').slice(0, 160)} ${f}`)
  })
  const t0 = Date.now()
  let status = 0
  let loadError = ''
  try {
    const resp = await load(page, url)
    status = resp?.status() || 0
  } catch (e) {
    loadError = String(e).split('\n')[0].slice(0, 200)
  }
  await page.waitForTimeout(400)
  const ms = Date.now() - t0
  let info = null
  try {
    info = await page.evaluate(inspect)
    const names = await axNames(page)
    for (const it of info.items) {
      const ax = names[it.i]
      it.name = ax ? ax.name : null
      it.axRole = ax ? ax.role : ''
      it.axIgnored = ax ? ax.ignored : null
    }
  } catch (e) {
    loadError = loadError || `inspect: ${String(e).split('\n')[0].slice(0, 200)}`
  }
  let shot = ''
  if (!flag('no-shots')) {
    shot = `${probe ? 'probe-' : ''}${slugOf(concrete)}--${vp}.jpg`
    await page.screenshot({ path: path.join(OUT, shot), fullPage: true, type: 'jpeg', quality: 55, timeout: 60000 }).catch(() => { shot = '' })
  }
  if (info) {
    for (const it of info.items) {
      if (!it.href || it.href.startsWith('javascript:')) continue
      let abs
      try { abs = new URL(it.href, info.url).href } catch { continue }
      if (!seenHrefs.has(abs)) seenHrefs.set(abs, concrete || '(home)')
    }
  }
  await page.close()
  const rec = { route, concrete, vp, url, status, final_url: info?.url || '', ms, loadError, consoleErrors: [...new Set(consoleErrors)], pageErrors: [...new Set(pageErrors)], badResponses: [...new Set(badResponses)], blockedWrites: [...new Set(blockedWrites)], shot, ...(info || {}) }
  const flags = [
    rec.blockedWrites.length ? `BLOCKED-WRITES:${rec.blockedWrites.length}` : '',
    status >= 400 ? `HTTP ${status}` : '', loadError ? 'LOAD-ERROR' : '', info?.markers?.errorBoundary ? 'ERROR-BOUNDARY' : '',
    info?.markers?.notFound ? 'NOT-FOUND' : '', info?.markers?.gate ? 'GATE' : '', rec.consoleErrors.length ? `console:${rec.consoleErrors.length}` : '',
    rec.pageErrors.length ? `pageerror:${rec.pageErrors.length}` : '', info && info.scrollWidth > info.innerWidth + 1 ? `overflow:${info.scrollWidth}` : '',
  ].filter(Boolean)
  console.log(`${probe ? 'probe ' : ''}${vp.padEnd(7)} ${String(status).padEnd(3)} ${String(ms).padStart(6)}ms /${concrete} ${info ? `items=${info.items.length}` : ''} ${flags.join(' ')}`)
  return rec
}

async function runRoute(route, concrete, opts = {}) {
  for (const vp of opts.probe ? ['desktop'] : VPS) {
    const rec = await auditPage(vp, route, concrete, opts)
    const list = opts.probe ? audit.probes : audit.pages
    const at = list.findIndex((p) => p.concrete === concrete && p.vp === vp)
    if (at >= 0) list[at] = rec
    else list.push(rec)
    save()
  }
}

const matches = (r) => !ONLY || r.includes(ONLY)
if (LINKS_ONLY) {
  audit.links = {}
  for (const p of [...audit.pages, ...audit.probes]) {
    for (const it of p.items || []) {
      if (!it.href || it.href.startsWith('javascript:')) continue
      try {
        const abs = new URL(it.href, p.final_url || p.url).href
        if (!seenHrefs.has(abs)) seenHrefs.set(abs, p.concrete || '(home)')
      } catch { /* not a URL */ }
    }
  }
}
try {
  if (!LINKS_ONLY) {
  // 1. Static routes, both widths.
  for (const r of ROUTES.filter((x) => STATIC.has(x) && matches(x))) await runRoute(r, r)

  // 2. Dynamic routes: ids from links the Workspace rendered, then the journal / API.
  const fallback = {
    'orders/[orderId]': journal.order_id,
    'offerings/[offeringId]': journal.products_live?.[0]?.id,
    'customers/[customerId]': firstId((await apiGet(`/v1/platform/businesses/${B}/customers`)).data),
    'locations/[locationId]': firstId((await apiGet(`/v1/platform/businesses/${B}/locations`)).data),
    'fulfilment/[jobId]': firstId((await apiGet(`/v1/b/${B}/fulfilment/jobs`)).data),
    'inventory/[recordId]': firstId((await apiGet(`/v1/platform/businesses/${B}/stock`)).data),
    'modules/[moduleId]': 'orders',
  }
  const PER_ROUTE = { 'modules/[moduleId]': 2 }
  const hrefPaths = [...seenHrefs.keys()].map((h) => { try { const u = new URL(h); return u.origin === WS ? u.pathname : '' } catch { return '' } }).filter(Boolean)
  for (const r of DYNAMIC.filter(matches)) {
    const segs = r.split('/')
    const pi = segs.findIndex((s) => s.startsWith('['))
    const prefix = segs.slice(0, pi).join('/')
    const tail = segs.slice(pi + 1).join('/')
    const re = new RegExp(`^/b/${B}/${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/([^/?#]+)${tail ? `/${tail}` : ''}$`)
    const found = []
    for (const p of hrefPaths) {
      const m = p.match(re)
      if (!m) continue
      const v = decodeURIComponent(m[1])
      if (STATIC.has(`${prefix}/${v}`) || found.includes(v)) continue
      found.push(v)
    }
    let values = found.slice(0, PER_ROUTE[r] || 1)
    let source = 'workspace link'
    if (!values.length && fallback[r]) { values = [fallback[r]]; source = 'journal/API' }
    if (!values.length) {
      audit.skipped.push({ route: r, reason: 'no record of this kind for this business (no link in the Workspace, none in the journal/API)' })
      save()
      await runRoute(r, segs.map((s, i) => (i === pi ? NIL : s)).join('/'), { probe: true })
      continue
    }
    audit.resolved[r] = { values, source }
    for (const v of values) await runRoute(r, segs.map((s, i) => (i === pi ? v : s)).join('/'))
  }

  // 3. The phone navigation drawer (a disclosure — the one thing clicked).
  if (VPS.includes('phone') && (!ONLY || ONLY === 'drawer')) {
    const page = await contexts.phone.newPage()
    const writes = []
    await guard(page, writes)
    await load(page, routeUrl(''))
    const toggle = page.locator('.ws-mobile-bar__toggle')
    const drawer = { toggle_name: await toggle.getAttribute('aria-label').catch(() => null), toggle_size: await toggle.boundingBox().catch(() => null) }
    await toggle.click()
    await page.waitForTimeout(500)
    drawer.after_open = await page.evaluate(() => {
      const nav = document.querySelector('[aria-label="Workspace navigation"]')
      const W = window.innerWidth
      const links = [...(nav?.querySelectorAll('a[href],button') || [])].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > 0 && r.left < W })
      return {
        focus_inside: !!(nav && nav.contains(document.activeElement)),
        active: document.activeElement?.tagName + ' ' + (document.activeElement?.getAttribute('aria-label') || document.activeElement?.textContent || '').trim().slice(0, 40),
        count: links.length,
        small: links.map((e) => { const r = e.getBoundingClientRect(); return { text: (e.textContent || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 40), w: Math.round(r.width), h: Math.round(r.height) } }).filter((x) => x.h < 44 || x.w < 44),
        nav_height: Math.round(nav?.scrollHeight || 0),
        body_scroll_locked: getComputedStyle(document.body).overflow === 'hidden',
      }
    })
    await page.screenshot({ path: path.join(OUT, 'drawer--phone.jpg'), type: 'jpeg', quality: 60 }).catch(() => {})
    await page.keyboard.press('Escape')
    await page.waitForTimeout(400)
    drawer.escape_closes = await page.evaluate(() => !document.querySelector('[aria-label="Workspace navigation"][data-mobile-open]'))
    drawer.blockedWrites = writes
    audit.drawer = drawer
    save()
    await page.close()
    console.log('drawer', JSON.stringify(drawer).slice(0, 400))
  }

  // 4. Keyboard probe: the first Tab stops on a few pages, and whether focus is visible.
  if (VPS.includes('desktop') && (!ONLY || ONLY === 'keyboard')) {
    audit.keyboard = []
    for (const concrete of ['', 'orders', 'offerings', 'inventory', 'modules']) {
      const page = await contexts.desktop.newPage()
      await guard(page, [])
      await load(page, routeUrl(concrete))
      const stops = []
      for (let i = 0; i < 6; i++) {
        await page.keyboard.press('Tab')
        stops.push(await page.evaluate(() => {
          const e = document.activeElement
          if (!e || e === document.body) return { what: 'body' }
          const cs = getComputedStyle(e)
          const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none')
          return { what: `${e.tagName.toLowerCase()} ${(e.getAttribute('aria-label') || e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40)}`, focus_visible: e.matches(':focus-visible'), ring: !!ring }
        }))
      }
      audit.keyboard.push({ route: concrete || '(home)', stops })
      await page.close()
    }
    save()
  }
  } // !LINKS_ONLY

  // 5. Every distinct link target, GET once (localhost only), signed in.
  if (!flag('no-links')) {
    const req = await pwRequest.newContext({
      storageState: { cookies: sessionCookies(owner).map((c) => ({ ...c, expires: -1 })), origins: [] },
    })
    const todo = [...seenHrefs.entries()].filter(([u]) => !audit.links[u])
    console.log(`\nlinks to check: ${todo.length}`)
    for (const [u, from] of todo) {
      let host = ''
      try { host = new URL(u).hostname } catch {}
      if (!['localhost', '127.0.0.1'].includes(host) || /sign-?out|logout/i.test(u)) {
        audit.links[u] = { from, checked: false, why: host ? 'not localhost — not fetched' : 'not http(s)' }
        continue
      }
      try {
        const r = await req.get(u, { timeout: 120000, maxRedirects: 10 })
        const ct = r.headers()['content-type'] || ''
        let marker = ''
        if (ct.includes('text/html')) {
          // Only the rendered markup: Next.js serialises the not-found and
          // error boundaries into every page's inline RSC payload.
          const html = (await r.text()).replace(/<script[\s\S]*?<\/script>/gi, '')
          if (/Something went wrong on this page/.test(html)) marker = 'error-boundary'
          else if (/Not your business/.test(html)) marker = 'not-found-page'
          else if (/This page could not be found/.test(html)) marker = 'next-404'
        }
        audit.links[u] = { from, checked: true, status: r.status(), final: r.url(), type: ct.split(';')[0], marker }
      } catch (e) {
        audit.links[u] = { from, checked: true, status: 0, error: String(e).split('\n')[0].slice(0, 160) }
      }
      const l = audit.links[u]
      if (!l.status || l.status >= 400 || l.marker) console.log(`  link ${l.status} ${l.marker || ''} ${u} (from /${from})`)
    }
    save()
    await req.dispose()
  }
} finally {
  audit.ended_at = new Date().toISOString()
  save()
  await browser.close()
}
console.log(`\nwrote ${path.relative(ROOT, AUDIT_JSON)}`)

// ------------------------------------------------------------------ summary
function summary(a) {
  const pages = a.pages
  const isButton = (it) => it.tag === 'button' || it.role === 'button' || (it.tag === 'input' && ['submit', 'button', 'reset', 'image'].includes(it.type))
  const isField = (it) => ['input', 'select', 'textarea'].includes(it.tag) && !isButton(it)
  const problemsOf = (p) => {
    const out = []
    if (p.status >= 400) out.push(['page', `HTTP ${p.status}`])
    if (p.loadError) out.push(['page', p.loadError])
    if (p.markers?.errorBoundary) out.push(['page', 'error boundary shown'])
    if (p.markers?.notFound) out.push(['page', 'not-found page shown'])
    if (p.markers?.devOverlay) out.push(['page', `dev overlay: ${p.markers.devOverlay.slice(0, 120)}`])
    for (const e of p.pageErrors || []) out.push(['page', `page error: ${e.slice(0, 160)}`])
    for (const e of p.consoleErrors || []) out.push(['page', `console error: ${e.slice(0, 160)}`])
    for (const e of p.badResponses || []) out.push(['page', `request: ${e.slice(0, 160)}`])
    for (const e of p.blockedWrites || []) out.push(['page', `write attempted on load (blocked by the audit): ${e}`])
    if ((p.zeroStats || []).length >= 3) out.push(['page', `${p.zeroStats.length} zero-valued figures: ${[...new Set(p.zeroStats)].slice(0, 5).map((z) => `"${z}"`).join(', ')}`])
    if (p.vp === 'phone' && p.scrollWidth > p.innerWidth + 1) out.push(['page', `horizontal overflow: ${p.scrollWidth}px > ${p.innerWidth}px (${(p.overflow || []).map((o) => `${o.what} "${o.text}" to ${o.right}px`).join('; ').slice(0, 200)})`])
    for (const it of p.items || []) {
      const label = `${it.tag}${it.role ? `[role=${it.role}]` : ''}${it.type && it.tag !== 'a' ? `[${it.type}]` : ''} "${(it.text || it.placeholder || it.value || '').slice(0, 40)}"${it.href ? ` -> ${it.href.replace(`/b/${a.business_id}`, '/b/{B}').slice(0, 60)}` : ''}`
      const where = it.chrome ? 'chrome' : 'content'
      if (it.axIgnored === false && it.name === '' && !it.srOnly) out.push([where, `no accessible name: ${label}`])
      if (it.axIgnored === true && !it.disabled && it.tag !== 'summary') out.push([where, `focusable but hidden from assistive tech: ${label}`])
      if (isField(it) && it.name && !it.labelled && it.placeholder && it.name === it.placeholder) out.push([where, `label is only a placeholder: ${label}`])
      if (isButton(it) && !it.disabled && it.action === 'none') out.push([where, `button with nothing wired to it: ${label}`])
      if (it.tag === 'a' && (it.href === '#' || it.href === '')) out.push([where, `link to nowhere (${JSON.stringify(it.href)}): ${label}`])
      if (it.hashOk === false) out.push([where, `in-page link target missing: ${label}`])
      if (it.nested) out.push([where, `interactive element nested in a link/button: ${label}`])
      if (isButton(it) && it.disabled && !it.title && !it.describedBy) out.push([where, `disabled; reason nearby? "${it.context || '(no text near it)'}": ${label}`])
    }
    for (const c of p.clickables || []) if (!c.tabbable && !['label'].includes(c.tag)) out.push([c.chrome ? 'chrome' : 'content', `clickable ${c.tag}${c.role ? `[role=${c.role}]` : ''}.${c.cls} "${c.text.slice(0, 40)}" — not keyboard reachable`])
    return out
  }
  const tap = (p, chromeOnly = false) => {
    const its = (p.items || []).filter((it) => it.onScreenX && !it.srOnly && it.chrome === chromeOnly && !it.inline)
    const small = its.filter((it) => it.rect.w < 44 || it.rect.h < 44)
    const name = (it) => `${it.tag} "${(it.name || it.text || it.placeholder || '').slice(0, 30)}" ${it.rect.w}x${it.rect.h}`
    return { small: small.length, tiny: its.filter((it) => it.rect.w < 24 || it.rect.h < 24).length, of: its.length, eg: [...new Set(small.map(name))].slice(0, 8) }
  }
  const chrome = new Map()
  const lines = []
  const byRoute = new Map()
  for (const p of pages) {
    if (!byRoute.has(p.concrete)) byRoute.set(p.concrete, [])
    byRoute.get(p.concrete).push(p)
  }
  lines.push('| Route | Desktop | Phone | Items | Phone taps <44 / <24 | Problems |', '|---|---|---|---|---|---|')
  const detail = []
  for (const [concrete, ps] of byRoute) {
    const d = ps.find((p) => p.vp === 'desktop')
    const ph = ps.find((p) => p.vp === 'phone')
    const st = (p) => (p ? `${p.status}${p.markers?.gate ? ' gate' : ''}${p.markers?.notFound ? ' 404pg' : ''}${p.markers?.errorBoundary ? ' ERR' : ''}` : '-')
    const probs = []
    for (const p of ps) for (const [where, text] of problemsOf(p)) {
      if (where === 'chrome') {
        const k = text.replace(/ -> \/b\/\{B\}[^ ]*/, '')
        if (!chrome.has(k)) chrome.set(k, new Set())
        chrome.get(k).add(`${p.vp}`)
        continue
      }
      probs.push(`${p.vp}: ${text}`)
    }
    const uniq = [...new Set(probs.map((x) => x.replace(/^(desktop|phone): /, '')))]
    const t = ph ? tap(ph) : null
    lines.push(`| /${concrete.replace(a.business_id, '{B}')} | ${st(d)} | ${st(ph)} | ${d?.items?.length ?? '-'} | ${t ? `${t.small} / ${t.tiny} of ${t.of}` : '-'} | ${uniq.length} |`)
    const tapLine = t && t.small ? [`- phone tap targets under 44px (${t.small}): ${t.eg.join('; ')}`] : []
    if (uniq.length || tapLine.length) detail.push(`\n#### /${concrete}\n`, ...uniq.map((u) => `- ${u.replace(/\|/g, '/')}`), ...tapLine)
  }
  const home = pages.find((p) => p.concrete === '' && p.vp === 'phone')
  if (home) {
    const ct = tap(home, true)
    lines.push('', `Phone chrome (mobile bar, on /): ${ct.small} of ${ct.of} visible targets under 44px — ${ct.eg.join('; ')}`)
  }
  console.log(lines.join('\n'))
  console.log('\n### Problems per route (content only; chrome below)')
  console.log(detail.join('\n'))
  console.log('\n### Chrome (sidebar / mobile bar), reported once')
  for (const [k, v] of chrome) console.log(`- ${k} (${[...v].join(', ')})`)
  console.log('\n### Links')
  const bad = Object.entries(a.links).filter(([, l]) => l.checked && (!l.status || l.status >= 400 || l.marker))
  console.log(`checked ${Object.values(a.links).filter((l) => l.checked).length}, not fetched ${Object.values(a.links).filter((l) => !l.checked).length}, failing ${bad.length}`)
  for (const [u, l] of bad) console.log(`- ${l.status} ${l.marker || ''} ${u.replace(a.business_id, '{B}')} (from /${String(l.from).replace(a.business_id, '{B}')})`)
  for (const [u, l] of Object.entries(a.links).filter(([, x]) => !x.checked)) console.log(`- not fetched: ${u} — ${l.why}`)
  console.log('\n### Skipped / probes')
  for (const s of a.skipped) console.log(`- ${s.route}: ${s.reason}`)
  for (const p of a.probes) console.log(`- probe /${p.concrete.replace(a.business_id, '{B}')}: ${p.status} ${p.markers?.notFound ? 'not-found page' : ''}${p.markers?.errorBoundary ? 'ERROR BOUNDARY' : ''}${p.markers?.gate ? `gate: ${p.markers.gate}` : ''} h1=${JSON.stringify(p.h1)} console=${(p.consoleErrors || []).length}`)
  console.log('\n### Resolved')
  for (const [r, v] of Object.entries(a.resolved)) console.log(`- ${r}: ${v.values.join(', ')} (${v.source})`)
  console.log('\n### Drawer / keyboard')
  console.log(JSON.stringify(a.drawer))
  for (const k of a.keyboard) console.log(`- ${k.route}: ${k.stops.map((s) => `${s.what}${s.focus_visible === false ? ' [no :focus-visible]' : ''}${s.ring === false ? ' [no ring]' : ''}`).join(' | ')}`)
}

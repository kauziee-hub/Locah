// Look at one page as a lab owner: headings, buttons, inputs, links, and a shot.
//   node tools/certify/owner-lab/look.mjs <scenario-variant> <url with {B}> [shot.png] [--guest] [--width 1440]
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { mintToken, sessionCookies } from './session.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const args = process.argv.slice(2)
const guest = args.includes('--guest')
const wi = args.indexOf('--width')
const width = wi >= 0 ? Number(args[wi + 1]) : 1440
const [run, url, shot] = args.filter((a, i) => !a.startsWith('--') && args[i - 1] !== '--width')
const journal = JSON.parse(readFileSync(path.join(ROOT, 'certify-out/product-e2e/SCENARIOS', run, 'journal.json'), 'utf8'))
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width, height: 900 } })
if (!guest) await ctx.addCookies(sessionCookies({ ...journal.owner, token: mintToken(journal.owner) }))
const page = await ctx.newPage()
await page.goto(url.replaceAll('{B}', journal.business_id).replaceAll('{SLUG}', journal.slug || ''), { waitUntil: 'networkidle', timeout: 120000 })
const info = await page.evaluate(() => {
  const vis = (e) => e.getClientRects().length > 0
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80)
  return {
    url: location.href,
    headings: [...document.querySelectorAll('h1,h2,h3')].filter(vis).map(txt).slice(0, 30),
    buttons: [...document.querySelectorAll('button,[role=button]')].filter(vis).map((b) => txt(b) + (b.disabled ? ' (disabled)' : '')).slice(0, 50),
    inputs: [...document.querySelectorAll('input,select,textarea')].filter(vis).map((i) => `${i.tagName.toLowerCase()}[${i.type || ''}] name=${i.name || ''} label=${(i.closest('label')?.innerText || i.getAttribute('aria-label') || i.placeholder || '').replace(/\s+/g, ' ').slice(0, 50)} value=${String(i.value).slice(0, 30)}`).slice(0, 50),
    links: [...document.querySelectorAll('main a')].filter(vis).map((a) => `${txt(a)} -> ${a.getAttribute('href')}`).slice(0, 40),
  }
})
console.log(JSON.stringify(info, null, 1))
if (shot) await page.screenshot({ path: shot, fullPage: true })
await browser.close()

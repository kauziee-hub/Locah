// First-screen and full-page shots of a public tenant site, desktop and phone.
//   node tools/certify/owner-lab/siteshots.mjs <base url> <out dir> [path ...]
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const [base, out, ...paths] = process.argv.slice(2)
mkdirSync(out, { recursive: true })
const browser = await chromium.launch()
for (const [label, viewport] of [['d', { width: 1440, height: 900 }], ['m', { width: 390, height: 844 }]]) {
  const ctx = await browser.newContext({ viewport, reducedMotion: 'reduce', deviceScaleFactor: 1 })
  const page = await ctx.newPage()
  for (const p of paths.length ? paths : ['']) {
    const name = (p || 'home').replace(/[^a-z0-9]+/gi, '-')
    await page.goto(base + (p ? `/${p}` : ''), { waitUntil: 'networkidle', timeout: 120000 }).catch(() => {})
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(out, `${name}-${label}-first.png`) })
    // Full pages are scaled down so a long site stays readable as one image.
    const height = await page.evaluate(() => document.documentElement.scrollHeight)
    await page.evaluate(async () => { for (let y = 0; y < document.documentElement.scrollHeight; y += 600) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)) } window.scrollTo(0, 0) })
    await page.waitForTimeout(400)
    await page.screenshot({ path: path.join(out, `${name}-${label}-full.png`), fullPage: true })
    const facts = await page.evaluate(() => ({
      h: [...document.querySelectorAll('h1,h2,h3')].map((e) => e.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 40),
      imgs: [...document.images].map((i) => ({ src: (i.currentSrc || i.src).slice(0, 90), ok: i.complete && i.naturalWidth > 0 })),
      buttons: [...document.querySelectorAll('button, a.ls-btn, [class*=btn]')].map((b) => b.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 40),
    }))
    console.log(JSON.stringify({ page: p || 'home', view: label, height, ...facts }))
  }
  await ctx.close()
}
await browser.close()

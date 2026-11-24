// Every composed section of a set of pages, photographed on its own at desktop and phone width.
//   node tools/site-lab/composition-shots.mjs <out dir> <url> [url ...]
// Reduced motion (the still state is the design). Prints each composition's
// role, recipe and size, and any block that overflows the page or its grid.
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const [out, ...urls] = process.argv.slice(2)
mkdirSync(out, { recursive: true })
const browser = await chromium.launch()
for (const [label, viewport] of [['d', { width: 1440, height: 900 }], ['m', { width: 390, height: 844 }]]) {
  const ctx = await browser.newContext({ viewport, reducedMotion: 'reduce', deviceScaleFactor: 1 })
  const page = await ctx.newPage()
  for (const url of urls) {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 120000 }).catch(() => {})
    await page.waitForTimeout(600)
    const name = url.replace(/^https?:\/\/[^/]+\//, '').replace(/[^a-z0-9]+/gi, '-')
    const comps = await page.$$('section.fx-comp')
    for (let i = 0; i < comps.length; i++) {
      const el = comps[i]
      await el.scrollIntoViewIfNeeded()
      await page.waitForTimeout(250)
      const facts = await el.evaluate((node) => {
        const width = document.documentElement.clientWidth
        const blocks = [...node.querySelectorAll('.fx-comp__b')].map((b) => {
          const r = b.getBoundingClientRect()
          return { kind: b.className.replace(/.*--/, ''), left: Math.round(r.left), right: Math.round(r.right), h: Math.round(r.height) }
        })
        return {
          height: Math.round(node.getBoundingClientRect().height),
          overflow: blocks.filter((b) => b.kind !== 'picture' && (b.left < 0 || b.right > width)).length,
          empty: blocks.filter((b) => b.h < 8).length,
          blocks: blocks.length,
        }
      })
      const file = path.join(out, `${name}-c${i + 1}-${label}.png`)
      await el.screenshot({ path: file })
      console.log(JSON.stringify({ url, comp: i + 1, view: label, ...facts }))
    }
  }
  await ctx.close()
}
await browser.close()

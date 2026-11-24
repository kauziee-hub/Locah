// The photo credit as a visitor sees it — for Unsplash's production review.
//   node tools/certify/owner-lab/credit-shot.mjs <public site url> <out.png>
import { chromium } from 'playwright'

const [url, out] = process.argv.slice(2)
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
await page.goto(url, { waitUntil: 'networkidle', timeout: 120000 })
const credits = page.locator('.ls-foot__credits')
await credits.scrollIntoViewIfNeeded()
await page.waitForTimeout(800)
const text = await credits.innerText()
const links = await credits.locator('a').evaluateAll((as) => as.map((a) => `${a.innerText} -> ${a.href}`))
await page.locator('footer').first().screenshot({ path: out })
console.log(JSON.stringify({ text, links }, null, 1))
await browser.close()

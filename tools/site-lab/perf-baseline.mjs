// Speed of a public tenant page on a mid-range Android phone over mobile data.
//
// The profile Lighthouse uses for "mobile": Slow 4G (150 ms RTT, 1.6 Mbit/s
// down, 750 kbit/s up) and the CPU slowed 4×, measured through the Chrome
// DevTools Protocol in a fresh, cache-less context per run. Run it against a
// PRODUCTION build (tools/certify/stack/web-prod.sh): a dev server's on-demand
// compiles make every page look slow.
//
//   node tools/site-lab/perf-baseline.mjs <out.json> <url> [url ...]
//   RUNS=3 node tools/site-lab/perf-baseline.mjs ...      (median of 3, default 2)
import { writeFileSync } from 'node:fs'
import { chromium } from 'playwright'

const [out, ...urls] = process.argv.slice(2)
const RUNS = Number(process.env.RUNS || 2)
const PHONE = {
  viewport: { width: 390, height: 844 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true,
  userAgent: 'Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36',
}
const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor((s.length - 1) / 2)] : null }

async function once(browser, url) {
  const ctx = await browser.newContext(PHONE)
  const page = await ctx.newPage()
  const cdp = await ctx.newCDPSession(page)
  await cdp.send('Network.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8,
  })
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
  // Bytes from the network layer: a cross-origin photo hides its size from the page.
  const kinds = new Map()
  const urlOf = new Map()
  const fontFiles = []
  const bytes = { script: 0, image: 0, font: 0, stylesheet: 0, document: 0, other: 0 }
  let requests = 0
  cdp.on('Network.responseReceived', (e) => {
    kinds.set(e.requestId, String(e.type || 'Other').toLowerCase())
    urlOf.set(e.requestId, e.response.url)
  })
  cdp.on('Network.loadingFinished', (e) => {
    requests += 1
    const kind = kinds.get(e.requestId) || 'other'
    bytes[kind in bytes ? kind : 'other'] += e.encodedDataLength || 0
    if (kind === 'font') fontFiles.push({ file: String(urlOf.get(e.requestId) || '').split('/').pop(), kb: Math.round((e.encodedDataLength || 0) / 1024) })
  })
  await page.addInitScript(() => {
    window.__perf = { lcp: 0, cls: 0, longTasks: 0 }
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.lcp = e.startTime }).observe({ type: 'largest-contentful-paint', buffered: true })
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__perf.cls += e.value }).observe({ type: 'layout-shift', buffered: true })
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.longTasks += Math.max(0, e.duration - 50) }).observe({ type: 'longtask', buffered: true })
  })
  const started = Date.now()
  // Not the load event: a page whose photographs keep streaming over Slow 4G
  // never fires it. What a visitor sees is settled by then.
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 180000 })
  const loaded = await page.waitForLoadState('load', { timeout: 30000 }).then(() => true).catch(() => false)
  await page.waitForTimeout(4000)
  const m = await page.evaluate(() => {
    const fcp = performance.getEntriesByName('first-contentful-paint')[0]
    const lcpEl = performance.getEntriesByType('largest-contentful-paint').slice(-1)[0]?.element
    return {
      lcp_ms: Math.round(window.__perf.lcp), fcp_ms: fcp ? Math.round(fcp.startTime) : null,
      cls: Number(window.__perf.cls.toFixed(3)), tbt_ms: Math.round(window.__perf.longTasks),
      // Which faces the page actually drew with: a font budget names its culprits.
      faces: [...document.fonts].filter((f) => f.status === 'loaded')
        .map((f) => `${f.family.replace(/['"]/g, '')} ${f.style} ${f.weight} [${f.unicodeRange.slice(0, 24)}]`),
      lcp_element: lcpEl ? `${lcpEl.tagName.toLowerCase()}.${String(lcpEl.className || '').split(' ')[0]}`.slice(0, 60) : '',
    }
  })
  await ctx.close()
  const kb = (n) => Math.round(n / 1024)
  return {
    ...m, js_kb: kb(bytes.script), img_kb: kb(bytes.image), font_kb: kb(bytes.font), css_kb: kb(bytes.stylesheet),
    html_kb: kb(bytes.document), total_kb: kb(Object.values(bytes).reduce((a, b) => a + b, 0)), requests,
    load_fired: loaded, wall_ms: Date.now() - started, font_files: fontFiles,
  }
}

const browser = await chromium.launch()
const report = []
for (const url of urls) {
  const runs = []
  for (let i = 0; i < RUNS; i++) runs.push(await once(browser, url))
  const row = { url, runs: runs.length }
  for (const k of Object.keys(runs[0])) {
    const vals = runs.map((r) => r[k])
    row[k] = typeof vals[0] === 'number' ? median(vals) : vals[vals.length - 1]
  }
  report.push(row)
  console.log(JSON.stringify(row))
}
await browser.close()
writeFileSync(out, JSON.stringify({ profile: 'Slow 4G (150ms, 1.6Mbps/750kbps) + 4x CPU, 390x844 @2.625x, cache off', report }, null, 1))

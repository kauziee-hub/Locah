#!/usr/bin/env node
// Inspect previous real generations across business models, through today's
// renderer. Read-only local API; no paid AI, publishing or customer actions.
// node tools/site-lab/business-matrix.mjs [output-directory] [--render-only | --fresh] [--recheck-failures]
import { chromium } from 'playwright'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

const out = path.resolve(process.argv[2] || '.site-lab/compare/business-matrix')
const lab = path.resolve(process.env.LOCAH_SITE_LAB_DIR || '.site-lab')
const api = 'http://localhost:8020'
const base = 'http://localhost:3005'
const manifestPath = path.join(out, 'manifest.json')
const recheck = process.argv.includes('--recheck-failures')
const reportPath = path.join(out, recheck ? 'recheck.json' : 'report.json')
await mkdir(out, { recursive: true })
let manifest = []
if (process.argv.includes('--fresh')) {
  const source = path.join(lab, 'fresh-matrix')
  const index = JSON.parse(await readFile(path.join(source, 'index.json'), 'utf8'))
  for (const site of index.sites) {
    const key = `fresh-${site.key}`
    const entry = {
      key,
      name: site.name,
      source: 'current composer, scripted interview, no photos or paid AI',
      pages: [],
    }
    for (const slug of site.pages) {
      const suffix = slug === 'home' ? '' : `~${slug}`
      const file = `${key}${suffix}.json`
      await writeFile(
        path.join(lab, file),
        await readFile(path.join(source, `${site.key}${suffix}.json`))
      )
      entry.pages.push({ slug, file })
    }
    manifest.push(entry)
  }
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2))
} else if (!process.argv.includes('--render-only') && !recheck) {
  const source = path.resolve('certify-out/run9/sites')
  for (const scenario of await readdir(source)) {
    const journey = JSON.parse(await readFile(path.join(source, scenario, 'journey.json'), 'utf8'))
    const slug = new URL(journey.public_url).pathname.split('/').filter(Boolean)[0]
    assert(/^[a-z0-9-]+$/.test(slug))
    const key = `audit-${scenario.replace('--normal', '')}`
    const homeResponse = await fetch(`${api}/v1/public/websites/${slug}`)
    assert(homeResponse.ok, `${scenario}: public API ${homeResponse.status}`)
    const home = (await homeResponse.json()).data
    const pages = new Set([
      'home',
      ...home.navigation
        .map((n) => n.path)
        .filter((p) => /^\/[a-z0-9-]+$/.test(p))
        .map((p) => p.slice(1)),
    ])
    const entry = {
      key,
      scenario,
      slug,
      name: home.business.display_name,
      source: 'previous real generation',
      pages: [],
    }
    for (const page of pages) {
      const response =
        page === 'home' ? null : await fetch(`${api}/v1/public/websites/${slug}/pages/${page}`)
      if (response && !response.ok) {
        entry.pages.push({
          slug: page,
          status: response.status,
          skipped: 'not a structured public page',
        })
        continue
      }
      const data = page === 'home' ? home : (await response.json()).data
      const filename = `${key}${page === 'home' ? '' : `~${page}`}.json`
      await writeFile(path.join(lab, filename), JSON.stringify(data))
      entry.pages.push({ slug: page, file: filename })
    }
    manifest.push(entry)
    console.log(`captured ${scenario}: ${entry.pages.filter((p) => p.file).length} pages`)
  }
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2))
} else {
  manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
}
const browser = await chromium.launch({ headless: true })
const report = { source: manifest[0]?.source, results: [] }
let work = manifest.flatMap((site) =>
  site.pages
    .filter((p) => p.file)
    .flatMap((page) => [390, 900, 1440].map((width) => ({ site, page, width })))
)
const failed = (r) =>
  r.error ||
  r.status !== 200 ||
  r.overflow ||
  r.headings !== 1 ||
  r.brokenImages.length ||
  r.overlays.length ||
  r.clippedCaptions ||
  r.floatingDock ||
  r.errors.length
if (recheck) {
  const previous = JSON.parse(await readFile(path.join(out, 'report.json'), 'utf8'))
  const keys = new Set(previous.results.filter(failed).map((r) => `${r.key}/${r.page}/${r.width}`))
  work = work.filter(({ site, page, width }) => keys.has(`${site.key}/${page.slug}/${width}`))
}
let next = 0
try {
  await Promise.all(
    Array.from({ length: 3 }, async () => {
      for (;;) {
        const job = work[next++]
        if (!job) break
        const { site, page: record, width } = job
        const page = await browser.newPage({
          viewport: { width, height: width < 600 ? 844 : 1000 },
          reducedMotion: 'reduce',
        })
        const errors = []
        page.on('pageerror', (e) => errors.push(e.message))
        // The lab rewrites the business slug. Read its live public catalogue
        // from the original local test tenant, so we also exercise live items.
        await page.route('**/v1/public/websites/**', async (route) => {
          try {
            const request = route.request()
            if (request.method() !== 'GET') {
              await route.abort()
              return
            }
            const source = new URL(request.url())
            const needle = `/v1/public/websites/site-lab/${site.key}`
            if (!source.pathname.startsWith(needle) || !site.slug) {
              await route.abort()
              return
            }
            const target = `${api}${source.pathname.replace(needle, `/v1/public/websites/${site.slug}`)}${source.search}`
            const result = await route.fetch({ url: target })
            await route.fulfill({ response: result })
          } catch (error) {
            if (!page.isClosed()) {
              errors.push(`public read: ${String(error).slice(0, 200)}`)
              await route.abort().catch(() => {})
            }
          }
        })
        const url = `${base}/site-lab/${site.key}${record.slug === 'home' ? '' : `/${record.slug}`}`
        try {
          const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 })
          await page.evaluate(() => document.fonts.ready)
          const checks = await page.evaluate(() => {
            const box = (el) => el?.getBoundingClientRect()
            const overlaps = [...document.querySelectorAll('.fx-bento__cell')].flatMap((card) => {
              const media = box(card.querySelector('.fx-bento__media'))
              const copy = box(card.querySelector('.fx-bento__copy'))
              return media && copy && copy.top < media.bottom - 1
                ? [card.textContent.trim().slice(0, 80)]
                : []
            })
            const clipped = [
              ...document.querySelectorAll('.fx-bento__copy, .fx-bento__foot'),
            ].filter(
              (el) => el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2
            )
            return {
              overflow: document.documentElement.scrollWidth > innerWidth + 1,
              headings: document.querySelectorAll('h1').length,
              brokenImages: [...document.images]
                .filter((i) => i.complete && !i.naturalWidth)
                .map((i) => i.currentSrc),
              overlays: overlaps,
              clippedCaptions: clipped.length,
              floatingDock: document.querySelectorAll('.fx-dock').length,
              typeLayout: document.querySelector('.fx-typecover')?.dataset.typeLayout || null,
              hero: (() => {
                const hero = document.querySelector('.ls-hero')
                if (!hero) return null
                const action = hero.querySelector('.ls-hero__cta a')?.getBoundingClientRect()
                return {
                  class: hero.className,
                  actionVisible: Boolean(action && action.top >= 0 && action.bottom <= innerHeight),
                }
              })(),
              catalogue: document.querySelectorAll(
                '.fx-bento__cell, .ls-pricelist__row, .fx-menu__item, .ls-product-grid > li'
              ).length,
              text: document.querySelector('main')?.innerText.slice(0, 320),
            }
          })
          const filename = `${site.key}-${record.slug}-${width}.png`
          await page.screenshot({ path: path.join(out, filename), fullPage: true })
          if (record.slug === 'home' && width === 1440) {
            await page.screenshot({ path: path.join(out, `${site.key}-first-screen.png`) })
          }
          if (
            record.slug === 'home' &&
            width === 900 &&
            (await page.locator('.fx-bento').count())
          ) {
            await page
              .locator('.fx-bento')
              .first()
              .screenshot({ path: path.join(out, `${site.key}-catalogue.png`) })
          }
          report.results.push({
            key: site.key,
            name: site.name,
            page: record.slug,
            width,
            status: response.status(),
            filename,
            ...checks,
            errors,
          })
        } catch (error) {
          report.results.push({
            key: site.key,
            page: record.slug,
            width,
            error: String(error),
            errors,
          })
        } finally {
          await page.unrouteAll({ behavior: 'wait' })
          await page.close()
        }
        await writeFile(reportPath, JSON.stringify(report, null, 2))
        if (report.results.length % 12 === 0)
          console.log(`rendered ${report.results.length}/${work.length}`)
      }
    })
  )
} finally {
  await browser.close()
}
await writeFile(reportPath, JSON.stringify(report, null, 2))
const failures = report.results.filter(failed)
console.log(
  JSON.stringify(
    {
      businesses: new Set(work.map((w) => w.site.key)).size,
      pagesAndSizes: report.results.length,
      failures: failures.map(
        ({
          key,
          page,
          width,
          error,
          overflow,
          brokenImages,
          errors,
          clippedCaptions,
          headings,
        }) => ({
          key,
          page,
          width,
          error,
          overflow,
          brokenImages,
          errors,
          clippedCaptions,
          headings,
        })
      ),
    },
    null,
    2
  )
)
if (failures.length) process.exitCode = 1

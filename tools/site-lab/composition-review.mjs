#!/usr/bin/env node
// Local-only render evidence. Requires saved premium_lab fixtures and the site
// lab on :3005. Never generates a site, spends AI credits or touches a database.
// node tools/site-lab/composition-review.mjs [output-directory] [fixture ...]
import { chromium } from 'playwright'
import { mkdir, readFile, writeFile, unlink } from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

const root = process.cwd()
const out = path.resolve(process.argv[2] || '.site-lab/compare/composition-review')
const lab = path.resolve(process.env.LOCAH_SITE_LAB_DIR || '.site-lab')
const base = process.env.SITE_LAB_URL || 'http://127.0.0.1:3005'
assert(['127.0.0.1', 'localhost', '[::1]'].includes(new URL(base).hostname), 'Use a local lab only')
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const report = {
  source: 'Saved lab fixtures; no live model evaluation',
  pages: [],
  interactions: [],
}
// Explicit synthetic rendering fixture, removed afterwards. It is not an owner
// journey or a claim that an API accepted an order.
const synthetic = path.join(lab, 'composition-check.json')
try {
  for (const key of process.argv.slice(3).length
    ? process.argv.slice(3)
    : ['lab-cleaver', 'lab-ishant', 'lab-crumb']) {
    const fixture = JSON.parse(await readFile(path.join(lab, `${key}.json`), 'utf8'))
    const range = fixture.navigation.find((n) => /shop|menu/.test(n.path || n.href || ''))
    const rangeSlug = (range?.path || range?.href || '').split('/').filter(Boolean).at(-1) || 'shop'
    for (const pageSlug of ['', rangeSlug, 'about']) {
      for (const width of [390, 768, 1440]) {
        const page = await browser.newPage({
          viewport: { width, height: width < 600 ? 844 : 1000 },
          reducedMotion: 'reduce',
        })
        const errors = []
        page.on('pageerror', (e) => errors.push(e.message))
        const response = await page.goto(
          `${base}/site-lab/${key}${pageSlug ? `/${pageSlug}` : ''}`,
          { waitUntil: 'networkidle' }
        )
        assert.equal(response.status(), 200)
        await page.evaluate(() => document.fonts.ready)
        const metrics = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          brokenImages: [...document.images]
            .filter((i) => i.complete && !i.naturalWidth)
            .map((i) => i.currentSrc),
          illustrativePlaceholders: [...document.images].filter((i) =>
            i.src.startsWith('data:image/svg')
          ).length,
          headings: document.querySelectorAll('h1').length,
          opening: document.querySelector('[data-locah-site]')?.dataset.pageOpening,
          chapter: document.querySelector('[data-locah-site]')?.dataset.chapterLayout,
          firstScreen: (() => {
            const stage = document.querySelector('.fx-stage[data-copy-density="long"]')
            if (!stage) return null
            const image = stage.querySelector('img')?.getBoundingClientRect()
            const action = stage.querySelector('.ls-hero__cta a')?.getBoundingClientRect()
            return {
              photoHeight: image
                ? Math.max(0, Math.min(image.bottom, innerHeight) - Math.max(image.top, 0))
                : 0,
              actionVisible: Boolean(action && action.top >= 0 && action.bottom <= innerHeight),
            }
          })(),
        }))
        if (metrics.firstScreen) {
          assert(
            metrics.firstScreen.photoHeight >= 100,
            'Long-copy stage must show its product in the first screen'
          )
          assert(
            metrics.firstScreen.actionVisible,
            'Long-copy stage must expose its useful action without scrolling'
          )
        }
        const file = `${key}-${pageSlug || 'home'}-${width}.png`
        await page.screenshot({ path: path.join(out, file), fullPage: true })
        report.pages.push({ key, page: pageSlug || 'home', width, file, ...metrics, errors })
        await page.close()
      }
    }
  }
  const fixture = JSON.parse(await readFile(path.join(lab, 'lab-cleaver~shop.json'), 'utf8'))
  fixture.business.display_name = 'Synthetic catalogue check'
  fixture.capabilities = { catalogue: true, order: true }
  fixture.theme.composition = { opening: 'poster', chapters: 'index', range_layout: 'compact_list' }
  fixture.page.sections = fixture.page.sections.filter((s) =>
    ['hero', 'product_showcase'].includes(s.section_type_id)
  )
  const range = fixture.page.sections.find((s) => s.section_type_id === 'product_showcase')
  range.layout_variant = 'compact_list'
  for (const section of fixture.page.sections) section.assets = {}
  fixture.page.sections.push({
    id: 'synthetic-story',
    section_type_id: 'media_text',
    layout_variant: 'sticky',
    content: {
      items: [{ title: 'Synthetic story', body: 'A saved narrative whose photo is unavailable.' }],
    },
    assets: {},
  })
  await writeFile(synthetic, JSON.stringify(fixture))
  const page = await browser.newPage({
    viewport: { width: 390, height: 844 },
    reducedMotion: 'reduce',
  })
  const rows = [
    {
      id: 'one',
      title: 'Synthetic counter item',
      category: 'Counter',
      price_amount: 260,
      currency: 'INR',
    },
    {
      id: 'two',
      title: 'Synthetic sold out item',
      category: 'Counter',
      price_amount: 100,
      currency: 'INR',
      availability: 'out_of_stock',
    },
    {
      id: 'three',
      title: 'Synthetic pack item',
      category: 'Counter',
      price_amount: 130,
      currency: 'INR',
      packs: [{ label: '500 g', price_amount: 130 }],
    },
  ]
  await page.route('**/v1/public/websites/**/offerings', (route) =>
    route.fulfill({ json: { data: { offerings: rows } } })
  )
  await page.goto(`${base}/site-lab/composition-check`, { waitUntil: 'networkidle' })
  assert.equal(
    await page.locator('.fx-mtext__pin').count(),
    0,
    'Missing story photos must not leave an empty sticky panel'
  )
  await page.getByRole('button', { name: '+ Add', exact: true }).click()
  await page.getByRole('status').filter({ hasText: 'Added Synthetic counter item' }).waitFor()
  assert.match(
    await page.locator('.ls-pricelist__row').filter({ hasText: rows[1].title }).innerText(),
    /Out of stock/
  )
  assert.equal(
    await page
      .locator('.ls-pricelist__row')
      .filter({ hasText: rows[1].title })
      .getByRole('button')
      .count(),
    0
  )
  await page.getByRole('button', { name: 'Choose', exact: true }).click()
  await page.getByRole('dialog').waitFor()
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  const basket = await page.evaluate(() =>
    Object.entries(localStorage).filter(([key]) => key.includes('cart'))
  )
  assert(basket.some(([, value]) => value.includes('Synthetic counter item')))
  await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }))
  await page.screenshot({ path: path.join(out, 'no-photos-390.png'), fullPage: true })
  report.interactions.push(
    'compact: add to basket, sold-out refusal, pack chooser opens and closes; synthetic public-read response'
  )
  await page.close()

  // The same live controls must survive the photographed layout. These are
  // synthetic offerings served only in this browser; no order is submitted.
  range.layout_variant = 'bento'
  fixture.theme.composition.range_layout = 'bento'
  await writeFile(synthetic, JSON.stringify(fixture))
  const photoFixture = JSON.parse(await readFile(path.join(lab, 'lab-cleaver.json'), 'utf8'))
  const photos = Object.values(
    photoFixture.page.sections.find((s) => s.section_type_id === 'product_showcase').assets
  ).filter((a) => a.url)
  for (const width of [390, 900, 1440]) {
    const livePage = await browser.newPage({
      viewport: { width, height: width < 600 ? 844 : 1000 },
      reducedMotion: 'reduce',
    })
    await livePage.route('**/v1/public/websites/**/offerings', (route) =>
      route.fulfill({
        json: {
          data: {
            offerings: rows.map((row, n) => ({
              ...row,
              image_url: photos[n % photos.length].url,
              description:
                'A deliberately long description to exercise wrapping beside a price and a real action.',
            })),
          },
        },
      })
    )
    await livePage.goto(`${base}/site-lab/composition-check`, { waitUntil: 'networkidle' })
    await livePage.getByRole('button', { name: '+ Add', exact: true }).click()
    await livePage.getByRole('status').filter({ hasText: 'Added Synthetic counter item' }).waitFor()
    const sold = livePage.locator('.fx-bento__cell').filter({ hasText: rows[1].title })
    assert.match(await sold.innerText(), /Out of stock/)
    assert.equal(await sold.getByRole('button').count(), 0)
    await livePage.getByRole('button', { name: 'Choose', exact: true }).click()
    await livePage.getByRole('dialog').waitFor()
    await livePage.getByRole('button', { name: 'Close', exact: true }).click()
    const layout = await livePage.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth + 1,
      overlaps: [...document.querySelectorAll('.fx-bento__cell')].filter(
        (el) =>
          el.querySelector('.fx-bento__copy').getBoundingClientRect().top <
          el.querySelector('.fx-bento__media').getBoundingClientRect().bottom - 1
      ).length,
      clipped: [...document.querySelectorAll('.fx-bento__copy, .fx-bento__foot')].filter(
        (el) => el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2
      ).length,
    }))
    assert(!layout.overflow && !layout.overlaps && !layout.clipped, JSON.stringify(layout))
    await livePage.screenshot({ path: path.join(out, `bento-live-${width}.png`), fullPage: true })
    report.interactions.push(
      `bento ${width}px: Add, sold-out, chooser; photo/caption separation and wrapping passed`
    )
    await livePage.close()
  }

  // Uneven counts used to reserve empty cells or squeeze the last card.
  // Exercise those grid shapes with long captions at the desktop breakpoint.
  fixture.capabilities = { catalogue: false, order: false }
  range.content.categories = []
  range.content.filters = []
  for (const count of [5, 7, 8, 10]) {
    range.content.items = Array.from({ length: count }, (_, n) => ({
      name: `Synthetic range item ${n + 1}`,
      price: 'From ₹12,500 per pack',
      description:
        n % 2
          ? 'Short description.'
          : 'A longer description that needs several lines without forcing its price or action across the photograph.',
    }))
    range.assets = Object.fromEntries(
      range.content.items.map((_, n) => [`items.${n}`, photos[n % photos.length]])
    )
    await writeFile(synthetic, JSON.stringify(fixture))
    const gridPage = await browser.newPage({
      viewport: { width: 900, height: 1000 },
      reducedMotion: 'reduce',
    })
    await gridPage.goto(`${base}/site-lab/composition-check`, { waitUntil: 'networkidle' })
    assert.equal(await gridPage.locator('.fx-bento__cell').count(), count)
    const clipped = await gridPage.evaluate(() =>
      [...document.querySelectorAll('.fx-bento__copy, .fx-bento__foot')].some(
        (el) => el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2
      )
    )
    assert(!clipped, `Clipped caption at count ${count}`)
    await gridPage.screenshot({ path: path.join(out, `bento-count-${count}.png`), fullPage: true })
    report.interactions.push(`bento ${count} items at 900px: all items present, captions fit`)
    await gridPage.close()
  }
} finally {
  await browser.close()
  await unlink(synthetic).catch(() => {})
  await writeFile(path.join(out, 'report.json'), JSON.stringify(report, null, 2))
}
const failures = report.pages.filter(
  (p) => p.overflow || p.errors.length || p.brokenImages.length || p.headings !== 1
)
console.log(
  JSON.stringify(
    { pages: report.pages.length, failures, interactions: report.interactions },
    null,
    2
  )
)
if (failures.length) process.exitCode = 1

// Self-hosted fonts (tools/fonts/build_fonts.py): a build never fetches a font,
// a page never downloads a face for a script it does not show.
//
//   node --test src/fonts/fonts.test.mjs      (from apps/web)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '..')
const read = (rel) => readFileSync(join(src, rel), 'utf8')

function* sources(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) yield* sources(path)
    else if (/\.(tsx?|mjs|js)$/.test(name)) yield path
  }
}

test('no page loads a font from Google at build time', () => {
  const offenders = [...sources(src)].filter((file) => /from ['"]next\/font\/google['"]/.test(readFileSync(file, 'utf8')))
  assert.deepEqual(offenders, [])
})

test('every self-hosted face points at a file that is in the repository', () => {
  for (const rel of ['components/website/site-fonts.ts', 'app/layout.tsx']) {
    const file = join(src, rel)
    const paths = [...readFileSync(file, 'utf8').matchAll(/path: '([^']+\.woff2)'/g)].map((m) => m[1])
    assert.ok(paths.length > 0, rel)
    for (const p of paths) assert.ok(existsSync(resolve(dirname(file), p)), `${rel}: ${p}`)
  }
})

test('the rupee sign is drawn by the Latin cut, never by an Indic face', () => {
  const fonts = read('components/website/site-fonts.ts')
  const ranges = [...fonts.matchAll(/variable: '(--font-site-[a-z]+)'/g)].map((m) => m[1])
  const blocks = fonts.split('export const ').slice(1)
  assert.equal(blocks.length, ranges.length)
  for (const block of blocks) {
    const range = /prop: 'unicode-range', value: '([^']+)'/.exec(block)?.[1] || ''
    const indic = /--font-site-(tamil|devanagari)/.test(block)
    assert.ok(range, block.slice(0, 40))
    assert.equal(range.includes('U+20B9'), !indic, block.slice(0, 40))
  }
})

test('an English page carries neither Indic face; each Indic face rides only on its own language', () => {
  const fonts = read('components/website/site-fonts.ts')
  const latin = /const latinFaces = \[([\s\S]*?)\]/.exec(fonts)?.[1] || ''
  assert.ok(latin.includes('fraunces'))
  assert.ok(!/noto/i.test(latin))
  assert.match(fonts, /if \(lang === 'ta'\) return `\$\{latinFaces\} \$\{notoTamil\.variable\}`/)
  assert.match(fonts, /if \(lang === 'hi'\) return `\$\{latinFaces\} \$\{notoDevanagari\.variable\}`/)
  for (const caller of ['components/website/WebsitePageView.tsx', 'components/website/SiteFrame.tsx']) {
    assert.match(read(caller), /siteFontVariables\(lang\)/, caller)
  }
})

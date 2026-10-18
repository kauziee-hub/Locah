#!/usr/bin/env node
// Motion-on screenshots of a tenant page: what a visitor with motion sees.
//
//   node tools/site-lab/motion-shots.mjs <url> <out_dir> [--width 1440] [--height 900]
//
// The lab's other shots force reduced motion (the still state). This one does
// not: it waits for the motion runtime and any WebGL moment, moves the pointer
// across the cover, then scrolls the page in steps, shooting each state —
// 01-arrive, 02-pointer, 03-scroll-25 … — and prints what it found: the site's
// signature moments, live canvases, the runtime's [gl] notes and console
// errors. Headless Chrome renders frames even when no window is visible
// (the desktop browser pane does not while it is hidden).

import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { launchChrome, sleep } from '../certify/cdp2.mjs'

const argv = process.argv.slice(2)
const flag = (name, fallback) => {
  const i = argv.indexOf(`--${name}`)
  return i >= 0 ? Number(argv[i + 1]) : fallback
}
const [url, outDir] = argv.filter((a, i) => !a.startsWith('--') && !argv[i - 1]?.startsWith('--'))
if (!url || !outDir) {
  console.error('usage: node tools/site-lab/motion-shots.mjs <url> <out_dir> [--width 1440] [--height 900]')
  process.exit(2)
}
const width = flag('width', 1440)
const height = flag('height', 900)
mkdirSync(outDir, { recursive: true })

const chrome = await launchChrome()
const { send, on } = chrome
const notes = []
const errors = []
on('Runtime.consoleAPICalled', (e) => {
  const text = (e.args || []).map((a) => a.value ?? a.description ?? '').join(' ')
  if (text.includes('[gl]')) notes.push(text)
  if (e.type === 'error') errors.push(text.slice(0, 300))
})
on('Runtime.exceptionThrown', (e) => errors.push(String(e.exceptionDetails?.exception?.description || e.exceptionDetails?.text).slice(0, 300)))

const evaluate = async (expression) =>
  (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value
let n = 0
const shot = async (label) => {
  const res = await send('Page.captureScreenshot', { format: 'jpeg', quality: 82 })
  const file = path.join(outDir, `${String(++n).padStart(2, '0')}-${label}.jpg`)
  writeFileSync(file, Buffer.from(res.data, 'base64'))
  return file
}
const mouse = (x, y) => send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, pointerType: 'mouse' })

try {
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 768 })
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] })
  await send('Page.navigate', { url })
  await sleep(6000)
  await shot('arrive')
  // Across the cover, slowly — a pointer effect needs a moving pointer.
  for (let i = 0; i <= 12; i++) {
    await mouse(width * (0.35 + i * 0.03), height * (0.42 + Math.sin(i / 2) * 0.08))
    await sleep(60)
  }
  await sleep(250)
  await shot('pointer')
  const total = await evaluate('document.documentElement.scrollHeight')
  for (const at of [0.12, 0.25, 0.4, 0.6, 0.8]) {
    const target = Math.round((total - height) * at)
    // In steps, so scroll velocity effects see a real scroll.
    await evaluate(`(async () => { const from = scrollY, to = ${target}; for (let i = 1; i <= 12; i++) { scrollTo(0, from + (to - from) * i / 12); await new Promise(r => setTimeout(r, 30)) } })()`)
    await sleep(900)
    await shot(`scroll-${Math.round(at * 100)}`)
  }
  const found = await evaluate(`(() => {
    const root = document.querySelector('[data-locah-site]') || document.body
    return {
      signature: root.dataset.signature || '', flourish: root.dataset.flourish || '', fx: root.getAttribute('data-fx'),
      ground: root.getAttribute('data-ground-now'), typeLive: root.hasAttribute('data-vt-live'),
      canvases: [...document.querySelectorAll('canvas')].map((c) => c.className + ' ' + Math.round(c.getBoundingClientRect().width) + 'x' + Math.round(c.getBoundingClientRect().height)),
      dock: document.querySelector('.fx-dock')?.hasAttribute('data-on') ?? null,
      pictured: { rail: document.querySelectorAll('.fx-rail__card .fx-rail__media > img').length, bento: document.querySelectorAll('.fx-bento__cell--pic > img').length },
    }
  })()`)
  const report = { url, width, height, ...found, gl_notes: notes, console_errors: errors, shots: n }
  writeFileSync(path.join(outDir, 'motion.json'), JSON.stringify(report, null, 1))
  console.log(JSON.stringify(report, null, 1))
} finally {
  await chrome.close()
}

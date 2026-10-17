// A second, lower-level Chrome DevTools Protocol driver for the certification
// renderer (tools/certify/render.mjs).
//
// tools/acceptance/cdp.mjs is tuned for driving the Workspace UI (type, click,
// wait for text). The certifier needs other things from the protocol: event
// payloads (document status, console and log errors, failed requests), every
// call bounded by a timeout, a free DevTools port chosen by Chrome itself, and
// real keyboard / mouse input. Nothing here downloads a browser: it drives the
// Chrome already installed, headless.

import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const CHROME =
  process.env.CHROME_PATH ||
  ({
    win32: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    darwin: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  }[process.platform] ?? 'google-chrome')

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * Start a headless Chrome and attach to its first page.
 * Returns { send, on, waitFor, close, version, userAgent }.
 */
export async function launchChrome({ extraArgs = [] } = {}) {
  const userDir = mkdtempSync(path.join(process.env.TEMP || os.tmpdir(), 'locah-certify-'))
  const proc = spawn(
    CHROME,
    [
      '--headless=new',
      '--disable-gpu',
      '--hide-scrollbars',
      '--remote-debugging-port=0',
      `--user-data-dir=${userDir}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-extensions',
      '--disable-sync',
      '--mute-audio',
      '--password-store=basic',
      '--force-color-profile=srgb',
      // A headless tab is never "visible"; without these, timers and
      // requestAnimationFrame are throttled and motion code stalls.
      '--disable-background-timer-throttling',
      '--disable-renderer-backgrounding',
      '--disable-backgrounding-occluded-windows',
      '--disable-features=Translate,MediaRouter,OptimizationHints',
      ...(process.env.CHROME_NO_SANDBOX ? ['--no-sandbox'] : []),
      ...extraArgs,
      'about:blank',
    ],
    { stdio: 'ignore' }
  )
  let exited = false
  proc.on('exit', () => {
    exited = true
  })

  // Chrome picks a free port and writes it to <user-data-dir>/DevToolsActivePort.
  const portFile = path.join(userDir, 'DevToolsActivePort')
  let port = 0
  for (let i = 0; i < 200 && !port && !exited; i++) {
    if (existsSync(portFile)) {
      const first = readFileSync(portFile, 'utf8').split(/\r?\n/)[0]
      port = Number(first) || 0
    }
    if (!port) await sleep(200)
  }
  if (!port) {
    killTree(proc)
    throw new Error(`Chrome did not start (${CHROME}); no DevToolsActivePort after 40 s`)
  }

  let target
  for (let i = 0; i < 100 && !target; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
      target = list.find((t) => t.type === 'page')
    } catch {}
    if (!target) await sleep(200)
  }
  if (!target) {
    killTree(proc)
    throw new Error(`Chrome on port ${port} offered no page target`)
  }
  let version = {}
  try {
    version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()
  } catch {}

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('DevTools socket did not open within 15 s')), 15000)
    ws.addEventListener('open', () => {
      clearTimeout(timer)
      resolve()
    })
    ws.addEventListener('error', () => {
      clearTimeout(timer)
      reject(new Error('DevTools socket error'))
    })
  })

  let nextId = 0
  const pending = new Map()
  const listeners = new Map()
  let closed = false
  ws.addEventListener('message', (m) => {
    let msg
    try {
      msg = JSON.parse(typeof m.data === 'string' ? m.data : m.data.toString())
    } catch {
      return
    }
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject, timer, method } = pending.get(msg.id)
      pending.delete(msg.id)
      clearTimeout(timer)
      if (msg.error) reject(new Error(`${method}: ${msg.error.message}${msg.error.data ? ' — ' + msg.error.data : ''}`))
      else resolve(msg.result || {})
    } else if (msg.method) {
      const set = listeners.get(msg.method)
      if (set) for (const fn of [...set]) {
        try {
          fn(msg.params || {})
        } catch {}
      }
    }
  })
  ws.addEventListener('close', () => {
    closed = true
    for (const { reject, timer, method } of pending.values()) {
      clearTimeout(timer)
      reject(new Error(`${method}: DevTools socket closed`))
    }
    pending.clear()
  })

  /** One protocol call; never waits longer than `timeout` ms. */
  function send(method, params = {}, { timeout = 60000 } = {}) {
    if (closed) return Promise.reject(new Error(`${method}: DevTools socket closed`))
    return new Promise((resolve, reject) => {
      const id = ++nextId
      const timer = setTimeout(() => {
        pending.delete(id)
        reject(new Error(`${method}: no answer within ${timeout} ms`))
      }, timeout)
      pending.set(id, { resolve, reject, timer, method })
      ws.send(JSON.stringify({ id, method, params }))
    })
  }

  /** Subscribe to a protocol event; returns the unsubscribe function. */
  function on(method, fn) {
    if (!listeners.has(method)) listeners.set(method, new Set())
    listeners.get(method).add(fn)
    return () => listeners.get(method)?.delete(fn)
  }

  /** Resolve with the first event `method` whose params satisfy `pred`. */
  function waitFor(method, pred = () => true, timeout = 60000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        off()
        reject(new Error(`timed out after ${timeout} ms waiting for ${method}`))
      }, timeout)
      const off = on(method, (p) => {
        if (!pred(p)) return
        clearTimeout(timer)
        off()
        resolve(p)
      })
    })
  }

  async function close() {
    try {
      await send('Browser.close', {}, { timeout: 5000 })
    } catch {}
    try {
      ws.close()
    } catch {}
    await sleep(300)
    if (!exited) killTree(proc)
    await sleep(300)
    try {
      rmSync(userDir, { recursive: true, force: true, maxRetries: 3 })
    } catch {}
  }

  return { send, on, waitFor, close, version: version.Browser || '', userAgent: version['User-Agent'] || '' }
}

function killTree(proc) {
  // On Windows killing chrome.exe leaves its renderers running; end the tree.
  if (process.platform === 'win32') spawn('taskkill', ['/pid', String(proc.pid), '/T', '/F'], { stdio: 'ignore' })
  else proc.kill('SIGKILL')
}

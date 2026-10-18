/**
 * The door every WebGL moment on a tenant site goes through.
 *
 * Statically imported by the small React mounts (GlLiving, useGlRibbon,
 * Dissolve), so it stays tiny: the renderers themselves (./living, ./ribbon,
 * ./dissolve) are fetched with a dynamic import() only once this says yes.
 *
 * WebGL is progressive enhancement over a real <img>. It runs only when:
 *   - the design asked for it: the site root's data-signature or
 *     data-flourish names the effect (the design DNA's signature traits);
 *   - motion is on for this visitor (data-fx='on': not reduced motion, not an
 *     owner who switched motion off) and stays on;
 *   - the device can afford it: WebGL2, deviceMemory >= 4 when the browser
 *     says, not a data-saver connection;
 *   - and the page has fewer than two GL moments already — a page has one
 *     signature moment, at most a second, never a wall of canvases.
 */

export type GlEffect = 'living' | 'ribbon' | 'dissolve'

type Nav = Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } }

/** The site asked for this effect as its signature or its flourish. */
export function wants(root: HTMLElement, effect: GlEffect): boolean {
  return root.dataset.signature === effect || root.dataset.flourish === effect
}

/** Motion is on and the device is capable. Checked at mount, never assumed. */
export function gateOpen(root: HTMLElement): boolean {
  if (typeof window === 'undefined') return false
  if (root.getAttribute('data-fx') !== 'on' || root.dataset.motion === 'none') return false
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  const nav = navigator as Nav
  if (nav.connection?.saveData) return false
  if (typeof nav.deviceMemory === 'number' && nav.deviceMemory < 4) return false
  return typeof window.WebGL2RenderingContext === 'function'
}

/** At most two GL moments per page, first come first served (covers mount first). */
const MAX_LIVE = 2
const live = new Set<object>()

export function claim(token: object): boolean {
  if (live.has(token)) return true
  if (live.size >= MAX_LIVE) return false
  live.add(token)
  return true
}

export function release(token: object): void {
  live.delete(token)
}

/** Run after the page has settled: never on the critical path of first paint. */
export function whenIdle(fn: () => void): () => void {
  const w = window as Window & {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number
    cancelIdleCallback?: (id: number) => void
  }
  if (w.requestIdleCallback && w.cancelIdleCallback) {
    const id = w.requestIdleCallback(fn, { timeout: 1200 })
    return () => w.cancelIdleCallback?.(id)
  }
  const id = window.setTimeout(fn, 180)
  return () => window.clearTimeout(id)
}

/**
 * Mount one GL effect from a React effect: check the gate, claim a slot, wait
 * for idle, import the renderer, start it. Returns the cleanup for useEffect.
 * `start` resolves to the effect's own stop function, or null when it could
 * not run (no picture, a tainted image, a lost context) — the page then simply
 * keeps its <img>.
 */
export function mountGl(
  root: HTMLElement,
  effect: GlEffect | null,
  start: () => Promise<(() => void) | null>
): () => void {
  if ((effect && !wants(root, effect)) || !gateOpen(root)) {
    if (process.env.NODE_ENV !== 'production' && effect && wants(root, effect)) console.info('[gl] gate closed for', effect)
    return () => undefined
  }
  const token = {}
  if (!claim(token)) {
    if (process.env.NODE_ENV !== 'production') console.info('[gl] two GL moments already on this page:', effect)
    return () => undefined
  }
  let gone = false
  let stop: (() => void) | null = null
  const cancel = whenIdle(() => {
    start()
      .then((fn) => {
        if (gone) fn?.()
        else if (fn) stop = fn
        else release(token)
      })
      .catch((error) => {
        if (process.env.NODE_ENV !== 'production') console.info('[gl] failed:', effect, String(error))
        release(token)
      })
  })
  return () => {
    gone = true
    cancel()
    stop?.()
    stop = null
    release(token)
  }
}

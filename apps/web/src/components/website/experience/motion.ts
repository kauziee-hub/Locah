/**
 * The motion runtime for tenant websites.
 *
 * A published site is server-rendered and complete without this file: every
 * word, price and button is in the HTML. This runtime only adds movement, and
 * only when the visitor has not asked their device for reduced motion.
 *
 * It is deliberately small and owns no animation library. Effects are
 * declared in the markup as data attributes and executed by CSS; the runtime's
 * job is to feed CSS a handful of numbers:
 *
 *   data-reveal      added .is-in when the element first enters the viewport
 *   data-split       its words wrapped (.fx-w > .fx-wi, --wi index) so CSS can
 *                    raise them one by one, or light them as the visitor reads
 *   data-progress    --p: 0 → 1 while the element crosses the viewport
 *   data-scene       --p: 0 → 1 while a tall section's sticky stage is held
 *   data-pointer     --mx / --my: -1 → 1, the pointer over the element
 *   data-tilt        --rx / --ry: a card leaning toward the pointer
 *   data-magnetic    --tx / --ty: a button drawn a little toward the pointer
 *   data-count       a number the owner stated, counted up once in view
 *   data-rail        --track: how far a pinned horizontal rail travels
 *
 * and, on the site root, --scroll (page progress) and --mv (scroll velocity,
 * for marquees), plus data-scrolled / data-nav-away for the header.
 *
 * Smooth scrolling (Lenis, MIT) is used on desktop pointers only, never on
 * touch, and never for the calm motion language.
 */

type Lang = 'silk' | 'snap' | 'float' | 'calm'

export type MotionHandle = { stop: () => void }

const clamp = (v: number, lo = 0, hi = 1) => (v < lo ? lo : v > hi ? hi : v)

/** Wrap each word of an element's text in two spans, keeping inner markup. */
export function splitWords(el: HTMLElement): number {
  if (el.dataset.splitDone) return Number(el.style.getPropertyValue('--wn')) || 0
  // A heading is still read as one phrase, not word by word.
  const label = el.closest<HTMLElement>('h1, h2, h3, h4, h5, h6')
  if (label && !label.hasAttribute('aria-label')) {
    label.setAttribute('aria-label', (label.textContent || '').replace(/\s+/g, ' ').trim())
  }
  let index = 0
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n as Text)
  for (const node of nodes) {
    const text = node.nodeValue || ''
    if (!text.trim()) continue
    const frag = document.createDocumentFragment()
    for (const token of text.split(/(\s+)/)) {
      if (!token) continue
      if (/^\s+$/.test(token)) {
        frag.appendChild(document.createTextNode(token))
        continue
      }
      const outer = document.createElement('span')
      outer.className = 'fx-w'
      if (label) outer.setAttribute('aria-hidden', 'true')
      const inner = document.createElement('span')
      inner.className = 'fx-wi'
      inner.style.setProperty('--wi', String(index++))
      inner.textContent = token
      outer.appendChild(inner)
      frag.appendChild(outer)
    }
    node.parentNode?.replaceChild(frag, node)
  }
  el.style.setProperty('--wn', String(Math.max(index, 1)))
  el.dataset.splitDone = '1'
  return index
}

/** "1,200+" → [1200, "", "+", 0]; null when the text is not a single number. */
function parseCount(text: string): [number, string, string, number] | null {
  const m = /^(\D{0,3})(\d[\d,]*)(\.\d+)?(\D{0,6})$/.exec(text.trim())
  if (!m) return null
  const whole = Number(m[2].replace(/,/g, ''))
  const frac = m[3] ? Number(m[3]) : 0
  if (!Number.isFinite(whole) || whole > 10_000_000) return null
  return [whole + frac, m[1], m[4], m[3] ? m[3].length - 1 : 0]
}

function formatCount(value: number, decimals: number, grouped: boolean) {
  const fixed = value.toFixed(decimals)
  if (!grouped) return fixed
  const [i, f] = fixed.split('.')
  // Indian grouping when the owner wrote it that way (1,00,000) is rare on a
  // site; plain thousands separators are kept as written otherwise.
  const withCommas = Number(i).toLocaleString('en-IN')
  return f ? `${withCommas}.${f}` : withCommas
}

export function start(root: HTMLElement): MotionHandle {
  const lang = (root.dataset.motionLang as Lang) || 'silk'
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches
  const wide = window.matchMedia('(min-width: 900px)').matches
  const cleanups: Array<() => void> = []
  let vh = window.innerHeight
  let lastY = window.scrollY
  let velocity = 0
  let frame = 0
  let stopped = false

  root.setAttribute('data-fx-live', '')

  /* ------------------------------------------------------------ reveals */
  const revealIO = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const el = entry.target as HTMLElement
        el.classList.add('is-in')
        revealIO.unobserve(el)
      }
    },
    { rootMargin: '0px 0px -10% 0px', threshold: 0.01 }
  )
  // Keyboard users must never tab onto something still invisible.
  const onFocus = (event: FocusEvent) => {
    const target = event.target as HTMLElement | null
    target?.closest('[data-reveal], [data-reveal-group], [data-split]')?.classList.add('is-in')
  }
  root.addEventListener('focusin', onFocus)
  cleanups.push(() => root.removeEventListener('focusin', onFocus), () => revealIO.disconnect())

  /* ---------------------------------------------------- scroll progress */
  const active = new Set<HTMLElement>()
  const progressIO = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const el = entry.target as HTMLElement
        if (entry.isIntersecting) active.add(el)
        else active.delete(el)
      }
      schedule()
    },
    { rootMargin: '30% 0px 30% 0px' }
  )
  cleanups.push(() => progressIO.disconnect())

  /* ------------------------------------------------------------- binding */
  const REVEAL = '[data-reveal], [data-reveal-group], [data-split]'
  const PROGRESS = '[data-progress], [data-scene], [data-parallax], [data-rail]'
  const bound = new WeakSet<Element>()
  function bindAll(scope: ParentNode) {
    scope.querySelectorAll<HTMLElement>('[data-split]').forEach((el) => {
      if (!el.dataset.splitDone) splitWords(el)
    })
    scope.querySelectorAll<HTMLElement>('[data-reveal-group]').forEach((group) => {
      let i = 0
      for (const child of Array.from(group.children) as HTMLElement[]) {
        child.style.setProperty('--ri', String(Math.min(i++, 12)))
      }
    })
    scope.querySelectorAll<HTMLElement>(REVEAL).forEach((el) => {
      if (bound.has(el)) return
      bound.add(el)
      revealIO.observe(el)
    })
    scope.querySelectorAll<HTMLElement>(PROGRESS).forEach((el) => {
      if (bound.has(el) && !el.matches(REVEAL)) return
      progressIO.observe(el)
    })
  }
  bindAll(root)
  // Client components (a catalogue that loads live items, a filtered list)
  // render after this ran; what they add is bound as it arrives, so nothing
  // stays hidden waiting for an observer that never saw it.
  const mutations = new MutationObserver((records) => {
    let touched = false
    for (const record of records) {
      for (const node of Array.from(record.addedNodes)) {
        if (node.nodeType !== 1) continue
        const el = node as HTMLElement
        if (el.closest('.fx-w')) continue
        touched = true
        if (el.matches(REVEAL) || el.matches(PROGRESS)) bindAll(el.parentElement || root)
        else bindAll(el)
      }
    }
    if (touched) schedule()
  })
  mutations.observe(root, { childList: true, subtree: true })
  cleanups.push(() => mutations.disconnect())

  /* --------------------------------------------------------------- rails */
  const rails = Array.from(root.querySelectorAll<HTMLElement>('[data-rail]'))
  function measureRails() {
    const pin = window.matchMedia('(min-width: 900px)').matches
    for (const rail of rails) {
      const track = rail.querySelector<HTMLElement>('[data-rail-track]')
      if (!track || !pin) {
        rail.removeAttribute('data-rail-pinned')
        rail.style.removeProperty('--track')
        continue
      }
      const travel = Math.max(0, track.scrollWidth - track.clientWidth)
      if (travel < 40) {
        rail.removeAttribute('data-rail-pinned')
        continue
      }
      rail.setAttribute('data-rail-pinned', '')
      rail.style.setProperty('--track', String(travel))
    }
  }
  measureRails()

  /* ---------------------------------------------------------------- loop */
  function update() {
    frame = 0
    if (stopped) return
    const y = window.scrollY
    velocity = velocity * 0.82 + (y - lastY) * 0.18
    lastY = y
    const doc = document.documentElement
    const max = Math.max(1, doc.scrollHeight - vh)
    root.style.setProperty('--scroll', (y / max).toFixed(4))
    root.style.setProperty('--mv', clamp(velocity / 40, -1, 1).toFixed(3))
    root.toggleAttribute('data-scrolled', y > 24)
    for (const el of active) {
      const rect = el.getBoundingClientRect()
      let p: number
      if (el.hasAttribute('data-scene') || el.hasAttribute('data-rail-pinned')) {
        const span = rect.height - vh
        p = span > 0 ? clamp(-rect.top / span) : clamp(1 - rect.top / vh)
        // Copy that arrives late in a scene can be pressed once it is there.
        el.toggleAttribute('data-late', p > 0.5)
      } else {
        p = clamp(1 - (rect.top + rect.height) / (vh + rect.height))
      }
      el.style.setProperty('--p', p.toFixed(4))
    }
    if (Math.abs(velocity) > 0.05) schedule()
  }
  function schedule() {
    if (!frame && !stopped) frame = window.requestAnimationFrame(update)
  }

  /* -------------------------------------------- header: away on the way down */
  let navY = window.scrollY
  function navWatch() {
    const y = window.scrollY
    if (Math.abs(y - navY) < 8) return
    root.toggleAttribute('data-nav-away', y > navY && y > vh * 0.6)
    navY = y
  }

  const onScroll = () => {
    navWatch()
    schedule()
  }
  const onResize = () => {
    vh = window.innerHeight
    measureRails()
    schedule()
  }
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onResize)
  // Pictures that arrive late change how far a rail travels.
  if (document.readyState !== 'complete') window.addEventListener('load', onResize, { once: true })
  cleanups.push(
    () => window.removeEventListener('scroll', onScroll),
    () => window.removeEventListener('resize', onResize),
    () => window.removeEventListener('load', onResize),
    () => frame && window.cancelAnimationFrame(frame)
  )

  /* ------------------------------------------------------------- counters */
  const countIO = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const el = entry.target as HTMLElement
        countIO.unobserve(el)
        const parsed = parseCount(el.textContent || '')
        if (!parsed) continue
        const [target, prefix, suffix, decimals] = parsed
        const grouped = /,/.test(el.textContent || '')
        const original = el.textContent
        const t0 = performance.now()
        const duration = lang === 'snap' ? 900 : 1400
        const tick = (now: number) => {
          if (stopped) {
            el.textContent = original
            return
          }
          const k = clamp((now - t0) / duration)
          const eased = 1 - Math.pow(1 - k, 3)
          el.textContent = `${prefix}${formatCount(target * eased, decimals, grouped)}${suffix}`
          if (k < 1) window.requestAnimationFrame(tick)
          else el.textContent = original
        }
        window.requestAnimationFrame(tick)
      }
    },
    { threshold: 0.6 }
  )
  root.querySelectorAll<HTMLElement>('[data-count]').forEach((el) => countIO.observe(el))
  cleanups.push(() => countIO.disconnect())

  /* -------------------------------------------------------------- pointer */
  if (finePointer) {
    // One delegated listener: cards and buttons added later lean too.
    const lean = lang === 'calm' ? 3 : lang === 'snap' ? 9 : 7
    const kinds = [
      {
        selector: '[data-pointer]',
        set: (el: HTMLElement, x: number, y: number) => {
          el.style.setProperty('--mx', x.toFixed(3))
          el.style.setProperty('--my', y.toFixed(3))
        },
        reset: (el: HTMLElement) => {
          el.style.setProperty('--mx', '0')
          el.style.setProperty('--my', '0')
        },
      },
      {
        selector: '[data-tilt]',
        set: (el: HTMLElement, x: number, y: number) => {
          el.style.setProperty('--rx', `${(-y * lean).toFixed(2)}deg`)
          el.style.setProperty('--ry', `${(x * lean).toFixed(2)}deg`)
          el.style.setProperty('--gx', `${((x + 1) * 50).toFixed(1)}%`)
          el.style.setProperty('--gy', `${((y + 1) * 50).toFixed(1)}%`)
        },
        reset: (el: HTMLElement) => {
          el.style.setProperty('--rx', '0deg')
          el.style.setProperty('--ry', '0deg')
        },
      },
      {
        selector: '[data-magnetic]',
        set: (el: HTMLElement, x: number, y: number) => {
          el.style.setProperty('--tx', `${(x * 6).toFixed(1)}px`)
          el.style.setProperty('--ty', `${(y * 5).toFixed(1)}px`)
        },
        reset: (el: HTMLElement) => {
          el.style.setProperty('--tx', '0px')
          el.style.setProperty('--ty', '0px')
        },
      },
    ]
    const current: Array<HTMLElement | null> = kinds.map(() => null)
    const onMove = (event: PointerEvent) => {
      const target = event.target as Element | null
      kinds.forEach((kind, k) => {
        const el = (target?.closest(kind.selector) as HTMLElement | null) || null
        if (current[k] && current[k] !== el) kind.reset(current[k] as HTMLElement)
        current[k] = el
        if (!el) return
        const r = el.getBoundingClientRect()
        kind.set(el, ((event.clientX - r.left) / r.width) * 2 - 1, ((event.clientY - r.top) / r.height) * 2 - 1)
      })
    }
    const onLeave = () => {
      kinds.forEach((kind, k) => {
        if (current[k]) kind.reset(current[k] as HTMLElement)
        current[k] = null
      })
    }
    root.addEventListener('pointermove', onMove, { passive: true })
    root.addEventListener('pointerleave', onLeave)
    cleanups.push(
      () => root.removeEventListener('pointermove', onMove),
      () => root.removeEventListener('pointerleave', onLeave)
    )
  }

  /* -------------------------------------------------------- smooth scroll */
  let lenis: { destroy: () => void } | null = null
  if (finePointer && wide && lang !== 'calm' && root.dataset.scroll !== 'native') {
    import('lenis')
      .then(({ default: Lenis }) => {
        if (stopped) return
        const instance = new Lenis({
          lerp: lang === 'silk' ? 0.085 : lang === 'float' ? 0.1 : 0.13,
          anchors: { offset: -84 },
          autoRaf: true,
        })
        instance.on('scroll', onScroll)
        lenis = instance
      })
      .catch(() => undefined)
  }
  cleanups.push(() => lenis?.destroy())

  schedule()
  return {
    stop() {
      stopped = true
      for (const fn of cleanups.splice(0)) {
        try {
          fn()
        } catch {
          /* a listener already gone */
        }
      }
      root.removeAttribute('data-fx-live')
    },
  }
}

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
 * The design DNA's signature moments (data-signature / data-flourish) that are
 * scroll and pointer choreography run here too; site-dna.css draws them:
 *
 *   ground_morph   each section declares its ground (data-ground: bg, alt,
 *                  ink, accent — read from its own class and the DNA's invert);
 *                  as one crosses the middle of the screen the page's ground
 *                  (data-ground-now → --ground / --ground-ink) eases to it
 *   variable_type  section titles and the statement carry --vk: 0 → 1 as they
 *                  arrive, which their face's axes (width, softness, weight)
 *                  follow; their height is held so nothing below moves
 *   cursor_label   the pointer's ring says what a click does (View, Add, Book,
 *                  Call) — from data-cursor-label, or read from the target
 *
 * zoom_through and velocity_skew are CSS alone (data-scene's --p, the root's
 * --mv); living, ribbon and dissolve are WebGL (./gl).
 *
 * Smooth scrolling (Lenis, MIT) is used on desktop pointers only, never on
 * touch, and never for the calm motion language.
 */

import { glue, textNodes } from './typeset'

type Lang = 'silk' | 'snap' | 'float' | 'calm'

export type MotionHandle = { stop: () => void }

const clamp = (v: number, lo = 0, hi = 1) => (v < lo ? lo : v > hi ? hi : v)

/** Display faces loaded with an axis to move on (site-fonts.ts; design_dna.MOVING_FACES). */
const MOVING_FACES = new Set([
  'fraunces', 'archivo', 'instrumentsans', 'bricolage', 'intertight', 'spacegrotesk', 'bigshoulders', 'newsreader',
  'bodoni', 'manrope', 'outfit',
])
const GROUND_TOKENS = { bg: '--site-bg', alt: '--site-bg-alt', ink: '--site-ink', accent: '--site-primary' } as const
type Ground = keyof typeof GROUND_TOKENS

/** [r, g, b, a] (0–255, a 0–1) from a computed colour: rgb(), rgba() or color(srgb …). */
function channels(color: string): [number, number, number, number] | null {
  const nums = color.match(/-?[\d.]+/g)?.map(Number)
  if (!nums || nums.length < 3) return null
  const unit = color.startsWith('color(') ? 255 : 1
  return [nums[0] * unit, nums[1] * unit, nums[2] * unit, nums.length > 3 ? nums[3] : 1]
}

function luminance([r, g, b]: [number, number, number, number]): number {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
}

/** The page's own sections (and its footer), each one's ground read from what
 *  it already is: its class, the DNA's invert, its computed background. */
function declareGrounds(root: HTMLElement): { hosts: HTMLElement[]; inferred: HTMLElement[] } {
  const probe = document.createElement('span')
  probe.setAttribute('aria-hidden', 'true')
  probe.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none'
  root.appendChild(probe)
  const tokens: Array<[Ground, string]> = []
  for (const [ground, token] of Object.entries(GROUND_TOKENS) as Array<[Ground, string]>) {
    probe.style.backgroundColor = `var(${token})`
    tokens.push([ground, getComputedStyle(probe).backgroundColor])
  }
  probe.remove()
  const hosts = Array.from(root.querySelectorAll<HTMLElement>('main section, footer.ls-foot')).filter(
    (el) => !el.parentElement?.closest('section')
  )
  const inferred: HTMLElement[] = []
  for (const host of hosts) {
    if (host.dataset.ground) continue
    const own = getComputedStyle(host).backgroundColor
    const rgba = channels(own)
    // A section with no background of its own sits on the page's ground.
    const ground = !rgba || rgba[3] < 0.05 ? 'bg' : tokens.find(([, value]) => value === own)?.[0]
    if (!ground) continue // its own colour (a picture band, a gradient): it keeps it
    host.dataset.ground = ground
    inferred.push(host)
  }
  return { hosts: hosts.filter((h) => h.dataset.ground), inferred }
}

export function splitWords(el: HTMLElement): number {
  if (el.dataset.splitDone) return Number(el.style.getPropertyValue('--wn')) || 0
  // A heading is still read as one phrase, not word by word.
  const label = el.closest<HTMLElement>('h1, h2, h3, h4, h5, h6')
  if (label && !label.hasAttribute('aria-label')) {
    label.setAttribute('aria-label', (label.textContent || '').replace(/\s+/g, ' ').trim())
  }
  glue(el)
  let index = 0
  for (const node of textNodes(el)) {
    const text = node.nodeValue || ''
    if (!text.trim()) continue
    const frag = document.createDocumentFragment()
    // A no-break space joins two words into one unit that moves together.
    for (const token of text.split(/([^\S\u00a0]+)/)) {
      if (!token) continue
      if (/^[^\S\u00a0]+$/.test(token)) {
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
  if (/^(19|20)\d{2}$/.test(text.trim())) return null
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
  // The motion director's budget (design DNA): a restrained brand's cards
  // neither lean nor stagger in; a gentle one's lean half as far.
  const budget = root.dataset.budget || ''
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches
  const wide = window.matchMedia('(min-width: 900px)').matches
  const cleanups: Array<() => void> = []
  let vh = window.innerHeight
  let lastY = window.scrollY
  let velocity = 0
  let frame = 0
  let stopped = false

  root.setAttribute('data-fx-live', '')
  // The signature moments this site drew (design DNA).
  const moments = new Set([root.dataset.signature, root.dataset.flourish].filter(Boolean))

  /* -------------------------------------------------------- ground morph */
  if (moments.has('ground_morph')) {
    // Read every section's own ground first: once the morph is live the
    // sections take the page's ground, and their own is no longer computable.
    const { hosts, inferred } = declareGrounds(root)
    if (hosts.length > 1) {
      root.setAttribute('data-ground-now', hosts[0].dataset.ground || 'bg')
      const groundIO = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            const ground = (entry.target as HTMLElement).dataset.ground
            // The ground travels between the page's light grounds only: an ink
            // or accent band keeps its own slab, or the words of the sections
            // beside it would sit dark on dark while it passes.
            if (entry.isIntersecting && (ground === 'bg' || ground === 'alt')) root.setAttribute('data-ground-now', ground)
          }
        },
        // A line across the middle of the screen.
        { rootMargin: '-49% 0px -49% 0px', threshold: 0 }
      )
      hosts.forEach((host) => groundIO.observe(host))
      root.setAttribute('data-ground-live', '')
      cleanups.push(() => {
        groundIO.disconnect()
        root.removeAttribute('data-ground-live')
        root.removeAttribute('data-ground-now')
        inferred.forEach((host) => host.removeAttribute('data-ground'))
      })
    }
  }

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
        child.style.setProperty('--ri', String(budget === 'restrained' ? 0 : Math.min(i++, 12)))
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

  /* ------------------------------------------------------- variable type */
  // Section titles and the statement move on their face's axes as they
  // arrive (--vk 0 → 1). A moving line is never wider than its still self,
  // and its still height is held, so the text below never shifts.
  const moving =
    moments.has('variable_type') && MOVING_FACES.has(root.dataset.display || '')
      ? Array.from(root.querySelectorAll<HTMLElement>('main :is(.ls-title, .fx-statement__text, .fx-cta__title)')).filter(
          (el) => !el.closest('.ls-hero')
        )
      : []
  const movingSet = new Set<Element>(moving)
  function holdType() {
    if (stopped || !moving.length) return
    root.removeAttribute('data-vt-live')
    moving.forEach((el) => el.style.removeProperty('min-height'))
    const heights = moving.map((el) => el.getBoundingClientRect().height)
    moving.forEach((el, i) => {
      el.style.minHeight = `${heights[i].toFixed(1)}px`
      el.setAttribute('data-vt', '')
    })
    root.setAttribute('data-vt-live', '')
    schedule()
  }
  if (moving.length) {
    moving.forEach((el) => progressIO.observe(el))
    // Measured in the real face, not the fallback it is drawn in while loading.
    const fonts = (document as Document & { fonts?: { ready: Promise<unknown> } }).fonts
    ;(fonts ? fonts.ready : Promise.resolve()).then(holdType, holdType)
    cleanups.push(() => {
      root.removeAttribute('data-vt-live')
      moving.forEach((el) => {
        el.style.removeProperty('min-height')
        el.style.removeProperty('--vk')
        el.removeAttribute('data-vt')
      })
    })
  }
  let holdTimer = 0
  cleanups.push(() => window.clearTimeout(holdTimer))

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
        // A pinned rail travels its --track; what follows its pin is not travel.
        const travel = el.hasAttribute('data-rail-pinned') ? parseFloat(el.style.getPropertyValue('--track')) : NaN
        const span = travel > 0 ? travel : rect.height - vh
        p = span > 0 ? clamp(-rect.top / span) : clamp(1 - rect.top / vh)
        // Copy that arrives late in a scene can be pressed once it is there.
        el.toggleAttribute('data-late', p > 0.5)
      } else {
        p = clamp(1 - (rect.top + rect.height) / (vh + rect.height))
      }
      if (movingSet.has(el)) {
        // Settled just below the middle of the screen, eased (smoothstep).
        const k = clamp(p / 0.42)
        if (el.hasAttribute('data-vt')) el.style.setProperty('--vk', (k * k * (3 - 2 * k)).toFixed(3))
        // A title is not a scene: its section's --p stays its section's.
        if (!el.matches(PROGRESS)) continue
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
    if (moving.length) {
      window.clearTimeout(holdTimer)
      holdTimer = window.setTimeout(holdType, 220)
    }
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
    const lean = (lang === 'calm' ? 3 : lang === 'snap' ? 9 : 7) * (budget === 'gentle' ? 0.5 : 1)
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
        selector: budget === 'restrained' ? '[data-tilt-never]' : '[data-tilt]',
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

    // A list whose lines carry a picture (data-hover-src): the picture follows
    // the pointer over its line, easing behind it.
    const follower = document.createElement('img')
    follower.className = 'fx-follow'
    follower.alt = ''
    follower.setAttribute('aria-hidden', 'true')
    root.appendChild(follower)
    // A ring that trails the pointer, grows over anything pressable and says
    // what a click does there — only where the design asked for it (the DNA's
    // cursor, or the cursor_label moment, which also reads the label from the
    // target itself: a pictured link is "View", an add button "Add").
    const labelled = moments.has('cursor_label')
    const dot = root.dataset.cursor === 'dot' || labelled ? document.createElement('span') : null
    const dotLabel = document.createElement('span')
    let cursorWords: Record<string, string> = {}
    try {
      cursorWords = JSON.parse(root.dataset.cursorWords || '{}') as Record<string, string>
    } catch {
      cursorWords = {}
    }
    if (dot) {
      dot.className = labelled ? 'fx-cursor fx-cursor--label' : 'fx-cursor'
      dot.setAttribute('aria-hidden', 'true')
      dotLabel.className = 'fx-cursor__label'
      dot.appendChild(dotLabel)
      root.appendChild(dot)
      root.setAttribute('data-cursor-live', '')
    }
    const wordFor = (key: string) => cursorWords[key] || ''
    const labelFor = (target: Element | null, pressable: Element | null): string => {
      const own = target?.closest<HTMLElement>('[data-cursor-label]')
      if (own) return wordFor(own.dataset.cursorLabel || '') || own.dataset.cursorLabel || ''
      if (!labelled || !pressable) return ''
      if (pressable.matches('.ls-order')) return wordFor('add')
      const href = pressable.getAttribute('href') || ''
      if (href.startsWith('tel:')) return wordFor('call')
      if (/wa\.me|^whatsapp:/.test(href)) return wordFor('chat')
      if (/\/book(?:[/?#]|$)/.test(href)) return wordFor('book')
      if (pressable.matches('a') && pressable.querySelector('img')) return wordFor('view')
      return ''
    }
    // Over a dark ground or a photograph the ring inverts what is under it.
    let groundEl: Element | null = null
    let groundAt = 0
    let groundDark = false
    const darkUnder = (target: Element | null): boolean => {
      if (!target) return false
      if (target.closest('img, picture, video, canvas, .fx-statement--image')) return true
      const host = target.closest('section, footer, header, .ls-utility') || root
      const now = performance.now()
      if (host === groundEl && now - groundAt < 400) return groundDark
      groundEl = host
      groundAt = now
      let el: Element | null = host
      while (el) {
        const rgba = channels(getComputedStyle(el).backgroundColor)
        if (rgba && rgba[3] > 0.5) {
          groundDark = luminance(rgba) < 0.42
          return groundDark
        }
        el = el === root ? null : el.parentElement
      }
      groundDark = root.dataset.palette === 'dark'
      return groundDark
    }
    let fx = 0
    let fy = 0
    let tx = 0
    let ty = 0
    let chase = 0
    const ease = () => {
      chase = 0
      fx += (tx - fx) * 0.18
      fy += (ty - fy) * 0.18
      follower.style.transform = `translate3d(${fx.toFixed(1)}px, ${fy.toFixed(1)}px, 0) translate(-50%, -50%)`
      if (dot) dot.style.transform = `translate3d(${fx.toFixed(1)}px, ${fy.toFixed(1)}px, 0) translate(-50%, -50%)`
      if (Math.abs(tx - fx) + Math.abs(ty - fy) > 0.5) chase = window.requestAnimationFrame(ease)
    }
    const onTrack = (event: PointerEvent) => {
      tx = event.clientX
      ty = event.clientY
      const target = event.target as Element | null
      const row = target?.closest<HTMLElement>('[data-hover-src]')
      if (row?.dataset.hoverSrc) {
        if (follower.getAttribute('src') !== row.dataset.hoverSrc) follower.src = row.dataset.hoverSrc
        follower.classList.add('is-on')
      } else {
        follower.classList.remove('is-on')
      }
      if (dot) {
        const pressable = target?.closest('a, button, summary, label, [data-tilt], [data-cursor-label]') || null
        const label = labelFor(target, pressable)
        if (dotLabel.textContent !== label) dotLabel.textContent = label
        dot.classList.add('is-on')
        dot.classList.toggle('is-big', Boolean(pressable))
        dot.classList.toggle('is-label', Boolean(label))
        dot.classList.toggle('is-dark', darkUnder(target))
      }
      if (!chase) chase = window.requestAnimationFrame(ease)
    }
    // Out of the window, the ring goes with the pointer.
    const onOut = (event: PointerEvent) => {
      if (!event.relatedTarget) dot?.classList.remove('is-on')
    }
    window.addEventListener('pointermove', onTrack, { passive: true })
    document.addEventListener('pointerout', onOut)
    cleanups.push(
      () => document.removeEventListener('pointerout', onOut),
      () => window.removeEventListener('pointermove', onTrack),
      () => chase && window.cancelAnimationFrame(chase),
      () => follower.remove(),
      () => dot?.remove(),
      () => root.removeAttribute('data-cursor-live')
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

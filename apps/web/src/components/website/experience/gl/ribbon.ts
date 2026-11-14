/**
 * `ribbon` — the curved gallery (design DNA signature/flourish).
 *
 * A range with six or more pictured things, drawn on a bent plane. The page's
 * own markup stays exactly as it is — the rail's cards (or the bento's cells)
 * with their names, prices and Add buttons, in the DOM, focusable, read by
 * crawlers — and each card's photograph is redrawn by the GPU where its
 * <img> sits, then bent:
 *
 *   rail   the pinned horizontal run: the strip bends round a vertical axis
 *          (a cylinder about 2.6 viewport-widths across); the page's scroll
 *          moves it sideways, scroll velocity bends it harder and turns the
 *          cards like pages being flicked.
 *   bento  the grid bends round a horizontal axis as it passes the middle
 *          of the screen; velocity bends it harder and tips the cells.
 *
 * A hovered (or keyboard-focused) card un-bends and comes forward while its
 * DOM caption rises (site-covers.css, [data-ribbon-live]); the others dim a
 * little. The canvas sits beneath the cards in their own stacking context,
 * so every word and button is painted over it by the browser as usual.
 *
 * Each card swaps to GL only once its own picture is on the GPU: it is drawn
 * flat, exactly over its <img>, in the frame the <img> steps back, and then
 * eases into the curve — so the swap is never seen. Stopping puts every <img>
 * back.
 */

import {
  type GL,
  type Texture,
  approach,
  context,
  fit,
  frameLoop,
  loadPicture,
  loseContext,
  objectPosition,
  pixelRatio,
  program,
  sourceFor,
  uniforms,
  upload,
  velocitySource,
} from './core'

export type RibbonKind = 'rail' | 'bento'

const VERT = `#version 300 es
layout(location = 0) in vec2 a_uv;
uniform vec2 u_canvas;
uniform vec4 u_view;
uniform vec4 u_rect;
uniform float u_bend;
uniform float u_axis;
uniform float u_tilt;
uniform float u_flat;
uniform float u_persp;
uniform float u_sag;
out vec2 v_uv;
out float v_depth;
void main() {
  vec2 half_view = u_view.zw * 0.5;
  vec2 p = u_rect.xy + a_uv * u_rect.zw;
  vec2 s = p + u_view.xy - half_view;
  vec2 c = u_rect.xy + u_rect.zw * 0.5 + u_view.xy - half_view;
  float a = mix(s.x, s.y, u_axis);
  float ac = mix(c.x, c.y, u_axis);
  float k = u_bend * (1.0 - u_flat);
  float along = a;
  float z = 0.0;
  if (k > 1e-7) {
    float r = 1.0 / k;
    float th = a * k;
    along = sin(th) * r;
    z = (cos(th) - 1.0) * r;
  }
  z += (a - ac) * sin(u_tilt * (1.0 - u_flat));
  z += u_flat * 36.0;
  float scale = u_persp / max(u_persp - z, 1.0);
  vec2 q = mix(vec2(along, s.y + z * u_sag), vec2(s.x + z * u_sag, along), u_axis) * scale;
  vec2 o = q - u_view.xy + half_view;
  gl_Position = vec4(o.x / u_canvas.x * 2.0 - 1.0, 1.0 - o.y / u_canvas.y * 2.0, 0.0, 1.0);
  v_uv = a_uv;
  v_depth = z;
}`

const FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
in float v_depth;
out vec4 o;
uniform sampler2D u_tex;
uniform vec4 u_fit;
uniform vec4 u_rect;
uniform float u_radius;
uniform float u_alpha;
uniform float u_flat;
uniform float u_dim;
float box(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
void main() {
  vec2 size = u_rect.zw;
  float dist = box((v_uv - 0.5) * size, size * 0.5, u_radius);
  float aa = max(fwidth(dist), 1e-3);
  float edge = 1.0 - smoothstep(-aa, aa, dist);
  vec2 uv = (v_uv - 0.5) / (1.0 + u_flat * 0.035) + 0.5;
  vec3 col = texture(u_tex, uv * u_fit.xy - u_fit.zw).rgb;
  col *= clamp(1.0 + v_depth * 0.0011, 0.7, 1.0);
  col *= mix(1.0, 0.84, u_dim * (1.0 - u_flat));
  float a = edge * u_alpha;
  o = vec4(col * a, a);
}`

const NAMES = [
  'u_canvas',
  'u_view',
  'u_rect',
  'u_bend',
  'u_axis',
  'u_tilt',
  'u_flat',
  'u_persp',
  'u_sag',
  'u_tex',
  'u_fit',
  'u_radius',
  'u_alpha',
  'u_dim',
] as const

type Card = {
  el: HTMLElement
  frame: HTMLElement
  img: HTMLImageElement
  style: CSSStyleDeclaration
  tex: Texture | null
  loading: boolean
  drawn: boolean
  /** 1 = flat over its <img> (where every card starts, and a hovered one goes). */
  flat: number
  radius: number
  pos: [number, number]
}

const SELECTORS: Record<RibbonKind, { card: string; img: string; host: string | null }> = {
  rail: { card: '.fx-rail__card', img: '.fx-rail__media > img', host: '.fx-rail__stage' },
  bento: { card: '.fx-bento__cell--pic', img: '.fx-bento__media > img', host: null },
}

function grid(gl: GL, n: number) {
  const verts: number[] = []
  for (let y = 0; y <= n; y++) for (let x = 0; x <= n; x++) verts.push(x / n, y / n)
  const index: number[] = []
  for (let y = 0; y < n; y++)
    for (let x = 0; x < n; x++) {
      const i = y * (n + 1) + x
      index.push(i, i + 1, i + n + 1, i + 1, i + n + 2, i + n + 1)
    }
  const vao = gl.createVertexArray()
  const vbo = gl.createBuffer()
  const ibo = gl.createBuffer()
  if (!vao || !vbo || !ibo) return null
  gl.bindVertexArray(vao)
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STATIC_DRAW)
  gl.enableVertexAttribArray(0)
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0)
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo)
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(index), gl.STATIC_DRAW)
  gl.bindVertexArray(null)
  return { vao, vbo, ibo, count: index.length }
}

export async function startRibbon(section: HTMLElement, kind: RibbonKind, root: HTMLElement): Promise<(() => void) | null> {
  const sel = SELECTORS[kind]
  const host = sel.host ? section.querySelector<HTMLElement>(sel.host) : section
  const list = section.querySelector<HTMLElement>(kind === 'rail' ? '.fx-rail__list' : '.fx-bento')
  const track = kind === 'rail' ? section.querySelector<HTMLElement>('.fx-rail__track') : null
  if (!host || !list) return null
  const cards: Card[] = []
  for (const el of Array.from(section.querySelectorAll<HTMLElement>(sel.card))) {
    const img = el.querySelector<HTMLImageElement>(sel.img)
    if (!img) continue
    cards.push({
      el,
      frame: img.parentElement as HTMLElement,
      img,
      style: getComputedStyle(el),
      tex: null,
      loading: false,
      drawn: false,
      flat: 1,
      radius: 0,
      pos: [0.5, 0.5],
    })
  }
  if (cards.length < 6) return null

  const undo: Array<() => void> = []
  const bail = () => {
    for (const fn of undo.splice(0).reverse()) fn()
    return null
  }
  const canvas = document.createElement('canvas')
  canvas.className = 'fx-gl fx-gl--ribbon'
  canvas.setAttribute('aria-hidden', 'true')
  const gl = context(canvas, false)
  if (!gl) return null
  undo.push(() => loseContext(gl))
  const prog = program(gl, VERT, FRAG)
  const mesh = grid(gl, 24)
  if (!prog || !mesh) return bail()
  undo.push(() => {
    gl.deleteProgram(prog)
    gl.deleteBuffer(mesh.vbo)
    gl.deleteBuffer(mesh.ibo)
    gl.deleteVertexArray(mesh.vao)
  })
  const u = uniforms(gl, prog, NAMES)

  // The canvas lives under the cards: the host becomes its containing block
  // and its own stacking context, and the canvas sits at z-index -1 inside.
  const hostBefore = { position: host.style.position, isolation: host.style.isolation }
  if (getComputedStyle(host).position === 'static') host.style.position = 'relative'
  host.style.isolation = 'isolate'
  undo.push(() => {
    host.style.position = hostBefore.position
    host.style.isolation = hostBefore.isolation
  })
  host.appendChild(canvas)
  undo.push(() => canvas.remove())
  canvas.style.transition = 'none'
  // One grade across the range, as the stylesheet gives every photograph.
  canvas.style.filter = getComputedStyle(cards[0].img).filter

  const velocity = velocitySource(root)
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches
  const budget = root.dataset.budget || ''
  const velocityScale = budget === 'restrained' ? 0 : budget === 'gentle' ? 0.6 : 1

  /* ------------------------------------------------------------- layout */
  let cssW = 0
  let cssH = 0
  let dpr = 1
  const layout = () => {
    cssW = host.clientWidth
    cssH = kind === 'bento' ? Math.min(window.innerHeight, host.clientHeight) : host.clientHeight
    dpr = pixelRatio(cssW, cssH)
    canvas.style.width = `${cssW}px`
    canvas.style.height = `${cssH}px`
    canvas.width = Math.max(2, Math.round(cssW * dpr))
    canvas.height = Math.max(2, Math.round(cssH * dpr))
    for (const card of cards) {
      card.radius = parseFloat(card.style.borderTopLeftRadius) || 0
      card.pos = objectPosition(getComputedStyle(card.img).objectPosition)
    }
    dirty = true
  }
  let dirty = true
  layout()
  const resize = new ResizeObserver(() => layout())
  resize.observe(host)
  resize.observe(list)
  window.addEventListener('resize', layout)
  undo.push(() => {
    resize.disconnect()
    window.removeEventListener('resize', layout)
  })

  /* ------------------------------------------------------- hover, focus */
  let hovered: Card | null = null
  let focused: Card | null = null
  const cardOf = (target: EventTarget | null) => {
    const el = (target as Element | null)?.closest?.(sel.card)
    return el ? cards.find((c) => c.el === el) || null : null
  }
  const onOver = (event: PointerEvent) => {
    if (event.pointerType === 'mouse' || event.pointerType === 'pen') hovered = cardOf(event.target)
  }
  const onLeave = () => {
    hovered = null
  }
  const onFocus = (event: FocusEvent) => {
    focused = cardOf(event.target)
  }
  const onBlur = (event: FocusEvent) => {
    if (!cardOf(event.relatedTarget)) focused = null
  }
  if (fine) {
    list.addEventListener('pointerover', onOver)
    list.addEventListener('pointerleave', onLeave)
  }
  list.addEventListener('focusin', onFocus)
  list.addEventListener('focusout', onBlur)
  undo.push(() => {
    list.removeEventListener('pointerover', onOver)
    list.removeEventListener('pointerleave', onLeave)
    list.removeEventListener('focusin', onFocus)
    list.removeEventListener('focusout', onBlur)
  })

  /* ------------------------------------------------------------ pictures */
  let inFlight = 0
  const loadNext = () => {
    for (const card of cards) {
      if (inFlight >= 3) return
      if (card.tex || card.loading) continue
      card.loading = true
      inFlight++
      const box = card.frame.getBoundingClientRect()
      const side = Math.min(1600, Math.ceil(Math.max(box.width, box.height) * dpr * 1.15) || 1200)
      loadPicture(sourceFor(card.img, box.width || 400), side)
        .then((picture) => {
          if (stopped || !picture) return
          card.tex = upload(gl, picture)
          dirty = true
        })
        .catch(() => undefined)
        .finally(() => {
          inFlight--
          if (!stopped) loadNext()
        })
    }
  }

  /* --------------------------------------------------------------- frame */
  let stopped = false
  let started = false
  let vel = 0
  let dim = 0
  let lastY = NaN
  let lastScrollLeft = track ? track.scrollLeft : 0
  let trackVel = 0
  let quiet = 0
  const listBefore = list.style.transform

  const draw = (_now: number, dt: number) => {
    if (gl.isContextLost()) return
    if (!started) {
      started = true
      loadNext()
    }
    const vw = window.innerWidth
    const vh = window.innerHeight
    const hostRect = host.getBoundingClientRect()

    // The pinned rail: the strip's travel is set here, in the same frame its
    // pictures are drawn, so the words and the photographs never part.
    if (kind === 'rail') {
      if (section.hasAttribute('data-rail-pinned') && root.getAttribute('data-fx') === 'on') {
        const rect = section.getBoundingClientRect()
        const travel = parseFloat(section.style.getPropertyValue('--track')) || 0
        // As motion.ts: over the pin's travel, not the whole section.
        const span = travel > 0 ? travel : rect.height - vh
        const p = span > 0 ? Math.min(1, Math.max(0, -rect.top / span)) : Math.min(1, Math.max(0, 1 - rect.top / vh))
        list.style.transform = `translate3d(${(-p * travel).toFixed(2)}px, 0, 0)`
      } else if (list.style.transform !== listBefore) {
        list.style.transform = listBefore
      }
    }
    // A rail swiped by thumb on a phone moves without the page scrolling.
    if (track) {
      const left = track.scrollLeft
      trackVel = approach(trackVel, Math.max(-1, Math.min(1, (left - lastScrollLeft) / 30)), dt, 60)
      lastScrollLeft = left
    }
    const mv = velocity()
    const v = Math.abs(trackVel) > Math.abs(mv) ? trackVel : mv
    vel = approach(vel, v * velocityScale, dt, 140)

    let offsetY = 0
    if (kind === 'bento') {
      offsetY = Math.min(Math.max(0, -hostRect.top), Math.max(0, hostRect.height - cssH))
      canvas.style.transform = `translate3d(0, ${offsetY.toFixed(1)}px, 0)`
    }
    const originX = hostRect.left
    const originY = hostRect.top + offsetY

    const active = hovered || focused
    dim = approach(dim, active && fine ? 1 : 0, dt, 220)
    let animating = Math.abs(vel) > 0.002 || Math.abs(dim - (active ? 1 : 0)) > 0.002 || dirty
    const y = window.scrollY
    if (y !== lastY) animating = true
    lastY = y
    for (const card of cards) {
      const target = card === active || !card.tex ? 1 : 0
      const next = approach(card.flat, target, dt, target ? 160 : 520)
      if (Math.abs(next - card.flat) > 0.0005) animating = true
      card.flat = next
      // A card still arriving (the list's reveal) is followed frame by frame.
      if (card.tex && parseFloat(card.style.opacity) < 0.999) animating = true
    }
    if (trackVel !== 0 && Math.abs(trackVel) > 0.002) animating = true
    // Nothing moved for a while: keep the last frame, spend nothing.
    quiet = animating ? 0 : quiet + 1
    if (quiet > 2) return
    dirty = false

    const bend = kind === 'rail' ? 1 / (2.6 * vw) : 1 / (2.2 * vh)
    gl.viewport(0, 0, canvas.width, canvas.height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
    gl.useProgram(prog)
    gl.bindVertexArray(mesh.vao)
    gl.activeTexture(gl.TEXTURE0)
    gl.uniform1i(u.u_tex, 0)
    gl.uniform2f(u.u_canvas, cssW, cssH)
    gl.uniform4f(u.u_view, originX, originY, vw, vh)
    gl.uniform1f(u.u_bend, bend * (1 + Math.abs(vel) * 1.8))
    gl.uniform1f(u.u_axis, kind === 'rail' ? 0 : 1)
    gl.uniform1f(u.u_persp, Math.max(vw, vh) * 1.2)
    gl.uniform1f(u.u_sag, kind === 'rail' ? 0.28 : 0)
    gl.uniform1f(u.u_tilt, vel * (kind === 'rail' ? 0.22 : 0.12))

    const order = active ? [...cards.filter((c) => c !== active), active] : cards
    const newlyDrawn: Card[] = []
    for (const card of order) {
      if (!card.tex) continue
      const r = card.frame.getBoundingClientRect()
      const x = r.left - originX
      const top = r.top - originY
      // Off the canvas (with room for the curve): skip.
      if (x > cssW + 80 || x + r.width < -80 || top > cssH + 80 || top + r.height < -80) continue
      const alpha = Math.min(1, parseFloat(card.style.opacity) || 0)
      const [sx, sy, ox, oy] = fit(r.width, r.height, card.tex.width, card.tex.height, card.pos)
      gl.bindTexture(gl.TEXTURE_2D, card.tex.tex)
      gl.uniform4f(u.u_rect, x, top, r.width, r.height)
      gl.uniform4f(u.u_fit, sx, sy, ox, oy)
      gl.uniform1f(u.u_flat, card.flat)
      gl.uniform1f(u.u_radius, Math.min(card.radius, r.width / 2, r.height / 2))
      gl.uniform1f(u.u_alpha, alpha)
      gl.uniform1f(u.u_dim, card === active ? 0 : dim)
      gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0)
      if (!card.drawn) newlyDrawn.push(card)
    }
    if (newlyDrawn.length && gl.getError() === gl.NO_ERROR) {
      // The swap, per card, in the frame its picture was first drawn.
      for (const card of newlyDrawn) {
        card.drawn = true
        card.el.setAttribute('data-gl-drawn', '')
      }
      section.setAttribute('data-ribbon-live', '')
    }
  }

  const loop = frameLoop(section, draw, '50% 0px')
  undo.push(() => loop.stop())
  undo.push(() => {
    for (const card of cards) card.el.removeAttribute('data-gl-drawn')
    section.removeAttribute('data-ribbon-live')
    list.style.transform = listBefore
    canvas.style.transform = ''
    for (const card of cards) if (card.tex) gl.deleteTexture(card.tex.tex)
  })

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  const stop = () => {
    if (stopped) return
    stopped = true
    reduced.removeEventListener('change', onReduce)
    canvas.removeEventListener('webglcontextlost', stop)
    for (const fn of undo.splice(0).reverse()) fn()
  }
  const onReduce = () => reduced.matches && stop()
  reduced.addEventListener('change', onReduce)
  canvas.addEventListener('webglcontextlost', stop)
  return stop
}

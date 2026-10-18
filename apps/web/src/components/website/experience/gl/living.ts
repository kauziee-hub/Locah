/**
 * `living` — the living photograph (design DNA signature/flourish).
 *
 * The cover's own photograph, drawn on a canvas laid exactly over its <img>,
 * inside the same clipped frame — so an arch, a rounded mat or a clip-path
 * band still shapes it. The <img> stays in the page for search engines,
 * assistive tech and every visitor without WebGL; it is made transparent only
 * after the first GL frame has been drawn, and comes back the moment this
 * stops. Everything the stylesheet does to the <img> (its transform, scale,
 * translate, clip-path, radius and the site's photo grade) is mirrored onto
 * the canvas every frame, so the swap is invisible.
 *
 * What it adds, all small:
 *   - a soft liquid displacement around a fine pointer (radius 0.25, the
 *     drag settles in ~600 ms), a lens and a ripple while hovering;
 *   - a vertical stretch with scroll velocity (at most 2% of the height,
 *     anchored at the trailing edge, eased back) and a tiny chromatic split;
 *   - a slow breath (idle drift) and film grain;
 *   - an arrival: a photograph not yet seen dissolves in through noise over
 *     1.2 s; one already on screen has a single liquid wave pass through it.
 *
 * Tuned by concept: quiet_luxury / calm_care move half as far with no split;
 * noir_editorial / kinetic_sport get it all. A restrained budget has no
 * velocity effects (design DNA budget).
 */

import {
  FULLSCREEN_VS,
  NOISE_GLSL,
  approach,
  context,
  fit,
  frameLoop,
  fullscreen,
  loadPicture,
  loseContext,
  objectPosition,
  pixelRatio,
  pointerSource,
  program,
  sourceFor,
  uniforms,
  upload,
  velocitySource,
} from './core'

const FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
out vec4 o;
uniform sampler2D u_tex;
uniform vec2 u_box;
uniform vec4 u_fit;
uniform float u_time;
uniform float u_progress;
uniform float u_velocity;
uniform vec2 u_pointer;
uniform vec2 u_pvel;
uniform float u_hover;
uniform float u_arrive;
uniform float u_mode;
uniform float u_disp;
uniform float u_chroma;
uniform float u_grain;
uniform float u_idle;
${NOISE_GLSL}
vec3 picture(vec2 uv, float split) {
  vec2 t = uv * u_fit.xy - u_fit.zw;
  vec2 off = vec2(0.0, split);
  return vec3(texture(u_tex, t + off).r, texture(u_tex, t).g, texture(u_tex, t - off).b);
}
void main() {
  vec2 asp = vec2(u_box.x / max(u_box.y, 1.0), 1.0);
  vec2 uv = v_uv;

  // The photograph breathes, barely.
  vec2 q = v_uv * asp * 1.6;
  vec2 drift = vec2(fbm(q + vec2(u_time * 0.045, 0.0)), fbm(q + vec2(5.2, u_time * 0.038))) - 0.5;
  uv += drift * u_idle;

  // Liquid under the pointer: a lens and a ripple while it hovers, and a
  // drag along its path that settles once it stops.
  vec2 d = (v_uv - u_pointer) * asp;
  float r = length(d);
  float fall = smoothstep(0.34, 0.0, r);
  fall *= fall;
  vec2 dir = d / max(r, 1e-4);
  float ripple = sin(r * 38.0 - u_time * 4.2) * 0.0075 * u_hover;
  vec2 push = -d * 0.26 * u_hover + dir * ripple - u_pvel * 0.06;
  uv += push * fall * u_disp / asp;

  // Scroll velocity stretches it vertically (2% at most), from the trailing edge.
  float v = u_velocity;
  float anchor = v > 0.0 ? 0.0 : 1.0;
  uv.y = anchor + (uv.y - anchor) / (1.0 + abs(v) * 0.02);

  // As the section leaves, a slow wave runs through it.
  float leave = smoothstep(0.62, 1.0, u_progress);
  uv.x += sin(uv.y * 8.0 + u_time * 1.3) * 0.0045 * leave * u_disp;

  // Arrival: a noise front sweeps across the picture.
  float n = fbm(v_uv * asp * 3.2 + 3.7);
  float front = u_arrive * 1.3 - 0.15;
  float pending = smoothstep(front - 0.07, front + 0.07, n);
  float band = 1.0 - abs(pending * 2.0 - 1.0);
  float wave = sin(3.14159265 * u_arrive);
  vec2 swirl = vec2(fbm(v_uv * 5.0 + 11.0), fbm(v_uv * 5.0 + 23.0)) - 0.5;
  float dissolving = step(0.5, u_mode);
  uv += swirl * mix(0.03 * wave * (pending * 0.6 + band), 0.05 * pending + 0.02 * band, dissolving);

  // A faint colour fringe where the pointer bends the picture — only for
  // brands whose tuning allows any split at all.
  vec3 col = picture(uv, (v + fall * u_hover * 1.1) * u_chroma);
  col *= 1.0 - leave * 0.08;
  col += band * mix(0.04 * wave, 0.1, dissolving);
  col += (hash12(gl_FragCoord.xy + fract(u_time * 13.7) * 311.0) - 0.5) * u_grain;
  float alpha = mix(1.0, 1.0 - pending, dissolving);
  o = vec4(clamp(col, 0.0, 1.0) * alpha, alpha);
}`

const NAMES = [
  'u_tex',
  'u_box',
  'u_fit',
  'u_time',
  'u_progress',
  'u_velocity',
  'u_pointer',
  'u_pvel',
  'u_hover',
  'u_arrive',
  'u_mode',
  'u_disp',
  'u_chroma',
  'u_grain',
  'u_idle',
] as const

/** Everything the stylesheet does to the <img> that the canvas must do too. */
const MIRROR = ['transform', 'translate', 'scale', 'rotate', 'transform-origin', 'clip-path', 'border-radius', 'filter'] as const

/** The canvas overhangs the picture by a pixel so a rounding never shows a hairline. */
const BLEED = 1
const ARRIVAL_MS = 1200

type Tuning = { disp: number; chroma: number; velocity: number; grain: number; idle: number }

function tuning(root: HTMLElement): Tuning {
  const concept = root.dataset.concept || ''
  const budget = root.dataset.budget || ''
  const calm = concept === 'quiet_luxury' || concept === 'calm_care'
  const full = concept === 'noir_editorial' || concept === 'kinetic_sport'
  const velocity = budget === 'restrained' ? 0 : budget === 'gentle' ? 0.6 : 1
  return {
    disp: calm ? 0.5 : full ? 1 : 0.75,
    chroma: calm || budget === 'restrained' ? 0 : (full ? 0.0025 : 0.0012) * velocity,
    velocity,
    grain: root.dataset.texture === 'grain' ? 0.045 : calm ? 0.018 : 0.028,
    idle: calm ? 0.0011 : 0.0018,
  }
}

/** Not on screen yet, or still behind a reveal that has not opened. */
function unseen(img: HTMLImageElement): boolean {
  if (img.closest('[data-reveal]:not(.is-in)')) return true
  const r = img.getBoundingClientRect()
  return r.bottom <= 0 || r.top >= window.innerHeight || r.width === 0
}

function waitForLoad(img: HTMLImageElement): Promise<boolean> {
  if (img.complete) return Promise.resolve(img.naturalWidth > 0)
  return new Promise((resolve) => {
    img.addEventListener('load', () => resolve(img.naturalWidth > 0), { once: true })
    img.addEventListener('error', () => resolve(false), { once: true })
  })
}

/** Why the photograph stays an <img> — said in development only. */
function why(reason: string): null {
  if (process.env.NODE_ENV !== 'production') console.info('[gl] living:', reason)
  return null
}

export async function startLiving(img: HTMLImageElement, root: HTMLElement): Promise<(() => void) | null> {
  const host = img.parentElement
  if (!host || !(await waitForLoad(img)) || !img.isConnected) return why('the photograph never loaded')

  const style = getComputedStyle(img)
  const undo: Array<() => void> = []
  const bail = (reason: string) => {
    for (const fn of undo.splice(0).reverse()) fn()
    return why(reason)
  }
  // The canvas is positioned in the img's own frame, so that frame must be
  // its containing block (an absolutely placed img in a static frame is not
  // a frame we can follow: leave it alone).
  if (getComputedStyle(host).position === 'static') {
    if (style.position === 'absolute' || style.position === 'fixed') return why('an absolutely placed photo in a static frame')
    const before = host.style.position
    host.style.position = 'relative'
    undo.push(() => {
      host.style.position = before
    })
  }
  if (img.offsetParent !== host) return bail('the photo is not placed by its frame')

  const canvas = document.createElement('canvas')
  canvas.className = 'fx-gl'
  canvas.setAttribute('aria-hidden', 'true')
  const gl = context(canvas)
  if (!gl) return bail('no WebGL2 context')
  undo.push(() => loseContext(gl))
  const prog = program(gl, FULLSCREEN_VS, FRAG)
  const tri = fullscreen(gl)
  if (!prog || !tri) return bail('the shader did not build')
  undo.push(() => {
    gl.deleteProgram(prog)
    gl.deleteBuffer(tri.buffer)
    gl.deleteVertexArray(tri.vao)
  })
  const picture = await loadPicture(sourceFor(img, img.offsetWidth), 2560)
  if (!picture || !img.isConnected) return bail('the picture could not be read (CORS?)')
  const texture = upload(gl, picture)
  if (!texture) return bail('the texture did not upload')
  undo.push(() => gl.deleteTexture(texture.tex))

  const seen = !unseen(img)
  const u = uniforms(gl, prog, NAMES)
  const tune = tuning(root)
  const section = img.closest<HTMLElement>('[data-scene], [data-progress]')
  const velocity = velocitySource(root)
  const pointer = pointerSource()
  undo.push(pointer.stop)

  img.after(canvas)
  undo.push(() => canvas.remove())
  canvas.style.transition = 'none'
  canvas.style.animation = 'none'

  /* ------------------------------------------------------------- layout */
  let cssW = 0
  let cssH = 0
  let fitUv: [number, number, number, number] = [1, 1, 0, 0]
  const layout = () => {
    const boxW = parseFloat(style.width) || img.offsetWidth
    const boxH = parseFloat(style.height) || img.offsetHeight
    cssW = boxW + BLEED * 2
    cssH = boxH + BLEED * 2
    canvas.style.left = `${img.offsetLeft - BLEED}px`
    canvas.style.top = `${img.offsetTop - BLEED}px`
    canvas.style.width = `${cssW}px`
    canvas.style.height = `${cssH}px`
    const dpr = pixelRatio(cssW, cssH)
    canvas.width = Math.max(2, Math.round(cssW * dpr))
    canvas.height = Math.max(2, Math.round(cssH * dpr))
    const [sx, sy, ox, oy] = fit(boxW, boxH, texture.width, texture.height, objectPosition(style.objectPosition), style.objectFit)
    fitUv = [(cssW / boxW) * sx, (cssH / boxH) * sy, (BLEED / boxW) * sx + ox, (BLEED / boxH) * sy + oy]
  }
  layout()
  const resize = new ResizeObserver(() => layout())
  resize.observe(img)
  undo.push(() => resize.disconnect())

  const mirrored: Record<string, string> = {}
  const mirror = () => {
    for (const key of MIRROR) {
      let value = style.getPropertyValue(key)
      if (key === 'transform-origin') {
        // The canvas is the picture plus its bleed: shift the origin with it.
        const [x, y, ...rest] = value.split(' ')
        if (x?.endsWith('px') && y?.endsWith('px')) {
          value = [`${parseFloat(x) + BLEED}px`, `${parseFloat(y) + BLEED}px`, ...rest].join(' ')
        }
      }
      if (mirrored[key] !== value) {
        mirrored[key] = value
        canvas.style.setProperty(key, value)
      }
    }
  }

  /* --------------------------------------------------------------- frame */
  const t0 = performance.now()
  let live = false
  // Seen already: a wave passes through it. Not yet seen: it dissolves in.
  const dissolveIn = !seen
  let arrivalStart = 0
  let vel = 0
  let hover = 0
  let px = 0.5
  let py = 0.5
  let lastUx = NaN
  let lastUy = NaN
  let pvx = 0
  let pvy = 0
  const opacityBefore = img.style.opacity

  const draw = (now: number, dt: number) => {
    if (gl.isContextLost()) return
    mirror()
    // The arrival begins the first time the picture is really on screen.
    if (!arrivalStart && !unseen(img)) arrivalStart = now
    const arrive = arrivalStart ? Math.min(1, (now - arrivalStart) / ARRIVAL_MS) : 0
    const eased = dissolveIn ? 1 - Math.pow(1 - arrive, 3) : arrive

    let target = 0
    let ivx = 0
    let ivy = 0
    if (pointer.state.fine && pointer.state.inside) {
      const rect = canvas.getBoundingClientRect()
      const ux = (pointer.state.x - rect.left) / Math.max(1, rect.width)
      const uy = (pointer.state.y - rect.top) / Math.max(1, rect.height)
      if (ux >= 0 && ux <= 1 && uy >= 0 && uy <= 1) {
        target = 1
        if (Number.isFinite(lastUx)) {
          ivx = ((ux - lastUx) / dt) * 1000
          ivy = ((uy - lastUy) / dt) * 1000
        }
        px = ux
        py = uy
        lastUx = ux
        lastUy = uy
      } else {
        lastUx = NaN
      }
    } else {
      lastUx = NaN
    }
    hover = approach(hover, target, dt, target ? 140 : 200)
    const clampV = (x: number) => Math.max(-2, Math.min(2, x))
    pvx = approach(pvx, clampV(ivx), dt, Math.abs(ivx) > Math.abs(pvx) ? 50 : 200)
    pvy = approach(pvy, clampV(ivy), dt, Math.abs(ivy) > Math.abs(pvy) ? 50 : 200)
    vel = approach(vel, velocity() * tune.velocity, dt, 120)
    const progress = section ? parseFloat(section.style.getPropertyValue('--p')) : NaN

    gl.viewport(0, 0, canvas.width, canvas.height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.useProgram(prog)
    gl.bindVertexArray(tri.vao)
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, texture.tex)
    gl.uniform1i(u.u_tex, 0)
    gl.uniform2f(u.u_box, cssW, cssH)
    gl.uniform4f(u.u_fit, fitUv[0], fitUv[1], fitUv[2], fitUv[3])
    gl.uniform1f(u.u_time, (now - t0) / 1000)
    gl.uniform1f(u.u_progress, Number.isFinite(progress) ? progress : 0)
    gl.uniform1f(u.u_velocity, vel)
    gl.uniform2f(u.u_pointer, px, py)
    gl.uniform2f(u.u_pvel, pvx, pvy)
    gl.uniform1f(u.u_hover, pointer.state.fine ? hover : 0)
    gl.uniform1f(u.u_arrive, eased)
    gl.uniform1f(u.u_mode, dissolveIn ? 1 : 0)
    gl.uniform1f(u.u_disp, tune.disp)
    gl.uniform1f(u.u_chroma, tune.chroma)
    gl.uniform1f(u.u_grain, tune.grain)
    gl.uniform1f(u.u_idle, tune.idle)
    gl.drawArrays(gl.TRIANGLES, 0, 3)

    // The swap: the canvas shows and the <img> steps back in the same frame,
    // only once a frame has really been drawn.
    if (!live && gl.getError() === gl.NO_ERROR) {
      live = true
      canvas.setAttribute('data-live', '')
      img.style.opacity = '0'
    }
  }

  const loop = frameLoop(host, draw)
  undo.push(() => loop.stop())
  undo.push(() => {
    img.style.opacity = opacityBefore
  })

  let stopped = false
  const stop = () => {
    if (stopped) return
    stopped = true
    reduced.removeEventListener('change', onReduce)
    canvas.removeEventListener('webglcontextlost', stop)
    for (const fn of undo.splice(0).reverse()) fn()
  }
  // A visitor who turns reduced motion on mid-visit gets the still photograph back.
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  const onReduce = () => reduced.matches && stop()
  reduced.addEventListener('change', onReduce)
  canvas.addEventListener('webglcontextlost', stop)
  return stop
}

/**
 * `dissolve` — one photograph becoming another as the section scrolls
 * (design DNA signature/flourish). Used through ./GlDissolve.tsx.
 *
 * Both pictures are real <img>s in the frame. The GPU draws them on one
 * canvas over the frame: a noise front, driven by the section's scroll
 * progress (--p, mapped through `range`), sweeps from the first picture to
 * the second, its edge warped a little and lit in the site's own accent
 * (--site-accent: the tenant's colour, never LOCAH's). Both <img>s step back
 * only once a frame is drawn and come back when this stops.
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
  program,
  siteColour,
  sourceFor,
  uniforms,
  upload,
  velocitySource,
} from './core'

const FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
out vec4 o;
uniform sampler2D u_a;
uniform sampler2D u_b;
uniform vec4 u_fit_a;
uniform vec4 u_fit_b;
uniform vec2 u_box;
uniform float u_t;
uniform float u_vel;
uniform vec3 u_edge;
${NOISE_GLSL}
void main() {
  vec2 asp = vec2(u_box.x / max(u_box.y, 1.0), 1.0);
  float n = fbm(v_uv * asp * 2.4 + 1.3) * 0.8 + vnoise(v_uv * asp * 14.0) * 0.2;
  float front = u_t * 1.3 - 0.15;
  float keep = smoothstep(front - 0.05, front + 0.05, n);
  float band = 1.0 - abs(keep * 2.0 - 1.0);
  vec2 warp = (vec2(fbm(v_uv * 4.0 + 7.0), fbm(v_uv * 4.0 + 13.0)) - 0.5) * band * (0.04 + abs(u_vel) * 0.03);
  vec3 a = texture(u_a, (v_uv + warp) * u_fit_a.xy - u_fit_a.zw).rgb;
  vec3 b = texture(u_b, (v_uv - warp) * u_fit_b.xy - u_fit_b.zw).rgb;
  vec3 col = mix(b, a, keep);
  col = mix(col, u_edge, band * 0.32);
  o = vec4(col, 1.0);
}`

const NAMES = ['u_a', 'u_b', 'u_fit_a', 'u_fit_b', 'u_box', 'u_t', 'u_vel', 'u_edge'] as const

const smooth = (lo: number, hi: number, x: number) => {
  const k = Math.min(1, Math.max(0, (x - lo) / Math.max(1e-4, hi - lo)))
  return k * k * (3 - 2 * k)
}

/** Why the pair stays two <img>s — said in development only. */
function why(reason: string): null {
  if (process.env.NODE_ENV !== 'production') console.info('[gl] dissolve:', reason)
  return null
}

export async function startDissolve(
  frame: HTMLElement,
  first: HTMLImageElement,
  second: HTMLImageElement,
  root: HTMLElement,
  range: [number, number] = [0.3, 0.7]
): Promise<(() => void) | null> {
  const canvas = document.createElement('canvas')
  canvas.className = 'fx-gl fx-gl--fill'
  canvas.setAttribute('aria-hidden', 'true')
  const gl = context(canvas)
  if (!gl) return why('no WebGL2 context')
  const undo: Array<() => void> = [() => loseContext(gl)]
  const bail = (reason: string) => {
    for (const fn of undo.splice(0).reverse()) fn()
    return why(reason)
  }
  const prog = program(gl, FULLSCREEN_VS, FRAG)
  const tri = fullscreen(gl)
  if (!prog || !tri) return bail('the shader did not build')
  undo.push(() => {
    gl.deleteProgram(prog)
    gl.deleteBuffer(tri.buffer)
    gl.deleteVertexArray(tri.vao)
  })
  const width = frame.clientWidth || 600
  const side = Math.min(2400, Math.ceil(Math.max(width, frame.clientHeight) * 1.75))
  const [pa, pb] = await Promise.all([
    loadPicture(sourceFor(first, width), side),
    loadPicture(sourceFor(second, width), side),
  ])
  if (!pa || !pb || !frame.isConnected) return bail('a picture could not be read (CORS?)')
  const ta = upload(gl, pa)
  const tb = upload(gl, pb)
  if (!ta || !tb) return bail('a texture did not upload')
  undo.push(() => {
    gl.deleteTexture(ta.tex)
    gl.deleteTexture(tb.tex)
  })

  const u = uniforms(gl, prog, NAMES)
  const edge = siteColour(root, '--site-accent', [1, 1, 1])
  const section = frame.closest<HTMLElement>('[data-scene], [data-progress]')
  const velocity = velocitySource(root)
  const styleA = getComputedStyle(first)
  const styleB = getComputedStyle(second)

  frame.appendChild(canvas)
  undo.push(() => canvas.remove())
  canvas.style.filter = styleA.filter

  let cssW = 0
  let cssH = 0
  let fitA: [number, number, number, number] = [1, 1, 0, 0]
  let fitB: [number, number, number, number] = [1, 1, 0, 0]
  let dirty = true
  const layout = () => {
    cssW = frame.clientWidth
    cssH = frame.clientHeight
    const dpr = pixelRatio(cssW, cssH)
    canvas.width = Math.max(2, Math.round(cssW * dpr))
    canvas.height = Math.max(2, Math.round(cssH * dpr))
    fitA = fit(cssW, cssH, ta.width, ta.height, objectPosition(styleA.objectPosition), styleA.objectFit)
    fitB = fit(cssW, cssH, tb.width, tb.height, objectPosition(styleB.objectPosition), styleB.objectFit)
    dirty = true
  }
  layout()
  const resize = new ResizeObserver(layout)
  resize.observe(frame)
  undo.push(() => resize.disconnect())

  let live = false
  let vel = 0
  let lastT = -1
  const before = [first.style.opacity, second.style.opacity]
  const draw = (_now: number, dt: number) => {
    if (gl.isContextLost()) return
    let p = section ? parseFloat(section.style.getPropertyValue('--p')) : NaN
    if (!Number.isFinite(p)) {
      const r = frame.getBoundingClientRect()
      p = Math.min(1, Math.max(0, 1 - (r.top + r.height) / (window.innerHeight + r.height)))
    }
    const t = smooth(range[0], range[1], p)
    vel = approach(vel, velocity(), dt, 140)
    if (!dirty && live && Math.abs(t - lastT) < 1e-4 && Math.abs(vel) < 0.002) return
    dirty = false
    lastT = t
    gl.viewport(0, 0, canvas.width, canvas.height)
    gl.useProgram(prog)
    gl.bindVertexArray(tri.vao)
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, ta.tex)
    gl.activeTexture(gl.TEXTURE1)
    gl.bindTexture(gl.TEXTURE_2D, tb.tex)
    gl.uniform1i(u.u_a, 0)
    gl.uniform1i(u.u_b, 1)
    gl.uniform4f(u.u_fit_a, fitA[0], fitA[1], fitA[2], fitA[3])
    gl.uniform4f(u.u_fit_b, fitB[0], fitB[1], fitB[2], fitB[3])
    gl.uniform2f(u.u_box, cssW, cssH)
    gl.uniform1f(u.u_t, t)
    gl.uniform1f(u.u_vel, vel)
    gl.uniform3f(u.u_edge, edge[0], edge[1], edge[2])
    gl.drawArrays(gl.TRIANGLES, 0, 3)
    if (!live && gl.getError() === gl.NO_ERROR) {
      live = true
      canvas.setAttribute('data-live', '')
      first.style.opacity = '0'
      second.style.opacity = '0'
    }
  }
  const loop = frameLoop(frame, draw)
  undo.push(() => loop.stop())
  undo.push(() => {
    first.style.opacity = before[0]
    second.style.opacity = before[1]
  })

  let stopped = false
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

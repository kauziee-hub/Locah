/**
 * A tiny hand-written WebGL2 renderer core for tenant websites — no library.
 *
 * Shared by the living photograph (./living), the curved gallery (./ribbon)
 * and the image-to-image dissolve (./dissolve). Everything here is loaded with
 * those modules through a dynamic import(), after ./gate has said the device
 * and the design want it; nothing of it is on the critical path.
 *
 * Pictures are drawn from the same URL the page's <img> already shows (its
 * currentSrc, or the srcset width that suits the box), fetched with CORS so
 * the canvas stays readable; a picture the browser will not share (no CORS)
 * simply leaves the <img> in charge.
 */

export type GL = WebGL2RenderingContext

export type Texture = { tex: WebGLTexture; width: number; height: number }

/** A WebGL2 context for a canvas we own, or null (no WebGL2, blocklisted GPU). */
export function context(canvas: HTMLCanvasElement, antialias = false): GL | null {
  try {
    const gl = canvas.getContext('webgl2', {
      alpha: true,
      premultipliedAlpha: true,
      antialias,
      depth: false,
      stencil: false,
      preserveDrawingBuffer: false,
      powerPreference: 'default',
    })
    if (!gl || gl.isContextLost()) return null
    return gl
  } catch {
    return null
  }
}

export function program(gl: GL, vertex: string, fragment: string): WebGLProgram | null {
  const compile = (type: number, source: string) => {
    const shader = gl.createShader(type)
    if (!shader) return null
    gl.shaderSource(shader, source)
    gl.compileShader(shader)
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      if (process.env.NODE_ENV !== 'production') console.warn('[gl] shader', gl.getShaderInfoLog(shader))
      gl.deleteShader(shader)
      return null
    }
    return shader
  }
  const vs = compile(gl.VERTEX_SHADER, vertex)
  const fs = compile(gl.FRAGMENT_SHADER, fragment)
  const prog = gl.createProgram()
  if (!vs || !fs || !prog) return null
  gl.attachShader(prog, vs)
  gl.attachShader(prog, fs)
  gl.linkProgram(prog)
  gl.deleteShader(vs)
  gl.deleteShader(fs)
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    if (process.env.NODE_ENV !== 'production') console.warn('[gl] link', gl.getProgramInfoLog(prog))
    gl.deleteProgram(prog)
    return null
  }
  return prog
}

/** Uniform locations by name, looked up once. */
export function uniforms<K extends string>(gl: GL, prog: WebGLProgram, names: readonly K[]) {
  const out = {} as Record<K, WebGLUniformLocation | null>
  for (const name of names) out[name] = gl.getUniformLocation(prog, name)
  return out
}

/** One triangle that covers the whole canvas (attribute 0 = a_pos). */
export function fullscreen(gl: GL): { vao: WebGLVertexArrayObject; buffer: WebGLBuffer } | null {
  const vao = gl.createVertexArray()
  const buffer = gl.createBuffer()
  if (!vao || !buffer) return null
  gl.bindVertexArray(vao)
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
  gl.enableVertexAttribArray(0)
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0)
  gl.bindVertexArray(null)
  return { vao, buffer }
}

/** The full-canvas vertex shader: v_uv 0→1, y down like the page. */
export const FULLSCREEN_VS = `#version 300 es
layout(location = 0) in vec2 a_pos;
out vec2 v_uv;
void main() {
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5);
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`

/** Value noise and fbm, shared by the fragment shaders. */
export const NOISE_GLSL = `
float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash12(i);
  float b = hash12(i + vec2(1.0, 0.0));
  float c = hash12(i + vec2(0.0, 1.0));
  float d = hash12(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float fbm(vec2 p) {
  float s = 0.0;
  float w = 0.5;
  for (int k = 0; k < 4; k++) {
    s += w * vnoise(p);
    p = p * 2.03 + 17.1;
    w *= 0.5;
  }
  return s;
}
`

/** The URL the page shows for this <img>, or the srcset width that suits `cssWidth`. */
export function sourceFor(img: HTMLImageElement, cssWidth: number): string {
  if (img.currentSrc) return img.currentSrc
  const want = cssWidth * Math.min(window.devicePixelRatio || 1, 2)
  const candidates = (img.getAttribute('srcset') || '')
    .split(',')
    .map((part) => part.trim().split(/\s+/))
    .map(([url, w]) => ({ url, w: parseInt(w || '', 10) }))
    .filter((c) => c.url && Number.isFinite(c.w))
    .sort((a, b) => a.w - b.w)
  const fit = candidates.find((c) => c.w >= want) || candidates[candidates.length - 1]
  return fit?.url || img.src
}

/** Fetch a picture for the GPU: CORS, decoded, and no larger than it is drawn. */
export async function loadPicture(url: string, maxSide = 2560): Promise<ImageBitmap | HTMLImageElement | null> {
  const image = await new Promise<HTMLImageElement | null>((resolve) => {
    const im = new Image()
    im.crossOrigin = 'anonymous'
    im.decoding = 'async'
    im.onload = () => resolve(im)
    im.onerror = () => resolve(null)
    im.src = url
  })
  if (!image || !image.naturalWidth) return null
  try {
    await image.decode()
  } catch {
    /* already decoded, or decoded on upload */
  }
  const side = Math.max(image.naturalWidth, image.naturalHeight)
  if (side > maxSide && typeof createImageBitmap === 'function') {
    const k = maxSide / side
    try {
      return await createImageBitmap(image, {
        resizeWidth: Math.round(image.naturalWidth * k),
        resizeHeight: Math.round(image.naturalHeight * k),
        resizeQuality: 'high',
      })
    } catch {
      return image
    }
  }
  return image
}

/** Upload a picture as a mipmapped texture; null if the browser refuses (a tainted image). */
export function upload(gl: GL, picture: ImageBitmap | HTMLImageElement): Texture | null {
  const tex = gl.createTexture()
  if (!tex) return null
  gl.bindTexture(gl.TEXTURE_2D, tex)
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false)
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
  try {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, picture)
  } catch {
    gl.deleteTexture(tex)
    return null
  }
  if (gl.getError() !== gl.NO_ERROR) {
    gl.deleteTexture(tex)
    return null
  }
  gl.generateMipmap(gl.TEXTURE_2D)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
  const aniso = gl.getExtension('EXT_texture_filter_anisotropic')
  if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, 4)
  const width = 'naturalWidth' in picture ? picture.naturalWidth : picture.width
  const height = 'naturalHeight' in picture ? picture.naturalHeight : picture.height
  if ('close' in picture) picture.close()
  return { tex, width, height }
}

/**
 * How an object-fit picture of `iw`×`ih` sits in a `bw`×`bh` box, as a uv
 * transform: texture uv = box uv × scale − offset. `pos` is object-position
 * as fractions (0.5 0.5 = centred).
 */
export function fit(
  bw: number,
  bh: number,
  iw: number,
  ih: number,
  pos: [number, number] = [0.5, 0.5],
  mode = 'cover'
): [number, number, number, number] {
  if (!iw || !ih || !bw || !bh) return [1, 1, 0, 0]
  let dw = bw
  let dh = bh
  if (mode !== 'fill') {
    const s = mode === 'contain' ? Math.min(bw / iw, bh / ih) : Math.max(bw / iw, bh / ih)
    dw = iw * s
    dh = ih * s
  }
  const ox = (bw - dw) * pos[0]
  const oy = (bh - dh) * pos[1]
  return [bw / dw, bh / dh, ox / dw, oy / dh]
}

/** object-position ("30% 60%", "left top", "12px 0px") as fractions; centred when unsure. */
export function objectPosition(value: string): [number, number] {
  const words: Record<string, number> = { left: 0, top: 0, center: 0.5, right: 1, bottom: 1 }
  const parts = value.trim().split(/\s+/).slice(0, 2)
  const out: [number, number] = [0.5, 0.5]
  parts.forEach((part, i) => {
    if (part in words) out[i] = words[part]
    else if (part.endsWith('%')) out[i] = parseFloat(part) / 100
  })
  return out
}

/** Device pixels for a canvas: crisp up to 1.75x, and never more than `budget` pixels. */
export function pixelRatio(cssW: number, cssH: number, budget = 4.2e6): number {
  let dpr = Math.min(window.devicePixelRatio || 1, 1.75)
  const area = Math.max(1, cssW * cssH)
  if (area * dpr * dpr > budget) dpr = Math.max(0.75, Math.sqrt(budget / area))
  return dpr
}

/** Give the GPU its memory back now, not whenever the canvas is collected. */
export function loseContext(gl: GL): void {
  try {
    gl.getExtension('WEBGL_lose_context')?.loseContext()
  } catch {
    /* already lost */
  }
}

/** A pausable frame loop: runs while visible on screen and the tab is shown. */
export function frameLoop(target: Element, draw: (now: number, dt: number) => void, margin = '10% 0px') {
  let raf = 0
  let onScreen = false
  let last = 0
  let stopped = false
  const tick = (now: number) => {
    raf = 0
    if (stopped || !onScreen || document.hidden) return
    const dt = last ? Math.min(64, now - last) : 16
    last = now
    draw(now, dt)
    raf = requestAnimationFrame(tick)
  }
  const wake = () => {
    if (!raf && !stopped && onScreen && !document.hidden) {
      last = 0
      raf = requestAnimationFrame(tick)
    }
  }
  const io = new IntersectionObserver(
    (entries) => {
      onScreen = entries.some((e) => e.isIntersecting)
      wake()
    },
    { rootMargin: margin }
  )
  io.observe(target)
  document.addEventListener('visibilitychange', wake)
  return {
    wake,
    get onScreen() {
      return onScreen
    },
    stop() {
      stopped = true
      if (raf) cancelAnimationFrame(raf)
      io.disconnect()
      document.removeEventListener('visibilitychange', wake)
    },
  }
}

/** Ease `current` toward `target` with a time constant of `tau` ms. */
export function approach(current: number, target: number, dt: number, tau: number): number {
  return current + (target - current) * (1 - Math.exp(-dt / Math.max(1, tau)))
}

/** The page's scroll velocity, -1..1: motion.ts's --mv when it runs, else measured here. */
export function velocitySource(root: HTMLElement) {
  let lastY = window.scrollY
  let own = 0
  return () => {
    const y = window.scrollY
    own = own * 0.8 + (y - lastY) * 0.2
    lastY = y
    const mv = parseFloat(root.style.getPropertyValue('--mv'))
    if (Number.isFinite(mv)) return mv
    return Math.max(-1, Math.min(1, own / 40))
  }
}

/** A fine pointer, tracked once for the page: where it is, and when it last moved. */
export function pointerSource() {
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches
  const state = { x: -1e4, y: -1e4, inside: false, fine }
  if (!fine) return { state, stop: () => undefined }
  const move = (event: PointerEvent) => {
    if (event.pointerType !== 'mouse' && event.pointerType !== 'pen') return
    state.x = event.clientX
    state.y = event.clientY
    state.inside = true
  }
  const out = (event: PointerEvent) => {
    if (!event.relatedTarget) state.inside = false
  }
  window.addEventListener('pointermove', move, { passive: true })
  window.addEventListener('pointerout', out, { passive: true })
  return {
    state,
    stop: () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerout', out)
    },
  }
}

/** The site's own colour token as linear-ish RGB 0..1 (tenant tokens only). */
export function siteColour(root: HTMLElement, token: string, fallback: [number, number, number]): [number, number, number] {
  const raw = getComputedStyle(root).getPropertyValue(token).trim()
  if (!raw) return fallback
  const ctx = document.createElement('canvas').getContext('2d')
  if (!ctx) return fallback
  ctx.fillStyle = '#000'
  ctx.fillStyle = raw
  const value = String(ctx.fillStyle)
  const hex = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(value)
  if (hex) return [parseInt(hex[1], 16) / 255, parseInt(hex[2], 16) / 255, parseInt(hex[3], 16) / 255]
  const rgb = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(value)
  return rgb ? [Number(rgb[1]) / 255, Number(rgb[2]) / 255, Number(rgb[3]) / 255] : fallback
}

'use client'

import { useEffect, useRef } from 'react'

/**
 * A slow, living gradient in the business's own colours, drawn on the GPU.
 *
 * For a business without photographs (a law firm, a consultant, a new shop),
 * the hero still moves. No library: one fragment shader, a few hundred bytes.
 * It renders at a fraction of the screen's resolution (it is soft anyway),
 * stops when the hero leaves the screen or the tab is hidden, and draws a
 * single still frame for anyone who asked for reduced motion. Without WebGL
 * the CSS wash underneath (.fx-aurora__wash) is what shows.
 */

const VERT = `attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}`

const FRAG = `precision mediump float;
uniform vec2 r;uniform float t;uniform vec3 a;uniform vec3 b;uniform vec3 c;uniform vec2 m;
float h(vec2 q){return fract(sin(dot(q,vec2(127.1,311.7)))*43758.5453);}
float n(vec2 q){vec2 i=floor(q),f=fract(q);f=f*f*(3.-2.*f);
return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x),f.y);}
float fbm(vec2 q){float s=0.,w=.5;for(int k=0;k<4;k++){s+=w*n(q);q*=2.03;w*=.5;}return s;}
void main(){vec2 uv=gl_FragCoord.xy/r;vec2 q=uv*vec2(r.x/r.y,1.)*1.4;
q+=m*.12;
float f1=fbm(q+vec2(t*.035,t*.02));
float f2=fbm(q*1.7+f1*1.6-vec2(t*.025,-t*.03));
vec3 col=mix(c,a,smoothstep(.3,.72,f1)*.9);
col=mix(col,b,smoothstep(.42,.8,f2)*.75);
col=mix(col,c,smoothstep(.55,1.,uv.x*.4+uv.y*.6)*.35);
col+=(h(gl_FragCoord.xy+t)-.5)*.035;
gl_FragColor=vec4(col,1.);}`

function rgb(value: string): [number, number, number] | null {
  const canvas = document.createElement('canvas').getContext('2d')
  if (!canvas || !value) return null
  canvas.fillStyle = '#000'
  canvas.fillStyle = value.trim()
  const hex = String(canvas.fillStyle)
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
  if (m) return [parseInt(m[1], 16) / 255, parseInt(m[2], 16) / 255, parseInt(m[3], 16) / 255]
  const n = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(hex)
  return n ? [Number(n[1]) / 255, Number(n[2]) / 255, Number(n[3]) / 255] : null
}

export function AuroraCanvas() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const site = canvas.closest<HTMLElement>('[data-locah-site]')
    const hero = canvas.parentElement
    if (!site || !hero) return
    const saveData = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData
    if (saveData) return
    const gl = canvas.getContext('webgl', { antialias: false, premultipliedAlpha: false, powerPreference: 'low-power' })
    if (!gl || gl.isContextLost()) return

    const styles = getComputedStyle(site)
    const primary = rgb(styles.getPropertyValue('--site-primary'))
    const accent = rgb(styles.getPropertyValue('--site-accent'))
    const ground = rgb(styles.getPropertyValue('--site-bg'))
    if (!primary || !accent || !ground) return

    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type)
      if (!shader) return null
      gl.shaderSource(shader, source)
      gl.compileShader(shader)
      return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null
    }
    const vs = compile(gl.VERTEX_SHADER, VERT)
    const fs = compile(gl.FRAGMENT_SHADER, FRAG)
    const program = gl.createProgram()
    if (!vs || !fs || !program) return
    gl.attachShader(program, vs)
    gl.attachShader(program, fs)
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return
    gl.useProgram(program)
    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const loc = gl.getAttribLocation(program, 'p')
    gl.enableVertexAttribArray(loc)
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
    const u = (name: string) => gl.getUniformLocation(program, name)
    // The ground mixed toward the brand colour keeps light sites light and
    // dark sites dark: the gradient is the business's, never LOCAH's.
    gl.uniform3fv(u('a'), primary)
    gl.uniform3fv(u('b'), accent)
    gl.uniform3fv(u('c'), ground)
    const uRes = u('r')
    const uTime = u('t')
    const uMouse = u('m')

    const scale = 0.5
    const resize = () => {
      const w = Math.max(2, Math.floor(hero.clientWidth * scale))
      const h = Math.max(2, Math.floor(hero.clientHeight * scale))
      canvas.width = w
      canvas.height = h
      gl.viewport(0, 0, w, h)
      gl.uniform2f(uRes, w, h)
    }
    resize()

    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let visible = true
    let raf = 0
    const t0 = performance.now()
    const draw = (now: number) => {
      raf = 0
      const mx = Number(hero.style.getPropertyValue('--mx')) || 0
      const my = Number(hero.style.getPropertyValue('--my')) || 0
      gl.uniform1f(uTime, still ? 12 : (now - t0) / 1000)
      gl.uniform2f(uMouse, mx, -my)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      // Shown only once a frame has really been drawn; until then (or with no
      // WebGL at all) the CSS wash underneath is the hero's colour.
      if (!canvas.hasAttribute('data-live') && gl.getError() === gl.NO_ERROR) canvas.setAttribute('data-live', '')
      if (!still && visible && !document.hidden) raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      if (visible && !raf) raf = requestAnimationFrame(draw)
    })
    io.observe(hero)
    const onVisibility = () => {
      if (!document.hidden && visible && !raf) raf = requestAnimationFrame(draw)
    }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('resize', resize)
    return () => {
      if (raf) cancelAnimationFrame(raf)
      io.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', resize)
      canvas.removeAttribute('data-live')
      // The context is left for the browser to collect: losing it here would
      // also lose it for a remount of the same canvas.
    }
  }, [])

  return <canvas ref={ref} className="fx-aurora__canvas" aria-hidden="true" />
}

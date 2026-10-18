'use client'

import { useEffect, useRef } from 'react'
import { mountGl } from './gate'

/**
 * Place right after a photograph's <img>, inside the same frame:
 *
 *   <figure className="fx-arch__main">
 *     <img … />
 *     <GlLiving />
 *   </figure>
 *
 * On a site whose design DNA chose `living` as its signature or flourish, on a
 * capable device with motion on, the photograph becomes the living photograph
 * (./living). Everywhere else this is an empty, hidden span and the <img> is
 * the design. It never blocks first paint: the renderer is imported after the
 * page is idle, and nothing in the layout moves.
 */
export function GlLiving() {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const anchor = ref.current
    const frame = anchor?.parentElement
    const img = frame?.querySelector<HTMLImageElement>(':scope > img')
    const root = anchor?.closest<HTMLElement>('[data-locah-site]')
    if (!img || !root) return
    return mountGl(root, 'living', () => import('./living').then(({ startLiving }) => startLiving(img, root)))
  }, [])
  return <span ref={ref} hidden data-gl-anchor="" />
}

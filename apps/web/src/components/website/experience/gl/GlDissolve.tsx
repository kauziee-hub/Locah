'use client'

import { useEffect, useRef, type CSSProperties } from 'react'
import { srcSetFor } from '../../picture'
import type { Pic } from '../HeroScenes'
import { mountGl } from './gate'

/**
 * Two of the business's photographs, the first becoming the second as the
 * section scrolls — the `dissolve` signature (design DNA), offered to any
 * section that has a pair (a story's before/after, the shop and its counter,
 * a visit's street and its door). Story.tsx HeldPicture wires it into a story's held picture.
 *
 *   <section data-progress="">           // or data-scene="" on a pinned one
 *     <figure className="…your frame, sized by your CSS…">
 *       <Dissolve from={pictures[0]} to={pictures[1]} sizes="50vw" />
 *     </figure>
 *   </section>
 *
 * The frame decides the size (Dissolve fills it: width and height 100%).
 * `range` is the part of the section's --p (0 → 1) over which it turns,
 * by default 0.3 → 0.7 — the middle of its pass across the screen.
 *
 * Still state (no JS, reduced motion, a crawler): the first photograph,
 * complete; the second is in the DOM with its alt text, transparent. With
 * motion on but no GL (or a site that did not choose `dissolve`): a CSS
 * crossfade on the same --p (site-covers.css). With GL on a site that chose
 * `dissolve`: a noise front sweeps from one to the other (./dissolve).
 */
export function Dissolve({
  from,
  to,
  sizes,
  className,
  range,
  eager = false,
}: {
  from: Pic
  to: Pic
  sizes?: string
  className?: string
  range?: [number, number]
  eager?: boolean
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const [lo, hi] = range || [0.3, 0.7]
  useEffect(() => {
    const frame = ref.current
    const first = frame?.querySelector<HTMLImageElement>('.fx-dissolve__a')
    const second = frame?.querySelector<HTMLImageElement>('.fx-dissolve__b')
    const root = frame?.closest<HTMLElement>('[data-locah-site]')
    if (!frame || !first || !second || !root) return
    return mountGl(root, 'dissolve', () =>
      import('./dissolve').then(({ startDissolve }) => startDissolve(frame, first, second, root, [lo, hi]))
    )
  }, [from.url, to.url, lo, hi])
  const load = eager ? {} : { loading: 'lazy' as const }
  return (
    <span
      ref={ref}
      className={`fx-dissolve${className ? ` ${className}` : ''}`}
      style={{ '--dis-lo': lo, '--dis-hi': hi } as CSSProperties}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="fx-dissolve__a" src={from.url} srcSet={srcSetFor(from.url)} sizes={sizes} alt={from.alt_text || ''} {...load} />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="fx-dissolve__b" src={to.url} srcSet={srcSetFor(to.url)} sizes={sizes} alt={to.alt_text || ''} {...load} />
    </span>
  )
}

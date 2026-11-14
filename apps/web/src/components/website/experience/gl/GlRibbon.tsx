'use client'

import { useEffect, type RefObject } from 'react'
import { mountGl } from './gate'

type Kind = 'rail' | 'bento'

const PICTURED: Record<Kind, string> = {
  rail: '.fx-rail__card .fx-rail__media > img',
  bento: '.fx-bento__media > img',
}

/**
 * The curved gallery for a range (./ribbon), from the range's own section.
 *
 *   const ref = useRef<HTMLElement>(null)
 *   useGlRibbon(ref, variant === 'rail' || variant === 'bento' ? variant : null, picturesKey)
 *   …
 *   <section ref={ref} …>   // the rail or bento markup, unchanged
 *
 * Only on a site whose design DNA chose `ribbon` as its signature or
 * flourish, for six or more pictured things, on a capable device with motion
 * on. The section's markup is the fallback and stays in the DOM either way;
 * `key` (the pictures shown, joined) restarts it when a filter changes them.
 */
export function useGlRibbon(ref: RefObject<HTMLElement>, kind: Kind | null, key: string) {
  useEffect(() => {
    const section = ref.current
    if (!section || !kind) return
    const root = section.closest<HTMLElement>('[data-locah-site]')
    if (!root) return
    const pictured = section.querySelectorAll(PICTURED[kind]).length
    if (pictured < 6) {
      if (process.env.NODE_ENV !== 'production' && root.dataset.signature === 'ribbon')
        console.info('[gl] ribbon: only', pictured, 'pictures in the', kind)
      return
    }
    return mountGl(root, 'ribbon', () =>
      import('./ribbon').then(({ startRibbon }) => startRibbon(section, kind, root))
    )
  }, [ref, kind, key])
}

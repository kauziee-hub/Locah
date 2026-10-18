'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'

import { openChip, openState, type OpenWords, type Week } from './open-now'
import { typeset } from './typeset'

/** Resolves the view transition a site link started, once the new page is in. */
let settleTransition: (() => void) | null = null

type TransitionDocument = Document & { startViewTransition?: (update: () => Promise<void>) => unknown }

/**
 * Starts the motion runtime for the tenant site that contains it.
 *
 * The page is complete before this runs; a visitor who asked their device for
 * reduced motion, or a site whose owner switched motion off, never loads it.
 * The runtime itself is fetched after the page is interactive, so it costs
 * nothing on the critical path.
 *
 * Two things here are not motion and run for every visitor: the typesetting,
 * and the desktop action dock (it shows once the cover has scrolled away and
 * steps aside at the closing band and the footer).
 */
export function SiteMotion() {
  const router = useRouter()
  const routerRef = useRef(router)
  routerRef.current = router
  const pathname = usePathname()

  // The new page is rendered: the transition into it can play.
  useEffect(() => {
    settleTransition?.()
    settleTransition = null
  }, [pathname])

  useEffect(() => {
    const anchor = document.querySelector<HTMLElement>('[data-locah-site]')
    if (!anchor) return
    const root = anchor
    // Typography is not motion: every visitor gets units kept with their
    // numbers and headings without a lone last word.
    typeset(root)
    const stopDock = watchDock(root)
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || root.dataset.motion === 'none') {
      root.removeAttribute('data-fx')
      return stopDock
    }
    // A client-side navigation renders a new page without running the inline
    // boot script, so the attribute is set here as well.
    root.setAttribute('data-fx', 'on')

    // Moving between the site's own pages (its header, menu and footer links)
    // is one continuous scene: the name and the header stay, the page under
    // them changes (site-dna.css draws the transition). A full page load gets
    // the same from @view-transition, which WebsitePageView opts the site into.
    const doc = document as TransitionDocument
    const onNavigate = (event: MouseEvent) => {
      if (!doc.startViewTransition || event.defaultPrevented || event.button !== 0) return
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      const link = (event.target as Element | null)?.closest<HTMLAnchorElement>('a[data-vt][href]')
      if (!link || (link.target && link.target !== '_self') || link.hasAttribute('download')) return
      const url = new URL(link.href, window.location.href)
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname) return
      event.preventDefault()
      doc.startViewTransition(
        () =>
          new Promise<void>((resolve) => {
            settleTransition = resolve
            // Never hold the page: a slow page arrives without the transition.
            window.setTimeout(resolve, 1600)
            routerRef.current.push(`${url.pathname}${url.search}${url.hash}`)
          })
      )
    }
    root.addEventListener('click', onNavigate, true)

    let handle: { stop: () => void } | null = null
    let gone = false
    import('./motion')
      .then(({ start }) => {
        if (!gone) handle = start(root)
      })
      .catch(() => root.removeAttribute('data-fx'))
    return () => {
      gone = true
      handle?.stop()
      stopDock()
      root.removeEventListener('click', onNavigate, true)
    }
  }, [])
  return null
}

/**
 * The desktop action dock (.fx-dock): the live action and one channel, within
 * a glance once the cover has gone and out of the way at the closing band and
 * the footer, which carry their own. Without JavaScript it stays hidden and the
 * header keeps the action.
 */
function watchDock(root: HTMLElement): () => void {
  const dock = root.querySelector<HTMLElement>('.fx-dock')
  if (!dock || typeof IntersectionObserver === 'undefined') return () => undefined
  const cover = root.querySelector<HTMLElement>('main .ls-hero') || root.querySelector<HTMLElement>('main section')
  const ends = Array.from(root.querySelectorAll<HTMLElement>('main .fx-cta, footer.ls-foot'))
  let pastCover = !cover
  const near = new Set<Element>()
  const show = () => dock.toggleAttribute('data-on', pastCover && near.size === 0)
  const coverIO = new IntersectionObserver((entries) => {
    for (const entry of entries) pastCover = !entry.isIntersecting && entry.boundingClientRect.bottom <= 0
    show()
  })
  const endIO = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) near.add(entry.target)
        else near.delete(entry.target)
      }
      show()
    },
    { rootMargin: '0px 0px -8% 0px' }
  )
  if (cover) coverIO.observe(cover)
  ends.forEach((el) => endIO.observe(el))
  show()
  return () => {
    coverIO.disconnect()
    endIO.disconnect()
    dock.removeAttribute('data-on')
  }
}

/**
 * "Open now · until 11 pm" / "Opens 7 am" from the location's own hours, on the
 * business's clock, worked out in the visitor's browser (never on the server:
 * a cached page would go stale). Renders nothing until then, and nothing at
 * all when there is nothing true to say.
 */
export function OpenNow({
  hours,
  words,
  locale,
  className,
}: {
  hours: Week
  words: OpenWords
  locale: string
  className?: string
}) {
  const [chip, setChip] = useState<ReturnType<typeof openChip>>(null)
  useEffect(() => {
    const tick = () => setChip(openChip(openState(hours, new Date()), words, locale))
    tick()
    const timer = window.setInterval(tick, 60_000)
    return () => window.clearInterval(timer)
  }, [hours, words, locale])
  if (!chip) return null
  return (
    <span className={`fx-open ${className || ''}`} data-open={chip.open ? 'yes' : 'no'}>
      <span className="fx-open__lead">{chip.lead}</span>
      {chip.rest ? <span className="fx-open__rest">{chip.rest}</span> : null}
    </span>
  )
}

/**
 * Runs while the HTML is still being parsed, before the first paint: content
 * that will animate in is hidden only once we know it will be animated. If
 * the runtime has not started within four seconds (a blocked script, a very
 * slow phone) everything is simply shown.
 */
export const MOTION_BOOT = `(function(){try{var s=document.currentScript,r=s&&s.parentElement;if(!r||r.getAttribute('data-motion')==='none')return;if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)return;r.setAttribute('data-fx','on');try{if(sessionStorage.getItem('fx-intro:'+location.pathname.split('/')[1]))r.setAttribute('data-intro','seen');else sessionStorage.setItem('fx-intro:'+location.pathname.split('/')[1],'1')}catch(e){}setTimeout(function(){if(!r.hasAttribute('data-fx-live'))r.removeAttribute('data-fx')},4000)}catch(e){}})();`

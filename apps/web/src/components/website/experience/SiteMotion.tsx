'use client'

import { useEffect } from 'react'

/**
 * Starts the motion runtime for the tenant site that contains it.
 *
 * The page is complete before this runs; a visitor who asked their device for
 * reduced motion, or a site whose owner switched motion off, never loads it.
 * The runtime itself is fetched after the page is interactive, so it costs
 * nothing on the critical path.
 */
export function SiteMotion() {
  useEffect(() => {
    const anchor = document.querySelector<HTMLElement>('[data-locah-site]')
    if (!anchor) return
    const root = anchor
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || root.dataset.motion === 'none') {
      root.removeAttribute('data-fx')
      return
    }
    // A client-side navigation renders a new page without running the inline
    // boot script, so the attribute is set here as well.
    root.setAttribute('data-fx', 'on')
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
    }
  }, [])
  return null
}

/**
 * Runs while the HTML is still being parsed, before the first paint: content
 * that will animate in is hidden only once we know it will be animated. If
 * the runtime has not started within four seconds (a blocked script, a very
 * slow phone) everything is simply shown.
 */
export const MOTION_BOOT = `(function(){try{var s=document.currentScript,r=s&&s.parentElement;if(!r||r.getAttribute('data-motion')==='none')return;if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)return;r.setAttribute('data-fx','on');try{if(sessionStorage.getItem('fx-intro:'+location.pathname.split('/')[1]))r.setAttribute('data-intro','seen');else sessionStorage.setItem('fx-intro:'+location.pathname.split('/')[1],'1')}catch(e){}setTimeout(function(){if(!r.hasAttribute('data-fx-live'))r.removeAttribute('data-fx')},4000)}catch(e){}})();`

'use client'

import { useEffect } from 'react'

/**
 * The Workspace editor and the page it is editing, talking.
 *
 * The editor shows the REAL site in a frame (a draft, by preview token) — it
 * never re-implements a section. This is the small bridge that makes that
 * frame editable by pointing: clicking a section here tells the editor which
 * one ("locah-editor:select"), and the editor tells this page which section
 * it has open ("locah-editor:focus") so it scrolls into view and is outlined.
 *
 * Rendered only on a preview (`is_preview`) and only does anything inside a
 * frame, so a visitor's page never carries it. Messages hold a section id and
 * nothing else; an unknown id is ignored. While it is listening, links and
 * buttons inside a section do not navigate on a plain click — the click
 * selects — so an owner arranging their page is not thrown to another one.
 * Holding Alt lets a click through.
 */
export function EditorBridge() {
  useEffect(() => {
    if (window.parent === window) return
    const root = document.querySelector<HTMLElement>('[data-locah-site]')
    if (!root) return
    root.setAttribute('data-editing', '')

    const mark = (id: string | null, scroll: boolean) => {
      root.querySelectorAll('[data-section-id][data-selected]').forEach((el) => el.removeAttribute('data-selected'))
      if (!id) return
      const wrapper = root.querySelector<HTMLElement>(`[data-section-id="${CSS.escape(id)}"]`)
      if (!wrapper) return
      wrapper.setAttribute('data-selected', '')
      if (scroll) wrapper.firstElementChild?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }

    const onClick = (event: MouseEvent) => {
      if (event.altKey) return
      const target = event.target as HTMLElement | null
      const wrapper = target?.closest<HTMLElement>('[data-section-id]')
      if (!wrapper) return
      event.preventDefault()
      event.stopPropagation()
      const id = wrapper.getAttribute('data-section-id') || ''
      mark(id, false)
      window.parent.postMessage({ type: 'locah-editor:select', sectionId: id }, '*')
    }

    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; sectionId?: string; y?: number } | null
      if (!data) return
      if (data.type === 'locah-editor:focus') mark(typeof data.sectionId === 'string' ? data.sectionId : null, true)
      // After a save the frame reloads: go back to where the owner was looking.
      if (data.type === 'locah-editor:restore' && typeof data.y === 'number') {
        window.scrollTo({ top: data.y, behavior: 'instant' as ScrollBehavior })
      }
    }
    // Where the owner is looking, so the editor can bring them back to it.
    let told = 0
    const onScroll = () => {
      const now = Date.now()
      if (now - told < 150) return
      told = now
      window.parent.postMessage({ type: 'locah-editor:scroll', y: Math.round(window.scrollY) }, '*')
    }

    document.addEventListener('click', onClick, true)
    window.addEventListener('message', onMessage)
    window.addEventListener('scroll', onScroll, { passive: true })
    window.parent.postMessage({ type: 'locah-editor:ready' }, '*')
    return () => {
      document.removeEventListener('click', onClick, true)
      window.removeEventListener('message', onMessage)
      window.removeEventListener('scroll', onScroll)
      root.removeAttribute('data-editing')
    }
  }, [])
  return null
}

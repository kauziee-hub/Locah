'use client'

/**
 * Look & menu — the site's colours, lettering and the links in its header.
 *
 * The same Design controls the editor has, and the header menu as a list an
 * owner can rename, reorder, add to and remove from. (This page used to be two
 * hex boxes and a "Navigation JSON" textarea, and saving it replaced the whole
 * theme — erasing the design the site was built with.)
 */

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { DesignPanel } from '../preview/DesignPanel'
import { saveNavigation } from '../preview/structure-actions'

type Link = { label: string; path: string }
type PageRef = { title: string; slug: string }

export function ThemeEditor({
  businessId,
  theme,
  navigation,
  pages,
}: {
  businessId: string
  theme: Record<string, unknown>
  navigation: Link[]
  pages: PageRef[]
}) {
  const router = useRouter()
  const [links, setLinks] = useState<Link[]>(navigation.map((l) => ({ label: String(l.label || ''), path: String(l.path || '/') })))
  const [status, setStatus] = useState<{ msg: string; error: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const pathOf = (page: PageRef) => (page.slug === 'home' ? '/' : `/${page.slug}`)
  const known = pages.map(pathOf)

  const save = async (next: Link[]) => {
    setLinks(next)
    const clean = next.map((l) => ({ label: l.label.trim(), path: l.path })).filter((l) => l.label)
    setBusy(true)
    setStatus({ msg: 'Saving…', error: false })
    const res = await saveNavigation(businessId, clean)
    setBusy(false)
    setStatus(res.ok ? { msg: 'Menu saved to your draft', error: false } : { msg: res.error, error: true })
    if (res.ok) router.refresh()
  }
  const move = (index: number, by: number) => {
    const to = index + by
    if (to < 0 || to >= links.length) return
    const next = [...links]
    const [row] = next.splice(index, 1)
    next.splice(to, 0, row)
    void save(next)
  }
  const unlinked = pages.filter((p) => !links.some((l) => l.path === pathOf(p)))

  return (
    <div style={{ display: 'grid', gap: '2rem', maxWidth: '44rem' }}>
      <section aria-labelledby="look-h">
        <h2 id="look-h" style={{ fontSize: '1.15rem', marginBottom: '0.25rem' }}>
          Colours, lettering and shape
        </h2>
        <div className="ed__rail">
          <DesignPanel
            businessId={businessId}
            theme={theme}
            onChanged={() => router.refresh()}
            onStatus={(msg, error = false) => setStatus({ msg, error })}
          />
        </div>
      </section>

      <section aria-labelledby="menu-h">
        <h2 id="menu-h" style={{ fontSize: '1.15rem', marginBottom: '0.25rem' }}>
          Links in your site’s header
        </h2>
        <p className="ed-help" style={{ marginBottom: '0.8rem' }}>
          What visitors can jump to from the top of every page. Rename a link, change its order, or take it out.
        </p>
        <div className="ed-nav">
          {links.map((link, index) => (
            <div className="ed-nav__row" key={`${link.path}-${index}`}>
              <input
                className="ed-input"
                aria-label={`Link ${index + 1} name`}
                defaultValue={link.label}
                maxLength={40}
                onBlur={(e) => {
                  if (e.target.value.trim() && e.target.value !== link.label) {
                    void save(links.map((l, i) => (i === index ? { ...l, label: e.target.value } : l)))
                  }
                }}
              />
              <select
                className="ed-select"
                aria-label={`Link ${index + 1} goes to`}
                value={link.path}
                disabled={busy}
                onChange={(e) => void save(links.map((l, i) => (i === index ? { ...l, path: e.target.value } : l)))}
              >
                {!known.includes(link.path) ? <option value={link.path}>{link.path}</option> : null}
                {pages.map((page) => (
                  <option key={page.slug} value={pathOf(page)}>
                    {page.title} page
                  </option>
                ))}
              </select>
              <div className="ed-nav__tools">
                <button type="button" className="ed-icon" aria-label={`Move ${link.label} earlier`} title="Earlier"
                  disabled={busy || index === 0} onClick={() => move(index, -1)}>
                  ↑
                </button>
                <button type="button" className="ed-icon" aria-label={`Move ${link.label} later`} title="Later"
                  disabled={busy || index === links.length - 1} onClick={() => move(index, 1)}>
                  ↓
                </button>
                <button type="button" className="ed-icon" aria-label={`Remove ${link.label} from the header`} title="Remove"
                  disabled={busy || links.length <= 1} onClick={() => void save(links.filter((_, i) => i !== index))}>
                  ✕
                </button>
              </div>
            </div>
          ))}
          {unlinked.length ? (
            <div className="ed-ask__ideas">
              {unlinked.map((page) => (
                <button
                  key={page.slug}
                  type="button"
                  className="ed-ask__idea"
                  disabled={busy}
                  onClick={() => void save([...links, { label: page.title, path: pathOf(page) }])}
                >
                  + Add “{page.title}”
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </section>

      {status ? (
        <p className={`ed-status${status.error ? ' is-error' : ''}`} role="status">
          {status.msg}
        </p>
      ) : null}
    </div>
  )
}

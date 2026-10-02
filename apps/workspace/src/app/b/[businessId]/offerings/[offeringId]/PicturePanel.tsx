'use client'

import { useRouter } from 'next/navigation'
import { useRef, useState, useTransition } from 'react'
import { drawPicture, finishPictureUpload, keepPicture, setPictures, startPictureUpload } from '../offering-actions'
import type { OfferingPicture } from '../types'

const ACCEPTED = 'image/jpeg,image/png,image/webp'

/**
 * The offering's pictures. The first one is what the website, the Marketplace
 * and the counter show. A real photo is best; "Draw a picture" asks LOCAH for
 * an illustrative one, which stays marked as drawn until the owner keeps it.
 * Removing a picture only detaches it — the file stays in Brand & media.
 */
export function PicturePanel({ businessId, offeringId, title, pictures, canChange }: {
  businessId: string
  offeringId: string
  title: string
  pictures: OfferingPicture[]
  canChange: boolean
}) {
  const router = useRouter()
  const file = useRef<HTMLInputElement>(null)
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const ids = pictures.map((p) => p.id)

  const run = (work: () => Promise<{ ok: boolean; message?: string }>) => {
    setError(null)
    start(async () => {
      const r = await work()
      if (!r.ok) return setError(r.message ?? 'That did not work. Try again.')
      router.refresh()
    })
  }

  const upload = (picked: File) =>
    run(async () => {
      const started = await startPictureUpload(businessId, { type: picked.type, size: picked.size, name: picked.name })
      if (!started.ok) return started
      const put = await fetch(started.data!.uploadUrl, { method: 'PUT', headers: { 'Content-Type': picked.type }, body: picked })
      if (!put.ok) return { ok: false, message: `Upload failed (${put.status}).` }
      return finishPictureUpload(businessId, offeringId, started.data!.assetId, ids)
    })

  return (
    <section className="bos-card" aria-labelledby="pictures-h" style={{ marginTop: '1rem' }}>
      <h2 id="pictures-h">Picture</h2>
      <p className="bos-hint">
        The first picture is the one customers see on your website and the Marketplace. A real photo of {title} is
        best.
      </p>
      {pictures.length ? (
        <ul className="bos-pictures">
          {pictures.map((p, i) => (
            <li key={p.id}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {p.url ? <img src={p.url} alt={p.alt_text ?? ''} /> : null}
              <span className="bos-hint" style={{ margin: 0 }}>
                {i === 0 ? 'Shown first' : `Picture ${i + 1}`}
                {p.draft ? ' · drawn by LOCAH, not kept yet' : ''}
              </span>
              {canChange ? (
                <div className="bos-pictures__actions">
                  {p.draft ? (
                    <button type="button" className="btn btn-ghost" disabled={pending}
                            onClick={() => run(() => keepPicture(businessId, offeringId, p.id))}>Keep</button>
                  ) : null}
                  {i > 0 ? (
                    <button type="button" className="btn btn-ghost" disabled={pending}
                            onClick={() => run(() => setPictures(businessId, offeringId, [p.id, ...ids.filter((x) => x !== p.id)]))}>
                      Show first
                    </button>
                  ) : null}
                  <button type="button" className="btn btn-ghost" disabled={pending}
                          onClick={() => run(() => setPictures(businessId, offeringId, ids.filter((x) => x !== p.id)))}>
                    Remove
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="bos-empty">No picture yet — customers see the name and price only.</p>
      )}
      {canChange ? (
        <div className="bos-pictures__add">
          <input ref={file} type="file" accept={ACCEPTED} hidden
                 onChange={(ev) => { const f = ev.target.files?.[0]; ev.target.value = ''; if (f) upload(f) }} />
          <button type="button" className="btn btn-primary" disabled={pending} onClick={() => file.current?.click()}>
            Upload a photo
          </button>
          <button type="button" className="btn btn-ghost" disabled={pending}
                  onClick={() => run(() => drawPicture(businessId, offeringId))}>
            Draw a picture
          </button>
          {pending ? <span className="bos-hint" style={{ margin: 0 }}>Working…</span> : null}
        </div>
      ) : null}
      {error ? <p className="bos-error" role="alert">{error}</p> : null}
    </section>
  )
}

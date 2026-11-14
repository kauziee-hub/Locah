'use client'

/**
 * Ask LOCAH — change the site by saying so.
 *
 * "Make the headings bigger", "move the menu above our story", "change the
 * colour to maroon". The same governed edits the other two tabs make, asked
 * for in words (spelling slips and all). LOCAH answers with what it did and,
 * plainly, what it could not do — it never claims a change it did not make.
 */

import React, { useEffect, useRef, useState } from 'react'
import { askLocah } from './structure-actions'

type Turn = { who: 'owner' | 'locah'; text: string; failed?: boolean }

const IDEAS = [
  'Make the headings bigger',
  'Change the colour to maroon and gold',
  'Use a more elegant font',
  'Move the menu above our story',
  'Hide the gallery',
  'Rounded buttons',
]

export function AssistantPanel({
  businessId,
  pageId,
  pageTitle,
  onChanged,
}: {
  businessId: string
  pageId?: string
  pageTitle?: string
  /** `structure` when sections moved, appeared, vanished or were reworded. */
  onChanged: (what: { structure: boolean; theme: boolean }) => void
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [turns, busy])

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || busy) return
    setTurns((t) => [...t, { who: 'owner', text: message }])
    setDraft('')
    setBusy(true)
    const res = await askLocah(businessId, message, pageId)
    setBusy(false)
    if (!res.ok) {
      setTurns((t) => [...t, { who: 'locah', text: res.error, failed: true }])
      return
    }
    setTurns((t) => [...t, { who: 'locah', text: res.data.reply, failed: !res.data.changed && !res.data.jobs?.length }])
    if (res.data.changed || res.data.jobs?.length) {
      onChanged({ structure: true, theme: res.data.theme_changed })
    }
  }

  return (
    <div className="ed-ask">
      <div className="ed-ask__log" aria-live="polite">
        {turns.length === 0 ? (
          <div className="ed-ask__intro">
            <p>
              Tell LOCAH what to change{pageTitle ? ` on ${pageTitle}` : ''}, in your own words. It changes your
              draft and shows you here.
            </p>
            <div className="ed-ask__ideas">
              {IDEAS.map((idea) => (
                <button key={idea} type="button" className="ed-ask__idea" disabled={busy} onClick={() => send(idea)}>
                  {idea}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {turns.map((turn, i) => (
          <p key={i} className="ed-ask__turn" data-who={turn.who} data-failed={turn.failed || undefined}>
            {turn.text}
          </p>
        ))}
        {busy ? (
          <p className="ed-ask__turn" data-who="locah" data-pending>
            Working on it…
          </p>
        ) : null}
        <div ref={end} />
      </div>
      <form
        className="ed-ask__form"
        onSubmit={(e) => {
          e.preventDefault()
          void send(draft)
        }}
      >
        <label className="ed-label" htmlFor="ed-ask-box">
          What should change?
        </label>
        <textarea
          id="ed-ask-box"
          className="ed-input ed-input--area ed-input--short"
          value={draft}
          maxLength={600}
          placeholder="e.g. make the text bigger and move contact to the top"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send(draft)
            }
          }}
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !draft.trim()}>
          {busy ? 'Changing…' : 'Change it'}
        </button>
      </form>
    </div>
  )
}

'use client'

import Link from 'next/link'
import { useRef, useState, useTransition } from 'react'
import { checkin, type CheckinResult } from '../member-actions'

const WORDS: Record<string, string> = { green: 'Come in', amber: 'In grace — ask them to renew', red: 'Not allowed in' }

/** A scanner types the code and presses Enter; the answer is the colour. */
export function CheckinDesk({ businessId }: { businessId: string }) {
  const [pending, start] = useTransition()
  const [result, setResult] = useState<CheckinResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className="bos-money">
      <form
        className="bos-money__form"
        onSubmit={(e) => {
          e.preventDefault()
          const code = String(new FormData(e.currentTarget).get('code') || '').trim()
          setError(null)
          start(async () => {
            const r = await checkin(businessId, code)
            if (r.ok && r.data) setResult(r.data)
            else {
              setResult(null)
              setError(r.ok ? 'No answer' : r.message)
            }
            if (input.current) {
              input.current.value = ''
              input.current.focus()
            }
          })
        }}
      >
        <label className="bos-money__wide">
          <span>Member code</span>
          <input ref={input} name="code" required minLength={6} autoFocus autoComplete="off" autoCapitalize="characters" inputMode="text" />
        </label>
        <button type="submit" disabled={pending}>
          {pending ? 'Checking…' : 'Check'}
        </button>
      </form>
      {error ? (
        <p className="bos-status bos-error" role="alert">
          {error === 'Membership not found' ? 'No membership with that code.' : error}
        </p>
      ) : null}
      {result ? (
        <section className={`bos-checkin bos-checkin--${result.colour}`} role="status" aria-live="polite">
          <p className="bos-checkin__word">{WORDS[result.colour]}</p>
          <p className="bos-checkin__who">
            {result.member || 'Member'} · {result.plan}
          </p>
          <p>
            {result.reason}
            {result.last_day || result.valid_until ? ` · valid until ${new Date(result.last_day ? `${result.last_day}T12:00:00` : result.valid_until ?? '').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}` : ''}
            {result.days_remaining !== null && result.decision !== 'denied' ? ` · ${result.days_remaining} days left` : ''}
            {result.sessions_remaining !== null ? ` · ${result.sessions_remaining} sessions left` : ''}
          </p>
          <Link href={`/b/${businessId}/memberships/${result.enrolment_id}`}>{result.renew || 'Open their membership'} →</Link>
        </section>
      ) : null}
    </div>
  )
}

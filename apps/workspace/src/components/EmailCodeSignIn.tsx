'use client'

import { useEffect, useRef, useState } from 'react'
import {
  isCompleteOtp,
  normalizeOtp,
  OTP_LENGTH,
  OTP_PROBLEM_WORDS,
  RESEND_COOLDOWN_SECONDS,
  requestEmailOtp,
  verifyEmailOtp,
  type OtpAuthClient,
} from '@platform/auth'

/**
 * Sign in — or create a login — with a six-digit code emailed to the person.
 *
 * No link is sent, so nothing depends on the auth project's URL settings, and
 * the person never leaves this page: an invitation, a destination or a half-
 * finished task is still right here when the code is accepted. `onSignedIn`
 * runs once Supabase has set the session cookie; it decides where to go next
 * (the API re-checks everything there). The shared, framework-free logic is in
 * @platform/auth; this is the Workspace's own presentation of it.
 */
export function EmailCodeSignIn({
  supabase,
  createAccount,
  onSignedIn,
  initialEmail = '',
  sendLabel = 'Email me a code',
  verifyLabel = 'Verify and continue',
}: {
  supabase: OtpAuthClient
  /** True: an unknown email becomes a new LOCAH login. False: sign-in only. */
  createAccount: boolean
  onSignedIn: () => void | Promise<void>
  initialEmail?: string
  sendLabel?: string
  verifyLabel?: string
}) {
  const [email, setEmail] = useState(initialEmail)
  const [code, setCode] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cooldown, setCooldown] = useState(0)
  const codeInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (cooldown <= 0) return
    const id = window.setTimeout(() => setCooldown((s) => s - 1), 1000)
    return () => window.clearTimeout(id)
  }, [cooldown])

  useEffect(() => {
    if (sentTo) codeInput.current?.focus()
  }, [sentTo])

  async function send() {
    setError(null)
    setBusy(true)
    const r = await requestEmailOtp(supabase, email, { createAccount })
    setBusy(false)
    if (!r.ok) return setError(OTP_PROBLEM_WORDS[r.problem])
    setCode('')
    setSentTo(email.trim())
    setCooldown(RESEND_COOLDOWN_SECONDS)
  }

  async function verify(value: string) {
    if (busy) return
    setError(null)
    setBusy(true)
    const r = await verifyEmailOtp(supabase, email, value)
    if (!r.ok) {
      setBusy(false)
      return setError(OTP_PROBLEM_WORDS[r.problem])
    }
    await onSignedIn()
    setBusy(false)
  }

  function onCode(raw: string) {
    const value = normalizeOtp(raw)
    setCode(value)
    if (isCompleteOtp(value)) void verify(value)
  }

  return (
    <form
      style={{ display: 'grid', gap: '0.85rem' }}
      noValidate={Boolean(sentTo)}
      onSubmit={(e) => {
        e.preventDefault()
        if (!sentTo) void send()
        else if (isCompleteOtp(code)) void verify(code)
        else setError(OTP_PROBLEM_WORDS.incomplete_code)
      }}
    >
      {!sentTo ? (
        <label style={{ display: 'grid', gap: 6 }}>
          <span className="bos-label">Email</span>
          <input type="email" autoComplete="email" inputMode="email" required value={email}
            onChange={(e) => setEmail(e.target.value)} />
        </label>
      ) : (
        <>
          <p className="bos-hint" role="status" aria-live="polite" style={{ margin: 0 }}>
            We sent a {OTP_LENGTH}-digit code to <strong>{sentTo}</strong>. It expires soon — use the newest one.
          </p>
          <label style={{ display: 'grid', gap: 6 }}>
            <span className="bos-label">{OTP_LENGTH}-digit code</span>
            <input
              ref={codeInput}
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={OTP_LENGTH + 4}
              value={code}
              onChange={(e) => onCode(e.target.value)}
              style={{ fontSize: '1.4rem', letterSpacing: '0.45em', textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}
            />
          </label>
        </>
      )}
      <button type="submit" disabled={busy} className="btn btn-primary">
        {busy ? (sentTo ? 'Checking…' : 'Sending code…') : sentTo ? verifyLabel : sendLabel}
      </button>
      {sentTo ? (
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button type="button" className="btn-quiet" disabled={busy || cooldown > 0} onClick={() => void send()}>
            {cooldown > 0 ? `Send a new code in ${cooldown}s` : 'Send a new code'}
          </button>
          <button type="button" className="btn-quiet" disabled={busy}
            onClick={() => { setSentTo(null); setCode(''); setError(null) }}>
            Use a different email
          </button>
        </div>
      ) : null}
      {error ? <p className="bos-status bos-error" role="alert" style={{ margin: 0 }}>{error}</p> : null}
    </form>
  )
}

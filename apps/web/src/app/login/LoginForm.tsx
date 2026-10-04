'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  isCompleteOtp,
  normalizeOtp,
  OTP_LENGTH,
  OTP_PROBLEM_WORDS,
  RESEND_COOLDOWN_SECONDS,
  requestEmailOtp,
  resolveDestinationIntent,
  verifyEmailOtp,
  type OtpProblem,
} from '@platform/auth'
import { createClient } from '@/lib/supabase/client'
import { Wordmark } from '@/components/public/Wordmark'

type Intent = 'signin' | 'signup'
type Step = 'email' | 'code' | 'password'

/**
 * Turn a password sign-in failure into something the person can act on.
 *
 * The provider's own wording describes its internals — "Anonymous sign-ins are
 * disabled" is what it says when the form was submitted empty — and putting
 * that in front of someone trying to open their business tells them nothing
 * and exposes how the platform is built. Anything unrecognised falls back to a
 * plain sentence rather than the raw message.
 */
function humanPasswordError(message: string): string {
  const m = message.toLowerCase()
  if (m.includes('anonymous')) return 'Enter your email and password to continue.'
  if (m.includes('invalid login credentials')) return 'That email and password do not match. Check both, or sign in with an email code.'
  if (m.includes('email not confirmed')) return 'This email is not confirmed yet. Sign in with an email code instead — it confirms it too.'
  if (m.includes('rate limit') || m.includes('too many')) return 'Too many attempts. Wait a minute and try again.'
  return 'We could not sign you in. Check the details, or sign in with an email code.'
}

/**
 * Sign in or create an account with an eight-digit code sent by email.
 *
 * There is no confirmation link to click: a link carries a host, and when the
 * auth project's URL settings and the deployment disagree the link points
 * somewhere else entirely (a real inbox once received a localhost link). The
 * code is typed back here, on the page the person is already on, so the
 * Destination Intent in this URL is what they return to — checkout, a booking,
 * a Business, onboarding — validated by `resolveDestinationIntent`.
 *
 * Password sign-in stays available for accounts that have a password.
 */
export function LoginForm({ initialMode = 'signin' }: { initialMode?: Intent }) {
  const [mode, setMode] = useState<Intent>(initialMode)
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [noAccount, setNoAccount] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const codeInput = useRef<HTMLInputElement>(null)
  const router = useRouter()
  const searchParams = useSearchParams()
  const supabase = createClient()
  const destination = resolveDestinationIntent(searchParams.get('destination'))

  useEffect(() => {
    if (cooldown <= 0) return
    const id = window.setTimeout(() => setCooldown((s) => s - 1), 1000)
    return () => window.clearTimeout(id)
  }, [cooldown])

  useEffect(() => {
    if (step === 'code') codeInput.current?.focus()
  }, [step])

  function problem(p: OtpProblem) {
    setNoAccount(p === 'no_account')
    setError(OTP_PROBLEM_WORDS[p])
  }

  function switchMode(next: Intent) {
    setMode(next)
    setStep('email')
    setError(null)
    setNotice(null)
    setNoAccount(false)
    setCode('')
  }

  async function sendCode(createAccount = mode === 'signup') {
    setError(null)
    setNotice(null)
    setNoAccount(false)
    setBusy(true)
    const sent = await requestEmailOtp(supabase, email, { createAccount })
    setBusy(false)
    if (!sent.ok) return problem(sent.problem)
    setCode('')
    setStep('code')
    setCooldown(RESEND_COOLDOWN_SECONDS)
    setNotice(`We sent a ${OTP_LENGTH}-digit code to ${email.trim()}. It expires soon — use the newest one.`)
  }

  async function verify(value: string) {
    if (busy) return
    setError(null)
    setBusy(true)
    const done = await verifyEmailOtp(supabase, email, value)
    if (!done.ok) {
      setBusy(false)
      return problem(done.problem)
    }
    // Keep the button busy through the navigation: the session cookie is set,
    // and the destination re-checks what this person may do there.
    router.replace(destination)
    router.refresh()
  }

  async function signInWithPassword() {
    setError(null)
    setNotice(null)
    setBusy(true)
    const { error: err } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
    if (err) {
      setBusy(false)
      return setError(humanPasswordError(err.message))
    }
    router.replace(destination)
    router.refresh()
  }

  function onCodeChange(raw: string) {
    const value = normalizeOtp(raw)
    setCode(value)
    // A pasted or autofilled code verifies at once; typing does on the 6th digit.
    if (isCompleteOtp(value)) void verify(value)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (step === 'email') return sendCode()
    if (step === 'code') return isCompleteOtp(code) ? verify(code) : problem('incomplete_code')
    return signInWithPassword()
  }

  const heading =
    step === 'code' ? 'Check your email.' : mode === 'signin' ? 'Welcome back.' : 'Let’s get started.'
  const lead =
    step === 'code'
      ? 'Enter the code to continue. Keep this page open — you will come straight back to where you were.'
      : mode === 'signin'
        ? 'Sign in to return to your business.'
        : 'Create an account with your email. We will send you a code — no password needed.'
  const submitLabel = busy
    ? step === 'code'
      ? 'Checking…'
      : step === 'password'
        ? 'Signing in…'
        : 'Sending code…'
    : step === 'code'
      ? 'Verify and continue'
      : step === 'password'
        ? 'Sign in'
        : 'Email me a code'

  return (
    <div className="locah-public ob-shell">
      <header className="ob-shell__head">
        <div className="lc-container">
          <Link href="/" aria-label="LOCAH home">
            <Wordmark />
          </Link>
        </div>
      </header>

      <main className="lc-container lc-container--wide ui-auth-layout">
        <div className="ui-auth-story"><p className="lc-eyebrow">Your business has a home here</p><h1>Good to have you <em>here.</em></h1><p>One place to shape your presence, connect your tools and keep the day moving.</p><div className="ui-auth-story__footer">Your business. Your pace. One connected place.</div></div>
        <form className="ui-auth-form" onSubmit={handleSubmit} noValidate={step === 'code'}>
          {step !== 'code' ? (
            <div className="ui-auth-switch" role="group" aria-label="Account action"><button type="button" aria-pressed={mode === 'signin'} onClick={() => switchMode('signin')}>Sign in</button><button type="button" aria-pressed={mode === 'signup'} onClick={() => switchMode('signup')}>Create account</button></div>
          ) : null}
          <h2>{heading}</h2>
          <p className="lc-muted lc-small" style={{ marginBottom: 'var(--sp-6)' }}>{lead}</p>

          {error ? (
            <div role="alert" className="ob-error" style={{ marginBottom: 'var(--sp-4)' }}>
              <p>{error}</p>
              {noAccount ? (
                <p style={{ marginTop: '0.4rem' }}>
                  <button type="button" className="lc-btn lc-btn--ghost lc-btn--sm" onClick={() => { switchMode('signup'); void sendCode(true) }}>
                    Create an account with {email.trim()}
                  </button>
                </p>
              ) : null}
            </div>
          ) : null}

          {notice ? (
            <div role="status" aria-live="polite" className="ob-notice" style={{ marginBottom: 'var(--sp-4)' }}>
              <p>{notice}</p>
            </div>
          ) : null}

          {step !== 'code' ? (
            <div className="ob-field">
              <label htmlFor="email" className="ob-label">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                inputMode="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="ob-input"
              />
            </div>
          ) : (
            <div className="ob-field">
              <label htmlFor="otp" className="ob-label">
                {OTP_LENGTH}-digit code
              </label>
              <input
                ref={codeInput}
                id="otp"
                name="otp"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={OTP_LENGTH + 4}
                aria-describedby="otp-help"
                value={code}
                onChange={(e) => onCodeChange(e.target.value)}
                className="ob-input"
                style={{ fontSize: '1.5rem', letterSpacing: '0.5em', textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}
              />
              <p id="otp-help" className="lc-muted lc-small" style={{ marginTop: '0.35rem' }}>
                Sent to <strong>{email.trim()}</strong>. You can paste the whole code.
              </p>
            </div>
          )}

          {step === 'password' ? (
            <div className="ob-field">
              <label htmlFor="password" className="ob-label">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="ob-input"
              />
            </div>
          ) : null}

          <div style={{ display: 'grid', gap: '0.6rem' }}>
            <button type="submit" disabled={busy} className="lc-btn lc-btn--primary lc-btn--block">
              {submitLabel}
            </button>
            {step === 'code' ? (
              <>
                <button type="button" className="lc-btn lc-btn--ghost lc-btn--block" disabled={busy || cooldown > 0} onClick={() => void sendCode()}>
                  {cooldown > 0 ? `Send a new code in ${cooldown}s` : 'Send a new code'}
                </button>
                <button type="button" className="lc-btn lc-btn--ghost lc-btn--block" disabled={busy} onClick={() => { setStep('email'); setCode(''); setError(null); setNotice(null) }}>
                  Use a different email
                </button>
              </>
            ) : mode === 'signin' ? (
              <button type="button" className="lc-btn lc-btn--ghost lc-btn--block" onClick={() => { setStep(step === 'password' ? 'email' : 'password'); setError(null) }}>
                {step === 'password' ? 'Email me a code instead' : 'Use my password instead'}
              </button>
            ) : null}
          </div>
        </form>
      </main>
    </div>
  )
}

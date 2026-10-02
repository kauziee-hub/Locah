'use client'

import { useState } from 'react'
import Link from 'next/link'
import { siteUrl } from '@platform/auth'
import { createClient } from '@/lib/supabase/client'
import { Wordmark } from '@/components/public/Wordmark'
import type { AuthFlow } from '../auth-errors'

export function AuthErrorPanel({
  flow,
  copy,
  canResend,
}: {
  flow: AuthFlow
  copy: { title: string; body: string }
  canResend: boolean
}) {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const supabase = createClient()

  const handleResend = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    // Only a password reset is re-sent as a link. A dead signup or sign-in
    // link is never replaced by another link: the email-code sign-in below
    // confirms the address too, and depends on no URL setting.
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: siteUrl('/auth/confirm?type=recovery'),
    })
    setBusy(false)
    if (error) {
      setError(error.message)
      return
    }
    // Deliberately not "we sent it to that address" — confirming which emails
    // are registered would turn this open form into an account-enumeration tool.
    setSent(true)
  }

  return (
    <div className="locah-public ob-shell">
      <header className="ob-shell__head">
        <div className="lc-container">
          <Link href="/" aria-label="LOCAH home">
            <Wordmark />
          </Link>
        </div>
      </header>

      <main className="lc-container" style={{ maxWidth: '27rem', paddingBlock: '3rem 4rem' }}>
        <div className="lc-card">
          <h1 style={{ fontSize: '1.6rem', marginBottom: '0.35rem' }}>{copy.title}</h1>
          <p className="lc-muted lc-small" style={{ marginBottom: 'var(--sp-6)' }}>
            {copy.body}
          </p>

          {sent ? (
            <div role="status" className="ob-notice">
              <p>
                If that address has a LOCAH account, a password reset link is on its way. It expires shortly, so open it soon.
              </p>
            </div>
          ) : canResend && flow === 'recovery' ? (
            <form onSubmit={handleResend}>
              {error ? (
                <div role="alert" className="ob-error" style={{ marginBottom: 'var(--sp-4)' }}>
                  <p>{error}</p>
                </div>
              ) : null}

              <div className="ob-field">
                <label htmlFor="resend-email" className="ob-label">
                  Email
                </label>
                <input
                  id="resend-email"
                  className="ob-input"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                />
              </div>

              <button className="lc-btn lc-btn--primary" type="submit" disabled={busy}>
                {busy ? 'Sending…' : 'Send a new reset link'}
              </button>
            </form>
          ) : null}

          <div style={{ marginTop: 'var(--sp-6)', display: 'grid', gap: '0.5rem' }}>
            <Link className={flow === 'recovery' ? 'lc-btn lc-btn--ghost' : 'lc-btn lc-btn--primary'} href="/login">
              Sign in with an email code
            </Link>
            <p className="lc-muted lc-small" style={{ margin: 0 }}>
              We email you a 6-digit code to type in — it also confirms your email, and no link is needed.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

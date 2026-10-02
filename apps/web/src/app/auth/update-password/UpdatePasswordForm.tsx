'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { Wordmark } from '@/components/public/Wordmark'

export function UpdatePasswordForm() {
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const router = useRouter()
  const supabase = createClient()

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) return setError('Choose a password of at least 8 characters.')
    if (password !== again) return setError('The two passwords are not the same.')
    setBusy(true)
    const { error: err } = await supabase.auth.updateUser({ password })
    setBusy(false)
    if (err) return setError('We could not save that password. Try a different one, or sign in with an email code.')
    router.replace('/')
    router.refresh()
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
        <form className="lc-card" onSubmit={save}>
          <h1 style={{ fontSize: '1.6rem', marginBottom: '0.35rem' }}>Choose a new password</h1>
          <p className="lc-muted lc-small" style={{ marginBottom: 'var(--sp-6)' }}>
            You can always sign in with an email code instead.
          </p>
          {error ? (
            <div role="alert" className="ob-error" style={{ marginBottom: 'var(--sp-4)' }}>
              <p>{error}</p>
            </div>
          ) : null}
          <div className="ob-field">
            <label htmlFor="new-password" className="ob-label">New password</label>
            <input id="new-password" className="ob-input" type="password" autoComplete="new-password" minLength={8}
              required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div className="ob-field">
            <label htmlFor="new-password-again" className="ob-label">Type it again</label>
            <input id="new-password-again" className="ob-input" type="password" autoComplete="new-password" minLength={8}
              required value={again} onChange={(e) => setAgain(e.target.value)} />
          </div>
          <button className="lc-btn lc-btn--primary lc-btn--block" type="submit" disabled={busy}>
            {busy ? 'Saving…' : 'Save password'}
          </button>
        </form>
      </main>
    </div>
  )
}

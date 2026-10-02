'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { createSupabaseBrowserClientInstance } from '@platform/auth'
import { EmailCodeSignIn } from '@/components/EmailCodeSignIn'
import { acceptInvitation } from './actions'

export type JoinView = {
  business: { id: string; name: string }
  invitation_id: string
  name: string | null
  email_hint: string
  role: { label: string; does: string | null; home: string | null }
  scope_words: string
  locations: string[]
  status: string
  expires_at: string
}

const supabase = createSupabaseBrowserClientInstance(
  process.env.NEXT_PUBLIC_SUPABASE_URL || 'http://127.0.0.1:54321',
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.signature',
)

export function JoinPanel({ view, signedInAs }: { view: JoinView; signedInAs: string | null }) {
  const router = useRouter()
  const [mode, setMode] = useState<'create' | 'signin'>('create')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [usePassword, setUsePassword] = useState(false)
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)

  const join = async () => {
    const r = await acceptInvitation(view.business.id, view.invitation_id)
    if (r.ok) {
      // A full load: the new session cookie and the business shell start fresh.
      window.location.assign(`/b/${view.business.id}`)
      return
    }
    setError(
      /not addressed/i.test(r.message)
        ? `This invitation is for ${view.email_hint}. Sign in with that email to join.`
        : r.message,
    )
  }

  const intro = (
    <section className="bos-card bos-join__intro">
      <h1>
        {view.name ? `${view.name}, join` : 'Join'} {view.business.name}
      </h1>
      <p className="bos-join__role">
        as <strong>{view.role.label}</strong>
      </p>
      <dl className="bos-join__facts">
        {view.role.does ? (
          <>
            <dt>You will</dt>
            <dd>{view.role.does}</dd>
          </>
        ) : null}
        <dt>Where</dt>
        <dd>{view.locations.length ? view.locations.join(', ') : view.scope_words}</dd>
        {view.role.home ? (
          <>
            <dt>Your home screen</dt>
            <dd>{view.role.home}</dd>
          </>
        ) : null}
      </dl>
    </section>
  )

  if (view.status !== 'pending') {
    const text =
      view.status === 'accepted'
        ? 'This link has already been used. Sign in to open the business.'
        : view.status === 'expired'
          ? `This link has expired. Ask ${view.business.name} for a new one.`
          : `This invitation was withdrawn. Ask ${view.business.name} if you should still join.`
    return (
      <>
        {intro}
        <section className="bos-card">
          <p>{text}</p>
          <Link href="/login">Sign in</Link>
        </section>
      </>
    )
  }

  if (signedInAs) {
    return (
      <>
        {intro}
        <section className="bos-card">
          <p className="bos-hint">
            Signed in as <strong>{signedInAs}</strong>. This invitation is for {view.email_hint}.
          </p>
          <div className="bos-meter__actions">
            <button type="button" disabled={pending} onClick={() => start(join)}>
              {pending ? 'Joining…' : `Join ${view.business.name}`}
            </button>
            <button
              type="button"
              className="btn-quiet"
              disabled={pending}
              onClick={() => start(async () => { await supabase.auth.signOut(); router.refresh() })}
            >
              Use a different login
            </button>
          </div>
          {error ? <p className="bos-status bos-error" role="alert">{error}</p> : null}
        </section>
      </>
    )
  }

  return (
    <>
      {intro}
      <section className="bos-card bos-join__form" style={{ display: 'grid', gap: '0.75rem' }}>
        <h2>{mode === 'create' ? 'Create your login' : 'Sign in to join'}</h2>
        <p className="bos-hint" style={{ margin: 0 }}>
          Use the email {view.business.name} added you with ({view.email_hint}). We will email you a code —
          {mode === 'create' ? ' no password to choose.' : ' or use your password.'}
        </p>
        {mode === 'signin' && usePassword ? (
          <form
            style={{ display: 'grid', gap: '0.75rem' }}
            onSubmit={(e) => {
              e.preventDefault()
              setError(null)
              start(async () => {
                const { error: err } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
                if (err) return setError('That email and password did not match. Try again, or use an email code.')
                await join()
              })
            }}
          >
            <label>
              <span className="bos-label">Email</span>
              <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label>
              <span className="bos-label">Password</span>
              <input type="password" autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} required />
            </label>
            <button type="submit" disabled={pending}>{pending ? 'One moment…' : 'Sign in and join'}</button>
          </form>
        ) : (
          // The code is checked on this page, so the invitation is still here
          // when it is accepted: create or sign in, then join, in one go.
          <EmailCodeSignIn
            key={mode}
            supabase={supabase}
            createAccount={mode === 'create'}
            onSignedIn={join}
            sendLabel="Email me a code"
            verifyLabel={mode === 'create' ? 'Create login and join' : 'Sign in and join'}
          />
        )}
        {error ? <p className="bos-status bos-error" role="alert">{error}</p> : null}
        <p className="bos-hint" style={{ margin: 0, display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <span>{mode === 'create' ? 'Already have a LOCAH login? ' : 'New to LOCAH? '}
            <button type="button" className="btn-quiet" onClick={() => { setMode(mode === 'create' ? 'signin' : 'create'); setUsePassword(false); setError(null) }}>
              {mode === 'create' ? 'Sign in instead' : 'Create a login'}
            </button>
          </span>
          {mode === 'signin' ? (
            <button type="button" className="btn-quiet" onClick={() => { setUsePassword(!usePassword); setError(null) }}>
              {usePassword ? 'Email me a code instead' : 'Use my password instead'}
            </button>
          ) : null}
        </p>
      </section>
    </>
  )
}

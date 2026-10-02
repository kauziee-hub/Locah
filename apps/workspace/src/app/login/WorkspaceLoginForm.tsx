'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { createSupabaseBrowserClientInstance } from '@platform/auth'
import { EmailCodeSignIn } from '@/components/EmailCodeSignIn'

const supabase = createSupabaseBrowserClientInstance(
  process.env.NEXT_PUBLIC_SUPABASE_URL || 'http://127.0.0.1:54321',
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.signature'
)

/**
 * Sign in on a Workspace host that cannot share the web app's session cookie.
 *
 * An email code is the default: accounts created with a code have no password,
 * and a code needs no link (so no URL setting can send it astray). Password
 * sign-in stays for accounts that have one. `destination` was validated by the
 * server page and is where the person returns.
 */
export function WorkspaceLoginForm({ destination }: { destination: string }) {
  const [method, setMethod] = useState<'code' | 'password'>('code')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const router = useRouter()

  const done = () => {
    router.replace(destination)
    router.refresh()
  }

  async function signInWithPassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    const result = await supabase.auth.signInWithPassword({ email, password })
    setBusy(false)
    if (result.error) {
      setError('We could not sign you in. Check your email and password, or sign in with an email code.')
      return
    }
    done()
  }

  return (
    <main style={{ maxWidth: 420, margin: '10vh auto', padding: '2rem', display: 'grid', gap: '1rem' }}>
      <p style={{ fontWeight: 700, color: 'var(--color-primary)', margin: 0 }}>LOCAH Workspace</p>
      <h1 style={{ margin: 0 }}>Sign in to your Workspace</h1>
      <p style={{ color: 'var(--color-muted)', margin: 0 }}>
        This Workspace has its own secure sign-in on this address. Use the same account as on Locah.
      </p>
      {method === 'code' ? (
        <EmailCodeSignIn supabase={supabase} createAccount={false} onSignedIn={done} />
      ) : (
        <form onSubmit={signInWithPassword} style={{ display: 'grid', gap: '1rem' }}>
          {error ? <p role="alert" style={{ color: 'var(--status-bad-fg)' }}>{error}</p> : null}
          <label style={{ display: 'grid', gap: 6 }}>
            Email
            <input type="email" autoComplete="email" required value={email}
              onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label style={{ display: 'grid', gap: 6 }}>
            Password
            <input type="password" autoComplete="current-password" required value={password}
              onChange={(event) => setPassword(event.target.value)} />
          </label>
          <button type="submit" disabled={busy} className="btn btn-primary">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      )}
      <button type="button" className="btn-quiet" style={{ justifySelf: 'start' }}
        onClick={() => { setMethod(method === 'code' ? 'password' : 'code'); setError('') }}>
        {method === 'code' ? 'Use my password instead' : 'Email me a code instead'}
      </button>
    </main>
  )
}

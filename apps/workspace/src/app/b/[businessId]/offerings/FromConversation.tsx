'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { addFromConversation } from './offering-actions'

/** What the owner named while setting up with LOCAH, offered as drafts — never added without asking. */
export function FromConversation({ businessId, names, revision }: { businessId: string; names: string[]; revision: number }) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)
  return (
    <section className="bos-card" aria-labelledby="from-talk-h" style={{ marginBottom: '1rem' }}>
      <h2 id="from-talk-h" style={{ marginTop: 0 }}>From your conversation with LOCAH</h2>
      <p className="bos-hint">
        You mentioned {names.join(', ')}. Add {names.length === 1 ? 'it' : 'them'} here as private drafts — you
        set the price and make each one live when it is ready.
      </p>
      <button type="button" className="btn btn-primary" disabled={pending}
              onClick={() => {
                setError(null)
                start(async () => {
                  const r = await addFromConversation(businessId, revision)
                  if (!r.ok) return setError(r.message)
                  router.refresh()
                })
              }}>
        {pending ? 'Adding…' : `Add ${names.length} as drafts`}
      </button>
      {error ? <p className="bos-error" role="alert">{error}</p> : null}
    </section>
  )
}

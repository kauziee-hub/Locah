'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'

type Result = { ok: true; data?: unknown } | { ok: false; message: string }

/**
 * One button that runs a server action and says what happened: busy while it
 * runs, the API's own reason on the page when it is refused (never the error
 * screen, never silence), and an optional "are you sure?" step for anything
 * that is hard to take back.
 */
export function ActionButton({
  run,
  label,
  busyLabel,
  confirm,
  confirmLabel,
  className,
}: {
  run: () => Promise<Result>
  label: string
  busyLabel?: string
  /** Asked before running, e.g. "Cancel ORD-12? The customer is told." */
  confirm?: string
  confirmLabel?: string
  className?: string
}) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const go = () => {
    setError(null)
    start(async () => {
      const r = await run()
      if (!r.ok) {
        setError(r.message)
        return
      }
      setAsking(false)
      router.refresh()
    })
  }

  return (
    <span className="ws-action">
      {asking ? (
        <span className="ws-action__confirm" role="group" aria-label={confirm}>
          <span>{confirm}</span>
          <button type="button" className={className} disabled={pending} onClick={go}>
            {pending ? busyLabel ?? 'Working…' : confirmLabel ?? label}
          </button>
          <button type="button" className="btn-ghost" disabled={pending} onClick={() => setAsking(false)}>Back</button>
        </span>
      ) : (
        <button type="button" className={className} disabled={pending} onClick={() => (confirm ? setAsking(true) : go())}>
          {pending ? busyLabel ?? 'Working…' : label}
        </button>
      )}
      {error ? <span className="ws-action__error" role="alert">{error}</span> : null}
    </span>
  )
}

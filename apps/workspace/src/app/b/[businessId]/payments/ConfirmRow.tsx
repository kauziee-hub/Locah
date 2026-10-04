'use client'

import { useState, useTransition } from 'react'
import { confirmPayment } from '@/lib/collect-actions'

/** "It arrived" / "Not received" for a customer's UPI payment, from the Payments overview. */
export function ConfirmRow({ businessId, paymentId, path }: { businessId: string; paymentId: string; path?: string }) {
  const [pending, start] = useTransition()
  const [msg, setMsg] = useState<string | null>(null)
  const act = (arrived: boolean) =>
    start(async () => {
      const r = await confirmPayment(businessId, path ?? `/b/${businessId}/payments`, paymentId, arrived)
      setMsg(r.ok ? (arrived ? 'Marked as received.' : 'The customer can try again.') : r.message)
    })
  return (
    <div className="bos-money__row">
      <button type="button" disabled={pending} onClick={() => act(true)}>
        It arrived
      </button>
      <button type="button" className="btn-ghost" disabled={pending} onClick={() => act(false)}>
        Not received
      </button>
      {msg ? <span className="bos-status">{msg}</span> : null}
    </div>
  )
}

'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { rupees } from '@/lib/when'
import { markPaymentReceived, recordRefund } from '../actions'

/** "Money received" for a cash-on-delivery or pay-at-the-business payment. */
export function MarkReceived({ businessId, paymentId, amount }: { businessId: string; paymentId: string; amount: number }) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [sure, setSure] = useState(false)
  return (
    <section className="bos-card bos-pay__action" aria-labelledby="pay-received">
      <h2 id="pay-received">Money received?</h2>
      <p className="bos-hint">Mark it paid only once you have the {rupees(amount)} in hand.</p>
      {sure ? (
        <div className="bos-pay__confirm" role="group" aria-label="Confirm">
          <button type="button" disabled={pending} onClick={() => {
            setError(null)
            start(async () => {
              const r = await markPaymentReceived(businessId, paymentId)
              if (!r.ok) {
                setError(r.message)
                return
              }
              setSure(false)
              router.refresh()
            })
          }}>
            {pending ? 'Saving…' : `Yes, I received ${rupees(amount)}`}
          </button>
          <button type="button" className="btn-ghost" disabled={pending} onClick={() => setSure(false)}>Cancel</button>
        </div>
      ) : (
        <button type="button" onClick={() => setSure(true)}>Mark as paid</button>
      )}
      {error ? <p className="bos-error" role="alert">{error}</p> : null}
    </section>
  )
}

const REASONS = ['Order cancelled', 'Item not available', 'Customer returned it', 'Paid twice', 'Charged too much']

/**
 * Record money given back. LOCAH records the refund (and keeps the order and
 * totals right); the money itself goes back the way the owner chooses.
 */
export function RefundForm({
  businessId,
  paymentId,
  refundable,
  online,
}: {
  businessId: string
  paymentId: string
  refundable: number
  online: boolean
}) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const [amount, setAmount] = useState(String(refundable))
  const [reason, setReason] = useState('')
  const [other, setOther] = useState('')
  const [step, setStep] = useState<'form' | 'confirm' | 'done'>('form')
  const [error, setError] = useState<string | null>(null)
  // One key for this form: a double-click or a retry records the refund once.
  const [key, setKey] = useState(() => crypto.randomUUID())
  const value = Number(amount)
  const why = reason === 'Other' ? other.trim() : reason
  const invalid = !(value > 0) ? 'Enter how much to refund.'
    : value > refundable ? `You can refund up to ${rupees(refundable)}.`
    : !why ? 'Choose why you are refunding.'
    : null

  if (step === 'done') {
    return (
      <section className="bos-card bos-pay__action" aria-live="polite">
        <h2>Refund recorded</h2>
        <p className="bos-hint">{rupees(value)} is recorded as refunded.</p>
        <button type="button" className="btn-ghost" onClick={() => {
          setStep('form')
          setKey(crypto.randomUUID())
        }}>Record another refund</button>
      </section>
    )
  }

  return (
    <section className="bos-card bos-pay__action" aria-labelledby="pay-refund">
      <h2 id="pay-refund">Refund</h2>
      <p className="bos-hint">
        {online
          ? 'Send the money back to the customer, then record it here so the order and your totals stay right.'
          : 'Give the money back (cash, UPI or bank transfer), then record it here so the order and your totals stay right.'}
      </p>
      {step === 'form' ? (
        <div className="bos-pay__form">
          <label className="bos-label" htmlFor="refund-amount">Amount (up to {rupees(refundable)})</label>
          <input id="refund-amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <label className="bos-label" htmlFor="refund-reason">Why</label>
          <select id="refund-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Choose a reason</option>
            {REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
            <option value="Other">Something else</option>
          </select>
          {reason === 'Other' ? (
            <input aria-label="Reason" maxLength={200} placeholder="Say why" value={other}
                   onChange={(e) => setOther(e.target.value)} />
          ) : null}
          {invalid && (amount !== String(refundable) || reason) ? <p className="bos-fieldhelp">{invalid}</p> : null}
          <div>
            <button type="button" disabled={!!invalid} onClick={() => { setError(null); setStep('confirm') }}>
              Continue
            </button>
          </div>
        </div>
      ) : (
        <div className="bos-pay__confirm" role="group" aria-label="Confirm the refund">
          <p><strong>Record a refund of {rupees(value)}?</strong> Reason: {why}. This can&apos;t be undone.</p>
          <button type="button" className="btn-danger" disabled={pending} onClick={() => {
            setError(null)
            start(async () => {
              const r = await recordRefund(businessId, paymentId, { amount: value, reason: why, idempotency_key: key })
              if (!r.ok) {
                setError(r.message)
                return
              }
              setStep('done')
              router.refresh()
            })
          }}>
            {pending ? 'Recording…' : `Record refund of ${rupees(value)}`}
          </button>
          <button type="button" className="btn-ghost" disabled={pending} onClick={() => setStep('form')}>Back</button>
        </div>
      )}
      {error ? <p className="bos-error" role="alert">{error}</p> : null}
    </section>
  )
}

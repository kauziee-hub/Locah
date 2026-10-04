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

type RefundAnswer = { refund?: { status: string; kind: string; failure_reason: string | null } }

/**
 * Give money back. An online payment a provider collected is refunded THROUGH
 * that provider (LOCAH asks it; the refund shows "in progress" until the
 * provider confirms). Anything else — or an online payment the owner already
 * gave back another way — is recorded: LOCAH moves no money then.
 */
export function RefundForm({
  businessId,
  paymentId,
  refundable,
  viaProvider,
}: {
  businessId: string
  paymentId: string
  refundable: number
  /** An online payment a provider collected: refunds go through the provider. */
  viaProvider: boolean
}) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const [amount, setAmount] = useState(String(refundable))
  const [reason, setReason] = useState('')
  const [other, setOther] = useState('')
  const [manual, setManual] = useState(!viaProvider)
  const [step, setStep] = useState<'form' | 'confirm' | 'done'>('form')
  const [outcome, setOutcome] = useState<'recorded' | 'processing' | 'succeeded'>('recorded')
  const [error, setError] = useState<string | null>(null)
  // One key for this form: a double-click or a retry records the refund once.
  const [key, setKey] = useState(() => crypto.randomUUID())
  const value = Number(amount)
  const why = reason === 'Other' ? other.trim() : reason
  const throughProvider = viaProvider && !manual
  const invalid = !(value > 0) ? 'Enter how much to refund.'
    : value > refundable ? `You can refund up to ${rupees(refundable)}.`
    : !why ? 'Choose why you are refunding.'
    : null

  if (step === 'done') {
    return (
      <section className="bos-card bos-pay__action" aria-live="polite">
        <h2>{outcome === 'processing' ? 'Refund requested' : outcome === 'succeeded' ? 'Refunded' : 'Refund recorded'}</h2>
        <p className="bos-hint">
          {outcome === 'processing'
            ? `The payment provider accepted the refund of ${rupees(value)}. It shows as in progress here until the provider confirms it has gone back to the customer — usually within 5–7 working days.`
            : outcome === 'succeeded'
              ? `The payment provider has sent ${rupees(value)} back to the customer.`
              : `${rupees(value)} is recorded as given back. LOCAH did not move this money — you did.`}
        </p>
        <button type="button" className="btn-ghost" onClick={() => {
          setStep('form')
          setKey(crypto.randomUUID())
        }}>Another refund</button>
      </section>
    )
  }

  return (
    <section className="bos-card bos-pay__action" aria-labelledby="pay-refund">
      <h2 id="pay-refund">Refund</h2>
      <p className="bos-hint">
        {throughProvider
          ? 'LOCAH asks the payment provider to send the money back to the customer’s card or UPI.'
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
          {viaProvider ? (
            <label className="bos-field__check">
              <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} />{' '}
              I already gave it back myself (cash, UPI or bank) — just record it
            </label>
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
          <p>
            <strong>{throughProvider ? `Ask the provider to refund ${rupees(value)}?` : `Record a refund of ${rupees(value)}?`}</strong>{' '}
            Reason: {why}. This can&apos;t be undone.
          </p>
          <button type="button" className="btn-danger" disabled={pending} onClick={() => {
            setError(null)
            start(async () => {
              const r = await recordRefund(businessId, paymentId,
                { amount: value, reason: why, idempotency_key: key, manual: !throughProvider })
              if (!r.ok) {
                setError(r.message)
                return
              }
              const refund = (r.data as RefundAnswer | undefined)?.refund
              if (refund?.status === 'failed') {
                // Nothing moved. A fresh key lets the owner try again or record it another way.
                setError(`The payment provider did not accept the refund: ${refund.failure_reason ?? 'no reason given'}. Nothing was refunded.`)
                setKey(crypto.randomUUID())
                setStep('form')
                return
              }
              setOutcome(refund?.kind === 'provider' ? (refund.status === 'succeeded' ? 'succeeded' : 'processing') : 'recorded')
              setStep('done')
              router.refresh()
            })
          }}>
            {pending ? 'Sending…' : throughProvider ? `Refund ${rupees(value)}` : `Record refund of ${rupees(value)}`}
          </button>
          <button type="button" className="btn-ghost" disabled={pending} onClick={() => setStep('form')}>Back</button>
        </div>
      )}
      {error ? <p className="bos-error" role="alert">{error}</p> : null}
    </section>
  )
}

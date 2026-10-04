'use client'

import { useState } from 'react'
import { platformUrl } from '@platform/config'
import { useWords } from '@/components/website/SiteWords'

export type PayMethod = { method: string; label: string; upi_link?: string; upi_id?: string; how?: string }
export type PayView = {
  business: { name: string; slug: string; contact?: { phone?: string; whatsapp?: string } }
  for: string
  purpose: string
  purpose_label: string
  note: string | null
  state: 'open' | 'being_confirmed' | 'failed' | 'paid' | 'cancelled' | 'expired'
  state_words: string | null
  amount_due: number | null
  already_paid: number | null
  paying_now: number
  balance_after: number | null
  balance_now: number | null
  methods: PayMethod[]
  last_attempt: { status: string; reference: string | null } | null
  expires_at: string
}

const rupees = (v: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: Number.isInteger(v) ? 0 : 2 }).format(v)

/** The customer's side of a payment link: pay, say so, check again, or take it back. */
export function PayActions({
  slug,
  token,
  initial,
  qrUrl,
}: {
  slug: string
  token: string
  initial: PayView
  qrUrl: string
}) {
  const t = useWords()
  const [view, setView] = useState<PayView>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [utr, setUtr] = useState('')
  const api = `${platformUrl('api')}/v1/public/websites/${encodeURIComponent(slug)}/pay/${encodeURIComponent(token)}`
  const upi = view.methods.find((m) => m.method === 'upi_direct')

  async function call(path: string, body?: unknown, method = 'POST') {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`${api}${path}`, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
      })
      const json = await res.json().catch(() => null)
      if (!res.ok) throw new Error(json?.error?.message || t('That did not go through. Try again.'))
      setView(json.data as PayView)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('That did not go through. Try again.'))
    } finally {
      setBusy(false)
    }
  }

  const closed = view.state === 'paid' || view.state === 'cancelled' || view.state === 'expired'
  return (
    <>
      <header className="ls-bill__head">
        <p className="ls-meta">{t('Payment to {business}', { business: view.business.name })}</p>
        <h1 className="ls-title">{view.for}</h1>
        {view.note ? <p className="ls-meta">{view.note}</p> : null}
      </header>

      {view.state_words ? (
        <p className={`ls-pay__state ls-pay__state--${view.state}`} role="status">
          {t(view.state_words)}
        </p>
      ) : null}

      <div className="ls-bill__card">
        <dl className="ls-bill__totals ls-pay__totals">
          {view.amount_due !== null ? (
            <>
              {/* Once settled it is the total, not something still due. */}
              <dt>{t(closed ? 'Total' : 'Amount due')}</dt>
              <dd>{rupees(view.amount_due)}</dd>
            </>
          ) : null}
          {view.already_paid ? (
            <>
              <dt>{t('Already paid')}</dt>
              <dd>{rupees(view.already_paid)}</dd>
            </>
          ) : null}
          {!closed ? (
            <>
              <dt className="is-total">{t('{purpose} — paying now', { purpose: t(view.purpose_label) })}</dt>
              <dd className="is-total">{rupees(view.paying_now)}</dd>
            </>
          ) : null}
          {view.balance_after !== null && !closed && view.balance_after > 0 ? (
            <>
              <dt>{t('Balance after this')}</dt>
              <dd>{rupees(view.balance_after)}</dd>
            </>
          ) : null}
          {closed && view.balance_now !== null && view.balance_now > 0 ? (
            <>
              <dt className="is-total">{t('Balance remaining')}</dt>
              <dd className="is-total">{rupees(view.balance_now)}</dd>
            </>
          ) : null}
        </dl>
      </div>

      {view.state === 'being_confirmed' ? (
        <div className="ls-pay__wait">
          <p className="ls-meta">
            {t('{business} checks their UPI app and confirms it. You don’t need to pay again.', { business: view.business.name })}
          </p>
          <div className="ls-bill__actions">
            <button type="button" className="ls-btn" disabled={busy} onClick={() => call('', undefined, 'GET')}>
              {t('Check again')}
            </button>
            <button
              type="button"
              className="ls-btn ls-btn--outline"
              disabled={busy}
              onClick={() => call('/not-paid')}
            >
              {t('I haven’t paid yet')}
            </button>
          </div>
        </div>
      ) : null}

      {(view.state === 'open' || view.state === 'failed') && upi ? (
        <div className="ls-pay__method">
          <a className="ls-btn ls-pay__upi" href={upi.upi_link}>
            {view.state === 'failed' ? t('Try again — pay by UPI') : t('Pay {amount} by UPI', { amount: rupees(view.paying_now) })}
          </a>
          <p className="ls-meta">
            {t('Pay {amount} to {business} in any UPI app, then tap “I have paid”. They confirm it arrived.', { amount: rupees(view.paying_now), business: view.business.name })}
          </p>
          <details className="ls-pay__qr">
            <summary>{t('On a computer? Scan to pay')}</summary>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={qrUrl} alt={t('UPI QR code to pay {business}', { business: view.business.name })} width={180} height={180} />
            <p className="ls-meta">{t('UPI ID {id}', { id: upi.upi_id ?? '' })}</p>
          </details>
          <label className="ls-pay__utr">
            <span>{t('UPI reference (optional)')}</span>
            <input value={utr} onChange={(e) => setUtr(e.target.value)} maxLength={120} inputMode="text" />
          </label>
          <button
            type="button"
            className="ls-btn ls-btn--outline"
            disabled={busy}
            onClick={() => call('/paid', { reference: utr || undefined })}
          >
            {t('I have paid {amount}', { amount: rupees(view.paying_now) })}
          </button>
        </div>
      ) : null}

      {(view.state === 'open' || view.state === 'failed') && !upi ? (
        <p className="ls-meta">
          {t('{business} has not set up online payment for this link yet.', { business: view.business.name })}
          {view.business.contact?.phone ? ` ${t('Call {phone} to pay another way.', { phone: view.business.contact.phone })}` : ''}
        </p>
      ) : null}

      {error ? (
        <p className="ls-offer__error" role="alert">
          {error}
        </p>
      ) : null}
    </>
  )
}

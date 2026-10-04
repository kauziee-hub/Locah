import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader, StatusPill } from '@/components/ModuleState'
import { dayTimeLabel, rupees } from '@/lib/when'
import { MarkReceived, RefundForm } from './PaymentActions'
import { sourceHref } from '../links'
import { ConfirmRow } from '../ConfirmRow'

export const dynamic = 'force-dynamic'

type Payment = {
  id: string
  source_type: string
  source_id: string
  amount: number
  currency: string
  payment_method: string
  status: string
  provider: string | null
  provider_reference: string | null
  refunded_amount: number
  refundable_amount: number
  failure_code: string | null
  failure_reason: string | null
  created_at: string
  for: string
  method_label: string
  status_label: string
  purpose_label: string | null
  verified_at: string | null
}

type Refund = { id: string; amount: number; reason: string | null; status: string; created_at: string }

const REFUND_WORDS: Record<string, string> = {
  succeeded: 'Refunded', pending: 'Being refunded', processing: 'Being refunded', failed: 'Refund failed',
}
// Payments a person settles by hand; online ones settle themselves.
const SETTLED_BY_HAND = new Set(['cod', 'pay_at_business', 'pay_later'])

/** One payment: what it was for, how it stands, and what the owner can do with it. */
export default async function PaymentDetailPage({ params }: { params: { businessId: string; paymentId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const back = <Link href={`/b/${params.businessId}/payments`}>Payments</Link>
  const base = `/v1/platform/businesses/${params.businessId}/payments/${params.paymentId}`
  const res = await apiTry<{ data: Payment }>(base, token)
  if (!res.ok) {
    return (
      <div className="bos-page">
        <PageHeader title="Payment" breadcrumb={back} />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Payments" />
      </div>
    )
  }
  const p = res.data.data
  const refundsRes = await apiTry<{ data: Refund[] }>(`${base}/refunds`, token)
  const refunds = refundsRes.ok ? refundsRes.data.data || [] : []
  // Cash on delivery / pay at the business: settled by hand once the money is in.
  const canSettle = p.status === 'pending_offline' && SETTLED_BY_HAND.has(p.payment_method)
  // The customer says they paid by UPI to the business's own UPI ID: check, then confirm.
  const toCheck = p.status === 'pending_offline' && p.payment_method === 'upi_direct'
  const canRefund = (p.status === 'succeeded' || p.status === 'partially_refunded') && p.refundable_amount > 0

  return (
    <div className="bos-page bos-pay">
      <PageHeader
        breadcrumb={back}
        title={rupees(p.amount)}
        subtitle={`${p.purpose_label && p.purpose_label !== 'Full payment' ? `${p.purpose_label} for ` : 'For '}${p.for} · ${p.method_label}`}
      />

      <section className="bos-card" aria-label="Payment">
        <div className="bos-pay__status">
          <StatusPill value={p.status} label={p.status_label} />
          <Link href={sourceHref(params.businessId, p.source_type, p.source_id)}>Open {p.for} →</Link>
        </div>
        <dl className="bos-pay__facts">
          <div><dt>Started</dt><dd>{dayTimeLabel(p.created_at)}</dd></div>
          {p.verified_at ? <div><dt>Confirmed</dt><dd>{dayTimeLabel(p.verified_at)}</dd></div> : null}
          {p.provider_reference ? <div><dt>Reference</dt><dd>{p.provider_reference}</dd></div> : null}
          {p.refunded_amount > 0 ? <div><dt>Refunded</dt><dd>{rupees(p.refunded_amount)}</dd></div> : null}
          {canRefund && p.refunded_amount > 0 ? <div><dt>Can still refund</dt><dd>{rupees(p.refundable_amount)}</dd></div> : null}
        </dl>
        {p.status === 'failed' ? (
          <div className="bos-pay__failed" role="status">
            <strong>This payment didn&apos;t go through.</strong>{' '}
            {p.failure_reason || 'The customer can try again from the same link.'}
            {p.failure_code ? (
              <details><summary>Technical details</summary><code>{p.failure_code}</code></details>
            ) : null}
          </div>
        ) : null}
      </section>

      {canSettle ? <MarkReceived businessId={params.businessId} paymentId={p.id} amount={p.amount} /> : null}
      {toCheck ? (
        <section className="bos-card bos-pay__action" aria-labelledby="pay-check">
          <h2 id="pay-check">Did it arrive?</h2>
          <p className="bos-hint">
            The customer says they paid {rupees(p.amount)} by UPI{p.provider_reference ? ` (reference ${p.provider_reference})` : ''}.
            Check your UPI app or bank first.
          </p>
          <ConfirmRow businessId={params.businessId} paymentId={p.id} path={`/b/${params.businessId}/payments/${p.id}`} />
        </section>
      ) : null}
      {canRefund ? (
        <RefundForm businessId={params.businessId} paymentId={p.id} refundable={p.refundable_amount}
                    online={p.payment_method === 'online'} />
      ) : null}

      {refunds.length > 0 ? (
        <section className="bos-section" aria-labelledby="pay-refunds">
          <h2 id="pay-refunds" className="ws-section-title">Refunds</h2>
          <ul className="bos-mini-list">
            {refunds.map((r) => (
              <li key={r.id}>
                <div>
                  <strong>{rupees(r.amount)}</strong>
                  <p>{r.reason || 'Refund'} · {dayTimeLabel(r.created_at)}</p>
                </div>
                <StatusPill value={r.status} label={REFUND_WORDS[r.status] ?? 'Being processed'} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}

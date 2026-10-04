import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader, ROW, StatusPill, TABLE, TD, TH } from '@/components/ModuleState'
import { recordSettlement, refundPayment } from '../actions'

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
}

type Refund = {
  id: string
  amount: number
  reason: string | null
  status: string
  created_at: string
}

export default async function PaymentDetailPage({
  params,
}: {
  params: { businessId: string; paymentId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const base = `/v1/platform/businesses/${params.businessId}/payments/${params.paymentId}`
  const res = await apiTry<{ data: Payment }>(base, token)
  if (!res.ok) {
    return (
      <div>
        <Link href={`/b/${params.businessId}/payments`}>← Payments</Link>
        <PageHeader title="Payment" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Payments" />
      </div>
    )
  }
  const payment = res.data.data

  const refundsRes = await apiTry<{ data: Refund[] }>(`${base}/refunds`, token)
  const refunds = refundsRes.ok ? refundsRes.data.data || [] : []

  const canSettle = payment.status === 'pending' && payment.payment_method !== 'online'
  const canRefund = payment.status === 'succeeded' && payment.refundable_amount > 0

  return (
    <div>
      <Link href={`/b/${params.businessId}/payments`}>← Payments</Link>
      <PageHeader
        title={`${payment.currency} ${payment.amount}`}
        subtitle={`For a ${payment.source_type} · ${payment.payment_method}`}
      />

      <p>
        Status: <StatusPill value={payment.status} />
        {payment.provider ? ` · via ${payment.provider}` : ''}
      </p>
      {payment.provider_reference ? (
        <p style={{ opacity: 0.75 }}>Reference: {payment.provider_reference}</p>
      ) : null}
      {payment.failure_reason ? (
        <p
          style={{
            padding: '0.75rem 1rem',
            borderRadius: '8px',
            background: 'var(--status-bad-bg)',
            border: '1px solid var(--status-bad-bd)',
          }}
        >
          This payment failed: {payment.failure_reason}
          {payment.failure_code ? ` (${payment.failure_code})` : ''}
        </p>
      ) : null}
      <p>
        Refunded: {payment.currency} {payment.refunded_amount} · Still refundable:{' '}
        {payment.currency} {payment.refundable_amount}
      </p>

      {canSettle ? (
        <section style={{ marginTop: '1.5rem' }}>
          <h2 >Record settlement</h2>
          <p style={{ opacity: 0.8 }}>
            Mark this as paid once you have received the money in person.
          </p>
          <form action={recordSettlement}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="paymentId" value={params.paymentId} />
            <button type="submit" style={BUTTON}>
              Mark as settled
            </button>
          </form>
        </section>
      ) : null}

      {canRefund ? (
        <section style={{ marginTop: '1.75rem', maxWidth: '28rem' }}>
          <h2 >Refund</h2>
          <form action={refundPayment} style={{ display: 'grid', gap: '0.6rem' }}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="paymentId" value={params.paymentId} />
            {/* One key per form shown: a double-click or a retried submit refunds once. */}
            <input type="hidden" name="idempotency_key" value={crypto.randomUUID()} />
            <input
              name="amount"
              type="number"
              step="0.01"
              min="0.01"
              max={payment.refundable_amount}
              defaultValue={payment.refundable_amount}
              required
              style={INPUT}
            />
            <input name="reason" placeholder="Reason for the refund" required style={INPUT} />
            <button type="submit" style={BUTTON}>
              Issue refund
            </button>
          </form>
        </section>
      ) : null}

      {refunds.length > 0 ? (
        <section style={{ marginTop: '1.75rem' }}>
          <h2 >Refund history</h2>
          <div className="ws-tablewrap">
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>Amount</th>
                  <th style={TH}>Reason</th>
                  <th style={TH}>Status</th>
                  <th style={TH}>When</th>
                </tr>
              </thead>
              <tbody>
                {refunds.map((refund) => (
                  <tr key={refund.id} style={ROW}>
                    <td style={{ ...TD, fontVariantNumeric: 'tabular-nums' }}>
                      {payment.currency} {refund.amount}
                    </td>
                    <td style={TD}>{refund.reason || '—'}</td>
                    <td style={TD}>
                      <StatusPill value={refund.status} />
                    </td>
                    <td style={TD}>{new Date(refund.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  )
}

const INPUT: React.CSSProperties = {
  width: '100%',
}
const BUTTON: React.CSSProperties = {
  justifySelf: 'start',
}

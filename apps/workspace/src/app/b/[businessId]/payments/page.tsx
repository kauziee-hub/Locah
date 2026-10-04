import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader, ROW, StatusPill, TABLE, TD, TH } from '@/components/ModuleState'
import { dayTimeLabel, rupees } from '@/lib/when'
import { sourceHref } from './links'
import { RazorpayConnect } from './RazorpayConnect'
import { ConfirmRow } from './ConfirmRow'
import { UpiSetting } from './UpiSetting'

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
  refunded_amount: number
  failure_reason: string | null
  created_at: string
  for: string
  method_label: string
  status_label: string
}

type Row = {
  id: string
  amount: number
  method_label: string
  status: string
  reference: string | null
  attention: string | null
  created_at: string | null
  failure_reason: string | null
  for: string
}
type Owed = { source_type: string; source_id: string; label: string; balance: number; paid: number | null }
type Overview = {
  paid_today: { total: number; links_and_recorded: number; bills_and_counter: number; khata: number }
  to_confirm: (Row & { source_type?: string })[]
  counter_upi_to_verify: number
  needs_attention: Row[]
  owed: { total: number; rows: Owed[] }
  refunds: { id: string; amount: number; status: string; reason: string | null; created_at: string; source_type: string; source_id: string; kind?: string; failure_reason?: string | null }[]
}

type MerchantConnection = {
  provider: string
  status: string
  key_id?: string | null
  has_credentials?: boolean
  connection_mode?: string | null
  linked_account_id?: string | null
  linked_account_status?: string | null
  requires_merchant_keys?: boolean
  external_dependency?: boolean
  last_verified_at?: string | null
  verification_error?: string | null
  provider_metadata?: { mode?: string; connection_mode?: string }
} | null

function refundWords(r: { status: string; kind?: string }): string {
  if (r.status === 'failed') return 'Refund failed'
  if (r.kind === 'provider') return r.status === 'succeeded' ? 'Refunded by the provider' : 'Refund in progress'
  return 'Recorded — you gave it back'
}
/**
 * Money in (Founder refinement — Payments §14): what arrived today, what is
 * waiting for you to confirm, what failed and needs you, who still owes what,
 * and refunds. Only money that was actually confirmed counts as paid.
 */
export default async function PaymentsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const base = `/v1/platform/businesses/${params.businessId}`
  const [overviewRes, res, merchantRes, upiRes, ctxRes] = await Promise.all([
    apiTry<{ data: Overview }>(`${base}/collect/overview`, token),
    apiTry<{ data: Payment[] }>(`${base}/payments`, token),
    apiTry<{ data: MerchantConnection }>(`${base}/payments/merchant-connection?provider=razorpay`, token),
    apiTry<{ data: { upi_vpa: string | null; upi_payee_name: string | null } }>(`${base}/payments/upi`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(params.businessId)),
  ])
  if (!overviewRes.ok) {
    return (
      <div>
        <PageHeader title="Payments" />
        <GateNotice error={overviewRes.error} businessId={params.businessId} moduleLabel="Payments" />
      </div>
    )
  }
  const o = overviewRes.data.data
  const payments = res.ok ? res.data.data || [] : []
  const merchant = merchantRes.ok ? merchantRes.data.data : null
  const legacy = merchant && merchant.status !== 'not_connected'

  return (
    <div className="bos-page">
      <PageHeader
        title="Payments"
        subtitle="Money in: what arrived today, what is waiting for you, and who still owes what."
      />

      <dl className="bos-money__sum" style={{ marginBottom: '1.5rem', maxWidth: 'none' }}>
        <div>
          <dt>Paid today</dt>
          <dd className="is-balance">{rupees(o.paid_today.total)}</dd>
        </div>
        <div>
          <dt>Bills &amp; counter</dt>
          <dd>{rupees(o.paid_today.bills_and_counter)}</dd>
        </div>
        <div>
          <dt>Links &amp; recorded</dt>
          <dd>{rupees(o.paid_today.links_and_recorded)}</dd>
        </div>
        <div>
          <dt>Khata received</dt>
          <dd>{rupees(o.paid_today.khata)}</dd>
        </div>
        <div>
          <dt>Still owed</dt>
          <dd>{rupees(o.owed.total)}</dd>
        </div>
      </dl>

      {upiRes.ok ? (
        <UpiSetting businessId={params.businessId} vpa={upiRes.data.data.upi_vpa} payee={upiRes.data.data.upi_payee_name}
                    canEdit={ctxRes.ok && ctxRes.data.data.permissions.includes('payments.manage_connection')} />
      ) : null}

      <section className="bos-section" aria-labelledby="pay-confirm">
        <h2 id="pay-confirm" className="ws-section-title">Waiting for you to confirm</h2>
        {o.to_confirm.length ? (
          <ul className="bos-mini-list">
            {o.to_confirm.map((a) => (
              <li key={a.id}>
                <div>
                  <strong>{rupees(a.amount)} by UPI · {a.for}</strong>
                  <p>Customer says they paid{a.reference ? ` · reference ${a.reference}` : ''}. Check your UPI app first.</p>
                </div>
                <ConfirmRow businessId={params.businessId} paymentId={a.id} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="bos-hint">Nothing to confirm. When a customer pays a payment link by UPI, it waits here until you check it arrived.</p>
        )}
        {o.counter_upi_to_verify > 0 ? (
          <p className="bos-hint">
            {o.counter_upi_to_verify} UPI payment{o.counter_upi_to_verify === 1 ? '' : 's'} from the counter still to check —{' '}
            <Link href={`/b/${params.businessId}/pos/shifts`}>open counter shifts</Link>.
          </p>
        ) : null}
      </section>

      <section className="bos-section" aria-labelledby="pay-attention">
        <h2 id="pay-attention" className="ws-section-title">Needs attention</h2>
        {o.needs_attention.length ? (
          <ul className="bos-mini-list">
            {o.needs_attention.map((a) => (
              <li key={a.id}>
                <div>
                  <strong>{rupees(a.amount)} · {a.for}</strong>
                  <p>
                    {a.attention === 'paid_twice'
                      ? 'Paid twice on the same link — refund the extra payment.'
                      : a.attention === 'refund_due'
                        ? 'The order was cancelled — refund what was paid.'
                      : a.attention === 'refund_failed'
                        ? 'The payment provider could not complete a refund — nothing went back. Open it to refund again or record that you gave it back.'
                      : a.attention === 'provider_update_failed'
                        ? 'An update from the payment provider could not be applied after several tries — check this payment in your provider dashboard. It is also listed for the LOCAH team.'
                      : a.failure_reason || 'Payment failed.'}
                  </p>
                </div>
                <Link href={`/b/${params.businessId}/payments/${a.id}`}>Open</Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="bos-hint">No failed payments waiting on you.</p>
        )}
      </section>

      <section className="bos-section" aria-labelledby="pay-owed">
        <h2 id="pay-owed" className="ws-section-title">Still owed</h2>
        {o.owed.rows.length ? (
          <ul className="bos-mini-list">
            {o.owed.rows.map((r) => (
              <li key={`${r.source_type}-${r.source_id}`}>
                <div>
                  <strong>{r.label}</strong>
                  <p>{rupees(r.balance)} due{r.paid ? ` · ${rupees(r.paid)} paid` : ''}</p>
                </div>
                <Link href={sourceHref(params.businessId, r.source_type, r.source_id)}>Collect</Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="bos-hint">Nobody owes you anything right now.</p>
        )}
      </section>

      {o.refunds.length ? (
        <section className="bos-section" aria-labelledby="pay-refunds">
          <h2 id="pay-refunds" className="ws-section-title">Refunds · last 30 days</h2>
          <ul className="bos-mini-list">
            {o.refunds.map((r) => (
              <li key={r.id}>
                <div>
                  <strong>{rupees(r.amount)}</strong>
                  <p>{r.reason || 'Refund'} · {refundWords(r)}{r.status === 'failed' && r.failure_reason ? ` — ${r.failure_reason}` : ''}</p>
                </div>
                <Link href={sourceHref(params.businessId, r.source_type, r.source_id)}>Open</Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="bos-section bos-card" aria-labelledby="pay-online">
        <h2 id="pay-online">Online payments</h2>
        <p className="bos-hint">
          Taking cards and UPI online through LOCAH is waiting for the payment provider to be switched on (Cashfree).
          Until then everything else works: cash, UPI to your own UPI ID, cards on your own terminal, and payment
          links your customers pay by UPI.
        </p>
        {legacy ? (
          <details>
            <summary>Your existing Razorpay connection</summary>
            <RazorpayConnect businessId={params.businessId} merchant={merchant} />
          </details>
        ) : null}
      </section>

      {payments.length ? (
        <details className="bos-section">
          <summary>All payments ({payments.length}{payments.length >= 200 ? ', latest 200' : ''})</summary>
          <div className="ws-tablewrap" style={{ marginTop: '.8rem' }}>
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>For</th>
                  <th style={TH}>Amount</th>
                  <th style={TH}>Method</th>
                  <th style={TH}>Status</th>
                  <th style={TH}>When</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((p) => (
                  <tr key={p.id} style={ROW}>
                    <td style={TD}>
                      <Link href={`/b/${params.businessId}/payments/${p.id}`}>{p.for}</Link>
                    </td>
                    <td style={{ ...TD, fontVariantNumeric: 'tabular-nums' }}>{rupees(p.amount)}</td>
                    <td style={TD}>{p.method_label}</td>
                    <td style={TD}>
                      <StatusPill value={p.status} label={p.status_label} />
                    </td>
                    <td style={TD}>{dayTimeLabel(p.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  )
}

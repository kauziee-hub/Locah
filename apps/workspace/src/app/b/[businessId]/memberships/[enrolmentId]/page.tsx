import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ModuleState'
import { MoneySection } from '@/components/MoneySection'
import { MemberActions, type Detail } from './MemberActions'

export const dynamic = 'force-dynamic'

const day = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
const STATUS_LABELS: Record<string, string> = {
  pending: 'Payment pending', active: 'Active', paused: 'Frozen', grace: 'In grace', expired: 'Expired',
  cancelled: 'Cancelled', completed: 'Completed',
}
const rupees = (v: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)

/**
 * One member, student, subscriber or contract (Founder refinement §6, §22):
 * where they stand now, what they paid, every period, freeze and session —
 * and the few actions the desk needs. Words follow the kind of plan.
 */
export default async function MemberPage({ params }: { params: { businessId: string; enrolmentId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const base = `/v1/platform/businesses/${b}/membership-enrolments/${params.enrolmentId}`
  const [res, qrRes] = await Promise.all([
    apiTry<{ data: { detail: Detail } }>(base, token),
    apiTry<{ data: { code: string; svg: string } }>(`${base}/qr`, token),
  ])
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Membership" breadcrumb={<Link href={`/b/${b}/memberships`}>← Memberships</Link>} />
        <GateNotice error={res.error} businessId={b} moduleLabel="Memberships" />
      </div>
    )
  }
  const d = res.data.data.detail
  const w = d.words
  const kind = d.plan.kind
  const qr = qrRes.ok ? qrRes.data.data : null
  const colour = d.status === 'active' ? 'is-ready' : ''

  return (
    <div className="bos-page">
      <PageHeader
        title={d.member.name || 'Member'}
        subtitle={`${d.plan.name} · ${w.kind_label}`}
        breadcrumb={<Link href={`/b/${b}/memberships?kind=${kind}`}>← {w.owner_home}</Link>}
      />

      <dl className="bos-money__sum" style={{ maxWidth: 'none' }}>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={`bos-state ${colour}`}>{d.expiring_soon ? 'Ending soon' : d.status_words}</span>
          </dd>
        </div>
        {kind !== 'fee_plan' ? (
          <div>
            <dt>{w.valid}</dt>
            <dd className="is-balance">{d.last_day ? day(`${d.last_day}T12:00:00`) : day(d.valid_until)}</dd>
          </div>
        ) : null}
        {d.days_remaining !== null && d.status !== 'expired' ? (
          <div>
            <dt>Days left</dt>
            <dd className="is-balance">{d.days_remaining}</dd>
          </div>
        ) : null}
        {d.sessions_remaining !== null ? (
          <div>
            <dt>Sessions left</dt>
            <dd className="is-balance">{d.sessions_remaining}</dd>
          </div>
        ) : null}
        {d.grace_until && d.status === 'grace' ? (
          <div>
            <dt>Grace until</dt>
            <dd>{day(d.grace_until)}</dd>
          </div>
        ) : null}
        <div>
          <dt>Paid</dt>
          <dd>{rupees(d.paid)}</dd>
        </div>
        {d.outstanding > 0 ? (
          <div>
            <dt>{kind === 'fee_plan' ? 'Outstanding' : 'Due'}</dt>
            <dd>{rupees(d.outstanding)}</dd>
          </div>
        ) : null}
        {kind === 'fee_plan' && d.next_due_on ? (
          <div>
            <dt>Next instalment</dt>
            <dd>{day(d.next_due_on)}</dd>
          </div>
        ) : null}
        {d.good_standing !== null ? (
          <div>
            <dt>Good standing</dt>
            <dd>{d.good_standing ? 'Yes' : 'No — dues unpaid'}</dd>
          </div>
        ) : null}
      </dl>
      {d.reason && d.reason !== d.status_words ? (
        <p className="bos-hint" style={{ marginTop: '.6rem' }}>{d.reason}</p>
      ) : null}

      <div className="bos-mem__grid">
        <section className="bos-card" aria-labelledby="mem-act">
          <h2 id="mem-act">What to do</h2>
          <MemberActions businessId={b} detail={d} />
        </section>
        {qr && ['access', 'session_pack', 'member_dues'].includes(kind) ? (
          <section className="bos-card bos-mem__qr" aria-labelledby="mem-qr">
            <h2 id="mem-qr">Front desk code</h2>
            <div dangerouslySetInnerHTML={{ __html: qr.svg }} />
            <p className="bos-mem__code">{qr.code}</p>
            <p className="bos-hint">Scan or type this at the desk. Send it to the member so they can show it.</p>
          </section>
        ) : null}
      </div>

      <MoneySection businessId={b} token={token} sourceType="membership" sourceId={d.id} path={`/b/${b}/memberships/${d.id}`} title="Money" />

      {d.instalments.length ? (
        <section className="bos-section" aria-labelledby="mem-inst">
          <h2 id="mem-inst" className="ws-section-title">Instalments</h2>
          <ul className="bos-mini-list">
            {d.instalments.map((i) => (
              <li key={i.id}>
                <div>
                  <strong>
                    {i.label} · {rupees(i.amount)}
                  </strong>
                  <p>
                    Due {day(i.due_on)}
                    {i.paid_amount > 0 && i.paid_amount < i.amount ? ` · ${rupees(i.paid_amount)} paid` : ''}
                  </p>
                </div>
                <span className={`bos-state ${i.status === 'paid' ? 'is-ready' : ''}`}>{i.status === 'paid' ? 'Paid' : i.status === 'part_paid' ? 'Part paid' : 'Due'}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {d.periods.length ? (
        <section className="bos-section" aria-labelledby="mem-periods">
          <h2 id="mem-periods" className="ws-section-title">Periods</h2>
          <ul className="bos-mini-list">
            {d.periods.map((p) => (
              <li key={p.id}>
                <div>
                  <strong>
                    {day(p.starts_at)} → {day(p.ends_at)}
                  </strong>
                  <p>
                    {rupees(p.amount)}
                    {p.extended_days ? ` · extended ${p.extended_days} days by freezes (bought to ${day(p.base_ends_at)})` : ''}
                    {p.sessions_included ? ` · ${p.sessions_included} sessions` : ''}
                    {p.source === 'early_renewal' ? ' · renewed early' : ''}
                  </p>
                </div>
                <span className={`bos-state ${p.payment_state === 'paid' || p.payment_state === 'waived' ? 'is-ready' : ''}`}>
                  {p.payment_state === 'paid' ? 'Paid' : p.payment_state === 'waived' ? 'Free' : p.payment_state === 'cancelled' ? 'Lapsed' : p.payment_state === 'part_paid' ? 'Part paid' : 'Waiting for payment'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {d.freezes.length ? (
        <section className="bos-section" aria-labelledby="mem-freezes">
          <h2 id="mem-freezes" className="ws-section-title">{kind === 'recurring_delivery' ? 'Pauses' : 'Freezes'}</h2>
          <ul className="bos-mini-list">
            {d.freezes.map((f) => (
              <li key={f.id}>
                <div>
                  <strong>
                    {day(f.starts_on)} → {day(f.ends_on)} · {f.days} days
                  </strong>
                  <p>
                    {f.reason || 'No reason given'}
                    {f.extends_cover ? ' · end date moved' : ''}
                  </p>
                </div>
                <span className="bos-state">{f.status === 'cancelled' ? 'Taken back' : 'Confirmed'}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {d.visits.length ? (
        <section className="bos-section" aria-labelledby="mem-visits">
          <h2 id="mem-visits" className="ws-section-title">Covered visits</h2>
          <ul className="bos-mini-list">
            {d.visits.map((v) => (
              <li key={v.id}>
                <div>
                  <strong>Visit {v.seq} · {day(v.due_on)}</strong>
                  <p>{v.status === 'requested' ? 'Sent to Jobs to schedule' : v.status === 'done' ? 'Done' : 'Scheduled'}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {d.session_uses.length ? (
        <section className="bos-section" aria-labelledby="mem-uses">
          <h2 id="mem-uses" className="ws-section-title">Sessions used</h2>
          <ul className="bos-mini-list">
            {d.session_uses.map((u) => (
              <li key={u.id}>
                <div>
                  <strong>{day(u.used_at)}</strong>
                  <p>{u.source_type === 'booking' ? 'Booked class' : u.source_type === 'checkin' ? 'Check-in' : 'Recorded at the desk'}{u.status === 'reversed' ? ' · given back' : ''}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="bos-section" aria-labelledby="mem-history">
        <h2 id="mem-history" className="ws-section-title">History</h2>
        <ul className="bos-mini-list">
          {d.history.map((h, i) => (
            <li key={i}>
              <div>
                <strong>{STATUS_LABELS[h.to] || h.to}</strong>
                <p>
                  {h.reason || ''} · {day(h.at)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

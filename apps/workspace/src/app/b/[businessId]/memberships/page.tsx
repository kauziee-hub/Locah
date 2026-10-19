import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ModuleState'
import { EnrolForm, FinaliseDay, PlanForm, type PlanLite } from './MembershipForms'
import { ActionButton } from '@/components/ActionButton'
import { makePlanLive } from './member-actions'

export const dynamic = 'force-dynamic'

type Row = {
  id: string
  member: string | null
  phone: string | null
  plan: string
  kind: string
  status: string
  status_words: string
  reason: string
  valid_until: string | null
  last_day?: string | null
  days_remaining: number | null
  expiring_soon: boolean
  sessions_remaining: number | null
  outstanding: number
  next_due_on: string | null
  overdue: boolean
  good_standing: boolean | null
  checkin_code: string | null
}
type Slot = { deliver: number; quantity: number; skipped: number; paused: number; not_covered: number }
type DayBoard = { on_date: string; generated: boolean; slots: Record<string, Slot>; subscribers: { enrolment_id: string; slot: string; quantity: number; status: string; why: string }[] }
type Board = {
  kind: string
  today: string
  words: Record<string, string>
  kinds: { kind: string; label: string; count: number }[]
  counts: Record<string, number>
  rows: Row[]
  tomorrow?: DayBoard
  instalments?: { id: string; enrolment_id: string; label: string; student: string | null; amount: number; due_on: string; overdue: boolean }[]
  visits_due?: { id: string; enrolment_id: string; due_on: string; status: string; customer: string | null; job_ref: string | null }[]
}
type Customer = { id: string; display_name: string; phone: string | null }

const rupees = (v: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)
const day = (v: string | null) => (v ? new Date(v).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '—')

const KIND_INTRO: Record<string, string> = {
  access: 'Who is active, who is about to end, who needs to renew — and the front desk check-in.',
  session_pack: 'Session packs: how many sessions each client has left.',
  recurring_delivery: "Tomorrow's quantities, skips and pauses. Orders are made for you at the cutoff.",
  fee_plan: 'Students, fee instalments due and overdue, and terms ending.',
  service_contract: 'Active contracts, preventive visits due and renewals.',
  member_dues: 'Members, annual dues and who is in good standing.',
}

const STAT_LABELS: Record<string, [string, string][]> = {
  access: [['active', 'Active'], ['expiring_soon', 'Ending this week'], ['grace', 'In grace'], ['payment_pending', 'Payment pending'], ['expired', 'Expired'], ['paused', 'Frozen'], ['renewed_today', 'Renewed today']],
  session_pack: [['active', 'Active packs'], ['expiring_soon', 'Ending this week'], ['payment_pending', 'Payment pending'], ['expired', 'Used up or expired']],
  recurring_delivery: [['active', 'Delivering'], ['paused', 'Paused'], ['payment_pending', 'Payment pending'], ['grace', 'Renewal due']],
  fee_plan: [['active', 'Enrolled'], ['overdue', 'Instalments overdue'], ['payment_pending', 'First instalment pending'], ['term_ending_week', 'Term ends this week']],
  service_contract: [['active', 'Active contracts'], ['expiring_soon', 'Ending this week'], ['grace', 'Renewal due'], ['expired', 'Expired']],
  member_dues: [['good_standing', 'In good standing'], ['not_in_good_standing', 'Dues not paid'], ['payment_pending', 'Payment pending'], ['renewed_today', 'Paid today']],
}

function MemberRow({ r, href }: { r: Row; href: string }) {
  // Only what is known: a member still waiting for payment has no "until".
  const facts = [
    r.plan,
    r.last_day ? `until ${day(`${r.last_day}T12:00:00`)}` : r.valid_until ? `until ${day(r.valid_until)}` : '',
    r.days_remaining !== null && r.status === 'active' ? `${r.days_remaining} days left` : '',
    r.sessions_remaining !== null ? `${r.sessions_remaining} sessions left` : '',
    r.outstanding > 0 ? `${rupees(r.outstanding)} due` : '',
  ].filter(Boolean)
  return (
    <li>
      <div>
        <strong>
          <Link href={href}>{r.member || 'Member'}</Link>
        </strong>
        <p>{facts.join(' · ')}</p>
      </div>
      <span className={`bos-state ${r.status === 'active' ? 'is-ready' : ''}`}>{r.expiring_soon ? 'Ending soon' : r.status_words}</span>
    </li>
  )
}

/**
 * Memberships & subscriptions (Founder refinement — Memberships §22): one
 * engine, the home each trade expects — members and renewals for a gym,
 * tomorrow's quantities for a milk or tiffin business, instalments for a
 * coaching centre, visits for an AMC business, good standing for a club.
 */
export default async function MembershipsPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { kind?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const base = `/v1/platform/businesses/${b}`
  const kindQs = searchParams?.kind ? `?kind=${encodeURIComponent(searchParams.kind)}` : ''
  const [boardRes, plansRes, customersRes, productsRes] = await Promise.all([
    apiTry<{ data: Board }>(`${base}/membership-board${kindQs}`, token),
    apiTry<{ data: PlanLite[] }>(`${base}/membership-plans`, token),
    apiTry<{ data: Customer[] }>(`${base}/customers?limit=200`, token),
    apiTry<{ data: { id: string; title: string; price_amount: number | null; status: string }[] }>(
      `${base}/products?limit=200`, token),
  ])
  if (!boardRes.ok) {
    return (
      <div>
        <PageHeader title="Memberships" />
        <GateNotice error={boardRes.error} businessId={b} moduleLabel="Memberships" />
      </div>
    )
  }
  const board = boardRes.data.data
  const w = board.words
  const plans = (plansRes.ok ? plansRes.data.data : []).filter((p) => p.status !== 'archived')
  const kindPlans = plans.filter((p) => p.plan_kind === board.kind)
  const customers = customersRes.ok ? customersRes.data.data : []
  const products = (productsRes.ok ? productsRes.data.data : []).filter((p) => p.status === 'active')
  const rows = board.rows
  const href = (id: string) => `/b/${b}/memberships/${id}`
  const needs = rows.filter((r) => r.expiring_soon || r.status === 'grace' || r.status === 'pending')
  const running = rows.filter((r) => r.status === 'active' && !r.expiring_soon)
  const quiet = rows.filter((r) => ['paused', 'expired', 'completed', 'cancelled'].includes(r.status))
  const stats = STAT_LABELS[board.kind] || STAT_LABELS.access
  const tomorrow = board.tomorrow

  return (
    <div className="bos-page">
      <PageHeader
        title={w.owner_home}
        subtitle={KIND_INTRO[board.kind]}
        actions={
          ['access', 'session_pack', 'member_dues'].includes(board.kind) ? (
            <Link className="btn" href={`/b/${b}/memberships/checkin`}>
              Front desk check-in
            </Link>
          ) : undefined
        }
      />

      {board.kinds.length > 1 ? (
        <nav className="bos-pills" aria-label="Kinds of plan" style={{ marginBottom: '1rem' }}>
          {board.kinds.map((k) => (
            <Link key={k.kind} className={`bos-pill ${k.kind === board.kind ? 'is-on' : ''}`} href={`/b/${b}/memberships?kind=${k.kind}`}>
              {k.label} · {k.count}
            </Link>
          ))}
        </nav>
      ) : null}

      <dl className="bos-money__sum" style={{ maxWidth: 'none', marginBottom: '1.4rem' }}>
        {stats.map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd className="is-balance">{board.counts[key] ?? 0}</dd>
          </div>
        ))}
      </dl>

      {tomorrow ? (
        <section className="bos-card bos-section" aria-labelledby="mem-tomorrow">
          <div className="bos-card__head">
            <h2 id="mem-tomorrow">Tomorrow · {day(tomorrow.on_date)}</h2>
            {tomorrow.generated ? <span className="bos-state is-ready">Orders made</span> : <FinaliseDay businessId={b} onDate={tomorrow.on_date} />}
          </div>
          {Object.keys(tomorrow.slots).length ? (
            <ul className="bos-mini-list">
              {Object.entries(tomorrow.slots).map(([slot, s]) => (
                <li key={slot}>
                  <div>
                    <strong>
                      {slot}: {s.quantity} to deliver
                    </strong>
                    <p>
                      {s.deliver} subscribers · {s.skipped} skipped · {s.paused} paused
                      {s.not_covered ? ` · ${s.not_covered} not paid for` : ''}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="bos-hint">No deliveries tomorrow.</p>
          )}
          <p className="bos-hint">Customers can skip or change tomorrow until the cutoff; after that the orders go to your kitchen and delivery.</p>
        </section>
      ) : null}

      {board.instalments && board.instalments.length ? (
        <section className="bos-section" aria-labelledby="mem-inst">
          <h2 id="mem-inst" className="ws-section-title">Instalments due this week</h2>
          <ul className="bos-mini-list">
            {board.instalments.map((i) => (
              <li key={i.id}>
                <div>
                  <strong>
                    <Link href={href(i.enrolment_id)}>{i.student || 'Student'}</Link> · {i.label}
                  </strong>
                  <p>
                    {rupees(i.amount)} · {i.overdue ? `overdue since ${day(i.due_on)}` : `due ${day(i.due_on)}`}
                  </p>
                </div>
                <span className={`bos-state ${i.overdue ? '' : 'is-ready'}`}>{i.overdue ? 'Overdue' : 'Due'}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {board.visits_due && board.visits_due.length ? (
        <section className="bos-section" aria-labelledby="mem-visits">
          <h2 id="mem-visits" className="ws-section-title">Service visits due · next 30 days</h2>
          <ul className="bos-mini-list">
            {board.visits_due.map((v) => (
              <li key={v.id}>
                <div>
                  <strong>
                    <Link href={href(v.enrolment_id)}>{v.customer || 'Customer'}</Link>
                  </strong>
                  <p>
                    Preventive visit {day(v.due_on)} · {v.status === 'requested' ? 'sent to Jobs' : 'scheduled'}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="bos-section" aria-labelledby="mem-needs">
        <h2 id="mem-needs" className="ws-section-title">Needs you</h2>
        {needs.length ? (
          <ul className="bos-mini-list">
            {needs.map((r) => (
              <MemberRow key={r.id} r={r} href={href(r.id)} />
            ))}
          </ul>
        ) : (
          <p className="bos-hint">Nothing ending, in grace or waiting for payment.</p>
        )}
      </section>

      <section className="bos-section" aria-labelledby="mem-all">
        <h2 id="mem-all" className="ws-section-title">
          {w.people} · {running.length}
        </h2>
        {running.length ? (
          <ul className="bos-mini-list">
            {running.map((r) => (
              <MemberRow key={r.id} r={r} href={href(r.id)} />
            ))}
          </ul>
        ) : (
          <p className="bos-hint">No one yet. Add the first below.</p>
        )}
        {quiet.length ? (
          <details style={{ marginTop: '.8rem' }}>
            <summary>
              Frozen, ended or cancelled · {quiet.length}
            </summary>
            <ul className="bos-mini-list" style={{ marginTop: '.6rem' }}>
              {quiet.map((r) => (
                <MemberRow key={r.id} r={r} href={href(r.id)} />
              ))}
            </ul>
          </details>
        ) : null}
      </section>

      <section className="bos-section bos-card" aria-labelledby="mem-enrol">
        <h2 id="mem-enrol">Add a {w.noun}</h2>
        {kindPlans.length ? (
          <EnrolForm businessId={b} plans={kindPlans} customers={customers} kind={board.kind} />
        ) : (
          <p className="bos-hint">Create a plan first.</p>
        )}
      </section>

      <section className="bos-section" aria-labelledby="mem-plans">
        <h2 id="mem-plans" className="ws-section-title">Plans</h2>
        {plans.length ? (
          <ul className="bos-mini-list">
            {plans.map((p) => (
              <li key={p.id}>
                <div>
                  <strong>{p.name}</strong>
                  <p>
                    {p.kind_label} · {p.price_amount > 0 ? rupees(p.price_amount) : 'Free'}
                    {p.duration_days ? ` · ${p.duration_days} days` : ' · ongoing'}
                    {p.sessions_included ? ` · ${p.sessions_included} sessions` : ''}
                    {p.grace_days ? ` · ${p.grace_days} days' grace` : ''}
                    {p.status !== 'active' ? ` · ${p.status === 'draft' ? 'draft — not offered yet' : p.status}` : ''}
                  </p>
                </div>
                {p.status === 'draft' ? (
                  <ActionButton className="btn-quiet" label="Make it live" busyLabel="Saving…"
                    run={makePlanLive.bind(null, b, p.id)} />
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        <details style={{ marginTop: '.8rem' }} open={!plans.length}>
          <summary>New plan</summary>
          <PlanForm businessId={b} defaultKind={board.kind} products={products} />
        </details>
      </section>
    </div>
  )
}

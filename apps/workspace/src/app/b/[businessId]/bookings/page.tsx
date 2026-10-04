import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, EmptyState, FilterTabs, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { BusinessEmpty } from '@/components/BusinessEmpty'
import { dayTimeLabel, rupees, timeLabel } from '@/lib/when'
import { saveBookingsPolicy, withdrawWaitlist } from './actions'
import { FILTERS, MODE_WORDS, PAYMENT_WORDS, STATUS_TONE, STATUS_WORDS } from './words'

export const dynamic = 'force-dynamic'

type Booking = {
  id: string; booking_number: string; title: string; reservation_mode: string; status: string
  starts_at: string; ends_at: string; party_size: number | null; payment_status: string
  deposit_required: boolean; deposit_amount: number
  customer: { id: string; name: string; phone: string | null } | null
  location_name: string | null; provider_name: string | null
}
type Waiting = {
  id: string; starts_at: string; party_size: number; status: string
  offer_expires_at: string | null; offer_link?: string
}
type Policy = {
  require_deposit: boolean; deposit_amount: number | null; cancel_window_hours: number
  hold_minutes: number; waitlist_enabled: boolean; waitlist_offer_minutes: number
}

/** Doc 11 §4.2 Bookings — who is coming, when, and what to do next; plus the booking rules. */
export default async function BookingsPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { status?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const base = `/b/${b}`
  const qs = searchParams?.status ? `?status=${encodeURIComponent(searchParams.status)}` : ''
  const [listRes, policyRes, meRes, waitRes] = await Promise.all([
    apiTry<{ data: Booking[] }>(`/v1/platform/businesses/${b}/bookings${qs}`, token),
    apiTry<{ data: Policy }>(`/v1/platform/businesses/${b}/bookings-policy`, token),
    apiTry<{ data: { permissions: string[] } }>(`/v1/me/context`, token,
      { 'X-Operating-Context': 'business', 'X-Business-Id': b }),
    apiTry<{ data: Waiting[] }>(`/v1/platform/businesses/${b}/bookings-waitlist`, token),
  ])
  const waiting = waitRes.ok ? waitRes.data.data || [] : []
  // Only people who set the business's booking rules see the policy form (a provider does not).
  const canSetPolicy = meRes.ok && (meRes.data.data.permissions ?? []).includes('bookings.manage_availability')
  if (!listRes.ok) {
    return (
      <div>
        <PageHeader title="Bookings" />
        <GateNotice error={listRes.error} businessId={b} moduleLabel="Bookings" />
      </div>
    )
  }
  // The next booking first: upcoming ones soonest-first, then past ones most recent first.
  const now = Date.now()
  const at = (x: Booking) => new Date(x.starts_at).getTime()
  const bookings = [...(listRes.data.data || [])].sort((p, q) => {
    const pUp = at(p) >= now
    const qUp = at(q) >= now
    if (pUp !== qUp) return pUp ? -1 : 1
    return pUp ? at(p) - at(q) : at(q) - at(p)
  })
  const policy: Policy = policyRes.ok
    ? policyRes.data.data
    : { require_deposit: false, deposit_amount: null, cancel_window_hours: 24, hold_minutes: 15,
        waitlist_enabled: false, waitlist_offer_minutes: 60 }
  const places = new Set(bookings.map((x) => x.location_name).filter(Boolean))
  const toConfirm = bookings.filter((x) => x.status === 'pending').length

  return (
    <div>
      <PageHeader title="Bookings" subtitle={canSetPolicy
        ? 'Who is coming and when. Confirm new ones, mark who arrived, and set your booking rules below.'
        : 'Your appointments: confirm them, and mark who arrived.'}
        actions={canSetPolicy ? <Link className="btn btn-ghost" href={`${base}/bookings/resources`}>Tables, rooms & equipment</Link> : null} />
      {toConfirm && !searchParams?.status ? (
        <p className="bos-status" role="status">
          {toConfirm === 1 ? '1 booking is' : `${toConfirm} bookings are`} waiting for you to confirm.{' '}
          <Link href={`${base}/bookings?status=pending`}>Show them</Link>
        </p>
      ) : null}
      <FilterTabs
        current={searchParams?.status}
        hrefFor={(v) => `${base}/bookings${v ? `?status=${v}` : ''}`}
        options={FILTERS}
      />
      <DataTable
        rows={bookings}
        rowKey={(x) => x.id}
        columns={[
          {
            key: 'booking',
            header: 'Booking',
            render: (x) => (
              <div>
                <Link href={`${base}/bookings/${x.id}`}>{x.title || MODE_WORDS[x.reservation_mode] || 'Booking'}</Link>
                <div className="bos-hint" style={{ margin: 0 }}>
                  {x.customer?.name ?? 'No customer recorded'}
                  {x.party_size && x.party_size > 1 ? ` · ${x.party_size} people` : ''}
                </div>
              </div>
            ),
          },
          {
            key: 'when',
            header: 'When',
            render: (x) => (
              <span style={{ whiteSpace: 'nowrap' }}>{dayTimeLabel(x.starts_at)}<span className="bos-hint"> – {timeLabel(x.ends_at)}</span></span>
            ),
          },
          {
            key: 'with',
            header: 'With',
            render: (x) => (
              <span>
                {x.provider_name ?? (x.reservation_mode === 'appointment' ? 'Anyone free' : MODE_WORDS[x.reservation_mode] ?? '—')}
                {places.size > 1 && x.location_name ? <span className="bos-hint"> · {x.location_name}</span> : null}
              </span>
            ),
          },
          {
            key: 'status',
            header: 'Status',
            render: (x) => <StatusPill value={x.status} tone={STATUS_TONE[x.status]} label={STATUS_WORDS[x.status] ?? x.status} />,
          },
          {
            key: 'payment',
            header: 'Payment',
            render: (x) => (
              <span className="bos-hint" style={{ margin: 0 }}>
                {PAYMENT_WORDS[x.payment_status] ?? '—'}
                {x.deposit_required && x.deposit_amount ? ` · deposit ${rupees(x.deposit_amount)}` : ''}
              </span>
            ),
          },
        ]}
        empty={
          searchParams?.status ? (
            <EmptyState title="No bookings here">
              {`Nothing marked “${FILTERS.find((f) => f.value === searchParams.status)?.label ?? searchParams.status}”.`}
            </EmptyState>
          ) : (
            <BusinessEmpty businessId={b} module="bookings" fallbackTitle="No bookings here"
                           fallback="Reservations made on your website appear here for you to confirm." />
          )
        }
      />

      {waiting.length ? (
        <Section title="Waitlist">
          <p className="bos-hint" style={{ marginTop: 0 }}>
            When a place opens up, the first person waiting is offered it on WhatsApp. Nobody is booked until they take it.
          </p>
          <ul className="bos-waitlist">
            {waiting.map((w) => (
              <li key={w.id}>
                <span>
                  <strong>{dayTimeLabel(w.starts_at)}</strong> · {w.party_size === 1 ? '1 person' : `${w.party_size} people`}
                  {' · '}{w.status === 'offered' ? 'offered the place' : 'waiting'}
                  {w.status === 'offered' && w.offer_expires_at ? ` until ${timeLabel(w.offer_expires_at)}` : ''}
                </span>
                {w.offer_link ? (
                  <input readOnly value={w.offer_link} aria-label="Offer link to share" className="bos-waitlist__link" />
                ) : null}
                <ActionButton className="btn-quiet" label="Remove" busyLabel="Removing…" confirmLabel="Yes, remove"
                  confirm="Take this person off the waitlist?" run={withdrawWaitlist.bind(null, b, w.id)} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {canSetPolicy ? (
        <Section title="Booking rules">
          <ActionForm action={saveBookingsPolicy} success="Saved." className="bos-policy" aria-label="Booking rules">
            <input type="hidden" name="businessId" value={b} />
            <label className="bos-check">
              <input type="checkbox" name="require_deposit" defaultChecked={policy.require_deposit} />
              Ask for a deposit to hold a booking
            </label>
            <label>
              Deposit (₹)
              <input name="deposit_amount" type="number" min={0} step="1" defaultValue={policy.deposit_amount ?? ''} />
            </label>
            <label>
              Customers can cancel up to (hours before)
              <input name="cancel_window_hours" type="number" min={0} max={720} defaultValue={policy.cancel_window_hours} />
            </label>
            <label>
              Hold an unpaid online deposit for (minutes)
              <input name="hold_minutes" type="number" min={5} max={1440} defaultValue={policy.hold_minutes} />
            </label>
            <label className="bos-check">
              <input type="checkbox" name="waitlist_enabled" defaultChecked={policy.waitlist_enabled} />
              Keep a waitlist when a time is full
            </label>
            <label>
              Keep an offered place for (minutes)
              <input name="waitlist_offer_minutes" type="number" min={5} max={2880} defaultValue={policy.waitlist_offer_minutes} />
            </label>
            <SubmitButton className="btn">Save booking rules</SubmitButton>
          </ActionForm>
        </Section>
      ) : null}
    </div>
  )
}

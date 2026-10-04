import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, EmptyState, FilterTabs, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { updateBookingsPolicy, withdrawWaitlist } from './actions'
import { LocalTime } from '@/components/LocalTime'
import { BusinessEmpty } from '@/components/BusinessEmpty'

export const dynamic = 'force-dynamic'

type Waiting = {
  id: string; starts_at: string; party_size: number; status: string
  offer_expires_at: string | null; offer_link?: string
}

/** Doc 11 §4.2 Bookings — list/calendar + policies. */
export default async function BookingsPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { status?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const base = `/b/${params.businessId}`
  const qs = searchParams?.status ? `?status=${encodeURIComponent(searchParams.status)}` : ''
  const [listRes, policyRes, meRes, waitRes] = await Promise.all([
    apiTry<{ data: Array<Record<string, unknown>> }>(
      `/v1/platform/businesses/${params.businessId}/bookings${qs}`,
      token
    ),
    apiTry<{
      data: {
        require_deposit: boolean; deposit_amount: number | null; cancel_window_hours: number
        hold_minutes: number; waitlist_enabled: boolean; waitlist_offer_minutes: number
      }
    }>(`/v1/platform/businesses/${params.businessId}/bookings-policy`, token),
    apiTry<{ data: { permissions: string[] } }>(`/v1/me/context`, token,
      { 'X-Operating-Context': 'business', 'X-Business-Id': params.businessId }),
    apiTry<{ data: Waiting[] }>(`/v1/platform/businesses/${params.businessId}/bookings-waitlist`, token),
  ])
  const waiting = waitRes.ok ? waitRes.data.data || [] : []
  // Only people who set the business's booking rules see the policy form (a provider does not).
  const canSetPolicy = meRes.ok && (meRes.data.data.permissions ?? []).includes('bookings.manage_availability')
  if (!listRes.ok) {
    return (
      <div>
        <PageHeader title="Bookings" />
        <GateNotice error={listRes.error} businessId={params.businessId} moduleLabel="Bookings" />
      </div>
    )
  }
  const bookings = listRes.data.data || []
  const policy = policyRes.ok
    ? policyRes.data.data
    : { require_deposit: false, deposit_amount: null, cancel_window_hours: 24, hold_minutes: 15,
        waitlist_enabled: false, waitlist_offer_minutes: 60 }

  async function savePolicy(formData: FormData) {
    'use server'
    await updateBookingsPolicy(params.businessId, {
      require_deposit: formData.get('require_deposit') === 'on',
      deposit_amount: formData.get('deposit_amount') ? Number(formData.get('deposit_amount')) : null,
      cancel_window_hours: Number(formData.get('cancel_window_hours') || 24),
      hold_minutes: Number(formData.get('hold_minutes') || 15),
      waitlist_enabled: formData.get('waitlist_enabled') === 'on',
      waitlist_offer_minutes: Number(formData.get('waitlist_offer_minutes') || 60),
    })
  }

  async function withdraw(formData: FormData) {
    'use server'
    await withdrawWaitlist(params.businessId, String(formData.get('id')))
  }

  return (
    <div>
      <PageHeader title="Bookings" subtitle={canSetPolicy
        ? 'Confirm or cancel reservations, and set the deposit and cancellation policy.'
        : 'Your appointments: confirm them, and mark them done.'}
        actions={canSetPolicy ? <Link className="btn btn-ghost" href={`${base}/bookings/resources`}>Tables, rooms & equipment</Link> : null} />
      <FilterTabs
        current={searchParams?.status}
        hrefFor={(v) => `${base}/bookings${v ? `?status=${v}` : ''}`}
        options={[
          { value: '', label: 'All' },
          { value: 'pending', label: 'Pending' },
          { value: 'confirmed', label: 'Confirmed' },
          { value: 'completed', label: 'Completed' },
          { value: 'cancelled', label: 'Cancelled' },
        ]}
      />
      <DataTable
        rows={bookings}
        rowKey={(b) => String(b.id)}
        columns={[
          {
            key: 'booking',
            header: 'Booking',
            render: (b) => (
              <div>
                <Link href={`${base}/bookings/${b.id}`}>{String(b.booking_number)}</Link>
                <div style={{ color: 'var(--color-muted)', fontSize: '0.82rem' }}>{String(b.title)}</div>
              </div>
            ),
          },
          {
            key: 'when',
            header: 'When',
            align: 'num',
            render: (b) => <LocalTime value={b.starts_at as string | null} />,
          },
          {
            key: 'mode',
            header: 'Mode',
            render: (b) => <span style={{ textTransform: 'capitalize' }}>{String(b.reservation_mode)}</span>,
          },
          { key: 'status', header: 'Status', render: (b) => <StatusPill value={String(b.status)} /> },
          {
            key: 'payment',
            header: 'Payment',
            render: (b) => <span style={{ color: 'var(--color-muted)' }}>{String(b.payment_status)}</span>,
          },
        ]}
        empty={
          searchParams?.status ? (
            <EmptyState title="No bookings here">{`Nothing with status "${searchParams.status}".`}</EmptyState>
          ) : (
            <BusinessEmpty businessId={params.businessId} module="bookings" fallbackTitle="No bookings here"
                           fallback="Reservations made on your website appear here for you to confirm." />
          )
        }
      />

      {waiting.length ? (
        <Section title="Waitlist">
          <p style={{ marginTop: 0, color: 'var(--color-muted)' }}>
            When a place opens up, the first person waiting is offered it on WhatsApp. Nobody is booked until they take it.
          </p>
          <ul>
            {waiting.map((w) => (
              <li key={w.id} style={{ marginBottom: '0.4rem' }}>
                <LocalTime value={w.starts_at} /> · party of {w.party_size} · {w.status === 'offered' ? 'offered' : 'waiting'}
                {w.status === 'offered' && w.offer_expires_at ? <> until <LocalTime value={w.offer_expires_at} /></> : null}
                {w.offer_link ? (
                  <input readOnly value={w.offer_link} aria-label="Offer link to share" style={{ display: 'block', width: '100%', maxWidth: 520, fontSize: '0.8rem' }} />
                ) : null}
                <form action={withdraw} style={{ display: 'inline' }}>
                  <input type="hidden" name="id" value={w.id} />
                  <button type="submit" className="btn-quiet">Remove</button>
                </form>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {canSetPolicy ? (
        <Section title="Booking policy">
          <form action={savePolicy} style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', color: 'var(--color-foreground)' }}>
              <input type="checkbox" name="require_deposit" defaultChecked={policy.require_deposit} style={{ minHeight: 'auto' }} />
              Require a deposit
            </label>
            <label style={{ display: 'grid', gap: '0.2rem' }}>
              Deposit amount
              <input name="deposit_amount" type="number" step="0.01" defaultValue={policy.deposit_amount ?? ''} />
            </label>
            <label style={{ display: 'grid', gap: '0.2rem' }}>
              Cancellation window (hours)
              <input name="cancel_window_hours" type="number" defaultValue={policy.cancel_window_hours} />
            </label>
            <label style={{ display: 'grid', gap: '0.2rem' }}>
              Hold an unpaid online deposit for (minutes)
              <input name="hold_minutes" type="number" min={5} max={1440} defaultValue={policy.hold_minutes} />
            </label>
            <label style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', color: 'var(--color-foreground)' }}>
              <input type="checkbox" name="waitlist_enabled" defaultChecked={policy.waitlist_enabled} style={{ minHeight: 'auto' }} />
              Keep a waitlist when a slot is full
            </label>
            <label style={{ display: 'grid', gap: '0.2rem' }}>
              Keep an offered place for (minutes)
              <input name="waitlist_offer_minutes" type="number" min={5} max={2880} defaultValue={policy.waitlist_offer_minutes} />
            </label>
            <button type="submit">Save policy</button>
          </form>
        </Section>
      ) : null}
    </div>
  )
}

import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, DetailShell, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { MoneySection } from '@/components/MoneySection'
import { dayLabel, dayTimeLabel, rupees, timeLabel } from '@/lib/when'
import { endSeries, repeatBooking, shiftSeries, transitionBooking } from '../actions'
import { MODE_WORDS, NEXT_STEPS, PAYMENT_WORDS, STATUS_TONE, STATUS_WORDS } from '../words'

export const dynamic = 'force-dynamic'

type Booking = {
  id: string; booking_number: string; title: string; reservation_mode: string; status: string
  starts_at: string; ends_at: string; party_size: number | null; payment_status: string
  deposit_required: boolean; deposit_amount: number; hold_expires_at: string | null
  series_id: string | null; occurrence_index: number | null; cancellation_reason: string | null
  channel: string | null
  customer: { id: string; name: string; phone: string | null } | null
  location_name: string | null; provider_name: string | null
}
type Series = { id: string; status: string; occurrences: { id: string; occurrence_index: number; starts_at: string; status: string }[] }
type Step = { id: string; from_status: string | null; to_status: string; reason: string | null; created_at: string }

// services/booking.py keeps one of these, or none.
const CHANNEL_WORDS: Record<string, string> = {
  web: 'Your website', whatsapp: 'WhatsApp', phone: 'Phone', workspace: 'Entered by your team',
  marketplace: 'Marketplace',
}

/** One booking: who, when, with whom, the next step, repeats, money and what happened. */
export default async function BookingDetailPage({ params }: { params: { businessId: string; bookingId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const base = `/v1/platform/businesses/${b}`
  const here = `/b/${b}/bookings/${params.bookingId}`
  const back = <Link href={`/b/${b}/bookings`}>← Bookings</Link>
  const [bookingRes, historyRes] = await Promise.all([
    apiTry<{ data: Booking }>(`${base}/bookings/${params.bookingId}`, token),
    apiTry<{ data: Step[] }>(`${base}/bookings/${params.bookingId}/history`, token),
  ])
  if (!bookingRes.ok) {
    return (
      <div>
        <PageHeader title="Booking" breadcrumb={back} />
        <GateNotice error={bookingRes.error} businessId={b} moduleLabel="Bookings" />
      </div>
    )
  }
  const bk = bookingRes.data.data
  const history = historyRes.ok ? historyRes.data.data || [] : []
  const seriesRes = bk.series_id ? await apiTry<{ data: Series }>(`${base}/bookings-series/${bk.series_id}`, token) : null
  const series = seriesRes && seriesRes.ok ? seriesRes.data.data : null
  const live = bk.status === 'pending' || bk.status === 'confirmed'
  const phone = bk.customer?.phone?.replace(/[^+\d]/g, '')
  const sameDay = dayLabel(bk.starts_at) === dayLabel(bk.ends_at)
  const steps = NEXT_STEPS[bk.status] ?? []

  return (
    <DetailShell
      breadcrumb={back}
      title={`${bk.title || MODE_WORDS[bk.reservation_mode] || 'Booking'} · ${bk.booking_number}`}
      status={<StatusPill value={bk.status} tone={STATUS_TONE[bk.status]} label={STATUS_WORDS[bk.status] ?? bk.status} />}
      meta={[
        ['Customer', bk.customer ? (
          <span key="c">
            <Link href={`/b/${b}/customers/${bk.customer.id}`}>{bk.customer.name}</Link>
            {phone ? <> · <a href={`tel:${phone}`}>{bk.customer.phone}</a></> : null}
          </span>
        ) : 'Not recorded'],
        ['When', sameDay
          ? `${dayTimeLabel(bk.starts_at)} – ${timeLabel(bk.ends_at)}`
          : `${dayTimeLabel(bk.starts_at)} – ${dayTimeLabel(bk.ends_at)}`],
        ...(bk.reservation_mode === 'appointment' || bk.provider_name
          ? [['With', bk.provider_name ?? 'Anyone free'] as [string, string]] : []),
        // The default "Primary Location" says nothing; a named place does.
        ...(bk.location_name && !/^(primary location|main( location)?)$/i.test(bk.location_name.trim())
          ? [['Where', bk.location_name] as [string, string]] : []),
        ...(bk.party_size && bk.party_size > 1 ? [['People', String(bk.party_size)] as [string, string]] : []),
        ['Payment', `${PAYMENT_WORDS[bk.payment_status] ?? '—'}${bk.deposit_required && bk.deposit_amount
          ? ` · deposit ${rupees(bk.deposit_amount)}` : ''}`],
        ...(bk.channel ? [['Booked through', CHANNEL_WORDS[bk.channel] ?? bk.channel] as [string, string]] : []),
      ]}
      actions={steps.length ? (
        <>
          {steps.map((s) => (
            <ActionButton key={s.to} label={s.label} busyLabel="Saving…" className={s.quiet ? 'btn-ghost' : undefined}
              confirm={s.confirm} confirmLabel={s.confirm ? `Yes, ${s.label.toLowerCase()}` : undefined}
              run={transitionBooking.bind(null, b, bk.id, s.to, s.reason)} />
          ))}
        </>
      ) : undefined}
    >
      {bk.status === 'pending' ? (
        <p className="bos-hint">Confirming tells the customer on WhatsApp when WhatsApp is connected.</p>
      ) : null}
      {bk.hold_expires_at && live ? (
        <p className="bos-status" role="status">
          Held until {dayTimeLabel(bk.hold_expires_at)} — the time is released if the deposit is not paid by then.
        </p>
      ) : null}
      {bk.cancellation_reason ? <p className="bos-hint">Reason: {bk.cancellation_reason}</p> : null}

      <Section title="Repeats">
        <Card>
          {series ? (
            <>
              <p style={{ marginTop: 0 }}>
                Booking {bk.occurrence_index} of {series.occurrences.length}
                {series.status === 'ended' ? ' · the series has ended' : ' · repeats'}
              </p>
              <ul className="bos-series">
                {series.occurrences.map((o) => (
                  <li key={o.id}>
                    {o.id === bk.id ? <strong>{dayTimeLabel(o.starts_at)} (this one)</strong> : (
                      <Link href={`/b/${b}/bookings/${o.id}`}>{dayTimeLabel(o.starts_at)}</Link>
                    )}
                    <span className="bos-hint"> · {STATUS_WORDS[o.status] ?? o.status}</span>
                  </li>
                ))}
              </ul>
              {series.status === 'active' && live ? (
                <>
                  <ActionForm action={shiftSeries} success="Moved." className="bos-inline-form" aria-label="Move later bookings">
                    <input type="hidden" name="businessId" value={b} />
                    <input type="hidden" name="bookingId" value={bk.id} />
                    <input type="hidden" name="seriesId" value={bk.series_id ?? ''} />
                    <input type="hidden" name="starts_at" value={bk.starts_at} />
                    <input type="hidden" name="ends_at" value={bk.ends_at} />
                    <span>Move this and later ones by</span>
                    <label><input name="days" type="number" min={-6} max={6} defaultValue={0} aria-label="Days" /> days</label>
                    <label><input name="minutes" type="number" min={-720} max={720} step={15} defaultValue={0} aria-label="Minutes" /> minutes</label>
                    <SubmitButton className="btn-ghost" busy="Moving…">Move</SubmitButton>
                  </ActionForm>
                  <ActionButton className="btn-quiet" label="End the series from this one" busyLabel="Ending…"
                    confirm="Cancel this booking and every later one in the series?" confirmLabel="Yes, end it"
                    run={endSeries.bind(null, b, bk.id, bk.series_id ?? '')} />
                </>
              ) : null}
            </>
          ) : live ? (
            <ActionForm action={repeatBooking} success="Repeats added." className="bos-inline-form" aria-label="Repeat this booking">
              <input type="hidden" name="businessId" value={b} />
              <input type="hidden" name="bookingId" value={bk.id} />
              <label>Every{' '}
                <select name="interval_weeks" defaultValue="1">
                  {[1, 2, 3, 4].map((w) => <option key={w} value={w}>{w === 1 ? 'week' : `${w} weeks`}</option>)}
                </select>
              </label>
              <label>for <input name="occurrences" type="number" min={2} max={52} defaultValue={4} aria-label="How many bookings" /> bookings</label>
              <SubmitButton className="btn-ghost" busy="Adding…">Repeat</SubmitButton>
            </ActionForm>
          ) : (
            <p className="bos-hint" style={{ margin: 0 }}>Not part of a series.</p>
          )}
        </Card>
      </Section>

      <MoneySection businessId={b} token={token} sourceType="booking" sourceId={params.bookingId} path={here} />

      <Section title="What happened">
        {history.length ? (
          <ul className="bos-history">
            {history.map((h) => (
              <li key={h.id}>
                <span>{h.from_status ? `${STATUS_WORDS[h.from_status] ?? h.from_status} → ` : 'Booked · '}{STATUS_WORDS[h.to_status] ?? h.to_status}</span>
                <span className="bos-hint"> · {dayTimeLabel(h.created_at)}{h.reason && h.reason !== 'Booking created' ? ` · ${h.reason}` : ''}</span>
              </li>
            ))}
          </ul>
        ) : <p className="bos-hint">Nothing yet.</p>}
      </Section>
    </DetailShell>
  )
}

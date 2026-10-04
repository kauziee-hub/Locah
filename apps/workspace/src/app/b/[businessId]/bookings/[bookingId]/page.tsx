import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, DetailShell, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { MoneySection } from '@/components/MoneySection'
import { dayLabel, dayTimeLabel, rupees, timeLabel } from '@/lib/when'
import { pageWords, wsLang } from '@/lib/ws-lang'
import { WS_LOCALE } from '@/lib/ws-words'
import { endSeries, repeatBooking, shiftSeries, transitionBooking } from '../actions'
import { CHANNEL_WORDS, MODE_WORDS, NEXT_STEPS, PAYMENT_WORDS, STATUS_TONE, STATUS_WORDS } from '../words'

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

/** One booking: who, when, with whom, the next step, repeats, money and what happened. */
export default async function BookingDetailPage({ params }: { params: { businessId: string; bookingId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const t = pageWords()
  const locale = WS_LOCALE[wsLang()]
  const b = params.businessId
  const base = `/v1/platform/businesses/${b}`
  const here = `/b/${b}/bookings/${params.bookingId}`
  const back = <Link href={`/b/${b}/bookings`}>← {t('Bookings')}</Link>
  const [bookingRes, historyRes] = await Promise.all([
    apiTry<{ data: Booking }>(`${base}/bookings/${params.bookingId}`, token),
    apiTry<{ data: Step[] }>(`${base}/bookings/${params.bookingId}/history`, token),
  ])
  if (!bookingRes.ok) {
    return (
      <div>
        <PageHeader title={t('Booking')} breadcrumb={back} />
        <GateNotice error={bookingRes.error} businessId={b} moduleLabel={t('Bookings')} />
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
  const status = (s: string) => (STATUS_WORDS[s] ? t(STATUS_WORDS[s]) : s)
  const when = (v: string) => dayTimeLabel(v, locale)

  return (
    <DetailShell
      breadcrumb={back}
      title={`${bk.title || t(MODE_WORDS[bk.reservation_mode] ?? 'Booking')} · ${bk.booking_number}`}
      status={<StatusPill value={bk.status} tone={STATUS_TONE[bk.status]} label={status(bk.status)} />}
      meta={[
        [t('Customer'), bk.customer ? (
          <span key="c">
            <Link href={`/b/${b}/customers/${bk.customer.id}`}>{bk.customer.name}</Link>
            {phone ? <> · <a href={`tel:${phone}`}>{bk.customer.phone}</a></> : null}
          </span>
        ) : t('Not recorded')],
        [t('When'), sameDay
          ? `${when(bk.starts_at)} – ${timeLabel(bk.ends_at, locale)}`
          : `${when(bk.starts_at)} – ${when(bk.ends_at)}`],
        ...(bk.reservation_mode === 'appointment' || bk.provider_name
          ? [[t('With'), bk.provider_name ?? t('Anyone free')] as [string, string]] : []),
        // The default "Primary Location" says nothing; a named place does.
        ...(bk.location_name && !/^(primary location|main( location)?)$/i.test(bk.location_name.trim())
          ? [[t('Where'), bk.location_name] as [string, string]] : []),
        ...(bk.party_size && bk.party_size > 1 ? [[t('People'), String(bk.party_size)] as [string, string]] : []),
        [t('Payment'), `${PAYMENT_WORDS[bk.payment_status] ? t(PAYMENT_WORDS[bk.payment_status]) : '—'}${
          bk.deposit_required && bk.deposit_amount ? ` · ${t('deposit {amount}', { amount: rupees(bk.deposit_amount) })}` : ''}`],
        ...(bk.channel ? [[t('Booked through'), CHANNEL_WORDS[bk.channel] ? t(CHANNEL_WORDS[bk.channel]) : bk.channel] as [string, string]] : []),
      ]}
      actions={steps.length ? (
        <>
          {steps.map((s) => (
            <ActionButton key={s.to} label={t(s.label)} busyLabel={t('Saving…')} className={s.quiet ? 'btn-ghost' : undefined}
              confirm={s.confirm ? t(s.confirm) : undefined} confirmLabel={s.yes ? t(s.yes) : undefined}
              run={transitionBooking.bind(null, b, bk.id, s.to, s.reason)} />
          ))}
        </>
      ) : undefined}
    >
      {bk.status === 'pending' ? (
        <p className="bos-hint">{t('Confirming tells the customer on WhatsApp when WhatsApp is connected.')}</p>
      ) : null}
      {bk.hold_expires_at && live ? (
        <p className="bos-status" role="status">
          {t('Held until {time} — the time is released if the deposit is not paid by then.', { time: when(bk.hold_expires_at) })}
        </p>
      ) : null}
      {bk.cancellation_reason ? <p className="bos-hint">{t('Reason: {why}', { why: bk.cancellation_reason })}</p> : null}

      <Section title={t('Repeats')}>
        <Card>
          {series ? (
            <>
              <p style={{ marginTop: 0 }}>
                {t('Booking {n} of {total}', { n: bk.occurrence_index ?? 1, total: series.occurrences.length })}
                {' · '}{series.status === 'ended' ? t('the series has ended') : t('repeats')}
              </p>
              <ul className="bos-series">
                {series.occurrences.map((o) => (
                  <li key={o.id}>
                    {o.id === bk.id ? <strong>{when(o.starts_at)} ({t('this one')})</strong> : (
                      <Link href={`/b/${b}/bookings/${o.id}`}>{when(o.starts_at)}</Link>
                    )}
                    <span className="bos-hint"> · {status(o.status)}</span>
                  </li>
                ))}
              </ul>
              {series.status === 'active' && live ? (
                <>
                  <ActionForm action={shiftSeries} success={t('Moved.')} className="bos-inline-form" aria-label={t('Move this and later ones')}>
                    <input type="hidden" name="businessId" value={b} />
                    <input type="hidden" name="bookingId" value={bk.id} />
                    <input type="hidden" name="seriesId" value={bk.series_id ?? ''} />
                    <input type="hidden" name="starts_at" value={bk.starts_at} />
                    <input type="hidden" name="ends_at" value={bk.ends_at} />
                    <span>{t('Move this and later ones by')}</span>
                    <label>{t('Days')} <input name="days" type="number" min={-6} max={6} defaultValue={0} /></label>
                    <label>{t('Minutes')} <input name="minutes" type="number" min={-720} max={720} step={15} defaultValue={0} /></label>
                    <SubmitButton className="btn-ghost" busy={t('Moving…')}>{t('Move')}</SubmitButton>
                  </ActionForm>
                  <ActionButton className="btn-quiet" label={t('End the series from this one')} busyLabel={t('Ending…')}
                    confirm={t('Cancel this booking and every later one in the series?')} confirmLabel={t('Yes, end it')}
                    run={endSeries.bind(null, b, bk.id, bk.series_id ?? '')} />
                </>
              ) : null}
            </>
          ) : live ? (
            <ActionForm action={repeatBooking} success={t('Repeats added.')} className="bos-inline-form" aria-label={t('Repeat this booking')}>
              <input type="hidden" name="businessId" value={b} />
              <input type="hidden" name="bookingId" value={bk.id} />
              <label>{t('Repeat every')}{' '}
                <select name="interval_weeks" defaultValue="1">
                  {[1, 2, 3, 4].map((w) => <option key={w} value={w}>{w === 1 ? t('week') : t('{n} weeks', { n: w })}</option>)}
                </select>
              </label>
              <label>{t('How many bookings')} <input name="occurrences" type="number" min={2} max={52} defaultValue={4} /></label>
              <SubmitButton className="btn-ghost" busy={t('Adding…')}>{t('Repeat')}</SubmitButton>
            </ActionForm>
          ) : (
            <p className="bos-hint" style={{ margin: 0 }}>{t('Not part of a series.')}</p>
          )}
        </Card>
      </Section>

      <MoneySection businessId={b} token={token} sourceType="booking" sourceId={params.bookingId} path={here} />

      <Section title={t('What happened')}>
        {history.length ? (
          <ul className="bos-history">
            {history.map((h) => (
              <li key={h.id}>
                <span>{h.from_status ? `${status(h.from_status)} → ` : `${t('Booked')} · `}{status(h.to_status)}</span>
                <span className="bos-hint"> · {when(h.created_at)}{h.reason && h.reason !== 'Booking created' ? ` · ${h.reason}` : ''}</span>
              </li>
            ))}
          </ul>
        ) : <p className="bos-hint">{t('Nothing yet.')}</p>}
      </Section>
    </DetailShell>
  )
}

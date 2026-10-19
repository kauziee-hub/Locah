'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import {
  cancelManagedBooking,
  fetchBookingOptions,
  fetchBookingSlots,
  fetchManagedBooking,
  rescheduleManagedBooking,
  type BookingOptions,
  type BookingSlot,
} from '@/lib/booking-api'
import type { PublicPlace } from '@/lib/public-website'
import { LANG_LOCALE, type Words } from '@/lib/site-words'
import { useSiteLang, useWords } from '@/components/website/SiteWords'

/**
 * WEB-010 — the guest's own booking, from the link they were given: what, when,
 * with whom and where to come, and the two things they can do about it (move it
 * to another free time of the same length, or cancel it after saying so).
 *
 * Owner lab (salon): this page showed the booking number over two bare
 * date-time boxes, with no address and no way to know which times were free —
 * a guest could only guess a time and be refused.
 */

type Booking = Record<string, unknown>

const SLOT_MODES = ['appointment', 'table', 'class_session', 'site_visit']
const OVER = new Set(['cancelled', 'completed', 'no_show', 'rejected'])

const statusWords = (t: Words): Record<string, string> => ({
  confirmed: t('Confirmed'), pending: t('Waiting to be confirmed'), cancelled: t('Cancelled'), completed: t('Completed'),
  no_show: t('Missed'), checked_in: t('Confirmed'),
})

/** "Wed 21 Oct · 4:00 – 5:00 pm" in the visitor's own zone (the wire format was shown here once, in UTC). */
function span(starts: unknown, ends: unknown, locale?: string): string {
  const a = new Date(String(starts ?? ''))
  const b = new Date(String(ends ?? ''))
  if (Number.isNaN(a.getTime())) return String(starts ?? '—')
  const day = a.toLocaleDateString(locale ?? 'en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
  const clock = (d: Date) => d.toLocaleTimeString(locale ?? 'en-IN', { hour: 'numeric', minute: '2-digit' })
  if (Number.isNaN(b.getTime())) return `${day} · ${clock(a)}`
  const sameDay = a.toDateString() === b.toDateString()
  return sameDay ? `${day} · ${clock(a)} – ${clock(b)}`
    : `${day} · ${clock(a)} → ${b.toLocaleDateString(locale ?? 'en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}`
}

function isoDay(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

/** The next fortnight from today, as the Book page offers it. */
function nextDays(count: number, locale?: string): { iso: string; weekday: string; date: string }[] {
  const start = new Date(`${isoDay(new Date())}T12:00:00`)
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(start.getTime() + i * 86_400_000)
    return {
      iso: isoDay(d),
      weekday: d.toLocaleDateString(locale ?? 'en-IN', { weekday: 'short' }),
      date: d.toLocaleDateString(locale ?? 'en-IN', { day: 'numeric', month: 'short' }),
    }
  })
}

export default function ManageBookingClient({
  slug,
  name,
  bookingId,
  token,
  place,
}: {
  slug: string
  name: string | null
  bookingId: string
  token: string
  /** Where the business is: its address, hours and phone, from its own website. */
  place?: PublicPlace | null
}) {
  const t = useWords()
  const lang = useSiteLang()
  // The visitor's own zone; in Tamil or Hindi, their script's weekday and month.
  const locale = lang === 'en' ? undefined : LANG_LOCALE[lang]
  const [state, setState] = useState<
    | { kind: 'loading' }
    | { kind: 'missing' }
    | { kind: 'expired' }
    | { kind: 'ready'; booking: Booking }
    | { kind: 'error'; message: string }
  >({ kind: 'loading' })
  const [options, setOptions] = useState<BookingOptions | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [panel, setPanel] = useState<'none' | 'move' | 'cancel'>('none')
  const [busy, setBusy] = useState(false)
  const [day, setDay] = useState('')
  const [slots, setSlots] = useState<BookingSlot[] | null>(null)
  const [slotNote, setSlotNote] = useState<string | null>(null)
  const [picked, setPicked] = useState<BookingSlot | null>(null)
  const [fresh, setFresh] = useState(0)

  useEffect(() => {
    if (!token) {
      setState({ kind: 'missing' })
      return
    }
    fetchManagedBooking(bookingId, token)
      .then((result) => {
        if (!result) setState({ kind: 'missing' })
        else if (result.expired) setState({ kind: 'expired' })
        else setState({ kind: 'ready', booking: result.booking })
      })
      .catch((e: Error) => setState({ kind: 'error', message: e.message }))
    // Who gives it and the cancellation window, from the website's own booking
    // page; the booking still shows if these cannot be read.
    fetchBookingOptions(slug).then(setOptions).catch(() => setOptions(null))
  }, [bookingId, token, slug])

  const booking = state.kind === 'ready' ? state.booking : null
  const mode = String(booking?.reservation_mode ?? '')

  // The free times that day for this booking: same service, same person, same
  // party — so the length stays and only a time the move would take is offered.
  useEffect(() => {
    setPicked(null)
    setSlots(null)
    setSlotNote(null)
    if (!booking || panel !== 'move' || !day || !SLOT_MODES.includes(mode)) return
    let live = true
    fetchBookingSlots(slug, {
      location_id: booking.location_id, offering_id: booking.offering_id ?? null, mode, date: day,
      party_size: booking.party_size ?? 1, provider_id: booking.provider_id ?? null,
    }).then((r) => {
      if (!live) return
      const now = String(booking.starts_at)
      const open = r.slots.filter((s) => !s.full && new Date(s.starts_at).getTime() !== new Date(now).getTime())
      if (r.closed) setSlotNote(t('Closed that day. Try another date.'))
      else if (!open.length) setSlotNote(t('Nothing is free that day. Try another date.'))
      setSlots(open)
    }).catch(() => live && setSlotNote(t('Could not load times. Try again.')))
    return () => { live = false }
  }, [slug, booking, mode, panel, day, t, fresh])

  async function onCancel() {
    setMessage(null)
    setProblem(null)
    setBusy(true)
    try {
      const data = await cancelManagedBooking(bookingId, token, 'Customer cancelled')
      setState({ kind: 'ready', booking: data })
      setPanel('none')
      setMessage(t('Booking cancelled.'))
    } catch (err) {
      const e = err as Error & { code?: string }
      if (e.code === 'cancellation_window_closed') setProblem(t('The cancellation window has closed for this booking.'))
      else if (e.code === 'expired_link') setState({ kind: 'expired' })
      else setProblem(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function onMove() {
    if (!picked) return
    setMessage(null)
    setProblem(null)
    setBusy(true)
    try {
      const data = await rescheduleManagedBooking(bookingId, token, picked.starts_at, picked.ends_at)
      setState({ kind: 'ready', booking: data })
      setPanel('none')
      setMessage(t('Booking rescheduled.'))
    } catch (err) {
      const e = err as Error & { code?: string }
      if (e.code === 'cancellation_window_closed') {
        setProblem(t('The reschedule window has closed for this booking.'))
      } else {
        // Most often someone took that time a moment ago: the day is asked
        // for again and the time taken away, never offered twice.
        setProblem(e.message || t('That time was just taken. Choose another.'))
        setFresh((n) => n + 1)
      }
    } finally {
      setBusy(false)
    }
  }

  const shell = (title: string, body: string) => (
    <main className="ls-section ls-book">
      <div className="ls-inner ls-checkout">
        <header className="ls-confirm__head">
          {name ? <p className="ls-meta">{name}</p> : null}
          <h1 className="ls-confirm__title">{title}</h1>
          <p className="ls-confirm__lede">{body}</p>
        </header>
        {place?.phone ? <a className="ls-btn ls-btn--outline" href={`tel:${place.phone}`}>{t('Call {phone}', { phone: place.phone })}</a> : null}
      </div>
    </main>
  )
  if (state.kind === 'loading') return shell(t('Your booking'), t('Loading…'))
  if (state.kind === 'missing') return shell(t('Booking not found'), t('This management link is invalid.'))
  if (state.kind === 'expired') return shell(t('Link expired'), t('This management link has expired. Contact the business for help.'))
  if (state.kind === 'error') return shell(t('Unavailable'), state.message)

  const b = state.booking
  const status = String(b.status)
  const over = OVER.has(status)
  const when = span(b.starts_at, b.ends_at, locale)
  const provider = options?.providers.find((p) => p.id === b.provider_id)?.display_name
  const location = options?.locations.find((l) => l.id === b.location_id)
  const where = [options && options.locations.length > 1 ? location?.name : '', place?.address || place?.locality]
    .filter(Boolean).join(', ')
  const payAtVisit = b.payment_status === 'pending_offline'
    || (b.payment_status === 'pending' && ['pay_at_business', 'cod', 'pay_later'].includes(String(b.payment_method)))
  const windowHours = options?.policy.cancel_window_hours ?? 0
  const canPickTimes = SLOT_MODES.includes(mode)

  return (
    <main className="ls-section ls-book">
      <div className="ls-inner ls-book__layout">
        <div className="ls-checkout ls-book__flow">
          <header className="ls-confirm__head">
            <p className="ls-meta">{name ?? slug}</p>
            <h1 className="ls-confirm__title">{statusWords(t)[status] ?? status}</h1>
            <p className="ls-confirm__lede">
              {t('Booking {number}', { number: String(b.booking_number) })} · {String(b.title)}
            </p>
          </header>

          {message ? <p className="ls-bill__card" role="status">{message}</p> : null}
          {problem ? <p role="alert">{problem}</p> : null}

          {!over && panel === 'none' ? (
            <div className="ls-bill__actions">
              {canPickTimes ? (
                <button type="button" className="ls-btn" onClick={() => { setPanel('move'); setDay(isoDay(new Date(String(b.starts_at)))) }}>
                  {t('Move to another time')}
                </button>
              ) : null}
              <button type="button" className="ls-btn ls-btn--outline" onClick={() => setPanel('cancel')}>
                {t('Cancel booking')}
              </button>
            </div>
          ) : null}

          {!over && panel === 'cancel' ? (
            <section className="ls-bill__card" aria-labelledby="cancel-h">
              <h2 id="cancel-h" className="ls-checkout__h">{t('Cancel this booking?')}</h2>
              <p>{t('{when} will be given to someone else.', { when })}</p>
              <div className="ls-bill__actions">
                <button type="button" className="ls-btn" disabled={busy} onClick={onCancel}>
                  {busy ? t('Cancelling…') : t('Yes, cancel it')}
                </button>
                <button type="button" className="ls-btn ls-btn--outline" disabled={busy} onClick={() => setPanel('none')}>
                  {t('Keep it')}
                </button>
              </div>
            </section>
          ) : null}

          {!over && panel === 'move' ? (
            <section className="ls-bill__card ls-checkout__fields ls-book__form" aria-labelledby="move-h">
              <h2 id="move-h" className="ls-checkout__h">{t('Move to another time')}</h2>
              <p className="ls-meta">{t('Only times that are free for this booking are shown.')}</p>
              <div className="ls-book__days" role="group" aria-label={t('Pick a day')}>
                {nextDays(14, locale).map((d) => (
                  <button key={d.iso} type="button" className={`ls-day${day === d.iso ? ' is-on' : ''}`}
                    onClick={() => setDay(d.iso)} data-day={d.iso} aria-pressed={day === d.iso}>
                    <small>{d.weekday}</small>
                    <strong>{d.date}</strong>
                  </button>
                ))}
              </div>
              <label>{t('Another date')}
                <input type="date" min={isoDay(new Date())} value={day} onChange={(e) => setDay(e.target.value)}
                  style={{ display: 'block', width: '100%', marginTop: 4 }} />
              </label>
              {slots && slots.length ? (
                <fieldset className="ls-book__times">
                  <legend>{t('Time')}</legend>
                  <div className="ls-choice">
                    {slots.map((s) => (
                      <button key={s.starts_at} type="button" aria-pressed={picked?.starts_at === s.starts_at}
                        className={`ls-chip${picked?.starts_at === s.starts_at ? ' is-on' : ''}`} onClick={() => setPicked(s)}>
                        {s.label}
                      </button>
                    ))}
                  </div>
                </fieldset>
              ) : null}
              {slotNote ? <p role="status">{slotNote}</p> : null}
              <div className="ls-bill__actions">
                <button type="button" className="ls-btn ls-checkout__place" disabled={!picked || busy} onClick={onMove}>
                  {busy ? t('Moving…') : picked ? t('Move to {when}', { when: span(picked.starts_at, picked.ends_at, locale) }) : t('Pick a new time')}
                </button>
                <button type="button" className="ls-btn ls-btn--outline" disabled={busy} onClick={() => setPanel('none')}>
                  {t('Keep this time')}
                </button>
              </div>
            </section>
          ) : null}

          {!over && !canPickTimes && place?.phone ? (
            <p className="ls-meta">{t('To change the dates, call {phone}.', { phone: place.phone })}</p>
          ) : null}

          <div className="ls-bill__actions" style={{ marginTop: '1.5rem' }}>
            <Link className="ls-btn ls-btn--outline" href={`/${slug}`}>{t('Back to {business}', { business: name ?? slug })}</Link>
          </div>
        </div>

        <aside className="ls-bill__card ls-book__summary" aria-label={t('Your booking')}>
          <p className="ls-meta">{name ?? slug}</p>
          <h2 className="ls-checkout__h">{String(b.title)}</h2>
          <dl className="ls-book__facts">
            <dt>{t('When')}</dt><dd>{when}</dd>
            {provider ? (<><dt>{t('With')}</dt><dd>{provider}</dd></>) : null}
            {where ? (<><dt>{t('Where')}</dt><dd>{where}</dd></>) : null}
            {payAtVisit ? (<><dt>{t('Payment')}</dt><dd>{t('Pay at your visit')}</dd></>) : null}
            {!over && windowHours > 0 ? (
              <><dt>{t('Changes')}</dt><dd>{t('Free to cancel up to {h} hours before.', { h: windowHours })}</dd></>
            ) : null}
          </dl>
          {place?.hours_summary ? <p className="ls-meta">{t('Open {hours}', { hours: place.hours_summary })}</p> : null}
          {place?.phone ? (
            <p><a href={`tel:${place.phone}`}>{t('Call {phone}', { phone: place.phone })}</a></p>
          ) : (
            <p className="ls-meta">{t('Need help? Contact the business directly with your booking number.')}</p>
          )}
        </aside>
      </div>
    </main>
  )
}

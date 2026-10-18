'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import {
  checkBookingRange,
  createPublicBooking,
  fetchBookingSlots,
  joinWaitlist,
  type BookingOptions,
  type BookingSlot,
} from '@/lib/booking-api'
import { useWords } from '@/components/website/SiteWords'

/**
 * WEB-009 Booking — one engine, a flow per kind of booking (Founder
 * refinement — Bookings §5–§14, §28): a service picks a person and a time, a
 * table picks party size and a time, a class shows places left, a stay picks
 * nights, a rental picks a range, a site visit a time with the team, an event
 * the date. Every time or range shown comes from the same checks the booking
 * makes when it is confirmed.
 */

type Mode = 'appointment' | 'table' | 'class_session' | 'accommodation' | 'rental' | 'site_visit' | 'event_date'
type Choice = {
  key: string; mode: Mode; title: string; offeringId: string | null; minutes: number; price: number | null
  description?: string | null
}
type Picked = { starts_at: string; ends_at: string; label: string; full?: boolean; resourceId?: string | null }

const SLOT_MODES: Mode[] = ['appointment', 'table', 'class_session', 'site_visit']
const GROUP: Record<Mode, string> = {
  appointment: 'Appointments', table: 'Tables', class_session: 'Classes', accommodation: 'Stays',
  rental: 'Rentals', site_visit: 'Site visits', event_date: 'Events',
}
const field = { display: 'block', width: '100%', marginTop: 4 } as const

function today(): string {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

/** The next week as a visitor picks from it: weekday and date, today first. */
function nextDays(count: number): { iso: string; weekday: string; date: string }[] {
  const start = new Date(`${today()}T12:00:00`)
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(start.getTime() + i * 86_400_000)
    return {
      iso: new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10),
      weekday: d.toLocaleDateString('en-IN', { weekday: 'short' }),
      date: d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
    }
  })
}

function sayDay(iso: string): string {
  if (!iso) return ''
  return new Date(`${iso}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

export default function BookClient({
  slug,
  options,
  customer,
  authToken,
  initialOfferingId,
}: {
  slug: string
  options: BookingOptions
  /** The signed-in LOCAH customer, if any: the booking joins their own record. */
  customer?: { name: string; email: string } | null
  authToken?: string | null
  /** From a Book button on the website: that offering is chosen already. */
  initialOfferingId?: string | null
}) {
  const t = useWords()
  const choices = useMemo<Choice[]>(() => {
    const list: Choice[] = options.offerings.map((o) => ({
      key: o.id, mode: o.mode as Mode, title: o.title, offeringId: o.id, minutes: o.minutes, price: o.price_amount,
      description: o.description,
    }))
    if (options.table) list.unshift({ key: 'table', mode: 'table', title: t('Reserve a table'), offeringId: null, minutes: 90, price: null })
    return list
  }, [options, t])
  const [choiceKey, setChoiceKey] = useState<string>(
    () => (initialOfferingId ? choices.find((c) => c.offeringId === initialOfferingId)?.key : undefined)
      ?? (choices.length === 1 ? choices[0].key : ''))
  const choice = choices.find((c) => c.key === choiceKey) ?? null
  const mode: Mode | null = choice?.mode ?? null

  const [locationId, setLocationId] = useState(options.locations[0]?.id || '')
  const [providerId, setProviderId] = useState('')
  const [partySize, setPartySize] = useState(mode === 'table' ? 2 : 1)
  const [day, setDay] = useState('')
  const [checkIn, setCheckIn] = useState('')
  const [checkOut, setCheckOut] = useState('')
  const [rentStart, setRentStart] = useState('')
  const [rentEnd, setRentEnd] = useState('')
  const [freeTime, setFreeTime] = useState('')
  const [slots, setSlots] = useState<BookingSlot[] | null>(null)
  const [slotNote, setSlotNote] = useState<string | null>(null)
  const [rooms, setRooms] = useState<{ resource_id: string; name: string }[]>([])
  const [picked, setPicked] = useState<Picked | null>(null)
  const [name, setName] = useState(customer?.name ?? '')
  const [email, setEmail] = useState(customer?.email ?? '')
  const [phone, setPhone] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<
    | { kind: 'booked'; id: string; number: string; token: string; deposit: number | null; payment: string }
    | { kind: 'waitlist' }
    | null
  >(null)

  const providers = useMemo(
    () => options.providers.filter((p) =>
      (!locationId || p.location_ids.includes(locationId)) && (!choice?.offeringId || p.offering_ids.includes(choice.offeringId))),
    [options.providers, locationId, choice],
  )

  // A new choice, place or day starts the time over.
  useEffect(() => {
    setPicked(null)
    setSlots(null)
    setSlotNote(null)
    setRooms([])
    setError(null)
  }, [choiceKey, locationId, providerId, partySize, day, checkIn, checkOut, rentStart, rentEnd])
  useEffect(() => { setPartySize(mode === 'table' ? 2 : 1) }, [mode])

  // Slot modes: the times open that day, straight from the engine.
  useEffect(() => {
    if (!choice || !mode || !SLOT_MODES.includes(mode) || !day || !locationId) return
    let live = true
    fetchBookingSlots(slug, {
      location_id: locationId, offering_id: choice.offeringId, mode, date: day,
      party_size: partySize, provider_id: providerId || null,
    }).then((r) => {
      if (!live) return
      if (!r.hours_known) setSlotNote(t('Pick a time and we will check it.'))
      else if (r.closed) setSlotNote(t('Closed that day. Try another date.'))
      else if (!r.slots.length) setSlotNote(t('Nothing is free that day. Try another date.'))
      setSlots(r.slots)
    }).catch(() => live && setError(t('Could not load times. Try again.')))
    return () => { live = false }
  }, [slug, choice, mode, day, locationId, partySize, providerId, t])

  async function checkRange() {
    if (!choice || !mode) return
    setBusy(true)
    setError(null)
    try {
      const body: Record<string, unknown> = { location_id: locationId, offering_id: choice.offeringId, mode, party_size: partySize }
      if (mode === 'accommodation') Object.assign(body, { check_in: checkIn, check_out: checkOut })
      else if (mode === 'event_date') Object.assign(body, { date: day })
      else Object.assign(body, { starts_at: new Date(rentStart).toISOString(), ends_at: new Date(rentEnd).toISOString() })
      const r = await checkBookingRange(slug, body)
      if (!r.available) {
        setError(r.reason || t('Not available for those dates.'))
        return
      }
      setRooms(mode === 'accommodation' ? r.resources : [])
      setPicked({ starts_at: r.starts_at, ends_at: r.ends_at, label: t('Available'), resourceId: null })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function pickFreeTime() {
    if (!day || !freeTime || !choice) return
    const start = new Date(`${day}T${freeTime}`)
    setPicked({ starts_at: start.toISOString(), ends_at: new Date(start.getTime() + choice.minutes * 60_000).toISOString(), label: freeTime })
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!choice || !mode || !picked) return
    setBusy(true)
    setError(null)
    const guest = { name, email, phone: phone || null }
    try {
      if (picked.full) {
        await joinWaitlist(slug, {
          location_id: locationId, offering_id: choice.offeringId, reservation_mode: mode,
          starts_at: picked.starts_at, ends_at: picked.ends_at, party_size: partySize, guest,
        }, authToken)
        setDone({ kind: 'waitlist' })
        return
      }
      const data = await createPublicBooking(slug, {
        location_id: locationId, offering_id: choice.offeringId, provider_id: providerId || null,
        reservation_mode: mode, title: choice.offeringId ? null : choice.title,
        starts_at: picked.starts_at, ends_at: picked.ends_at, party_size: partySize,
        resource_ids: picked.resourceId ? [picked.resourceId] : [],
        payment_method: options.payment_methods[0] || 'cod', notes: notes || null, guest,
      }, authToken)
      setDone({
        kind: 'booked', id: String(data.id), number: String(data.booking_number), token: String(data.management_token),
        deposit: data.deposit_required ? Number(data.deposit_amount || 0) : null, payment: String(data.payment_status),
      })
    } catch (err) {
      const x = err as Error & { code?: string }
      setError(x.code === 'slot_conflict' || x.code === 'no_resource_free'
        ? t('That time was just taken. Choose another.') : x.message)
      if (x.code === 'slot_conflict' || x.code === 'no_resource_free') setPicked(null)
    } finally {
      setBusy(false)
    }
  }

  if (done?.kind === 'waitlist') {
    return (
      <main className="ls-section ls-book">
        <div className="ls-inner ls-checkout">
          <h1 className="ls-confirm__title">{t('You are on the waitlist')}</h1>
          <p className="ls-confirm__lede">{t('If a place opens, we will offer it to you with a link. Nothing is booked until you take it.')}</p>
        </div>
      </main>
    )
  }
  if (done?.kind === 'booked') {
    return (
      <main className="ls-section ls-book">
        <div className="ls-inner ls-checkout">
          <header className="ls-confirm__head">
            <h1 className="ls-confirm__title">{t('Confirmed')}</h1>
            <p className="ls-confirm__lede">
              {t('Booking {number} is reserved.', { number: done.number })}
              {done.deposit !== null ? ` ${t('Deposit {amount}', { amount: done.deposit })} · ${done.payment}.` : null}
            </p>
          </header>
          <div className="ls-bill__actions">
            <Link className="ls-btn" href={`/${slug}/bookings/${done.id}?token=${encodeURIComponent(done.token)}`}>{t('Manage this booking')}</Link>
            <Link className="ls-btn ls-btn--outline" href={`/${slug}`}>{t('Back to {business}', { business: options.business.display_name })}</Link>
          </div>
        </div>
      </main>
    )
  }

  const grouped = (Object.keys(GROUP) as Mode[]).map((m) => [m, choices.filter((c) => c.mode === m)] as const).filter(([, cs]) => cs.length)
  const showProvider = (mode === 'appointment' || mode === 'site_visit') && providers.length > 0
  const readyForContact = Boolean(picked)

  // The whole flow is visible from the start — what, when, who you are — and
  // what is being booked is summed up beside it (certification: a Book page
  // that showed only two chips read as "not a booking flow").
  // A retreat whose every choice is a stay asks for dates, never "a day and a time".
  const timed = choice ? SLOT_MODES.includes(choice.mode) : choices.some((c) => SLOT_MODES.includes(c.mode))
  return (
    <main className="ls-section ls-book">
      <div className="ls-inner ls-book__layout">
      <div className="ls-checkout ls-book__flow">
      <h1 className="ls-confirm__title">{t('Book')}</h1>

      {choices.length === 0 ? <p>{t('Nothing can be booked online yet.')}</p> : null}

      {choices.length > 1 ? (
        <section aria-labelledby="what-h" className="ls-bill__card">
          <h2 id="what-h" className="ls-checkout__h"><span className="ls-book__n" aria-hidden="true">1</span>{t('What would you like to book?')}</h2>
          {grouped.map(([m, cs]) => (
            <div key={m} className="ls-book__group">
              <p className="ls-meta">{t(GROUP[m])}</p>
              <div className="ls-choice">
                {cs.map((c) => {
                  // Each choice says what it is, how long it takes and what it
                  // costs — not a pill of a name and a price (certification).
                  const meta = [SLOT_MODES.includes(c.mode) && c.minutes ? t('{n} min', { n: c.minutes }) : '',
                    c.price === null ? '' : c.mode === 'accommodation' ? t('₹{amount} a night', { amount: c.price })
                      : `₹${c.price}`].filter(Boolean).join(' · ')
                  return (
                    <button key={c.key} type="button" onClick={() => setChoiceKey(c.key)} aria-pressed={c.key === choiceKey}
                      className={`ls-chip ls-book__choice${c.key === choiceKey ? ' is-on' : ''}`}>
                      <span className="ls-book__choice-name">{c.title}</span>
                      {meta ? <span className="ls-book__choice-meta">{meta}</span> : null}
                      {c.description ? <span className="ls-book__choice-text">{c.description}</span> : null}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </section>
      ) : choice ? <h2 className="ls-checkout__h ls-book__one">{choice.title}</h2> : null}

      {choice && mode ? (
        <form onSubmit={submit} className="ls-bill__card ls-checkout__fields ls-book__form">
          {options.locations.length > 1 ? (
            <label>{t('Location')}
              <select value={locationId} onChange={(e) => setLocationId(e.target.value)} style={field}>
                {options.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
          ) : null}

          {showProvider ? (
            <label>{mode === 'site_visit' ? t('Who will show you around') : t('With')}
              <select value={providerId} onChange={(e) => setProviderId(e.target.value)} style={field}>
                <option value="">{t('Anyone available')}</option>
                {providers.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
              </select>
            </label>
          ) : null}

          {mode === 'table' ? (
            <label>{t('How many people')}
              <input type="number" min={1} max={options.table?.max_party ?? 20} value={partySize}
                onChange={(e) => setPartySize(Math.max(1, Number(e.target.value) || 1))} style={field} />
            </label>
          ) : null}

          {SLOT_MODES.includes(mode) ? (
            <>
              <div className="ls-book__days" role="group" aria-label={t('Pick a day')}>
                {nextDays(7).map((d) => (
                  <button key={d.iso} type="button" className={`ls-day${day === d.iso ? ' is-on' : ''}`}
                    onClick={() => setDay(d.iso)} data-day={d.iso}>
                    <small>{d.weekday}</small>
                    <strong>{d.date}</strong>
                  </button>
                ))}
              </div>
              <label>{t('Another date')}
                <input type="date" min={today()} value={day} onChange={(e) => setDay(e.target.value)} required style={field} />
              </label>
              {slots && slots.length ? (
                <fieldset className="ls-book__times">
                  <legend>{t('Time')}</legend>
                  <div className="ls-choice">
                    {slots.map((s) => {
                      const on = picked?.starts_at === s.starts_at
                      const full = Boolean(s.full)
                      if (full && !options.policy.waitlist_enabled) return null
                      return (
                        <button key={s.starts_at} type="button" aria-pressed={on}
                          className={`ls-chip${on ? ' is-on' : ''}`}
                          onClick={() => setPicked({ ...s, resourceId: null })}>
                          {s.label}
                          {full ? ` · ${t('full — join waitlist')}`
                            : s.places_left !== undefined && s.places_left !== null ? ` · ${t('{n} left', { n: s.places_left })}` : ''}
                        </button>
                      )
                    })}
                  </div>
                </fieldset>
              ) : null}
              {slotNote ? <p role="status">{slotNote}</p> : null}
              {slots && !slots.length && day && slotNote === t('Pick a time and we will check it.') ? (
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'end' }}>
                  <label style={{ flex: 1 }}>{t('Time')}
                    <input type="time" value={freeTime} onChange={(e) => setFreeTime(e.target.value)} style={field} />
                  </label>
                  <button type="button" className="ls-btn ls-btn--outline" onClick={pickFreeTime}>{t('Use this time')}</button>
                </div>
              ) : null}
            </>
          ) : null}

          {mode === 'accommodation' ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(9rem, 1fr))', gap: '0.75rem' }}>
                <label>{t('Check-in')}<input type="date" min={today()} value={checkIn} onChange={(e) => setCheckIn(e.target.value)} required style={field} /></label>
                <label>{t('Check-out')}<input type="date" min={checkIn || today()} value={checkOut} onChange={(e) => setCheckOut(e.target.value)} required style={field} /></label>
                <label>{t('Guests')}<input type="number" min={1} max={20} value={partySize} onChange={(e) => setPartySize(Math.max(1, Number(e.target.value) || 1))} style={field} /></label>
              </div>
              {!picked ? <button type="button" className="ls-btn ls-btn--outline" disabled={busy || !checkIn || !checkOut} onClick={checkRange}>{t('Check availability')}</button> : null}
              {picked && rooms.length > 1 ? (
                <label>{t('Room')}
                  <select value={picked.resourceId ?? ''} onChange={(e) => setPicked({ ...picked, resourceId: e.target.value || null })} style={field}>
                    <option value="">{t('Any free room')}</option>
                    {rooms.map((r) => <option key={r.resource_id} value={r.resource_id}>{r.name}</option>)}
                  </select>
                </label>
              ) : null}
            </>
          ) : null}

          {mode === 'rental' ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(12rem, 1fr))', gap: '0.75rem' }}>
                <label>{t('From')}<input type="datetime-local" value={rentStart} onChange={(e) => setRentStart(e.target.value)} required style={field} /></label>
                <label>{t('Until')}<input type="datetime-local" value={rentEnd} onChange={(e) => setRentEnd(e.target.value)} required style={field} /></label>
              </div>
              <label>{t('How many')}<input type="number" min={1} max={50} value={partySize} onChange={(e) => setPartySize(Math.max(1, Number(e.target.value) || 1))} style={field} /></label>
              {!picked ? <button type="button" className="ls-btn ls-btn--outline" disabled={busy || !rentStart || !rentEnd} onClick={checkRange}>{t('Check availability')}</button> : null}
            </>
          ) : null}

          {mode === 'event_date' ? (
            <>
              <label>{t('Event date')}<input type="date" min={today()} value={day} onChange={(e) => setDay(e.target.value)} required style={field} /></label>
              <label>{t('Guests')}<input type="number" min={1} max={5000} value={partySize} onChange={(e) => setPartySize(Math.max(1, Number(e.target.value) || 1))} style={field} /></label>
              {!picked ? <button type="button" className="ls-btn ls-btn--outline" disabled={busy || !day} onClick={checkRange}>{t('Check the date')}</button> : null}
            </>
          ) : null}

          {picked && !SLOT_MODES.includes(mode) ? <p role="status">{t('Available')} ✓</p> : null}
          {error ? <p role="alert">{error}</p> : null}

          {!readyForContact ? (
            // Where the booking is confirmed, shown before it can be: the whole
            // way to a booking is visible from the first screen.
            <div className="ls-book__last ls-book__pending">
              <span className="ls-meta">{t('Your name and phone number')}</span>
              <button type="button" className="ls-btn ls-checkout__place" disabled aria-describedby="book-time-first">
                {t('Confirm booking')}
              </button>
              <small id="book-time-first" className="ls-meta">
                {timed ? t('Choose a day and a time first.') : t('Choose your dates first.')}
              </small>
            </div>
          ) : null}

          {readyForContact ? (
            <>
              <label>{t('Name')}<input value={name} onChange={(e) => setName(e.target.value)} required style={field} /></label>
              <label>{t('Email')}<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} readOnly={Boolean(customer)} required style={field} /></label>
              <label>{t('Phone')}<input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" style={field} /></label>
              {mode !== 'class_session' ? (
                <label>{t('Anything we should know? (optional)')}
                  <textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} rows={2} style={field} />
                </label>
              ) : null}
              {options.policy.require_deposit && !picked?.full ? (
                <p style={{ opacity: 0.85 }}>{t('A deposit of {amount} is required.', { amount: options.policy.deposit_amount ?? '' })}</p>
              ) : null}
              <button type="submit" className="ls-btn ls-checkout__place" disabled={busy}>
                {busy ? t('Booking…') : picked?.full ? t('Join the waitlist') : t('Confirm booking')}
              </button>
            </>
          ) : null}
        </form>
      ) : null}

      {!choice && choices.length > 1 ? (
        <ol className="ls-book__next">
          <li className="ls-bill__card">
            <span className="ls-book__n" aria-hidden="true">2</span>
            {timed ? t('Choose a day and a time') : t('Choose your dates')}
          </li>
          <li className="ls-bill__card ls-book__last">
            <span>
              <span className="ls-book__n" aria-hidden="true">3</span>
              {t('Your name and phone number')}
            </span>
            {/* Where the booking is confirmed, shown from the start. */}
            <button type="button" className="ls-btn ls-checkout__place" disabled aria-describedby="book-first">
              {t('Confirm booking')}
            </button>
            <small id="book-first" className="ls-meta">{t('Choose what you would like to book first.')}</small>
          </li>
        </ol>
      ) : null}
      </div>

      {choices.length ? (
        <aside className="ls-bill__card ls-book__summary" aria-label={t('Your booking')}>
          <p className="ls-meta">{options.business.display_name}</p>
          <h2 className="ls-checkout__h">{choice ? choice.title : t('Your booking')}</h2>
          <dl className="ls-book__facts">
            {choice && choice.price !== null ? (<><dt>{t('Price')}</dt><dd>₹{choice.price}</dd></>) : null}
            {choice && timed && choice.minutes ? (<><dt>{t('Takes')}</dt><dd>{t('{n} min', { n: choice.minutes })}</dd></>) : null}
            {picked ? (<><dt>{t('When')}</dt><dd>{day ? `${sayDay(day)} · ` : ''}{picked.label}</dd></>) : null}
            {options.policy.cancel_window_hours > 0 ? (
              <><dt>{t('Changes')}</dt><dd>{t('Free to cancel up to {h} hours before.', { h: options.policy.cancel_window_hours })}</dd></>
            ) : null}
            {options.policy.require_deposit ? (
              <><dt>{t('Deposit')}</dt><dd>₹{options.policy.deposit_amount ?? ''}</dd></>
            ) : (<><dt>{t('Payment')}</dt><dd>{t('Pay at your visit')}</dd></>)}
          </dl>
          {!choice ? <p className="ls-meta">{t('Choose what you would like to book to see the times.')}</p> : null}
        </aside>
      ) : null}
      </div>
    </main>
  )
}

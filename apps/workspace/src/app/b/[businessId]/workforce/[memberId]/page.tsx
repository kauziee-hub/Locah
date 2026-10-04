import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { clockLabel, dayLabel, todayInIndia } from '@/lib/when'
import { pageWords, wsLang } from '@/lib/ws-lang'
import { WS_LOCALE } from '@/lib/ws-words'
import {
  addDatedHours, addPlace, addService, addWeeklyHours, removeHours, removePlace, removeService, setMemberActive,
} from '../actions'

export const dynamic = 'force-dynamic'

type Slot = {
  id: string; location_id: string | null; weekday: number | null; exception_date: string | null
  start_time: string; end_time: string; is_available: boolean
}
type Member = {
  display_name: string; designation: string | null; phone: string | null; status: string
  locations: { location_id: string; is_primary: boolean }[]
  services: { offering_id: string }[]
  availability: Slot[]
}
type Named = { id: string; name?: string; title?: string; offering_type?: string; status?: string }

// Weekly hours count days as Python does: 0 is Monday.
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const BOOKABLE = new Set(['service', 'class_session', 'accommodation', 'rental'])
const allDay = (a: Slot) => a.start_time.startsWith('00:00') && a.end_time.startsWith('23:59')

/** One person: where they work, what customers can book them for, their hours and time off. */
export default async function WorkforceMemberPage({ params }: { params: { businessId: string; memberId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const t = pageWords()
  const locale = WS_LOCALE[wsLang()]
  const b = params.businessId
  const id = params.memberId
  const back = <Link href={`/b/${b}/workforce`}>← {t('Staff & rota')}</Link>
  const [memberRes, offeringsRes, locationsRes] = await Promise.all([
    apiTry<{ data: Member }>(`/v1/platform/businesses/${b}/workforce/members/${id}`, token),
    apiTry<{ data: Named[] }>(`/v1/platform/businesses/${b}/products`, token),
    apiTry<{ data: Named[] }>(`/v1/platform/businesses/${b}/locations`, token),
  ])
  if (!memberRes.ok) {
    return (
      <div>
        <PageHeader title={t('Team member')} breadcrumb={back} />
        <GateNotice error={memberRes.error} businessId={b} moduleLabel={t('Staff & rota')} />
      </div>
    )
  }
  const m = memberRes.data.data
  const name = m.display_name
  const offerings = offeringsRes.ok ? offeringsRes.data.data || [] : []
  const locations = locationsRes.ok ? locationsRes.data.data || [] : []
  const placeName = (lid: string | null) => (lid ? locations.find((l) => l.id === lid)?.name || t('Another place') : t('Any place'))
  const serviceName = (oid: string) => offerings.find((o) => o.id === oid)?.title || t('A service no longer listed')
  const doing = new Set(m.services.map((s) => s.offering_id))
  const canAdd = offerings.filter((o) => BOOKABLE.has(String(o.offering_type)) && o.status !== 'archived' && !doing.has(o.id))
  const notYetAt = locations.filter((l) => !m.locations.some((x) => x.location_id === l.id))
  const weekly = m.availability.filter((a) => a.weekday !== null)
    .sort((x, y) => (x.weekday! - y.weekday!) || x.start_time.localeCompare(y.start_time))
  const today = todayInIndia()
  const dated = m.availability.filter((a) => a.exception_date && a.exception_date >= today)
    .sort((x, y) => x.exception_date!.localeCompare(y.exception_date!) || x.start_time.localeCompare(y.start_time))
  const active = m.status === 'active'
  const span = (a: Slot) => `${clockLabel(a.start_time)}–${clockLabel(a.end_time)}`
  const hidden = (
    <>
      <input type="hidden" name="businessId" value={b} />
      <input type="hidden" name="memberId" value={id} />
    </>
  )
  const removeSlot = (slotId: string) => (
    <ActionButton className="btn-quiet" label={t('Remove')} busyLabel={t('Removing…')} confirm={t('Remove these hours?')}
      confirmLabel={t('Yes, remove')} run={removeHours.bind(null, b, id, slotId)} />
  )

  return (
    <div className="bos-page">
      <PageHeader
        title={name}
        subtitle={m.designation || undefined}
        breadcrumb={back}
        actions={<StatusPill value={m.status} tone={active ? 'good' : 'neutral'} label={active ? t('Taking bookings') : t('Not taking bookings')} />}
      />
      {m.phone ? <p className="bos-hint" style={{ marginTop: 0 }}><a href={`tel:${m.phone.replace(/[^+\d]/g, '')}`}>{m.phone}</a></p> : null}

      <Section title={t('Works at')}>
        <Card>
          <ul className="bos-resources">
            {m.locations.map((l) => (
              <li key={l.location_id}>
                <strong>{placeName(l.location_id)}</strong>
                {l.is_primary ? <span className="bos-hint">{t('main place')}</span> : null}
                {m.locations.length > 1 ? (
                  <ActionButton className="btn-quiet" label={t('Remove')} busyLabel={t('Removing…')}
                    confirm={t('{name} no longer works at {place}?', { name, place: placeName(l.location_id) })}
                    confirmLabel={t('Yes, remove')} run={removePlace.bind(null, b, id, l.location_id)} />
                ) : null}
              </li>
            ))}
          </ul>
          {notYetAt.length ? (
            <ActionForm action={addPlace} success={t('Added.')} className="bos-inline-form" aria-label={t('Add a place they work')}>
              {hidden}
              <select name="location_id" aria-label={t('Place')}>
                {notYetAt.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <label className="bos-check"><input type="checkbox" name="is_primary" /> {t('Main place')}</label>
              <SubmitButton className="btn-ghost" busy={t('Adding…')}>{t('Add place')}</SubmitButton>
            </ActionForm>
          ) : null}
        </Card>
      </Section>

      <Section title={t('Customers can book them for')}>
        <Card>
          {m.services.length ? (
            <ul className="bos-resources">
              {m.services.map((s) => (
                <li key={s.offering_id}>
                  <strong>{serviceName(s.offering_id)}</strong>
                  <ActionButton className="btn-quiet" label={t('Remove')} busyLabel={t('Removing…')}
                    confirm={t('Stop offering {name} for {service}? Bookings already made stay.', { name, service: serviceName(s.offering_id) })}
                    confirmLabel={t('Yes, remove')} run={removeService.bind(null, b, id, s.offering_id)} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="bos-hint" style={{ marginTop: 0 }}>{t('Nothing yet. Customers can pick {name} only for services listed here.', { name })}</p>
          )}
          {canAdd.length ? (
            <ActionForm action={addService} success={t('Added.')} className="bos-inline-form" aria-label={t('Add a service they do')}>
              {hidden}
              <select name="offering_id" aria-label={t('Service')}>
                {canAdd.map((o) => <option key={o.id} value={o.id}>{o.title}</option>)}
              </select>
              <SubmitButton className="btn-ghost" busy={t('Adding…')}>{t('Add service')}</SubmitButton>
            </ActionForm>
          ) : m.services.length ? null : (
            <p className="bos-hint">
              {t('There are no bookable services yet.')} <Link href={`/b/${b}/offerings/new`}>{t('Add a service first')}</Link>
            </p>
          )}
        </Card>
      </Section>

      <Section title={t('Weekly hours')}>
        <Card>
          {weekly.length ? (
            <ul className="bos-resources">
              {weekly.map((a) => (
                <li key={a.id}>
                  <strong>{t(DAYS[a.weekday!])}</strong>
                  <span>{a.is_available ? span(a) : t('Break {time}', { time: span(a) })}</span>
                  {locations.length > 1 ? <span className="bos-hint">{placeName(a.location_id)}</span> : null}
                  {removeSlot(a.id)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="bos-hint" style={{ marginTop: 0 }}>
              {t('No hours saved, so bookings follow your opening hours. Once any are saved, {name} is booked only inside them.', { name })}
            </p>
          )}
          <ActionForm action={addWeeklyHours} success={t('Saved.')} className="bos-inline-form" aria-label={t('Add weekly hours')}>
            {hidden}
            <select name="weekday" aria-label={t('Day')} defaultValue="0">
              {DAYS.map((d, i) => <option key={d} value={i}>{t(d)}</option>)}
            </select>
            <input name="start_time" type="time" defaultValue="09:00" aria-label={t('Start time')} required />
            <input name="end_time" type="time" defaultValue="17:00" aria-label={t('End time')} required />
            <select name="kind" aria-label={t('Working or a break')} defaultValue="work">
              <option value="work">{t('Working')}</option>
              <option value="break">{t('Break (not bookable)')}</option>
            </select>
            <SubmitButton className="btn-ghost" busy={t('Saving…')}>{t('Add hours')}</SubmitButton>
          </ActionForm>
        </Card>
      </Section>

      <Section title={t('Time off and one-off hours')}>
        <Card>
          {dated.length ? (
            <ul className="bos-resources">
              {dated.map((a) => (
                <li key={a.id}>
                  <strong>{dayLabel(a.exception_date, locale)}</strong>
                  <span>{a.is_available ? t('Working {time}', { time: span(a) }) : allDay(a) ? t('Away all day') : t('Away {time}', { time: span(a) })}</span>
                  {removeSlot(a.id)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="bos-hint" style={{ marginTop: 0 }}>{t('No leave or one-off hours coming up.')}</p>
          )}
          <ActionForm action={addDatedHours} success={t('Saved.')} className="bos-inline-form" aria-label={t('Add time off or one-off hours')}>
            {hidden}
            <input name="exception_date" type="date" min={today} aria-label={t('Date')} required />
            <select name="kind" aria-label={t('Away or working')} defaultValue="away">
              <option value="away">{t('Away')}</option>
              <option value="extra">{t('Working (instead of the usual hours)')}</option>
            </select>
            <label className="bos-check"><input name="all_day" type="checkbox" defaultChecked /> {t('All day')}</label>
            <input name="start_time" type="time" defaultValue="09:00" aria-label={t('Start time')} />
            <input name="end_time" type="time" defaultValue="17:00" aria-label={t('End time')} />
            <SubmitButton className="btn-ghost" busy={t('Saving…')}>{t('Save')}</SubmitButton>
          </ActionForm>
          <p className="bos-hint">{t('Away all day ignores the times. Working replaces their usual hours for that date.')}</p>
        </Card>
      </Section>

      <Section title={active ? t('Stop taking bookings') : t('Taking bookings again')}>
        <Card>
          <p className="bos-hint" style={{ marginTop: 0 }}>
            {active
              ? t('If {name} has left or is on long leave, customers stop seeing them. Their past bookings stay.', { name })
              : t('{name} is not offered to customers. Bring them back to take bookings again.', { name })}
          </p>
          {active ? (
            <ActionButton className="btn-ghost" label={t('Stop taking bookings')} busyLabel={t('Saving…')}
              confirm={t('Stop offering {name} to customers? Bookings already made stay.', { name })} confirmLabel={t('Yes, stop')}
              run={setMemberActive.bind(null, b, id, false)} />
          ) : (
            <ActionButton label={t('Take bookings again')} busyLabel={t('Saving…')} run={setMemberActive.bind(null, b, id, true)} />
          )}
        </Card>
      </Section>
    </div>
  )
}

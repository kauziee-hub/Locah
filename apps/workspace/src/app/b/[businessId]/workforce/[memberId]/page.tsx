import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { clockLabel, dayLabel, todayInIndia } from '@/lib/when'
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
const span = (a: Slot) => `${clockLabel(a.start_time)}–${clockLabel(a.end_time)}`
const allDay = (a: Slot) => a.start_time.startsWith('00:00') && a.end_time.startsWith('23:59')

/** One person: where they work, what customers can book them for, their hours and time off. */
export default async function WorkforceMemberPage({ params }: { params: { businessId: string; memberId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const id = params.memberId
  const back = <Link href={`/b/${b}/workforce`}>← Staff & rota</Link>
  const [memberRes, offeringsRes, locationsRes] = await Promise.all([
    apiTry<{ data: Member }>(`/v1/platform/businesses/${b}/workforce/members/${id}`, token),
    apiTry<{ data: Named[] }>(`/v1/platform/businesses/${b}/products`, token),
    apiTry<{ data: Named[] }>(`/v1/platform/businesses/${b}/locations`, token),
  ])
  if (!memberRes.ok) {
    return (
      <div>
        <PageHeader title="Team member" breadcrumb={back} />
        <GateNotice error={memberRes.error} businessId={b} moduleLabel="Staff & rota" />
      </div>
    )
  }
  const m = memberRes.data.data
  const offerings = offeringsRes.ok ? offeringsRes.data.data || [] : []
  const locations = locationsRes.ok ? locationsRes.data.data || [] : []
  const placeName = (lid: string | null) => (lid ? locations.find((l) => l.id === lid)?.name || 'Another place' : 'Any place')
  const serviceName = (oid: string) => offerings.find((o) => o.id === oid)?.title || 'A service no longer listed'
  const doing = new Set(m.services.map((s) => s.offering_id))
  const canAdd = offerings.filter((o) => BOOKABLE.has(String(o.offering_type)) && o.status !== 'archived' && !doing.has(o.id))
  const notYetAt = locations.filter((l) => !m.locations.some((x) => x.location_id === l.id))
  const weekly = m.availability.filter((a) => a.weekday !== null)
    .sort((x, y) => (x.weekday! - y.weekday!) || x.start_time.localeCompare(y.start_time))
  const today = todayInIndia()
  const dated = m.availability.filter((a) => a.exception_date && a.exception_date >= today)
    .sort((x, y) => x.exception_date!.localeCompare(y.exception_date!) || x.start_time.localeCompare(y.start_time))
  const active = m.status === 'active'
  const hidden = (
    <>
      <input type="hidden" name="businessId" value={b} />
      <input type="hidden" name="memberId" value={id} />
    </>
  )
  const removeSlot = (slotId: string, what: string) => (
    <ActionButton className="btn-quiet" label="Remove" busyLabel="Removing…" confirm={`Remove ${what}?`} confirmLabel="Yes, remove"
      run={removeHours.bind(null, b, id, slotId)} />
  )

  return (
    <div className="bos-page">
      <PageHeader
        title={m.display_name}
        subtitle={m.designation || undefined}
        breadcrumb={back}
        actions={<StatusPill value={m.status} tone={active ? 'good' : 'neutral'} label={active ? 'Taking bookings' : 'Not taking bookings'} />}
      />
      {m.phone ? <p className="bos-hint" style={{ marginTop: 0 }}><a href={`tel:${m.phone.replace(/[^+\d]/g, '')}`}>{m.phone}</a></p> : null}

      <Section title="Works at">
        <Card>
          <ul className="bos-resources">
            {m.locations.map((l) => (
              <li key={l.location_id}>
                <strong>{placeName(l.location_id)}</strong>
                {l.is_primary ? <span className="bos-hint">main place</span> : null}
                {m.locations.length > 1 ? (
                  <ActionButton className="btn-quiet" label="Remove" busyLabel="Removing…"
                    confirm={`${m.display_name} no longer works at ${placeName(l.location_id)}?`} confirmLabel="Yes, remove"
                    run={removePlace.bind(null, b, id, l.location_id)} />
                ) : null}
              </li>
            ))}
          </ul>
          {notYetAt.length ? (
            <ActionForm action={addPlace} success="Added." className="bos-inline-form" aria-label="Add a place they work">
              {hidden}
              <select name="location_id" aria-label="Place">
                {notYetAt.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <label className="bos-check"><input type="checkbox" name="is_primary" /> Main place</label>
              <SubmitButton className="btn-ghost" busy="Adding…">Add place</SubmitButton>
            </ActionForm>
          ) : null}
        </Card>
      </Section>

      <Section title="Customers can book them for">
        <Card>
          {m.services.length ? (
            <ul className="bos-resources">
              {m.services.map((s) => (
                <li key={s.offering_id}>
                  <strong>{serviceName(s.offering_id)}</strong>
                  <ActionButton className="btn-quiet" label="Remove" busyLabel="Removing…"
                    confirm={`Stop offering ${m.display_name} for ${serviceName(s.offering_id)}? Bookings already made stay.`}
                    confirmLabel="Yes, remove" run={removeService.bind(null, b, id, s.offering_id)} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="bos-hint" style={{ marginTop: 0 }}>Nothing yet. Customers can pick {m.display_name} only for services listed here.</p>
          )}
          {canAdd.length ? (
            <ActionForm action={addService} success="Added." className="bos-inline-form" aria-label="Add a service they do">
              {hidden}
              <select name="offering_id" aria-label="Service">
                {canAdd.map((o) => <option key={o.id} value={o.id}>{o.title}</option>)}
              </select>
              <SubmitButton className="btn-ghost" busy="Adding…">Add service</SubmitButton>
            </ActionForm>
          ) : m.services.length ? null : (
            <p className="bos-hint">
              There are no bookable services yet. <Link href={`/b/${b}/offerings/new`}>Add a service</Link> first.
            </p>
          )}
        </Card>
      </Section>

      <Section title="Weekly hours">
        <Card>
          {weekly.length ? (
            <ul className="bos-resources">
              {weekly.map((a) => (
                <li key={a.id}>
                  <strong>{DAYS[a.weekday!]}</strong>
                  <span>{a.is_available ? span(a) : `Break ${span(a)}`}</span>
                  {locations.length > 1 ? <span className="bos-hint">{placeName(a.location_id)}</span> : null}
                  {removeSlot(a.id, `${DAYS[a.weekday!]} ${span(a)}`)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="bos-hint" style={{ marginTop: 0 }}>
              No hours saved, so bookings follow your opening hours. Once any are saved, {m.display_name} is booked only inside them.
            </p>
          )}
          <ActionForm action={addWeeklyHours} success="Saved." className="bos-inline-form" aria-label="Add weekly hours">
            {hidden}
            <select name="weekday" aria-label="Day" defaultValue="0">
              {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
            <input name="start_time" type="time" defaultValue="09:00" aria-label="From" required />
            <input name="end_time" type="time" defaultValue="17:00" aria-label="Until" required />
            <select name="kind" aria-label="Working or a break" defaultValue="work">
              <option value="work">Working</option>
              <option value="break">Break (not bookable)</option>
            </select>
            <SubmitButton className="btn-ghost" busy="Saving…">Add hours</SubmitButton>
          </ActionForm>
        </Card>
      </Section>

      <Section title="Time off and one-off hours">
        <Card>
          {dated.length ? (
            <ul className="bos-resources">
              {dated.map((a) => (
                <li key={a.id}>
                  <strong>{dayLabel(a.exception_date)}</strong>
                  <span>{a.is_available ? `Working ${span(a)}` : allDay(a) ? 'Away all day' : `Away ${span(a)}`}</span>
                  {removeSlot(a.id, `this on ${dayLabel(a.exception_date)}`)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="bos-hint" style={{ marginTop: 0 }}>No leave or one-off hours coming up.</p>
          )}
          <ActionForm action={addDatedHours} success="Saved." className="bos-inline-form" aria-label="Add time off or one-off hours">
            {hidden}
            <input name="exception_date" type="date" min={today} aria-label="Date" required />
            <select name="kind" aria-label="Away or working" defaultValue="away">
              <option value="away">Away</option>
              <option value="extra">Working (instead of the usual hours)</option>
            </select>
            <label className="bos-check"><input name="all_day" type="checkbox" defaultChecked /> All day</label>
            <input name="start_time" type="time" defaultValue="09:00" aria-label="From" />
            <input name="end_time" type="time" defaultValue="17:00" aria-label="Until" />
            <SubmitButton className="btn-ghost" busy="Saving…">Save</SubmitButton>
          </ActionForm>
          <p className="bos-hint">Away all day ignores the times. Working replaces their usual hours for that date.</p>
        </Card>
      </Section>

      <Section title={active ? 'Stop taking bookings' : 'Taking bookings again'}>
        <Card>
          <p className="bos-hint" style={{ marginTop: 0 }}>
            {active
              ? `If ${m.display_name} has left or is on long leave, customers stop seeing them. Their past bookings stay.`
              : `${m.display_name} is not offered to customers. Bring them back to take bookings again.`}
          </p>
          {active ? (
            <ActionButton className="btn-ghost" label="Stop taking bookings" busyLabel="Saving…"
              confirm={`Stop offering ${m.display_name} to customers? Bookings already made stay.`} confirmLabel="Yes, stop"
              run={setMemberActive.bind(null, b, id, false)} />
          ) : (
            <ActionButton label="Take bookings again" busyLabel="Saving…" run={setMemberActive.bind(null, b, id, true)} />
          )}
        </Card>
      </Section>
    </div>
  )
}

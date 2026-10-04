import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { locationStep, updateLocation } from '../actions'
import { addressLine, zoneWords } from '../words'
import { OpeningHours } from './OpeningHours'

export const dynamic = 'force-dynamic'

type LocationDetail = {
  id: string; name: string; timezone: string; address: Record<string, unknown> | null
  hours: Record<string, unknown> | null; is_primary: boolean; status: string
  phone: string | null; email: string | null; notes: string | null
}

const field = (address: Record<string, unknown> | null, ...keys: string[]) => {
  for (const k of keys) {
    const v = address?.[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  return ''
}

/** Doc 09 CORE-009 — one place: its address and contact, opening hours, and whether it is the main one. */
export default async function LocationDetailPage({ params }: { params: { businessId: string; locationId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const back = <Link href={`/b/${b}/locations`}>← Locations</Link>
  const [res, me] = await Promise.all([
    apiTry<{ data: LocationDetail }>(`/v1/platform/businesses/${b}/locations/${params.locationId}`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(b)),
  ])
  const perms = new Set(me.ok ? me.data.data.permissions ?? [] : [])
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Location" breadcrumb={back} />
        <GateNotice error={res.error} businessId={b} moduleLabel="Locations" />
      </div>
    )
  }
  const l = res.data.data
  const canEdit = perms.has('locations.update')
  const open = l.status === 'active'
  const where = addressLine(l.address)

  return (
    <div className="bos-page">
      <PageHeader
        title={l.name}
        breadcrumb={back}
        subtitle={[where || 'No address yet', l.is_primary ? 'main place' : '', l.timezone !== 'Asia/Kolkata' ? zoneWords(l.timezone) : '']
          .filter(Boolean).join(' · ')}
        actions={<StatusPill value={l.status} tone={open ? 'good' : 'neutral'} label={open ? 'Open' : 'Archived'} />}
      />

      {canEdit ? (
        <div className="bos-inline-form">
          {!l.is_primary && open ? (
            <ActionButton className="btn-ghost" label="Make this the main place" busyLabel="Saving…"
              run={locationStep.bind(null, b, l.id, 'set-primary')} />
          ) : null}
          {open && !l.is_primary ? (
            <ActionButton className="btn-quiet" label="Archive" busyLabel="Archiving…" confirmLabel="Yes, archive"
              confirm={`Archive ${l.name}? Customers stop seeing it and it takes no new orders or bookings. Its records stay.`}
              run={locationStep.bind(null, b, l.id, 'archive')} />
          ) : null}
          {!open ? (
            <ActionButton label="Open it again" busyLabel="Saving…" run={locationStep.bind(null, b, l.id, 'reactivate')} />
          ) : null}
        </div>
      ) : null}
      {l.is_primary ? (
        <p className="bos-hint">The main place can&apos;t be archived. Make another place the main one first.</p>
      ) : null}

      <Section title="Address and contact">
        <ActionForm action={updateLocation} success="Saved." className="bos-resource-form" aria-label="Address and contact">
          <input type="hidden" name="businessId" value={b} />
          <input type="hidden" name="locationId" value={l.id} />
          <label>Name<input name="name" defaultValue={l.name} required maxLength={120} disabled={!canEdit} /></label>
          <label>Street and building<input name="line1" defaultValue={field(l.address, 'line1', 'line_1', 'street')} maxLength={160} disabled={!canEdit} /></label>
          <label>Area<input name="locality" defaultValue={field(l.address, 'locality', 'area')} maxLength={80} placeholder="Anna Nagar" disabled={!canEdit} /></label>
          <label>Landmark<input name="landmark" defaultValue={field(l.address, 'landmark')} maxLength={120} placeholder="Near the park" disabled={!canEdit} /></label>
          <label>City<input name="city" defaultValue={field(l.address, 'city')} maxLength={80} disabled={!canEdit} /></label>
          <label>State<input name="state" defaultValue={field(l.address, 'state')} maxLength={80} disabled={!canEdit} /></label>
          <label>PIN code<input name="postal_code" defaultValue={field(l.address, 'postal_code', 'pincode', 'pin')} inputMode="numeric" maxLength={6} disabled={!canEdit} /></label>
          <label>Phone<input name="phone" type="tel" defaultValue={l.phone ?? ''} maxLength={20} disabled={!canEdit} /></label>
          <label>Email<input name="email" type="email" defaultValue={l.email ?? ''} disabled={!canEdit} /></label>
          <label style={{ gridColumn: '1 / -1' }}>Notes for your team<textarea name="notes" defaultValue={l.notes ?? ''} rows={2} disabled={!canEdit} /></label>
          {canEdit ? <SubmitButton className="btn">Save</SubmitButton> : null}
        </ActionForm>
        <p className="bos-hint">Customers see the address on your website and in Marketplace; the AI receptionist gives it when asked where you are.</p>
      </Section>

      <OpeningHours businessId={b} locationId={l.id} hours={l.hours} canEdit={canEdit} />
    </div>
  )
}

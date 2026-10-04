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
import { pageWords } from '@/lib/ws-lang'

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
  const t = pageWords()
  const b = params.businessId
  const back = <Link href={`/b/${b}/locations`}>← {t('Locations')}</Link>
  const [res, me] = await Promise.all([
    apiTry<{ data: LocationDetail }>(`/v1/platform/businesses/${b}/locations/${params.locationId}`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(b)),
  ])
  const perms = new Set(me.ok ? me.data.data.permissions ?? [] : [])
  if (!res.ok) {
    return (
      <div>
        <PageHeader title={t('Location')} breadcrumb={back} />
        <GateNotice error={res.error} businessId={b} moduleLabel={t('Locations')} />
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
        subtitle={[where || t('No address yet'), l.is_primary ? t('main place') : '', l.timezone !== 'Asia/Kolkata' ? t(zoneWords(l.timezone)) : '']
          .filter(Boolean).join(' · ')}
        actions={<StatusPill value={l.status} tone={open ? 'good' : 'neutral'} label={open ? t('Open') : t('Archived')} />}
      />

      {canEdit ? (
        <div className="bos-inline-form">
          {!l.is_primary && open ? (
            <ActionButton className="btn-ghost" label={t('Make this the main place')} busyLabel={t('Saving…')}
              run={locationStep.bind(null, b, l.id, 'set-primary')} />
          ) : null}
          {open && !l.is_primary ? (
            <ActionButton className="btn-quiet" label={t('Archive')} busyLabel={t('Archiving…')} confirmLabel={t('Yes, archive')}
              confirm={t('Archive {name}? Customers stop seeing it and it takes no new orders or bookings. Its records stay.', { name: l.name })}
              run={locationStep.bind(null, b, l.id, 'archive')} />
          ) : null}
          {!open ? (
            <ActionButton label={t('Open it again')} busyLabel={t('Saving…')} run={locationStep.bind(null, b, l.id, 'reactivate')} />
          ) : null}
        </div>
      ) : null}
      {l.is_primary ? (
        <p className="bos-hint">{t("The main place can't be archived. Make another place the main one first.")}</p>
      ) : null}

      <Section title={t('Address and contact')}>
        <ActionForm action={updateLocation} success={t('Saved.')} className="bos-resource-form" aria-label={t('Address and contact')}>
          <input type="hidden" name="businessId" value={b} />
          <input type="hidden" name="locationId" value={l.id} />
          <label>{t('Name')}<input name="name" defaultValue={l.name} required maxLength={120} disabled={!canEdit} /></label>
          <label>{t('Street and building')}<input name="line1" defaultValue={field(l.address, 'line1', 'line_1', 'street')} maxLength={160} disabled={!canEdit} /></label>
          <label>{t('Area')}<input name="locality" defaultValue={field(l.address, 'locality', 'area')} maxLength={80} placeholder="Anna Nagar" disabled={!canEdit} /></label>
          <label>{t('Landmark')}<input name="landmark" defaultValue={field(l.address, 'landmark')} maxLength={120} placeholder={t('Near the park')} disabled={!canEdit} /></label>
          <label>{t('City')}<input name="city" defaultValue={field(l.address, 'city')} maxLength={80} disabled={!canEdit} /></label>
          <label>{t('State or UT')}<input name="state" defaultValue={field(l.address, 'state')} maxLength={80} disabled={!canEdit} /></label>
          <label>{t('PIN code')}<input name="postal_code" defaultValue={field(l.address, 'postal_code', 'pincode', 'pin')} inputMode="numeric" maxLength={6} disabled={!canEdit} /></label>
          <label>{t('Phone')}<input name="phone" type="tel" defaultValue={l.phone ?? ''} maxLength={20} disabled={!canEdit} /></label>
          <label>{t('Email')}<input name="email" type="email" defaultValue={l.email ?? ''} disabled={!canEdit} /></label>
          <label style={{ gridColumn: '1 / -1' }}>{t('Notes for your team')}<textarea name="notes" defaultValue={l.notes ?? ''} rows={2} disabled={!canEdit} /></label>
          {canEdit ? <SubmitButton className="btn" busy={t('Saving…')}>{t('Save')}</SubmitButton> : null}
        </ActionForm>
        <p className="bos-hint">{t('Customers see the address on your website and in Marketplace; the AI receptionist gives it when asked where you are.')}</p>
      </Section>

      <OpeningHours businessId={b} locationId={l.id} hours={l.hours} canEdit={canEdit} />
    </div>
  )
}

import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, EmptyState, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { pageWords } from '@/lib/ws-lang'
import { createLocation } from './actions'
import { addressLine, zoneWords } from './words'

export const dynamic = 'force-dynamic'

type LocationRow = {
  id: string; name: string; timezone: string; is_primary: boolean; status: string
  phone: string | null; email: string | null; address: Record<string, unknown> | null
  hours: Record<string, unknown> | null
}

/** Doc 09 CORE-008 Locations — where the Business serves customers. */
export default async function LocationsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const t = pageWords()
  const b = params.businessId
  const res = await apiTry<{ data: LocationRow[] }>(`/v1/platform/businesses/${b}/locations`, token)
  if (!res.ok) {
    return (
      <div>
        <PageHeader title={t('Locations')} />
        <GateNotice error={res.error} businessId={b} moduleLabel={t('Locations')} />
      </div>
    )
  }
  const locations = [...(res.data.data || [])].sort((x, y) =>
    Number(y.is_primary) - Number(x.is_primary) || (x.status === 'active' ? 0 : 1) - (y.status === 'active' ? 0 : 1))

  return (
    <div>
      <PageHeader
        title={t('Locations')}
        subtitle={t('Where you serve customers: the address, contact and opening hours your website, bookings and AI use. One is the main place.')}
      />
      <DataTable
        rows={locations}
        rowKey={(l) => l.id}
        columns={[
          {
            key: 'name',
            header: t('Place'),
            render: (l) => (
              <div>
                <Link href={`/b/${b}/locations/${l.id}`}>{l.name}</Link>
                {l.is_primary ? <span className="bos-hint"> · {t('main place')}</span> : null}
                <div className="bos-hint" style={{ margin: 0 }}>{addressLine(l.address) || t('No address yet')}</div>
              </div>
            ),
          },
          {
            key: 'contact',
            header: t('Contact'),
            render: (l) => (l.phone ? <a href={`tel:${l.phone.replace(/[^+\d]/g, '')}`}>{l.phone}</a> : l.email || <span className="bos-hint">—</span>),
          },
          {
            key: 'hours',
            header: t('Hours'),
            render: (l) => <span className="bos-hint" style={{ margin: 0 }}>{l.hours && Object.keys(l.hours).some((k) => k !== 'note') ? t('Set') : t('Not set')}{l.timezone !== 'Asia/Kolkata' ? ` · ${t(zoneWords(l.timezone))}` : ''}</span>,
          },
          {
            key: 'status',
            header: t('Status'),
            render: (l) => <StatusPill value={l.status} tone={l.status === 'active' ? 'good' : 'neutral'} label={l.status === 'active' ? t('Open') : t('Archived')} />,
          },
        ]}
        empty={<EmptyState title={t('No locations yet')}>{t('Add the first one below.')}</EmptyState>}
      />

      <Section title={t('Add a location')}>
        <ActionForm action={createLocation} success={t('Added. Open it to set its opening hours.')} resetOnSuccess
          className="bos-resource-form" aria-label={t('Add a location')}>
          <input type="hidden" name="businessId" value={b} />
          <label>{t('Name')}<input name="name" required maxLength={120} placeholder={t('Anna Nagar branch')} /></label>
          <label>{t('Street and building')}<input name="line1" maxLength={160} placeholder="12, 2nd Avenue" /></label>
          <label>{t('Area')}<input name="locality" maxLength={80} placeholder="Anna Nagar" /></label>
          <label>{t('City')}<input name="city" maxLength={80} placeholder="Chennai" /></label>
          <label>{t('PIN code')}<input name="postal_code" inputMode="numeric" maxLength={6} placeholder="600040" /></label>
          <label>{t('Phone')}<input name="phone" type="tel" maxLength={20} placeholder="+91…" /></label>
          <label>{t('Time zone')}
            <select name="timezone" defaultValue="Asia/Kolkata">
              {['Asia/Kolkata', 'Asia/Dubai', 'Asia/Singapore', 'Europe/London', 'America/New_York', 'Australia/Sydney'].map((tz) => (
                <option key={tz} value={tz}>{t(zoneWords(tz))}</option>
              ))}
            </select>
          </label>
          <SubmitButton className="btn" busy={t('Adding…')}>{t('Add location')}</SubmitButton>
        </ActionForm>
      </Section>
    </div>
  )
}

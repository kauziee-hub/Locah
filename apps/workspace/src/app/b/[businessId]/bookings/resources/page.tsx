import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, EmptyState, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { addResource, setResourceActive } from '../actions'
import { RESOURCE_KINDS } from '../words'

export const dynamic = 'force-dynamic'

type Resource = {
  id: string; location_id: string; resource_type: string; name: string; allocation_mode: 'exclusive' | 'pooled'
  capacity: number; max_party_size: number | null; buffer_after_minutes: number; granularity: string; is_active: boolean
  version: number
}

/** What customers book time on. A guest who does not choose is given a free one that fits. */
export default async function ResourcesPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const base = `/v1/platform/businesses/${b}`
  const [resRes, locRes] = await Promise.all([
    apiTry<{ data: { resources: Resource[] } }>(`${base}/bookings/resources?include_inactive=true`, token),
    apiTry<{ data: { id: string; name: string }[] }>(`${base}/locations`, token),
  ])
  const header = <PageHeader title="Tables, rooms & equipment" breadcrumb={<Link href={`/b/${b}/bookings`}>← Bookings</Link>}
    subtitle="What customers book time on. A guest who does not choose is given a free one that fits." />
  if (!resRes.ok) return <div className="bos-page">{header}<GateNotice error={resRes.error} businessId={b} moduleLabel="Bookings" /></div>
  const resources = resRes.data.data.resources ?? []
  const locations = locRes.ok ? locRes.data.data : []
  const placeName = (id: string) => locations.find((l) => l.id === id)?.name ?? ''
  const groups = Object.entries(RESOURCE_KINDS).map(([key, k]) => [key, k, resources.filter((r) => r.resource_type === key)] as const)
  const other = resources.filter((r) => !(r.resource_type in RESOURCE_KINDS))

  return (
    <div className="bos-page">
      {header}
      {!resources.length ? (
        <EmptyState title="Nothing set up yet">Add your tables, rooms or chairs so bookings can hold them.</EmptyState>
      ) : null}
      {groups.filter(([, , rows]) => rows.length).map(([key, k, rows]) => (
        <Section key={key} title={k.plural}>
          <Card>
            <ul className="bos-resources">
              {rows.map((r) => (
                <li key={r.id}>
                  <strong>{r.name}</strong>
                  <span className="bos-hint">
                    {r.allocation_mode === 'pooled' ? `${r.capacity} places` : r.max_party_size ? `${k.seats}: ${r.max_party_size}` : ''}
                    {r.buffer_after_minutes ? ` · ${r.buffer_after_minutes} min to reset` : ''}
                    {locations.length > 1 ? ` · ${placeName(r.location_id)}` : ''}
                  </span>
                  <StatusPill value={r.is_active ? 'active' : 'paused'} tone={r.is_active ? 'good' : 'neutral'}
                    label={r.is_active ? 'Taking bookings' : 'Paused'} />
                  <ActionButton className="btn-quiet" label={r.is_active ? 'Pause' : 'Resume'} busyLabel="Saving…"
                    confirm={r.is_active ? `Pause ${r.name}? New bookings won't be given it; existing ones stay.` : undefined}
                    confirmLabel="Yes, pause"
                    run={setResourceActive.bind(null, b, r.id, !r.is_active)} />
                </li>
              ))}
            </ul>
            <p className="bos-hint" style={{ margin: '0.4rem 0 0' }}>{k.help}</p>
          </Card>
        </Section>
      ))}
      {other.length ? (
        <Section title="Other">
          <Card><ul style={{ margin: 0 }}>{other.map((r) => <li key={r.id}>{r.name}</li>)}</ul></Card>
        </Section>
      ) : null}

      <Section title="Add">
        <Card>
          <ActionForm action={addResource} success="Added." resetOnSuccess className="bos-resource-form" aria-label="Add a table, room or equipment">
            <input type="hidden" name="businessId" value={b} />
            <label>Kind
              <select name="kind" defaultValue="table">
                {Object.entries(RESOURCE_KINDS).map(([key, k]) => <option key={key} value={key}>{k.label}</option>)}
              </select>
            </label>
            <label>Name<input name="name" required placeholder="Table 4, Room 101…" maxLength={80} /></label>
            <label>Seats / guests / places<input name="size" type="number" min={1} max={500} defaultValue={4} required /></label>
            <label>Minutes to reset after<input name="buffer" type="number" min={0} max={240} defaultValue={0} /></label>
            {locations.length > 1 ? (
              <label>Place
                <select name="location_id">{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
              </label>
            ) : <input type="hidden" name="location_id" value={locations[0]?.id ?? ''} />}
            <SubmitButton className="btn" busy="Adding…">Add</SubmitButton>
          </ActionForm>
        </Card>
      </Section>
    </div>
  )
}

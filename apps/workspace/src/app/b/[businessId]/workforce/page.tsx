import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, EmptyState, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { createWorkforceMember } from './actions'

export const dynamic = 'force-dynamic'

type Member = { id: string; display_name: string; designation: string | null; phone: string | null; status: string }
type Place = { id: string; name: string; is_primary: boolean }

/** Doc 11 §4.2 Workforce — the people customers can book (no HR or payroll depth). */
export default async function WorkforcePage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const [membersRes, locationsRes] = await Promise.all([
    apiTry<{ data: Member[] }>(`/v1/platform/businesses/${b}/workforce/members`, token),
    apiTry<{ data: Place[] }>(`/v1/platform/businesses/${b}/locations`, token),
  ])
  if (!membersRes.ok) {
    return (
      <div>
        <PageHeader title="Staff & rota" />
        <GateNotice error={membersRes.error} businessId={b} moduleLabel="Staff & rota" />
      </div>
    )
  }
  // Working first, then anyone who has left; by name.
  const members = [...(membersRes.data.data || [])].sort((x, y) =>
    (x.status === 'active' ? 0 : 1) - (y.status === 'active' ? 0 : 1) || x.display_name.localeCompare(y.display_name))
  const locations = locationsRes.ok ? locationsRes.data.data || [] : []
  const primary = locations.find((l) => l.is_primary) || locations[0]

  return (
    <div>
      <PageHeader
        title="Staff & rota"
        subtitle="The people customers can book: where they work, what they do and their hours. Adding someone here does not let them into this Workspace — invite them from Team for that."
      />

      <DataTable
        rows={members}
        rowKey={(m) => m.id}
        columns={[
          {
            key: 'name',
            header: 'Name',
            render: (m) => (
              <div>
                <Link href={`/b/${b}/workforce/${m.id}`}>{m.display_name}</Link>
                {m.designation ? <div className="bos-hint" style={{ margin: 0 }}>{m.designation}</div> : null}
              </div>
            ),
          },
          {
            key: 'phone',
            header: 'Phone',
            render: (m) => (m.phone ? <a href={`tel:${m.phone.replace(/[^+\d]/g, '')}`}>{m.phone}</a> : <span className="bos-hint">—</span>),
          },
          {
            key: 'status',
            header: 'Status',
            render: (m) => (
              <StatusPill value={m.status} tone={m.status === 'active' ? 'good' : 'neutral'}
                label={m.status === 'active' ? 'Taking bookings' : 'Not taking bookings'} />
            ),
          },
        ]}
        empty={<EmptyState title="Nobody added yet">Add the people customers book — a stylist, a trainer, a doctor — below.</EmptyState>}
      />

      <Section title="Add someone" id="add">
        <ActionForm action={createWorkforceMember} success="Added. Open their page to set what they do and their hours."
          resetOnSuccess className="bos-resource-form" aria-label="Add a staff member">
          <input type="hidden" name="businessId" value={b} />
          <label>Name<input name="display_name" required maxLength={120} placeholder="Priya" /></label>
          <label>Role (optional)<input name="designation" maxLength={80} placeholder="Senior stylist" /></label>
          <label>Phone (optional)<input name="phone" type="tel" maxLength={20} placeholder="+91…" /></label>
          {locations.length > 1 ? (
            <label>Works at
              <select name="location_id" defaultValue={primary?.id ?? ''}>
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
          ) : <input type="hidden" name="location_id" value={primary?.id ?? ''} />}
          <SubmitButton className="btn" busy="Adding…">Add</SubmitButton>
        </ActionForm>
      </Section>
    </div>
  )
}

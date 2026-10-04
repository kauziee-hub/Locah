import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, GateNotice, PageHeader } from '@/components/ui'
import { createProject } from '../actions'
import { PRIORITY_LABEL, type ProjectSemantics } from '../shared'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Customer = { id: string; display_name: string }
type Member = { id: string; display_name: string; status?: string | null }

/**
 * Starting a piece of work.
 *
 * The stages are pre-filled from the business's own type — a clinic opens at
 * Assessment, a studio at Brief — and are editable before anything is created,
 * because the profile is a starting point and not a workflow anyone is held to.
 */
export default async function NewProjectPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) {
    redirect(`/login?destination=${encodeURIComponent(`/b/${params.businessId}/projects/new`)}`)
  }

  const base = `/b/${params.businessId}/projects`
  const gate = await apiTry<{ data: { semantics: ProjectSemantics } }>(
    `/v1/platform/businesses/${params.businessId}/projects?limit=1`,
    token
  )
  if (!gate.ok) {
    return (
      <div>
        <PageHeader title="New project" />
        <GateNotice
          error={gate.error}
          businessId={params.businessId}
          moduleLabel="Projects & Work Orders"
        />
      </div>
    )
  }

  const semantics = gate.data.data.semantics
  const [customersRes, membersRes] = await Promise.all([
    apiTry<{ data: Customer[] }>(
      `/v1/platform/businesses/${params.businessId}/customers`,
      token
    ),
    apiTry<{ data: Member[] }>(
      `/v1/platform/businesses/${params.businessId}/workforce/members`,
      token
    ),
  ])
  const customers = customersRes.ok ? customersRes.data.data || [] : []
  const members = (membersRes.ok ? membersRes.data.data || [] : []).filter(
    (m) => m.status !== 'inactive'
  )

  const noun = semantics.noun.toLowerCase()

  return (
    <div>
      <PageHeader
        title={`New ${noun}`}
        subtitle={`It starts as a draft. Nothing is committed until you start the work.`}
        breadcrumb={<Link href={base}>← {semantics.noun_plural}</Link>}
      />

      <SafeForm action={createProject} style={{ display: 'grid', gap: '1.25rem', maxWidth: '52rem' }}>
        <input type="hidden" name="businessId" value={params.businessId} />

        <Card style={{ display: 'grid', gap: '0.9rem' }}>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>What and who</h2>
          <label style={FIELD}>
            <span style={LABEL}>What is this {noun} for</span>
            <input
              name="title"
              required
              maxLength={200}
              placeholder="e.g. Ground floor refit — 14 Alipore Road"
            />
          </label>
          <label style={FIELD}>
            <span style={LABEL}>Scope</span>
            <textarea
              name="summary"
              rows={3}
              maxLength={4000}
              placeholder="What is included, and anything that defines done."
            />
          </label>
          <div style={{ display: 'grid', gap: '0.9rem', gridTemplateColumns: 'repeat(auto-fit, minmax(13rem, 1fr))' }}>
            <label style={FIELD}>
              <span style={LABEL}>Customer</span>
              <select name="customer_contact_id" defaultValue="">
                <option value="">Not set</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label style={FIELD}>
              <span style={LABEL}>Who owns it</span>
              <select name="lead_member_id" defaultValue="">
                <option value="">Not set</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
              {members.length === 0 ? (
                <span style={HINT}>No team members yet — you can set this later.</span>
              ) : null}
            </label>
            <label style={FIELD}>
              <span style={LABEL}>Priority</span>
              <select name="priority" defaultValue="normal">
                {Object.entries(PRIORITY_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </Card>

        <Card style={{ display: 'grid', gap: '0.9rem' }}>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>When</h2>
          <div style={{ display: 'grid', gap: '0.9rem', gridTemplateColumns: 'repeat(auto-fit, minmax(13rem, 1fr))' }}>
            <label style={FIELD}>
              <span style={LABEL}>Starts</span>
              <input type="date" name="starts_on" />
            </label>
            <label style={FIELD}>
              <span style={LABEL}>Due</span>
              <input type="date" name="due_on" />
            </label>
          </div>
        </Card>

        <Card style={{ display: 'grid', gap: '0.9rem' }}>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Stages</h2>
          <label style={FIELD}>
            <span style={LABEL}>One per line</span>
            <textarea
              name="phases"
              rows={Math.max(3, semantics.default_phases.length)}
              defaultValue={semantics.default_phases.join('\n')}
              placeholder="Leave empty for a single-visit job with no stages."
            />
            <span style={HINT}>
              {semantics.default_phases.length > 0
                ? `Pre-filled from how ${semantics.noun_plural.toLowerCase()} usually run for this kind of business. Change them freely.`
                : `No suggested stages for this kind of business — add your own, or leave it empty.`}
            </span>
          </label>
        </Card>

        <Card style={{ display: 'grid', gap: '0.9rem' }}>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Internal notes</h2>
          <label style={FIELD}>
            <textarea name="internal_notes" rows={2} maxLength={4000} />
            <span style={HINT}>Only your team sees this.</span>
          </label>
        </Card>

        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button type="submit" className="btn">
            Create {noun}
          </button>
          <Link href={base} className="btn btn-ghost">
            Cancel
          </Link>
        </div>
      </SafeForm>
    </div>
  )
}

const FIELD: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: '0.3rem' }
const LABEL: React.CSSProperties = { fontSize: '0.85rem', color: 'var(--color-muted)' }
const HINT: React.CSSProperties = { fontSize: '0.8rem', color: 'var(--color-muted)' }

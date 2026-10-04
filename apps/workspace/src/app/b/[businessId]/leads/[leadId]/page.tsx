import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DetailShell, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { addLeadNote, moveLeadStage, setLeadStage } from '../actions'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { dayTimeLabel } from '@/lib/when'
import { MOVE_WORDS, SOURCE_WORDS, STAGE_WORDS } from '../words'
import { StageTrack, type StageWhere } from '@/components/StageTrack'

export const dynamic = 'force-dynamic'

type LeadDetail = {
  id: string
  display_name: string
  email: string | null
  phone: string | null
  message: string | null
  status: string
  source: string
  lost_reason: string | null
  customer_contact_id: string | null
  status_history: Array<{ from_status: string | null; to_status: string; created_at: string }>
  notes: Array<{ id: string; body: string; created_at: string }>
}

// Doc 11 §10.2: won is terminal; lost can reopen.
const NEXT_STAGE: Record<string, string[]> = {
  new: ['contacted', 'qualified', 'won', 'lost'],
  contacted: ['qualified', 'won', 'lost'],
  qualified: ['won', 'lost'],
  lost: ['new', 'contacted', 'qualified'],
  won: [],
}

export default async function LeadDetailPage({
  params,
}: {
  params: { businessId: string; leadId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const back = `/b/${params.businessId}/leads`

  const res = await apiTry<{ data: LeadDetail }>(
    `/v1/platform/businesses/${params.businessId}/leads/${params.leadId}`,
    token
  )
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Enquiry" breadcrumb={<Link href={back}>Enquiries</Link>} />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Enquiries" />
      </div>
    )
  }

  const lead = res.data.data
  const next = NEXT_STAGE[lead.status] ?? []
  const stage = await apiTry<{ data: StageWhere }>(`/v1/b/${params.businessId}/stages/leads/${params.leadId}`, token)

  return (
    <DetailShell
      breadcrumb={<Link href={back}>Enquiries</Link>}
      title={lead.display_name}
      status={<StatusPill value={lead.status} label={STAGE_WORDS[lead.status] ?? lead.status} />}
      meta={[
        ['Contact', (
          <span key="contact">
            {lead.phone ? <a href={`tel:${lead.phone.replace(/[^+\d]/g, '')}`}>{lead.phone}</a> : null}
            {lead.phone && lead.email ? ' · ' : null}
            {lead.email ? <a href={`mailto:${lead.email}`}>{lead.email}</a> : null}
            {!lead.phone && !lead.email ? '—' : null}
          </span>
        )],
        ['Came from', SOURCE_WORDS[lead.source] ?? lead.source],
        ...(lead.lost_reason ? ([['Lost because', lead.lost_reason]] as [string, string][]) : []),
      ]}
    >
      {lead.message ? (
        <blockquote
          style={{
            margin: '0 0 1.5rem',
            padding: '0.75rem 1rem',
            borderLeft: '3px solid var(--color-border-strong)',
            color: 'var(--color-muted)',
          }}
        >
          “{lead.message}”
        </blockquote>
      ) : null}
      {lead.customer_contact_id ? (
        <p>
          Now a customer —{' '}
          <Link href={`/b/${params.businessId}/customers/${lead.customer_contact_id}`}>
            open their record
          </Link>
          .
        </p>
      ) : null}

      {stage.ok && stage.data.data.has_steps ? (
        <Section title="Steps">
          <StageTrack businessId={params.businessId} entity="leads" recordId={params.leadId} where={stage.data.data} />
        </Section>
      ) : null}

      <Section title="Where it stands">
        {next.length === 0 ? (
          <p style={{ color: 'var(--color-muted)' }}>
            Won — this enquiry became business. It stays here as history.
          </p>
        ) : (
          <div className="bos-lead__moves">
            {next.filter((stage) => stage !== 'lost').map((stage) => (
              <ActionButton key={stage} className="btn-ghost" label={MOVE_WORDS[stage] ?? stage} busyLabel="Saving…"
                run={setLeadStage.bind(null, params.businessId, params.leadId, stage)} />
            ))}
            {next.includes('lost') ? (
              <ActionForm action={moveLeadStage} className="bos-lead__lost" aria-label="Mark as lost">
                <input type="hidden" name="businessId" value={params.businessId} />
                <input type="hidden" name="leadId" value={params.leadId} />
                <input type="hidden" name="status" value="lost" />
                <input name="reason" placeholder="Why was it lost?" required maxLength={500} aria-label="Why it was lost" />
                <SubmitButton className="btn-ghost">Mark as lost</SubmitButton>
              </ActionForm>
            ) : null}
          </div>
        )}
      </Section>

      <Section title="History">
        <ol style={{ margin: 0, paddingLeft: '1.1rem', color: 'var(--color-foreground)' }}>
          {lead.status_history.map((event, idx) => (
            <li key={idx} style={{ marginBottom: '0.3rem' }}>
              {event.from_status ? `${STAGE_WORDS[event.from_status] ?? event.from_status} → ` : 'Came in as '}
              <strong>{STAGE_WORDS[event.to_status] ?? event.to_status}</strong>
              <span style={{ color: 'var(--color-muted)' }}>
                {' '}
                · {dayTimeLabel(event.created_at)}
              </span>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Notes" style={{ maxWidth: '34rem' }}>
        {lead.notes.length === 0 ? (
          <p style={{ color: 'var(--color-muted)' }}>No notes yet.</p>
        ) : (
          <ul style={{ margin: '0 0 0.75rem', paddingLeft: '1.1rem' }}>
            {lead.notes.map((note) => (
              <li key={note.id} style={{ marginBottom: '0.4rem' }}>
                {note.body}
                <span style={{ color: 'var(--color-muted)' }}>
                  {' '}
                  · {dayTimeLabel(note.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <ActionForm action={addLeadNote} className="ws-form" resetOnSuccess aria-label="Add a note">
          <input type="hidden" name="businessId" value={params.businessId} />
          <input type="hidden" name="leadId" value={params.leadId} />
          <textarea name="body" placeholder="Add a note — only your team sees it" required maxLength={5000} aria-label="Note" />
          <div><SubmitButton busy="Adding…">Add note</SubmitButton></div>
        </ActionForm>
      </Section>
    </DetailShell>
  )
}

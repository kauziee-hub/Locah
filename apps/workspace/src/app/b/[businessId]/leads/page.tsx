import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, EmptyState, FilterTabs, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { createLead } from './actions'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { SOURCE_WORDS, STAGE_WORDS } from './words'
import { BusinessEmpty } from '@/components/BusinessEmpty'

export const dynamic = 'force-dynamic'

type LeadRow = {
  id: string
  display_name: string
  email: string | null
  phone: string | null
  status: string
  source: string
}

const STAGES = ['new', 'contacted', 'qualified', 'won', 'lost']

/** Doc 11 §10.2 Leads — pipeline. */
export default async function LeadsPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { status?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')

  const base = `/b/${params.businessId}`
  const qs = searchParams?.status ? `?status=${encodeURIComponent(searchParams.status)}` : ''
  const res = await apiTry<{ data: LeadRow[]; meta: { pipeline: Record<string, number> } }>(
    `/v1/platform/businesses/${params.businessId}/leads${qs}`,
    token
  )
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Enquiries" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Enquiries" />
      </div>
    )
  }

  const leads = res.data.data || []
  const pipeline = res.data.meta?.pipeline || {}

  return (
    <div>
      <PageHeader title="Enquiries" subtitle="Everyone who asked about what you offer — follow each one up until it's won or lost." />
      <FilterTabs
        current={searchParams?.status}
        hrefFor={(v) => `${base}/leads${v ? `?status=${v}` : ''}`}
        options={[
          { value: '', label: 'All' },
          ...STAGES.map((s) => ({
            value: s,
            label: STAGE_WORDS[s] ?? s,
            count: pipeline[s] ?? 0,
          })),
        ]}
      />
      <DataTable
        rows={leads}
        rowKey={(l) => l.id}
        columns={[
          {
            key: 'name',
            header: 'Name',
            render: (l) => <Link href={`${base}/leads/${l.id}`}>{l.display_name}</Link>,
          },
          { key: 'contact', header: 'Contact', render: (l) => l.email || l.phone || '—' },
          { key: 'stage', header: 'Stage', render: (l) => <StatusPill value={l.status} label={STAGE_WORDS[l.status] ?? l.status} /> },
          {
            key: 'source',
            header: 'Source',
            render: (l) => <span style={{ color: 'var(--color-muted)' }}>{SOURCE_WORDS[l.source] ?? l.source}</span>,
          },
        ]}
        empty={
          searchParams?.status ? (
            <EmptyState title="No enquiries here">{`Nothing is at “${STAGE_WORDS[searchParams.status] ?? searchParams.status}” right now.`}</EmptyState>
          ) : (
            <BusinessEmpty businessId={params.businessId} module="leads" fallbackTitle="No enquiries yet"
                           fallback="Website enquiries arrive here automatically. You can also add one below." />
          )
        }
      />

      <Section title="Add an enquiry" id="add">
        <ActionForm action={createLead} className="ws-form" success="Enquiry added." resetOnSuccess>
          <input type="hidden" name="businessId" value={params.businessId} />
          <label className="bos-label" htmlFor="l-name">Name</label>
          <input id="l-name" name="display_name" required maxLength={200} autoComplete="off" />
          <label className="bos-label" htmlFor="l-phone">Phone</label>
          <input id="l-phone" name="phone" type="tel" inputMode="tel" autoComplete="off" />
          <label className="bos-label" htmlFor="l-email">Email (optional)</label>
          <input id="l-email" name="email" type="email" autoComplete="off" />
          <label className="bos-label" htmlFor="l-msg">What are they asking about?</label>
          <textarea id="l-msg" name="message" maxLength={5000} />
          <div><SubmitButton busy="Adding…">Add enquiry</SubmitButton></div>
        </ActionForm>
      </Section>
    </div>
  )
}

import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, EmptyState, FilterTabs, GateNotice, PageHeader, Section, StatusPill } from '@/components/ui'
import { createLead } from './actions'

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
        <PageHeader title="Leads" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Leads" />
      </div>
    )
  }

  const leads = res.data.data || []
  const pipeline = res.data.meta?.pipeline || {}

  return (
    <div>
      <PageHeader title="Leads" subtitle="Enquiries from capture through to won or lost." />
      <FilterTabs
        current={searchParams?.status}
        hrefFor={(v) => `${base}/leads${v ? `?status=${v}` : ''}`}
        options={[
          { value: '', label: 'All' },
          ...STAGES.map((s) => ({
            value: s,
            label: s[0].toUpperCase() + s.slice(1),
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
          { key: 'stage', header: 'Stage', render: (l) => <StatusPill value={l.status} /> },
          {
            key: 'source',
            header: 'Source',
            render: (l) => <span style={{ color: 'var(--color-muted)' }}>{l.source}</span>,
          },
        ]}
        empty={
          <EmptyState title="No leads here">
            {searchParams?.status
              ? `Nothing at the "${searchParams.status}" stage.`
              : 'Website enquiries arrive here automatically. You can also add one below.'}
          </EmptyState>
        }
      />

      <Section title="Add a lead" id="add">
        <form action={createLead} style={{ display: 'grid', gap: '0.6rem', maxWidth: '32rem' }}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input name="display_name" placeholder="Name" required />
          <input name="email" type="email" placeholder="Email" />
          <input name="phone" placeholder="Phone" />
          <textarea name="message" placeholder="What are they asking about?" />
          <button type="submit" style={{ justifySelf: 'start' }}>
            Add lead
          </button>
        </form>
      </Section>
    </div>
  )
}

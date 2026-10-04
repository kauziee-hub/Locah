import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { BusinessEmpty } from '@/components/BusinessEmpty'

export const dynamic = 'force-dynamic'

/** Doc 11 §4.2 fulfilment — board/list. */
export default async function FulfilmentBoardPage({
  params,
  searchParams,
}: {
  params: { businessId: string }
  searchParams?: { status?: string; mode?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const base = `/b/${params.businessId}`
  const qs = new URLSearchParams()
  if (searchParams?.status) qs.set('status', searchParams.status)
  if (searchParams?.mode) qs.set('mode', searchParams.mode)
  const suffix = qs.toString() ? `?${qs}` : ''
  const [jobsRes, settingsRes] = await Promise.all([
    apiTry<{ data: Array<Record<string, unknown>> }>(
      `/v1/b/${params.businessId}/fulfilment/jobs${suffix}`,
      token
    ),
    apiTry<{ data: { active_modes?: string[]; pickup_enabled: boolean; delivery_enabled: boolean } }>(
      `/v1/b/${params.businessId}/fulfilment/settings`,
      token
    ),
  ])
  if (!jobsRes.ok) {
    return (
      <div>
        <PageHeader title="Fulfilment" />
        <GateNotice error={jobsRes.error} businessId={params.businessId} moduleLabel="Fulfilment" />
      </div>
    )
  }
  const jobs = jobsRes.data.data || []
  const settings = settingsRes.ok
    ? settingsRes.data.data
    : { active_modes: [], pickup_enabled: false, delivery_enabled: false }

  return (
    <div>
      <PageHeader
        title="Fulfilment"
        subtitle={`Active modes: ${(settings.active_modes || []).join(', ') || 'none'}.`}
        actions={
          <Link href={`${base}/fulfilment/zones`} className="btn btn-ghost">
            Zones & charges
          </Link>
        }
      />
      <DataTable
        rows={jobs}
        rowKey={(j) => String(j.id)}
        columns={[
          {
            key: 'job',
            header: 'Job',
            render: (j) => (
              <Link href={`${base}/fulfilment/${j.id}`}>{String(j.id).slice(0, 8)}…</Link>
            ),
          },
          {
            key: 'mode',
            header: 'Mode',
            render: (j) => <span style={{ textTransform: 'capitalize' }}>{String(j.mode)}</span>,
          },
          { key: 'status', header: 'Status', render: (j) => <StatusPill value={String(j.status)} /> },
          {
            key: 'charge',
            header: 'Charge',
            align: 'num',
            render: (j) => `${String(j.currency)} ${String(j.delivery_charge)}`,
          },
        ]}
        empty={
          <BusinessEmpty businessId={params.businessId} module="fulfilment" fallbackTitle="No fulfilment jobs yet"
                         fallback="A job is created for each order that needs pickup, delivery, or shipping." />
        }
      />
    </div>
  )
}

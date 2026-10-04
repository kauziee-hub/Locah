import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DataTable, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { BusinessEmpty } from '@/components/BusinessEmpty'
import { ActionButton } from '@/components/ActionButton'
import { dayTimeLabel, rupees } from '@/lib/when'
import { setJobStatus } from './actions'
import { MODE_WORDS, moveWords, statusWords } from './words'

export const dynamic = 'force-dynamic'

type Job = {
  id: string
  mode: string
  status: string
  order_id: string
  order_number: string | null
  order_total: number | null
  customer_name: string | null
  address_line: string | null
  delivery_charge: number
  created_at: string | null
}

// The one next step a busy counter takes from the list; the job page has the rest.
const NEXT: Record<string, Record<string, string>> = {
  pickup: { pending: 'preparing', preparing: 'ready', ready: 'delivered' },
  delivery: { pending: 'preparing', preparing: 'ready', ready: 'out_for_delivery', out_for_delivery: 'delivered' },
  shipping: { pending: 'preparing', preparing: 'ready', ready: 'out_for_delivery', out_for_delivery: 'delivered' },
}

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
    apiTry<{ data: Job[] }>(
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
        <PageHeader title="Deliveries & pickup" />
        <GateNotice error={jobsRes.error} businessId={params.businessId} moduleLabel="Deliveries & pickup" />
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
        title="Deliveries & pickup"
        subtitle={(settings.active_modes || []).length
          ? `Every order to hand over or deliver, from preparing to done. Customers can choose ${(settings.active_modes || []).map((m) => (MODE_WORDS[m] ?? m).toLowerCase()).join(' or ')}.`
          : 'Customers can’t choose pickup or delivery yet — switch one on.'}
        actions={
          <Link href={`${base}/fulfilment/zones`} className="btn btn-ghost">
            Delivery areas &amp; charges
          </Link>
        }
      />
      <DataTable
        rows={jobs}
        rowKey={(j) => j.id}
        columns={[
          {
            key: 'order',
            header: 'Order',
            render: (j) => (
              <Link href={`${base}/fulfilment/${j.id}`}>
                {j.order_number ?? 'Order'}{j.customer_name ? ` · ${j.customer_name}` : ''}
              </Link>
            ),
          },
          {
            key: 'how',
            header: 'How',
            render: (j) => (
              <span>
                {MODE_WORDS[j.mode] ?? j.mode}
                {j.mode === 'delivery' && j.address_line ? <small className="bos-line-basis">{j.address_line}</small> : null}
              </span>
            ),
          },
          { key: 'status', header: 'Where it is', render: (j) => <StatusPill value={j.status} label={statusWords(j.mode)[j.status] ?? j.status} /> },
          { key: 'when', header: 'Placed', render: (j) => dayTimeLabel(j.created_at) },
          {
            key: 'next',
            header: '',
            render: (j) => {
              const to = NEXT[j.mode]?.[j.status]
              return to ? (
                <ActionButton className="btn-ghost" label={moveWords(j.mode)[to] ?? to} busyLabel="Saving…"
                  run={setJobStatus.bind(null, params.businessId, j.id, to, undefined)} />
              ) : j.order_total !== null ? rupees(j.order_total) : null
            },
          },
        ]}
        empty={
          <BusinessEmpty businessId={params.businessId} module="fulfilment" fallbackTitle="Nothing to hand over yet"
                         fallback="A job is created for each order that needs pickup, delivery, or shipping." />
        }
      />
    </div>
  )
}

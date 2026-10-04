import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { DetailShell, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { ActionButton } from '@/components/ActionButton'
import { ActionForm, SubmitButton } from '@/components/ActionForm'
import { dayTimeLabel, rupees } from '@/lib/when'
import { failJob, setJobStatus } from '../actions'
import { MODE_WORDS, moveWords, statusWords } from '../words'

export const dynamic = 'force-dynamic'

type Job = {
  id: string
  order_id: string
  order_number: string | null
  order_total: number | null
  customer_name: string | null
  customer_phone: string | null
  address_line: string | null
  note: string | null
  mode: string
  status: string
  delivery_charge: number
  outcome_reason?: string | null
  tracking_token: string
  created_at: string | null
  updated_at: string | null
}

/** One order to hand over or deliver: who, where, and the next step. */
export default async function FulfilmentJobDetailPage({ params }: { params: { businessId: string; jobId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const base = `/b/${params.businessId}`
  const back = <Link href={`${base}/fulfilment`}>Deliveries &amp; pickup</Link>
  const res = await apiTry<{ data: Job }>(`/v1/b/${params.businessId}/fulfilment/jobs/${params.jobId}`, token)
  if (!res.ok) {
    return (
      <div className="bos-page">
        <PageHeader title="Delivery" breadcrumb={back} />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Deliveries & pickup" />
      </div>
    )
  }
  const job = res.data.data
  const words = statusWords(job.mode)
  const moves = moveWords(job.mode)
  const forward: Record<string, string[]> = {
    pending: ['preparing'],
    preparing: ['ready'],
    ready: job.mode === 'pickup' ? ['delivered'] : ['out_for_delivery'],
    out_for_delivery: ['delivered'],
  }
  const next = forward[job.status] ?? []
  const open = !['delivered', 'failed', 'cancelled'].includes(job.status)
  const phone = job.customer_phone?.replace(/[^+\d]/g, '')

  return (
    <DetailShell
      breadcrumb={back}
      title={`${MODE_WORDS[job.mode] ?? 'Delivery'} · ${job.order_number ?? 'Order'}`}
      status={<StatusPill value={job.status} label={words[job.status] ?? job.status} />}
      meta={[
        ['Customer', job.customer_name ? (
          <span key="c">{job.customer_name}{phone ? <> · <a href={`tel:${phone}`}>{job.customer_phone}</a></> : null}</span>
        ) : '—'],
        ...(job.mode !== 'pickup' ? [['Deliver to', job.address_line ?? 'Address not given'] as [string, string]] : []),
        ...(job.note ? [['Note', job.note] as [string, string]] : []),
        ...(job.delivery_charge ? [['Delivery charge', rupees(job.delivery_charge)] as [string, string]] : []),
        ['Placed', dayTimeLabel(job.created_at)],
      ]}
      actions={open ? (
        <>
          {next.map((to) => (
            <ActionButton key={to} label={moves[to] ?? to} busyLabel="Saving…"
              run={setJobStatus.bind(null, params.businessId, job.id, to, undefined)} />
          ))}
          <ActionButton className="btn-ghost" label="Cancel" busyLabel="Saving…" confirmLabel="Yes, cancel it"
            confirm={`Cancel this ${job.mode === 'pickup' ? 'pickup' : 'delivery'}? The customer's tracking page will say so.`}
            run={setJobStatus.bind(null, params.businessId, job.id, 'cancelled', 'Cancelled from Workspace')} />
        </>
      ) : undefined}
    >
      <p>
        <Link href={`${base}/orders/${job.order_id}`}>Open order {job.order_number ?? ''} →</Link>
        {job.order_total !== null ? <span className="bos-hint"> · {rupees(job.order_total)}</span> : null}
      </p>
      {job.outcome_reason ? <p className="bos-hint">Reason: {job.outcome_reason}</p> : null}
      {open && job.status !== 'pending' ? (
        <section className="bos-card" aria-labelledby="fail-h" style={{ maxWidth: '32rem' }}>
          <h2 id="fail-h">Couldn&apos;t complete it?</h2>
          <p className="bos-hint">Say what happened — nobody home, wrong address, item damaged. The customer&apos;s tracking page shows it couldn&apos;t be completed.</p>
          <ActionForm action={failJob} className="bos-lead__lost">
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="jobId" value={job.id} />
            <input name="reason" required maxLength={300} placeholder="What happened" aria-label="What happened" />
            <SubmitButton className="btn-ghost">{moves.failed}</SubmitButton>
          </ActionForm>
        </section>
      ) : null}
    </DetailShell>
  )
}

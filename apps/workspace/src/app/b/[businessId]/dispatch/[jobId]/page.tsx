import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { advanceDispatchJob, assignDispatchJob } from '../actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Job = {
  id: string
  order_id: string
  order_number: string
  kind: string
  status: string
  assignee_name: string | null
  pickup: { label: string | null; maps_url: string | null }
  dropoff: { line?: string; area?: string; city?: string } | null
  dropoff_maps_url: string | null
  customer: { name: string | null; phone: string | null }
  timestamps: Record<string, string | null>
  proof_note: string | null
  failure_reason: string | null
  location_mode: string
}

type Member = { id: string; display_name: string; status: string }

function place(dropoff: Job['dropoff']): string {
  if (!dropoff) return 'No drop-off yet'
  return [dropoff.line, dropoff.area, dropoff.city].filter(Boolean).join(', ') || 'No drop-off yet'
}

export default async function DispatchJobPage({
  params,
}: {
  params: { businessId: string; jobId: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const base = `/b/${params.businessId}`
  const res = await apiTry<{ data: Job }>(`/v1/b/${params.businessId}/dispatch/jobs/${params.jobId}`, token)
  if (!res.ok) {
    return (
      <div>
        <Link href={`${base}/dispatch`}>← Dispatch</Link>
        <PageHeader title="Delivery job" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Dispatch" />
      </div>
    )
  }
  const job = res.data.data
  const membersRes = await apiTry<{ data: Member[] }>(
    `/v1/platform/businesses/${params.businessId}/workforce/members`,
    token,
  )
  const members = membersRes.ok ? membersRes.data.data.filter((member) => member.status === 'active') : []
  const canAssign = job.status === 'unassigned' || job.status === 'failed'

  return (
    <div>
      <Link href={`${base}/dispatch`}>← Dispatch</Link>
      <PageHeader title={job.order_number} subtitle={`${job.kind} · ${job.location_mode === 'status_only' ? 'Status and times only' : 'Device location'}`} />
      <p>
        <StatusPill value={job.status} /> {job.assignee_name ? `· ${job.assignee_name}` : '· Nobody assigned'}
      </p>
      <p>Pickup: {job.pickup.label || 'Shop'}</p>
      <p>Drop-off: {place(job.dropoff)}</p>
      <p>
        Customer: {job.customer.name || '—'}
        {job.customer.phone ? ` · ${job.customer.phone}` : ''}
      </p>
      {job.proof_note ? <p>Proof: {job.proof_note}</p> : null}
      {job.failure_reason ? <p>Failed: {job.failure_reason}</p> : null}
      <p>
        <Link href={`${base}/orders/${job.order_id}`}>Open the order</Link>
      </p>

      {canAssign && members.length > 0 ? (
        <SafeForm action={assignDispatchJob} style={{ display: 'flex', gap: '0.5rem', alignItems: 'end', marginTop: '1rem' }}>
          <input type="hidden" name="businessId" value={params.businessId} />
          <input type="hidden" name="jobId" value={job.id} />
          <label>
            Assign crew
            <select name="memberId" required defaultValue="">
              <option value="" disabled>Choose a person</option>
              {members.map((member) => (
                <option key={member.id} value={member.id}>{member.display_name}</option>
              ))}
            </select>
          </label>
          <button type="submit">Assign</button>
        </SafeForm>
      ) : null}

      <section style={{ marginTop: '1.25rem', display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        {job.status === 'assigned' ? (
          <SafeForm action={advanceDispatchJob}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="jobId" value={job.id} />
            <input type="hidden" name="status" value="picked_up" />
            <button type="submit">Picked up</button>
          </SafeForm>
        ) : null}
        {job.status === 'picked_up' && job.kind === 'delivery' ? (
          <SafeForm action={advanceDispatchJob}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="jobId" value={job.id} />
            <input type="hidden" name="status" value="out_for_delivery" />
            <button type="submit">Out for delivery</button>
          </SafeForm>
        ) : null}
      </section>
    </div>
  )
}

import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { advanceDispatchJob } from '../dispatch/actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Job = {
  id: string
  order_number: string
  kind: string
  status: string
  pickup: { label: string | null; maps_url: string | null }
  dropoff: { line?: string; area?: string; city?: string } | null
  dropoff_maps_url: string | null
  customer: { name: string | null; phone: string | null }
  timestamps: { planned_at: string | null }
}

function place(dropoff: Job['dropoff']): string {
  if (!dropoff) return 'No drop-off'
  return [dropoff.line, dropoff.area, dropoff.city].filter(Boolean).join(', ') || 'No drop-off'
}

function JobCard({
  job,
  businessId,
  next,
}: {
  job: Job
  businessId: string
  next: boolean
}) {
  return (
    <article style={{ border: '1px solid var(--color-border, #ddd)', borderRadius: '8px', padding: '1rem', marginBottom: '0.75rem' }}>
      <h3 style={{ marginTop: 0 }}>
        {next ? 'Next stop · ' : ''}
        {job.order_number}
      </h3>
      <p><StatusPill value={job.status} /> · {job.kind === 'pickup' ? 'Pickup' : 'Delivery'}</p>
      <p>Pickup: {job.pickup.label || 'Shop'}</p>
      {job.pickup.maps_url ? <p><a href={job.pickup.maps_url}>Open pickup in Maps</a></p> : null}
      <p>Drop-off: {place(job.dropoff)}</p>
      {job.dropoff_maps_url ? <p><a href={job.dropoff_maps_url}>Open drop-off in Maps</a></p> : null}
      <p>
        Customer: {job.customer.name || '—'}
        {job.customer.phone ? (
          <> · <a href={`tel:${job.customer.phone}`}>{job.customer.phone}</a></>
        ) : null}
      </p>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        {job.status === 'assigned' ? (
          <SafeForm action={advanceDispatchJob}>
            <input type="hidden" name="businessId" value={businessId} />
            <input type="hidden" name="jobId" value={job.id} />
            <input type="hidden" name="status" value="picked_up" />
            <button type="submit">Picked up</button>
          </SafeForm>
        ) : null}
        {job.status === 'picked_up' && job.kind === 'delivery' ? (
          <SafeForm action={advanceDispatchJob}>
            <input type="hidden" name="businessId" value={businessId} />
            <input type="hidden" name="jobId" value={job.id} />
            <input type="hidden" name="status" value="out_for_delivery" />
            <button type="submit">Out for delivery</button>
          </SafeForm>
        ) : null}
        {(job.status === 'out_for_delivery' || (job.status === 'picked_up' && job.kind === 'pickup')) ? (
          <SafeForm action={advanceDispatchJob} style={{ display: 'flex', gap: '0.35rem' }}>
            <input type="hidden" name="businessId" value={businessId} />
            <input type="hidden" name="jobId" value={job.id} />
            <input type="hidden" name="status" value="delivered" />
            <input name="proof" required placeholder="Proof note" aria-label="Proof note" />
            <button type="submit">Delivered</button>
          </SafeForm>
        ) : null}
        {job.status !== 'delivered' && job.status !== 'failed' && job.status !== 'unassigned' ? (
          <SafeForm action={advanceDispatchJob} style={{ display: 'flex', gap: '0.35rem' }}>
            <input type="hidden" name="businessId" value={businessId} />
            <input type="hidden" name="jobId" value={job.id} />
            <input type="hidden" name="status" value="failed" />
            <input name="reason" required placeholder="Why it failed" aria-label="Why it failed" />
            <button type="submit">Failed</button>
          </SafeForm>
        ) : null}
      </div>
    </article>
  )
}

/** Crew operational view: my jobs, the next stop, pickup, drop-off, contact, status. */
export default async function CrewJobsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const res = await apiTry<{ data: { next: Job | null; jobs: Job[] } }>(
    `/v1/b/${params.businessId}/dispatch/mine`,
    token,
  )
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="My jobs" />
        <GateNotice error={res.error} businessId={params.businessId} moduleLabel="Dispatch" />
      </div>
    )
  }
  const { next, jobs } = res.data.data
  const rest = jobs.filter((job) => !next || job.id !== next.id)

  return (
    <div>
      <PageHeader title="My jobs" subtitle="Your assigned stops. The customer's number shows only while the job is active." />
      {next ? <JobCard job={next} businessId={params.businessId} next /> : <p>No next stop.</p>}
      {rest.map((job) => (
        <JobCard key={job.id} job={job} businessId={params.businessId} next={false} />
      ))}
    </div>
  )
}

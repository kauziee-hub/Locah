import Link from 'next/link'
import { randomUUID } from 'crypto'
import { redirect } from 'next/navigation'
import { apiTry } from '@/lib/api'
import { getAccessToken } from '@/lib/supabase/access-token'
import { Card, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { assignJob, consumePart, moveJob, returnPart } from '../actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Job = {
  id: string; reference: string; title: string; status: string; version: number
  customer_contact_id: string; project_id: string | null; source_quote_id: string | null
  customer_name: string | null; customer_phone: string | null
  assigned_member_id: string | null; problem: string | null; work_performed: string | null
  asset_description: string | null; asset_serial: string | null; priority: string
  approval_note: string | null; approval_recorded_at: string | null
  scheduled_at: string | null; completed_at: string | null; completion_note: string | null
  parts: { id: string; offering_id: string; quantity: number; inventory_movement_id: string; location_id: string | null }[]
  parts_out: { location_id: string; location_name: string; offering_id: string; title: string; quantity_out: number; quantity_back: number; open: number; open_text: string; serial_tracked: boolean }[]
}
type Named = { id: string; display_name: string; status?: string }
// Only what this person may use on this job: its location and, for a technician, their vans.
type Stock = { inventory_record_id: string; offering_id: string; title: string; available_text: string; available: number; location_id: string; location_name: string; is_van: boolean; serial_tracked: boolean }

const next: Record<string, string[]> = {
  new: ['assigned', 'cancelled'], assigned: ['inspecting', 'in_progress', 'cancelled'],
  inspecting: ['awaiting_approval', 'in_progress', 'cancelled'],
  awaiting_approval: ['approved', 'cancelled'], approved: ['in_progress', 'cancelled'],
  in_progress: ['waiting_parts', 'quality_check', 'cancelled'],
  waiting_parts: ['in_progress', 'cancelled'], quality_check: ['in_progress', 'completed', 'cancelled'],
}
const label: Record<string, string> = {
  assigned: 'Assigned', inspecting: 'Inspecting', awaiting_approval: 'Awaiting approval',
  approved: 'Customer approved', in_progress: 'Work under way', waiting_parts: 'Waiting for parts',
  quality_check: 'Quality check', completed: 'Complete job', cancelled: 'Cancel job',
}

export default async function JobPage({ params }: { params: { businessId: string; jobId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const [jobRes, membersRes, stockRes] = await Promise.all([
    apiTry<{ data: Job }>(`/v1/b/${b}/jobs/${params.jobId}`, token),
    apiTry<{ data: Named[] }>(`/v1/platform/businesses/${b}/workforce/members`, token),
    apiTry<{ data: Stock[] }>(`/v1/b/${b}/jobs/${params.jobId}/parts/stock`, token),
  ])
  if (!jobRes.ok) return <div><PageHeader title="Job card" breadcrumb={<Link href={`/b/${b}/jobs`}>← Job cards</Link>} /><GateNotice error={jobRes.error} businessId={b} moduleLabel="Jobs" /></div>
  const job = jobRes.data.data
  const members = membersRes.ok ? membersRes.data.data || [] : []
  const technician = members.find((m) => m.id === job.assigned_member_id)
  const stock = stockRes.ok ? stockRes.data.data : []
  const open = !['completed', 'cancelled'].includes(job.status)
  return <div className="bos-page">
    <PageHeader title={`${job.reference} · ${job.title}`} breadcrumb={<Link href={`/b/${b}/jobs`}>← Job cards</Link>}
      actions={<StatusPill value={label[job.status] || job.status} />} />
    <Card style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(12rem, 1fr))', gap: '1rem' }}>
      <div><small>Customer</small><p style={{ margin: 0 }}>{job.customer_name || 'Customer'}{job.customer_phone ? <span style={{ display: 'block' }}>{job.customer_phone}</span> : null}</p></div>
      <div><small>Asset</small><p style={{ margin: 0 }}>{job.asset_description || 'Not recorded'}{job.asset_serial ? ` · ${job.asset_serial}` : ''}</p></div>
      <div><small>Assigned to</small><p style={{ margin: 0 }}>{technician?.display_name || 'Not yet assigned'}</p></div>
      <div><small>Visit (IST)</small><p style={{ margin: 0 }}>{job.scheduled_at ? new Date(job.scheduled_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' }) : 'Not scheduled'}</p></div>
      {job.project_id ? <div><small>Part of project</small><p style={{ margin: 0 }}><Link href={`/b/${b}/projects/${job.project_id}`}>Open project</Link></p></div> : null}
      {job.source_quote_id ? <div><small>Agreed quote</small><p style={{ margin: 0 }}><Link href={`/b/${b}/quotes/${job.source_quote_id}`}>Open quote</Link></p></div> : null}
    </Card>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 22rem), 1fr))', gap: '1rem', marginTop: '1rem' }}>
      <Card>
        <h2 style={{ marginTop: 0 }}>Work record</h2>
        <p><strong>Reported problem</strong><br />{job.problem || 'No problem description yet.'}</p>
        <p><strong>Work performed</strong><br />{job.work_performed || 'No work recorded yet.'}</p>
        {job.approval_note ? <p><strong>Approval recorded</strong><br />{job.approval_note}</p> : null}
        {job.completion_note ? <p><strong>Completion</strong><br />{job.completion_note}</p> : null}
      </Card>
      <Card>
        <h2 style={{ marginTop: 0 }}>Next step</h2>
        {open && !job.assigned_member_id ? <SafeForm action={assignJob} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={b} /><input type="hidden" name="jobId" value={job.id} />
          <label>Assign a person<select name="member_id" required defaultValue=""><option value="">Choose team member</option>{members.filter((m) => m.status !== 'inactive').map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select></label>
          <button type="submit" className="btn">Assign job</button>
        </SafeForm> : null}
        {open && job.assigned_member_id ? <SafeForm action={moveJob} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={b} /><input type="hidden" name="jobId" value={job.id} />
          <input type="hidden" name="version" value={job.version} />
          <label>Move to<select name="status" required defaultValue=""><option value="">Choose next step</option>{(next[job.status] || []).map((status) => <option key={status} value={status}>{label[status] || status}</option>)}</select></label>
          <label>Work performed<textarea name="work_performed" rows={3} defaultValue={job.work_performed || ''} placeholder="Required before completion" /></label>
          <label>Completion note<textarea name="completion_note" rows={2} placeholder="Optional handover note" /></label>
          {job.status === 'awaiting_approval' ? <label>How did the customer approve?<textarea name="approval_note" rows={2} placeholder="Accepted quote, message, or phone confirmation" /></label> : null}
          <button type="submit" className="btn">Update job</button>
        </SafeForm> : null}
        {!open ? <p style={{ marginBottom: 0 }}>This job is closed. Its work record and parts remain available in the customer history.</p> : null}
      </Card>
    </div>
    <Card style={{ marginTop: '1rem' }}>
      <h2 style={{ marginTop: 0 }}>Parts used</h2>
      {job.parts_out.length ? <ul className="bos-mini-list">{job.parts_out.map((row) => {
        // A return goes back to where the part came from; any part row of that item there will do.
        const part = [...job.parts].reverse().find((p) => p.offering_id === row.offering_id && p.location_id === row.location_id)
        return <li key={`${row.location_id}-${row.offering_id}`}>
          <div>
            <strong>{row.title}</strong>
            <p>{row.location_name} · {row.quantity_out} used{row.quantity_back ? ` · ${row.quantity_back} given back` : ''} · {row.open_text} still out</p>
          </div>
          {part && row.open > 0 && !row.serial_tracked ? <SafeForm action={returnPart} style={{ display: 'flex', gap: '0.4rem', alignItems: 'end' }}>
            <input type="hidden" name="businessId" value={b} /><input type="hidden" name="jobId" value={job.id} />
            <input type="hidden" name="partId" value={part.id} /><input type="hidden" name="idempotency_key" value={randomUUID()} />
            <label>Unused<input name="quantity" type="number" min="1" max={row.open} step="1" required style={{ width: '5rem' }} /></label>
            <button type="submit" className="btn-ghost">Give back</button>
          </SafeForm> : null}
        </li>
      })}</ul>
        : <p>No business stock consumed on this job.</p>}
      {open && ['in_progress', 'waiting_parts', 'quality_check'].includes(job.status) && stock.length ? <SafeForm action={consumePart} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(10rem, 1fr))', gap: '0.6rem' }}>
        <input type="hidden" name="businessId" value={b} /><input type="hidden" name="jobId" value={job.id} />
        <input type="hidden" name="idempotency_key" value={randomUUID()} />
        <label>Stock item<select name="inventory_record_id" required defaultValue=""><option value="">Choose available stock</option>{stock.map((s) => <option key={s.inventory_record_id} value={s.inventory_record_id}>{s.title} · {s.location_name}{s.is_van ? ' (van)' : ''} · {s.available_text}</option>)}</select></label>
        <label>Quantity in stock units<input name="quantity" type="number" min="1" step="1" required /></label>
        <label>Serials, if tracked<textarea name="serials" rows={2} placeholder="One per line" /></label>
        <button type="submit" className="btn">Record part used</button>
      </SafeForm> : null}
      {open && !stockRes.ok ? <p style={{ color: 'var(--color-muted)' }}>Enable and configure Inventory to record business-owned parts; customer-owned parts are not stock.</p> : null}
      {open && stockRes.ok && !stock.length && ['in_progress', 'waiting_parts', 'quality_check'].includes(job.status) ? <p style={{ color: 'var(--color-muted)' }}>No free stock at this job&apos;s location or the technician&apos;s van.</p> : null}
    </Card>
  </div>
}

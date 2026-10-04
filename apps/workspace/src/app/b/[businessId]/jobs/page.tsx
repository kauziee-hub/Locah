import Link from 'next/link'
import { redirect } from 'next/navigation'
import { apiTry } from '@/lib/api'
import { getAccessToken } from '@/lib/supabase/access-token'
import { Card, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { createJob } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Job = {
  id: string; reference: string; title: string; status: string; priority: string
  customer_contact_id: string; project_id: string | null; scheduled_at: string | null
  customer_name: string | null
  assigned_member_id: string | null; asset_description: string | null
}
type Contact = { id: string; display_name: string }
type Member = { id: string; display_name: string; status?: string }
type Project = { id: string; reference: string; title: string }

const words: Record<string, string> = {
  new: 'Needs assignment', assigned: 'Assigned', inspecting: 'Inspecting',
  awaiting_approval: 'Waiting for customer', approved: 'Approved',
  in_progress: 'Work under way', waiting_parts: 'Waiting for parts',
  quality_check: 'Quality check', completed: 'Completed', cancelled: 'Cancelled',
}

export default async function JobsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect(`/login?destination=${encodeURIComponent(`/b/${params.businessId}/jobs`)}`)
  const b = params.businessId
  const [jobsRes, contactsRes, membersRes, projectsRes] = await Promise.all([
    apiTry<{ data: Job[] }>(`/v1/b/${b}/jobs`, token),
    apiTry<{ data: Contact[] }>(`/v1/platform/businesses/${b}/customers`, token),
    apiTry<{ data: Member[] }>(`/v1/platform/businesses/${b}/workforce/members`, token),
    apiTry<{ data: { projects: Project[] } }>(`/v1/platform/businesses/${b}/projects`, token),
  ])
  if (!jobsRes.ok) return <div><PageHeader title="Job cards" /><GateNotice error={jobsRes.error} businessId={b} moduleLabel="Jobs" /></div>
  const jobs = jobsRes.data.data || []
  const contacts = contactsRes.ok ? contactsRes.data.data || [] : []
  const members = membersRes.ok ? membersRes.data.data || [] : []
  const projects = projectsRes.ok ? projectsRes.data.data.projects || [] : []
  const groups = [
    { title: 'Needs attention', hint: 'Unassigned, awaiting a decision, or blocked by parts',
      rows: jobs.filter((j) => ['new', 'awaiting_approval', 'waiting_parts'].includes(j.status)) },
    { title: 'On the bench or on site', hint: 'Assigned work moving through inspection, repair and quality check',
      rows: jobs.filter((j) => ['assigned', 'inspecting', 'approved', 'in_progress', 'quality_check'].includes(j.status)) },
    { title: 'Finished', hint: 'Service history stays with the customer and asset',
      rows: jobs.filter((j) => j.status === 'completed') },
  ]
  return <div className="bos-page">
    <PageHeader title="Job cards" subtitle="One card for each visit or repair. Bookings reserve time; projects coordinate larger work." />
    <details className="bos-panel" style={{ marginBottom: '1.5rem' }}>
      <summary style={{ cursor: 'pointer', fontWeight: 650 }}>Start a job</summary>
      <SafeForm action={createJob} style={{ display: 'grid', gap: '0.8rem', gridTemplateColumns: 'repeat(auto-fit, minmax(13rem, 1fr))', paddingTop: '1rem' }}>
        <input type="hidden" name="businessId" value={b} />
        <label>Customer<select name="customer_contact_id" required defaultValue=""><option value="">Choose customer</option>{contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></label>
        <label>Work to do<input name="title" required maxLength={200} placeholder="Repair AC compressor" /></label>
        <label>Assigned person<select name="assigned_member_id" defaultValue=""><option value="">Assign later</option>{members.filter((m) => m.status !== 'inactive').map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select></label>
        <label>Project, if part of one<select name="project_id" defaultValue=""><option value="">Standalone job</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.reference} · {p.title}</option>)}</select></label>
        <label>Scheduled for (IST)<input name="scheduled_at" type="datetime-local" /></label>
        <label>Priority<select name="priority" defaultValue="normal"><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option><option value="low">Low</option></select></label>
        <label>Customer asset<input name="asset_description" placeholder="AC unit, vehicle, machine…" /></label>
        <label>Serial / registration<input name="asset_serial" placeholder="Optional" /></label>
        <label style={{ gridColumn: '1 / -1' }}>Problem or request<textarea name="problem" rows={2} /></label>
        <button className="btn" type="submit" style={{ justifySelf: 'start' }}>Create job card</button>
      </SafeForm>
    </details>
    {jobs.length === 0 ? <Card><p style={{ margin: 0 }}>No job cards yet. Start with a customer request, then assign the person doing the work.</p></Card> : null}
    {groups.map((group) => group.rows.length ? <section key={group.title} style={{ marginBottom: '1.6rem' }}>
      <h2 style={{ marginBottom: '0.2rem' }}>{group.title} <small style={{ color: 'var(--color-muted)' }}>{group.rows.length}</small></h2>
      <p style={{ color: 'var(--color-muted)', marginTop: 0 }}>{group.hint}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 19rem), 1fr))', gap: '0.75rem' }}>
        {group.rows.map((job) => <Card key={job.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.6rem' }}>
            <Link href={`/b/${b}/jobs/${job.id}`} style={{ fontWeight: 650 }}>{job.reference} · {job.title}</Link>
            <StatusPill value={words[job.status] || job.status} />
          </div>
          <p style={{ color: 'var(--color-muted)', marginBottom: 0 }}>{job.customer_name || 'Customer'}
            {job.asset_description ? ` · ${job.asset_description}` : ''}</p>
          {job.scheduled_at ? <p style={{ marginBottom: 0, fontSize: '0.85rem' }}>Scheduled {new Date(job.scheduled_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' })} IST</p> : null}
        </Card>)}
      </div>
    </section> : null)}
  </div>
}

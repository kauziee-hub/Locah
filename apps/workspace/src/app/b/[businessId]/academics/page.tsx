import Link from 'next/link'
import { redirect } from 'next/navigation'
import { apiTry } from '@/lib/api'
import { getAccessToken } from '@/lib/supabase/access-token'
import { Card, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { createBatch, createCourse } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Course = { id: string; title: string; description: string | null; status: string }
type Batch = { id: string; course_id: string; name: string; teacher_member_id: string | null; starts_on: string | null; ends_on: string | null; capacity: number | null; status: string }
type Member = { id: string; display_name: string; status?: string }
type Location = { id: string; name: string }

export default async function AcademicsPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect(`/login?destination=${encodeURIComponent(`/b/${params.businessId}/academics`)}`)
  const b = params.businessId
  const [coursesRes, batchesRes, membersRes, locationsRes] = await Promise.all([
    apiTry<{ data: Course[] }>(`/v1/b/${b}/academics/courses`, token),
    apiTry<{ data: Batch[] }>(`/v1/b/${b}/academics/batches`, token),
    apiTry<{ data: Member[] }>(`/v1/platform/businesses/${b}/workforce/members`, token),
    apiTry<{ data: Location[] }>(`/v1/platform/businesses/${b}/locations`, token),
  ])
  if (!coursesRes.ok) return <div><PageHeader title="Courses & batches" /><GateNotice error={coursesRes.error} businessId={b} moduleLabel="Academics" /></div>
  const courses = coursesRes.data.data || []
  const batches = batchesRes.ok ? batchesRes.data.data || [] : []
  const members = membersRes.ok ? membersRes.data.data || [] : []
  const locations = locationsRes.ok ? locationsRes.data.data || [] : []
  const memberName = new Map(members.map((m) => [m.id, m.display_name]))
  return <div className="bos-page">
    <PageHeader title="Courses & batches" subtitle="A clear home for programmes, cohorts and class times. Fees and attendance stay in their own modules." />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 20rem), 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
      <Card>
        <h2 style={{ marginTop: 0 }}>New course</h2>
        <p style={{ color: 'var(--color-muted)' }}>What students come here to learn.</p>
        <SafeForm action={createCourse} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={b} />
          <label>Name<input name="title" required maxLength={200} placeholder="Foundation Mathematics" /></label>
          <label>Description<textarea name="description" rows={2} /></label>
          <button type="submit" className="btn">Add course</button>
        </SafeForm>
      </Card>
      <Card>
        <h2 style={{ marginTop: 0 }}>New batch</h2>
        <p style={{ color: 'var(--color-muted)' }}>The actual group, teacher and place.</p>
        <SafeForm action={createBatch} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={b} />
          <label>Course<select name="course_id" required defaultValue=""><option value="">Choose course</option>{courses.filter((c) => c.status !== 'archived').map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
          <label>Batch name<input name="name" required maxLength={200} placeholder="Morning · 2026" /></label>
          <label>Teacher<select name="teacher_member_id" defaultValue=""><option value="">Assign later</option>{members.filter((m) => m.status !== 'inactive').map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select></label>
          <label>Place<select name="location_id" defaultValue=""><option value="">Online / no set location</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
          <label>Room<input name="room" placeholder="Optional" /></label>
          <label>Capacity<input name="capacity" type="number" min="1" placeholder="No limit" /></label>
          <label>Starts<input name="starts_on" type="date" /></label>
          <label>Ends<input name="ends_on" type="date" /></label>
          <label>Online link<input name="meeting_url" type="url" placeholder="Optional" /></label>
          <button type="submit" className="btn" disabled={!courses.length}>Create batch</button>
        </SafeForm>
      </Card>
    </div>
    <h2>Teaching now</h2>
    {!batches.length ? <Card><p style={{ margin: 0 }}>No batches yet. Add a course, then give it a group and a teacher.</p></Card> : null}
    {courses.map((course) => {
      const groups = batches.filter((batch) => batch.course_id === course.id)
      return groups.length ? <section key={course.id} style={{ marginBottom: '1.4rem' }}>
        <h3>{course.title}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 17rem), 1fr))', gap: '0.7rem' }}>
          {groups.map((batch) => <Card key={batch.id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}><Link href={`/b/${b}/academics/${batch.id}`} style={{ fontWeight: 650 }}>{batch.name}</Link><StatusPill value={batch.status} /></div>
            <p style={{ color: 'var(--color-muted)', marginBottom: 0 }}>{batch.teacher_member_id ? memberName.get(batch.teacher_member_id) || 'Teacher' : 'Teacher not assigned'}
              {batch.capacity ? ` · ${batch.capacity} places` : ''}</p>
            {batch.starts_on ? <p style={{ fontSize: '0.85rem', marginBottom: 0 }}>From {new Date(`${batch.starts_on}T00:00:00`).toLocaleDateString('en-IN', { dateStyle: 'medium' })}</p> : null}
          </Card>)}
        </div>
      </section> : null
    })}
  </div>
}

import Link from 'next/link'
import { redirect } from 'next/navigation'
import { apiTry } from '@/lib/api'
import { getAccessToken } from '@/lib/supabase/access-token'
import { Card, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { addSession, createAssessment, enrolStudent, postAnnouncement, recordResult } from '../actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Batch = { id: string; name: string; course_id: string; capacity: number | null; teacher_member_id: string | null; status: string; room: string | null; meeting_url: string | null }
type Course = { id: string; title: string }
type Contact = { id: string; display_name: string }
type Session = { id: string; starts_at: string; ends_at: string; topic: string | null; status: string; meeting_url: string | null }
type Enrolment = { id: string; student_name: string; guardian_name: string | null; status: string }
type Assessment = { id: string; title: string; maximum: string; enrolment_id: string | null; marks: string | null }
type Announcement = { id: string; title: string; body: string; created_at: string }

export default async function BatchPage({ params }: { params: { businessId: string; batchId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId, id = params.batchId
  const root = `/v1/b/${b}/academics`
  const [batchesRes, coursesRes, sessionsRes, enrolmentsRes, assessmentsRes, contactsRes, announcementsRes] = await Promise.all([
    apiTry<{ data: Batch[] }>(`${root}/batches`, token),
    apiTry<{ data: Course[] }>(`${root}/courses`, token),
    apiTry<{ data: Session[] }>(`${root}/batches/${id}/sessions`, token),
    apiTry<{ data: Enrolment[] }>(`${root}/batches/${id}/enrolments`, token),
    apiTry<{ data: Assessment[] }>(`${root}/batches/${id}/assessments`, token),
    apiTry<{ data: Contact[] }>(`/v1/platform/businesses/${b}/customers`, token),
    apiTry<{ data: Announcement[] }>(`${root}/batches/${id}/announcements`, token),
  ])
  if (!batchesRes.ok) return <div><PageHeader title="Batch" /><GateNotice error={batchesRes.error} businessId={b} moduleLabel="Academics" /></div>
  const batch = batchesRes.data.data.find((item) => item.id === id)
  if (!batch) return <div><PageHeader title="Batch not found" breadcrumb={<Link href={`/b/${b}/academics`}>← Courses</Link>} /></div>
  const course = coursesRes.ok ? coursesRes.data.data.find((item) => item.id === batch.course_id) : null
  const sessions = sessionsRes.ok ? sessionsRes.data.data : []
  const enrolments = enrolmentsRes.ok ? enrolmentsRes.data.data : []
  const assessments = assessmentsRes.ok ? assessmentsRes.data.data : []
  const contacts = contactsRes.ok ? contactsRes.data.data : []
  const announcements = announcementsRes.ok ? announcementsRes.data.data : []
  const uniqueAssessments = Array.from(new Map(assessments.map((a) => [a.id, a])).values())
  return <div className="bos-page">
    <PageHeader title={batch.name} subtitle={course?.title || 'Course batch'} breadcrumb={<Link href={`/b/${b}/academics`}>← Courses & batches</Link>}
      actions={<StatusPill value={batch.status} />} />
    <Card><p style={{ margin: 0 }}>This cohort has {enrolments.filter((e) => e.status === 'active').length}{batch.capacity ? ` of ${batch.capacity}` : ''} students, {sessions.filter((s) => s.status === 'scheduled').length} scheduled classes, and {uniqueAssessments.length} assessments.</p>
      {batch.room ? <p>Room: {batch.room}</p> : null}{batch.meeting_url ? <p><a href={batch.meeting_url}>Online class link</a></p> : null}
      <p style={{ color: 'var(--color-muted)', marginBottom: 0 }}>Fees are handled by Memberships; attendance by Attendance. This page records teaching and progress only.</p>
    </Card>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 21rem), 1fr))', gap: '1rem', marginTop: '1rem' }}>
      <Card>
        <h2 style={{ marginTop: 0 }}>Class timetable</h2>
          {sessions.length ? <ol>{sessions.map((s) => <li key={s.id} style={{ marginBottom: '0.7rem' }}><strong>{new Date(s.starts_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' })} IST</strong> · {s.topic || 'Class'} <small>({s.status})</small></li>)}</ol>
          : <p>No classes scheduled yet.</p>}
        <SafeForm action={addSession} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={b} /><input type="hidden" name="batchId" value={id} />
          <label>Starts (IST)<input name="starts_at" type="datetime-local" required /></label>
          <label>Ends (IST)<input name="ends_at" type="datetime-local" required /></label>
          <label>Topic<input name="topic" placeholder="Algebra: quadratic equations" /></label>
          <label>Class link<input name="meeting_url" type="url" placeholder="Optional override" /></label>
          <button type="submit" className="btn">Schedule class</button>
        </SafeForm>
      </Card>
      <Card>
        <h2 style={{ marginTop: 0 }}>Students</h2>
        {enrolments.length ? <ul>{enrolments.map((e) => <li key={e.id}>{e.student_name}{e.guardian_name ? ` · guardian ${e.guardian_name}` : ''} <small>({e.status})</small></li>)}</ul>
          : <p>No students enrolled yet.</p>}
        {/* Keyed on the roll so it starts empty after each enrolment: a guardian chosen for one
            student must never carry over to the next. */}
        <SafeForm key={`enrol-${enrolments.length}`} action={enrolStudent} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={b} /><input type="hidden" name="batchId" value={id} />
          <label>Student<select name="student_contact_id" required defaultValue=""><option value="">Choose student contact</option>{contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></label>
          <label>Guardian<select name="guardian_contact_id" defaultValue=""><option value="">No guardian / adult learner</option>{contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></label>
          <label><input name="is_minor" type="checkbox" /> Student is under 18 (guardian required)</label>
          <button type="submit" className="btn">Enrol in batch</button>
          <small>Only the nominated guardian&apos;s signed-in identity can open the portal for this student.</small>
        </SafeForm>
      </Card>
      <Card>
        <h2 style={{ marginTop: 0 }}>Assessments & marks</h2>
        {uniqueAssessments.length ? <ul>{uniqueAssessments.map((a) => <li key={a.id}>{a.title} · out of {a.maximum}</li>)}</ul>
          : <p>No assessments recorded yet.</p>}
        <SafeForm action={createAssessment} style={{ display: 'grid', gap: '0.6rem', marginBottom: '1rem' }}>
          <input type="hidden" name="businessId" value={b} /><input type="hidden" name="batchId" value={id} />
          <label>Assessment<input name="title" required placeholder="Monthly test" /></label>
          <label>Maximum marks<input name="maximum" type="number" min="0.01" step="0.01" required /></label>
          <button type="submit" className="btn">Add assessment</button>
        </SafeForm>
        {uniqueAssessments.length && enrolments.length ? <SafeForm key={`result-${assessments.filter((a) => a.marks !== null).length}`} action={recordResult} style={{ display: 'grid', gap: '0.6rem', borderTop: '1px solid var(--color-border)', paddingTop: '1rem' }}>
          <input type="hidden" name="businessId" value={b} /><input type="hidden" name="batchId" value={id} />
          <label>Test<select name="assessmentId" required defaultValue=""><option value="">Choose assessment</option>{uniqueAssessments.map((a) => <option key={a.id} value={a.id}>{a.title} / {a.maximum}</option>)}</select></label>
          <label>Student<select name="enrolment_id" required defaultValue=""><option value="">Choose student</option>{enrolments.filter((e) => e.status === 'active').map((e) => <option key={e.id} value={e.id}>{e.student_name}</option>)}</select></label>
          <label>Marks<input name="marks" type="number" min="0" step="0.01" required /></label>
          <label>Teacher note<textarea name="teacher_note" rows={2} /></label>
          <button type="submit" className="btn">Save result</button>
        </SafeForm> : null}
      </Card>
      <Card>
        <h2 style={{ marginTop: 0 }}>Batch notices</h2>
        {announcements.length ? <ul>{announcements.map((notice) => <li key={notice.id}><strong>{notice.title}</strong><p>{notice.body}</p></li>)}</ul>
          : <p>No notices posted yet.</p>}
        <SafeForm action={postAnnouncement} style={{ display: 'grid', gap: '0.6rem' }}>
          <input type="hidden" name="businessId" value={b} /><input type="hidden" name="batchId" value={id} />
          <label>Title<input name="title" required maxLength={200} /></label>
          <label>Message<textarea name="body" required maxLength={4000} rows={3} /></label>
          <button type="submit" className="btn">Post to portal</button>
        </SafeForm>
      </Card>
    </div>
  </div>
}

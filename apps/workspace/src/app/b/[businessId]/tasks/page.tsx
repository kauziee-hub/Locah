import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry, businessHeaders } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { addChecklistItem, checkChecklistItem, completeTask, createChecklistTemplate, createTask, spawnChecklist } from './actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Task = {
  id: string
  title: string
  description: string | null
  status: string
  priority: string
  due_at: string | null
  assignee_member_id: string | null
  related_type: string
  checklist?: { id: string; label: string; required: boolean; done: boolean; photo_required: boolean }[]
}
type Member = { id: string; display_name: string }
type Location = { id: string; name: string }

const VIEWS: { key: string; label: string }[] = [
  { key: 'mine', label: 'My tasks' },
  { key: 'due_today', label: 'Due today' },
  { key: 'overdue', label: 'Overdue' },
  { key: 'unassigned', label: 'Unassigned' },
  { key: 'open', label: 'Open' },
  { key: 'completed', label: 'Completed' },
]

export default async function TasksPage({ params, searchParams }: {
  params: { businessId: string }
  searchParams?: { view?: string; task?: string }
}) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const view = VIEWS.some((item) => item.key === searchParams?.view) ? searchParams?.view : 'open'
  const [listRes, context, peopleRes, locRes] = await Promise.all([
    apiTry<{ data: { tasks: Task[] } }>(`/v1/platform/businesses/${b}/tasks?view=${view}`, token),
    apiTry<{ data: { permissions: string[] } }>('/v1/me/context', token, businessHeaders(b)),
    apiTry<{ data: Member[] }>(`/v1/platform/businesses/${b}/workforce/members`, token),
    apiTry<{ data: Location[] }>(`/v1/platform/businesses/${b}/locations`, token),
  ])
  const header = <PageHeader title="Tasks" subtitle="One list for housekeeping, prep, follow-ups and checklists. A task points at a booking, order, project or licence — it does not become a separate list for each." />
  if (!listRes.ok) return <div className="bos-page">{header}<GateNotice error={listRes.error} businessId={b} moduleLabel="Tasks" /></div>
  const tasks = listRes.data.data.tasks
  const perms = context.ok ? context.data.data.permissions : []
  const canManage = perms.includes('tasks.manage')
  const canComplete = perms.includes('tasks.complete')
  const people = peopleRes.ok ? peopleRes.data.data : []
  const locations = locRes.ok ? locRes.data.data : []
  const selectedId = searchParams?.task
  const detail = selectedId
    ? await apiTry<{ data: Task }>(`/v1/platform/businesses/${b}/tasks/${selectedId}`, token)
    : null
  const selected = detail?.ok ? detail.data.data : null
  return (
    <div className="bos-page bos-tasks">
      {header}
      <nav className="bos-compliance__tabs" aria-label="Task views">
        {VIEWS.map((item) => (
          <Link key={item.key} href={`/b/${b}/tasks?view=${item.key}`} aria-current={item.key === view ? 'page' : undefined}>{item.label}</Link>
        ))}
      </nav>
      {tasks.length ? (
        <ul className="bos-tasks__list">
          {tasks.map((task) => (
            <li key={task.id}>
              <Link href={`/b/${b}/tasks?view=${view}&task=${task.id}`}>{task.title}</Link>
              <span className="bos-hint"> {task.status.replace('_', ' ')} · {task.priority}{task.due_at ? ` · due ${new Date(task.due_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}` : ''}</span>
            </li>
          ))}
        </ul>
      ) : <p className="bos-empty">Nothing in this view.</p>}
      {selected ? (
        <section className="bos-compliance__detail" aria-labelledby="task-detail">
          <h2 id="task-detail">{selected.title}</h2>
          {selected.description ? <p>{selected.description}</p> : null}
          <p className="bos-hint">Linked to {selected.related_type.replace('_', ' ')}</p>
          {selected.checklist?.length ? (
            <ul>
              {selected.checklist.map((item) => (
                <li key={item.id}>
                  {canComplete && selected.status !== 'completed' && selected.status !== 'cancelled' ? (
                    <SafeForm action={checkChecklistItem}>
                      <input type="hidden" name="businessId" value={b} />
                      <input type="hidden" name="taskId" value={selected.id} />
                      <input type="hidden" name="itemId" value={item.id} />
                      <input type="hidden" name="done" value={item.done ? '0' : '1'} />
                      <button className="btn-ghost" type="submit">{item.done ? 'Undo' : 'Mark done'}</button>
                      {' '}{item.label}{item.required ? '' : ' (optional)'}{item.photo_required ? ' · photo' : ''}
                    </SafeForm>
                  ) : <span>{item.done ? 'Done' : 'Open'} · {item.label}</span>}
                </li>
              ))}
            </ul>
          ) : <p className="bos-hint">No checklist on this task.</p>}
          {canManage && selected.status !== 'completed' && selected.status !== 'cancelled' ? (
            <SafeForm action={addChecklistItem} className="bos-queue__issue">
              <input type="hidden" name="businessId" value={b} />
              <input type="hidden" name="taskId" value={selected.id} />
              <label>Checklist step<input name="label" required maxLength={200} /></label>
              <label className="bos-compliance__check"><input type="checkbox" name="required" defaultChecked /> Required</label>
              <button className="btn-ghost" type="submit">Add step</button>
            </SafeForm>
          ) : null}
          {canComplete && (selected.status === 'open' || selected.status === 'in_progress') ? (
            <SafeForm action={completeTask}>
              <input type="hidden" name="businessId" value={b} />
              <input type="hidden" name="taskId" value={selected.id} />
              <button className="btn" type="submit">Complete task</button>
            </SafeForm>
          ) : null}
        </section>
      ) : null}
      {canManage ? (
        <section className="bos-compliance__detail" aria-labelledby="new-task">
          <h2 id="new-task">New task</h2>
          <SafeForm action={createTask} className="bos-compliance__form">
            <input type="hidden" name="businessId" value={b} />
            <label>Title<input name="title" required maxLength={160} /></label>
            <label>Details<textarea name="description" maxLength={4000} /></label>
            <label>Priority<select name="priority" defaultValue="normal"><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
            <label>Due<input type="datetime-local" name="dueAt" /></label>
            <label>Related to<select name="relatedType"><option value="business">This business</option><option value="customer">Customer</option><option value="booking">Booking</option><option value="order">Order</option><option value="project">Project</option><option value="compliance_item">Licence or filing</option><option value="location">Location</option><option value="staff_assignment">Staff</option><option value="job">Job</option></select></label>
            <label>Related id<input name="relatedId" placeholder="Leave empty for this business" /></label>
            <label>Location<select name="locationId"><option value="">Whole business</option>{locations.map((loc) => <option key={loc.id} value={loc.id}>{loc.name}</option>)}</select></label>
            <label>Assign<select name="assigneeId"><option value="">Unassigned</option>{people.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></label>
            <button className="btn" type="submit">Add task</button>
          </SafeForm>
          <h2>Repeatable checklist</h2>
          <SafeForm action={createChecklistTemplate} className="bos-compliance__form">
            <input type="hidden" name="businessId" value={b} />
            <label>Name<input name="name" required maxLength={120} placeholder="Opening" /></label>
            <label>Kind<select name="kind"><option value="opening">Opening</option><option value="closing">Closing</option><option value="handover">Handover</option><option value="prep">Prep</option><option value="custom">Custom</option></select></label>
            <label>Steps, one per line<textarea name="items" required placeholder={'Unlock\nCount the till'} /></label>
            <button className="btn" type="submit">Save checklist</button>
          </SafeForm>
          <SafeForm action={spawnChecklist} className="bos-queue__issue">
            <input type="hidden" name="businessId" value={b} />
            <label>Checklist id<input name="templateId" required /></label>
            <label>For this occurrence<input name="occurrenceKey" required placeholder="2026-09-29-opening" /></label>
            <button className="btn-ghost" type="submit">Start this list</button>
          </SafeForm>
        </section>
      ) : null}
    </div>
  )
}

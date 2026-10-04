import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { Card, EmptyState, GateNotice, PageHeader, StatusPill } from '@/components/ui'
import { StageTrack, type StageWhere } from '@/components/StageTrack'
import {
  addPhase,
  assignPhase,
  addTask,
  changeProjectStatus,
  updatePhase,
  updateTask,
} from '../actions'
import { createJob } from '../../jobs/actions'
import {
  dayLabel,
  daysUntil,
  money,
  NEXT_STATUSES,
  PHASE_STATUS_LABEL,
  PRIORITY_LABEL,
  statusLabel,
  STATUS_ACTION_LABEL,
  STATUS_TONE,
  TASK_STATUS_LABEL,
  TASK_STATUS_TONE,
  type ProjectPhase,
  type ProjectRow,
  type ProjectSemantics,
  type ProjectTask,
} from '../shared'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Customer = { id: string; display_name: string }
type Member = { id: string; display_name: string; status?: string | null }
type RelatedJob = { id: string; reference: string; title: string; status: string }

/**
 * One project, as a place to work rather than a record to read.
 *
 * The phases are the plan and the tasks are the work, so both are editable in
 * place: a status is a select that submits, an assignee is a select that
 * submits. Nothing here opens a modal to change one field.
 */
export default async function ProjectDetailPage({
  params,
}: {
  params: { businessId: string; projectId: string }
}) {
  const token = await getAccessToken()
  if (!token) {
    redirect(
      `/login?destination=${encodeURIComponent(
        `/b/${params.businessId}/projects/${params.projectId}`
      )}`
    )
  }

  const base = `/b/${params.businessId}/projects`
  const res = await apiTry<{ data: ProjectRow }>(
    `/v1/platform/businesses/${params.businessId}/projects/${params.projectId}`,
    token
  )
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Project" breadcrumb={<Link href={base}>← Projects</Link>} />
        <GateNotice
          error={res.error}
          businessId={params.businessId}
          moduleLabel="Projects & Work Orders"
        />
      </div>
    )
  }

  const project = res.data.data
  const open = project.is_open

  const [listRes, customersRes, membersRes, stageRes, jobsRes] = await Promise.all([
    // The list carries the business's vocabulary; the detail page borrows it
    // rather than the API repeating it on every read.
    apiTry<{ data: { semantics: ProjectSemantics } }>(
      `/v1/platform/businesses/${params.businessId}/projects?limit=1`,
      token
    ),
    apiTry<{ data: Customer[] }>(
      `/v1/platform/businesses/${params.businessId}/customers`,
      token
    ),
    apiTry<{ data: Member[] }>(
      `/v1/platform/businesses/${params.businessId}/workforce/members`,
      token
    ),
    apiTry<{ data: StageWhere }>(`/v1/b/${params.businessId}/stages/projects/${params.projectId}`, token),
    apiTry<{ data: RelatedJob[] }>(`/v1/b/${params.businessId}/jobs?project_id=${params.projectId}`, token),
  ])

  const semantics = listRes.ok
    ? listRes.data.data.semantics
    : { noun: 'Project', noun_plural: 'Projects', default_phases: [], typical: false }
  const customers = customersRes.ok ? customersRes.data.data || [] : []
  const members = (membersRes.ok ? membersRes.data.data || [] : []).filter(
    (m) => m.status !== 'inactive'
  )
  const memberName = new Map(members.map((m) => [m.id, m.display_name]))
  const customer = project.customer_contact_id
    ? customers.find((c) => c.id === project.customer_contact_id)
    : undefined

  const phases = project.phases || []
  const tasks = project.tasks || []

  return (
    <div>
      <PageHeader
        title={project.reference}
        subtitle={project.title}
        breadcrumb={<Link href={base}>← {semantics.noun_plural}</Link>}
        actions={<StatusPill value={statusLabel(project.status)} tone={STATUS_TONE[project.status]} />}
      />

      <Overview project={project} customerName={customer?.display_name} memberName={memberName} />

      <Lifecycle businessId={params.businessId} project={project} />

      {stageRes.ok && stageRes.data.data.has_steps ? (
        <Card style={{ marginTop: '1.25rem', display: 'grid', gap: '0.75rem' }}>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Steps</h2>
          <StageTrack businessId={params.businessId} entity="projects" recordId={params.projectId}
            where={stageRes.data.data} />
        </Card>
      ) : null}

      <Phases
        businessId={params.businessId}
        project={project}
        phases={phases}
        tasks={tasks}
        members={members}
        memberName={memberName}
        open={open}
      />
      {jobsRes.ok ? <Card style={{ marginTop: '1.25rem' }}>
        <h2 style={{ marginTop: 0 }}>Jobs in this project</h2>
        {jobsRes.data.data.length ? <ul>{jobsRes.data.data.map((job) => <li key={job.id}>
          <Link href={`/b/${params.businessId}/jobs/${job.id}`}>{job.reference} · {job.title}</Link> · {job.status.replaceAll('_', ' ')}
        </li>)}</ul> : <p>No executable jobs linked yet. Keep the project for the overall commitment; create a job card when work needs a technician or parts.</p>}
        <Link href={`/b/${params.businessId}/jobs`}>Open job cards</Link>
        {open && project.customer_contact_id ? (
          <SafeForm action={createJob} style={{ display: 'grid', gap: '0.6rem', marginTop: '0.8rem', maxWidth: '28rem' }}>
            <input type="hidden" name="businessId" value={params.businessId} />
            <input type="hidden" name="customer_contact_id" value={project.customer_contact_id} />
            <input type="hidden" name="project_id" value={project.id} />
            <input type="hidden" name="location_id" value={project.location_id || ''} />
            <label>Work for this project<input name="title" required maxLength={200} placeholder="Site visit, install, or repair" /></label>
            <label>What needs doing<textarea name="problem" rows={2} /></label>
            <button type="submit" className="btn">Start a job card</button>
          </SafeForm>
        ) : null}
      </Card> : null}

      <Tasks
        businessId={params.businessId}
        project={project}
        phases={phases}
        tasks={tasks}
        members={members}
        memberName={memberName}
        open={open}
      />

      {project.source_quote_id ? (
        <p style={{ marginTop: '1.25rem', color: 'var(--color-muted)' }}>
          Created from{' '}
          <Link href={`/b/${params.businessId}/quotes/${project.source_quote_id}`}>
            the accepted quote
          </Link>
          .
        </p>
      ) : null}
    </div>
  )
}

/* ----------------------------------------------------------------- overview */

function Overview({
  project,
  customerName,
  memberName,
}: {
  project: ProjectRow
  customerName?: string
  memberName: Map<string, string>
}) {
  const days = daysUntil(project.due_on)
  const late = project.is_open && days !== null && days < 0
  const percent = project.progress_percent

  const facts: [string, React.ReactNode][] = [
    ['Customer', customerName || (project.customer_contact_id ? 'Customer' : 'Not set')],
    [
      'Lead',
      project.lead_member_id ? memberName.get(project.lead_member_id) || 'Assigned' : 'Not set',
    ],
    ['Priority', PRIORITY_LABEL[project.priority] ?? project.priority],
    ['Starts', dayLabel(project.starts_on)],
    [
      'Due',
      project.due_on ? (
        <span style={{ color: late ? 'var(--status-bad-fg, #b3261e)' : undefined }}>
          {dayLabel(project.due_on)}
          {project.is_open && days !== null
            ? ` (${days < 0 ? `${Math.abs(days)} days late` : days === 0 ? 'today' : `in ${days} days`})`
            : ''}
        </span>
      ) : (
        'No date'
      ),
    ],
  ]

  return (
    <Card style={{ display: 'grid', gap: '1rem' }}>
      <div
        style={{
          display: 'flex',
          gap: '1.5rem',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
        }}
      >
        <dl
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(9rem, 1fr))',
            gap: '0.9rem',
            margin: 0,
            flex: '1 1 26rem',
          }}
        >
          {facts.map(([label, value]) => (
            <div key={label}>
              <dt style={{ fontSize: '0.82rem', color: 'var(--color-muted)' }}>{label}</dt>
              <dd style={{ margin: '0.15rem 0 0' }}>{value}</dd>
            </div>
          ))}
        </dl>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '0.82rem', color: 'var(--color-muted)' }}>Progress</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 650, fontVariantNumeric: 'tabular-nums' }}>
            {percent === null || percent === undefined ? '—' : `${percent}%`}
          </div>
          {project.agreed_value ? (
            <div style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>
              {money(project.agreed_value, project.currency)} agreed
            </div>
          ) : null}
        </div>
      </div>
      {project.summary ? (
        <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{project.summary}</p>
      ) : null}
      {project.on_hold_reason ? (
        <p style={{ margin: 0, color: 'var(--color-muted)' }}>
          On hold: {project.on_hold_reason}
        </p>
      ) : null}
      {project.cancellation_reason ? (
        <p style={{ margin: 0, color: 'var(--color-muted)' }}>
          Cancelled: {project.cancellation_reason}
        </p>
      ) : null}
    </Card>
  )
}

/* ---------------------------------------------------------------- lifecycle */

function Lifecycle({ businessId, project }: { businessId: string; project: ProjectRow }) {
  const next = NEXT_STATUSES[project.status] || []
  if (next.length === 0) return null
  return (
    <Card style={{ marginTop: '1.25rem', display: 'grid', gap: '0.75rem' }}>
      <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Where this stands</h2>
      <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {next.map((status) => (
          <SafeForm key={status} action={changeProjectStatus} style={{ display: 'flex', gap: '0.4rem' }}>
            <input type="hidden" name="businessId" value={businessId} />
            <input type="hidden" name="projectId" value={project.id} />
            <input type="hidden" name="status" value={status} />
            {status === 'on_hold' || status === 'cancelled' ? (
              <input name="reason" placeholder="Reason (optional)" style={{ width: '12rem' }} />
            ) : null}
            <button
              type="submit"
              className={status === 'cancelled' ? 'btn btn-danger' : status === 'completed' ? 'btn' : 'btn btn-ghost'}
            >
              {STATUS_ACTION_LABEL[status] ?? status}
            </button>
          </SafeForm>
        ))}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ phases */

function Phases({
  businessId,
  project,
  phases,
  tasks,
  members,
  memberName,
  open,
}: {
  businessId: string
  project: ProjectRow
  phases: ProjectPhase[]
  tasks: ProjectTask[]
  members: Member[]
  memberName: Map<string, string>
  open: boolean
}) {
  return (
    <Card style={{ marginTop: '1.5rem', display: 'grid', gap: '0.9rem' }}>
      <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Work phases & milestones</h2>

      {phases.length === 0 ? (
        <p style={{ color: 'var(--color-muted)', margin: 0 }}>
          No stages. This one is a flat list of tasks, which is fine for a single visit.
        </p>
      ) : (
        <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
          {phases.map((phase) => {
            const inPhase = tasks.filter((t) => t.phase_id === phase.id && t.status !== 'cancelled')
            const done = inPhase.filter((t) => t.status === 'done').length
            return (
              <li
                key={phase.id}
                style={{
                  display: 'flex',
                  gap: '0.75rem',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  padding: '0.7rem 0.9rem',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius)',
                  background: phase.status === 'done' ? 'var(--status-good-bg, transparent)' : undefined,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <strong>{phase.name}</strong>
                  {phase.is_milestone ? (
                    <span style={{ marginLeft: '0.5rem', fontSize: '0.78rem', color: 'var(--color-muted)' }}>
                      milestone
                    </span>
                  ) : null}
                  <span style={{ display: 'block', fontSize: '0.84rem', color: 'var(--color-muted)' }}>
                    {inPhase.length > 0 ? `${done}/${inPhase.length} tasks` : 'No tasks yet'}
                    {phase.due_on ? ` · due ${dayLabel(phase.due_on)}` : ''}
                    {phase.responsible_member_id ? ` · ${memberName.get(phase.responsible_member_id) || 'Responsible person'}` : ''}
                  </span>
                  {phase.completion_note ? <span style={{ display: 'block', fontSize: '0.84rem' }}>{phase.completion_note}</span> : null}
                  {phase.invoice_id ? <span style={{ display: 'block', fontSize: '0.84rem' }}>Linked invoice {phase.invoice_id.slice(0, 8)}…</span> : null}
                </div>
                {open ? (
                  <SafeForm action={updatePhase} style={{ display: 'flex', gap: '0.4rem' }}>
                    <input type="hidden" name="businessId" value={businessId} />
                    <input type="hidden" name="projectId" value={project.id} />
                    <input type="hidden" name="phaseId" value={phase.id} />
                    <select name="status" defaultValue={phase.status} aria-label={`${phase.name} status`}>
                      {Object.entries(PHASE_STATUS_LABEL).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <button type="submit" className="btn btn-ghost">
                      Save
                    </button>
                  </SafeForm>
                ) : (
                  <span style={{ color: 'var(--color-muted)' }}>
                    {PHASE_STATUS_LABEL[phase.status] ?? phase.status}
                  </span>
                )}
                {open && phase.is_milestone ? <SafeForm action={assignPhase} style={{ display: 'flex', gap: '0.4rem' }}>
                  <input type="hidden" name="businessId" value={businessId} />
                  <input type="hidden" name="projectId" value={project.id} />
                  <input type="hidden" name="phaseId" value={phase.id} />
                  <select name="responsible_member_id" defaultValue={phase.responsible_member_id || ''} aria-label={`${phase.name} responsible person`}>
                    <option value="">No owner</option>
                    {members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}
                  </select>
                  <button type="submit" className="btn btn-ghost">Assign</button>
                </SafeForm> : null}
              </li>
            )
          })}
        </ol>
      )}

      {open ? (
        <SafeForm
          resetOnSuccess
          action={addPhase}
          style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}
        >
          <input type="hidden" name="businessId" value={businessId} />
          <input type="hidden" name="projectId" value={project.id} />
          <input name="name" placeholder="Add a stage" required maxLength={120} style={{ flex: '1 1 14rem' }} />
          <input type="date" name="due_on" aria-label="Stage due date" />
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.85rem' }}>
            <input type="checkbox" name="is_milestone" />
            Milestone
          </label>
          <button type="submit" className="btn btn-ghost">
            Add stage
          </button>
        </SafeForm>
      ) : null}
    </Card>
  )
}

/* ------------------------------------------------------------------- tasks */

function Tasks({
  businessId,
  project,
  phases,
  tasks,
  members,
  memberName,
  open,
}: {
  businessId: string
  project: ProjectRow
  phases: ProjectPhase[]
  tasks: ProjectTask[]
  members: Member[]
  memberName: Map<string, string>
  open: boolean
}) {
  return (
    <Card style={{ marginTop: '1.5rem', display: 'grid', gap: '0.9rem' }}>
      <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Tasks</h2>

      {tasks.length === 0 ? (
        <EmptyState title="Nothing planned yet">
          Add the work as tasks. Progress is counted from them, so there is nothing else to keep
          up to date.
        </EmptyState>
      ) : (
        <div className="ws-tablewrap">
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Stage</th>
                <th>Who</th>
                <th>Due</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id}>
                  <td>
                    {task.title}
                    {task.description ? (
                      <span style={{ display: 'block', color: 'var(--color-muted)', fontSize: '0.85rem' }}>
                        {task.description}
                      </span>
                    ) : null}
                    {task.blocked_reason ? (
                      <span style={{ display: 'block', color: 'var(--status-bad-fg, #b3261e)', fontSize: '0.85rem' }}>
                        Blocked: {task.blocked_reason}
                      </span>
                    ) : null}
                  </td>
                  <td>
                    {task.phase_id
                      ? phases.find((p) => p.id === task.phase_id)?.name || '—'
                      : '—'}
                  </td>
                  <td>
                    {open ? (
                      <SafeForm action={updateTask} style={{ display: 'flex', gap: '0.35rem' }}>
                        <input type="hidden" name="businessId" value={businessId} />
                        <input type="hidden" name="projectId" value={project.id} />
                        <input type="hidden" name="taskId" value={task.id} />
                        <input type="hidden" name="version" value={task.version} />
                        <select
                          name="assignee_member_id"
                          defaultValue={task.assignee_member_id || ''}
                          aria-label={`Who is doing ${task.title}`}
                        >
                          <option value="">Unassigned</option>
                          {members.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.display_name}
                            </option>
                          ))}
                        </select>
                        <button type="submit" className="btn btn-ghost">
                          Set
                        </button>
                      </SafeForm>
                    ) : task.assignee_member_id ? (
                      memberName.get(task.assignee_member_id) || 'Assigned'
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>{dayLabel(task.due_on)}</td>
                  <td>
                    {open ? (
                      <SafeForm action={updateTask} style={{ display: 'flex', gap: '0.35rem' }}>
                        <input type="hidden" name="businessId" value={businessId} />
                        <input type="hidden" name="projectId" value={project.id} />
                        <input type="hidden" name="taskId" value={task.id} />
                        <input type="hidden" name="version" value={task.version} />
                        <select name="status" defaultValue={task.status} aria-label={`${task.title} status`}>
                          {Object.entries(TASK_STATUS_LABEL).map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                        <button type="submit" className="btn btn-ghost">
                          Save
                        </button>
                      </SafeForm>
                    ) : (
                      <StatusPill
                        value={TASK_STATUS_LABEL[task.status] ?? task.status}
                        tone={TASK_STATUS_TONE[task.status]}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open ? (
        <SafeForm
          resetOnSuccess
          action={addTask}
          style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}
        >
          <input type="hidden" name="businessId" value={businessId} />
          <input type="hidden" name="projectId" value={project.id} />
          <input name="title" placeholder="Add a task" required maxLength={200} style={{ flex: '1 1 14rem' }} />
          {phases.length > 0 ? (
            <select name="phase_id" aria-label="Stage" defaultValue="">
              <option value="">No stage</option>
              {phases.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          ) : null}
          <select name="assignee_member_id" aria-label="Assign to" defaultValue="">
            <option value="">Unassigned</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name}
              </option>
            ))}
          </select>
          <input type="date" name="due_on" aria-label="Task due date" />
          <button type="submit" className="btn btn-ghost">
            Add task
          </button>
        </SafeForm>
      ) : null}
    </Card>
  )
}

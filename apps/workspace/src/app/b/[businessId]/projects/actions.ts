'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { sendJson, type ActionResult } from '@/lib/server-send'

/**
 * Every write goes to the projects API as it stands.
 *
 * Nothing here decides whether a status change is legal, what a project's
 * progress is, or whether a person may be assigned to it. Those are the
 * service's rules, and a second copy of them in the Workspace would be a second
 * opinion about the state of real work.
 */
async function send<T = unknown>(path: string, method: string, body?: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(path, method, body)
}

function optional(form: FormData, field: string): string | undefined {
  const value = form.get(field)
  const text = value === null ? '' : String(value).trim()
  return text ? text : undefined
}

function refresh(businessId: string, projectId?: string): void {
  revalidatePath(`/b/${businessId}/projects`)
  if (projectId) revalidatePath(`/b/${businessId}/projects/${projectId}`)
}

export async function createProject(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  // An empty phase list is a real choice — a single-visit job has no stages —
  // so it is only sent when the person actually edited the field. Leaving it
  // out is what asks the API to seed from the business type.
  const phasesRaw = formData.get('phases')
  const phases =
    phasesRaw === null
      ? undefined
      : String(phasesRaw)
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean)

  const created = await send<{ id?: string }>(`/v1/platform/businesses/${businessId}/projects`, 'POST', {
    title: String(formData.get('title') || '').trim(),
    summary: optional(formData, 'summary'),
    internal_notes: optional(formData, 'internal_notes'),
    customer_contact_id: optional(formData, 'customer_contact_id'),
    lead_member_id: optional(formData, 'lead_member_id'),
    priority: optional(formData, 'priority') ?? 'normal',
    starts_on: optional(formData, 'starts_on'),
    due_on: optional(formData, 'due_on'),
    ...(phases === undefined ? {} : { phases }),
  })
  if (!created.ok) return created
  const projectId = created.data?.id
  refresh(businessId, projectId)
  redirect(
    projectId
      ? `/b/${businessId}/projects/${projectId}`
      : `/b/${businessId}/projects`
  )
  return { ok: true }
}

export async function updateProject(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const projectId = String(formData.get('projectId'))
  const version = Number(formData.get('version'))
  const r = await send(`/v1/platform/businesses/${businessId}/projects/${projectId}`, 'PATCH', {
    title: String(formData.get('title') || '').trim(),
    summary: optional(formData, 'summary') ?? null,
    internal_notes: optional(formData, 'internal_notes') ?? null,
    customer_contact_id: optional(formData, 'customer_contact_id') ?? null,
    lead_member_id: optional(formData, 'lead_member_id') ?? null,
    priority: optional(formData, 'priority') ?? 'normal',
    starts_on: optional(formData, 'starts_on') ?? null,
    due_on: optional(formData, 'due_on') ?? null,
    ...(Number.isFinite(version) && version >= 1 ? { version } : {}),
  })
  if (!r.ok) return r
  refresh(businessId, projectId)
  return { ok: true }
}

export async function changeProjectStatus(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const projectId = String(formData.get('projectId'))
  const r = await send(`/v1/platform/businesses/${businessId}/projects/${projectId}/status`, 'POST', {
    status: String(formData.get('status')),
    reason: optional(formData, 'reason'),
  })
  if (!r.ok) return r
  refresh(businessId, projectId)
  return { ok: true }
}

export async function addPhase(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const projectId = String(formData.get('projectId'))
  const r = await send(`/v1/platform/businesses/${businessId}/projects/${projectId}/phases`, 'POST', {
    name: String(formData.get('name') || '').trim(),
    due_on: optional(formData, 'due_on'),
    is_milestone: formData.get('is_milestone') === 'on',
  })
  if (!r.ok) return r
  refresh(businessId, projectId)
  return { ok: true }
}

export async function updatePhase(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const projectId = String(formData.get('projectId'))
  const phaseId = String(formData.get('phaseId'))
  const r = await send(
    `/v1/platform/businesses/${businessId}/projects/${projectId}/phases/${phaseId}`,
    'PATCH',
    {
      status: String(formData.get('status')),
      ...(formData.has('completion_note') ? { completion_note: optional(formData, 'completion_note') } : {}),
    }
  )
  if (!r.ok) return r
  refresh(businessId, projectId)
  return { ok: true }
}

export async function assignPhase(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const projectId = String(formData.get('projectId'))
  const phaseId = String(formData.get('phaseId'))
  const r = await send(`/v1/platform/businesses/${businessId}/projects/${projectId}/phases/${phaseId}/assign`, 'POST', {
    responsible_member_id: optional(formData, 'responsible_member_id'),
  })
  if (!r.ok) return r
  refresh(businessId, projectId)
  return { ok: true }
}

export async function addTask(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const projectId = String(formData.get('projectId'))
  const r = await send(`/v1/platform/businesses/${businessId}/projects/${projectId}/tasks`, 'POST', {
    title: String(formData.get('title') || '').trim(),
    description: optional(formData, 'description'),
    phase_id: optional(formData, 'phase_id'),
    assignee_member_id: optional(formData, 'assignee_member_id'),
    due_on: optional(formData, 'due_on'),
  })
  if (!r.ok) return r
  refresh(businessId, projectId)
  return { ok: true }
}

export async function updateTask(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const projectId = String(formData.get('projectId'))
  const taskId = String(formData.get('taskId'))
  const version = Number(formData.get('version'))

  // Each control on a task row submits only what it changes, so an unrelated
  // field is never blanked by a form that did not ask about it.
  const body: Record<string, unknown> = {}
  if (formData.has('status')) body.status = String(formData.get('status'))
  if (formData.has('assignee_member_id')) {
    body.assignee_member_id = optional(formData, 'assignee_member_id') ?? null
  }
  if (formData.has('blocked_reason')) body.blocked_reason = optional(formData, 'blocked_reason')
  if (Number.isFinite(version) && version >= 1) body.version = version

  const r = await send(
    `/v1/platform/businesses/${businessId}/projects/${projectId}/tasks/${taskId}`,
    'PATCH',
    body
  )

  if (!r.ok) return r
  refresh(businessId, projectId)
  return { ok: true }
}

export async function convertQuoteToProject(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const quoteId = String(formData.get('quoteId'))
  const created = await send<{ id?: string }>(
    `/v1/platform/businesses/${businessId}/quotes/${quoteId}/convert-to-project`,
    'POST',
    {}
  )
  if (!created.ok) return created
  const projectId = created.data?.id
  refresh(businessId, projectId)
  revalidatePath(`/b/${businessId}/quotes/${quoteId}`)
  if (projectId) redirect(`/b/${businessId}/projects/${projectId}`)
  return { ok: true }
}

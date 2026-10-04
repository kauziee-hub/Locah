'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send(businessId: string, path: string, body?: unknown): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}/tasks${path}`, 'POST', body)
  if (r.ok) revalidatePath(`/b/${businessId}/tasks`)
  return r
}

export async function createTask(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const due = String(form.get('dueAt') || '').trim()
  const assignee = String(form.get('assigneeId') || '').trim()
  const location = String(form.get('locationId') || '').trim()
  const related = String(form.get('relatedId') || '').trim()
  const relatedType = String(form.get('relatedType') || 'business')
  const r = await send(businessId, '', {
    title: String(form.get('title')),
    description: String(form.get('description') || '') || null,
    priority: String(form.get('priority') || 'normal'),
    due_at: due ? `${due.length === 16 ? due : due.slice(0, 16)}:00+05:30` : null,
    assignee_member_id: assignee || null,
    location_id: location || null,
    related_type: relatedType,
    related_id: relatedType === 'business' ? businessId : related,
  })
  if (!r.ok) return r
  return { ok: true }
}

export async function addChecklistItem(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const taskId = String(form.get('taskId'))
  const r = await send(businessId, `/${taskId}/items`, {
    label: String(form.get('label')),
    required: form.get('required') === 'on',
    photo_required: form.get('photoRequired') === 'on',
  })
  if (!r.ok) return r
  return { ok: true }
}

export async function checkChecklistItem(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const taskId = String(form.get('taskId'))
  const itemId = String(form.get('itemId'))
  const r = await send(businessId, `/${taskId}/items/${itemId}/check`, { done: form.get('done') !== '0' })
  if (!r.ok) return r
  return { ok: true }
}

export async function completeTask(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const r = await send(businessId, `/${String(form.get('taskId'))}/complete`, {})
  if (!r.ok) return r
  return { ok: true }
}

export async function spawnChecklist(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const templateId = String(form.get('templateId'))
  const r = await send(businessId, `/templates/${templateId}/spawn`, {
    occurrence_key: String(form.get('occurrenceKey')),
  })
  if (!r.ok) return r
  return { ok: true }
}

export async function createChecklistTemplate(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const labels = String(form.get('items') || '').split('\n').map((line) => line.trim()).filter(Boolean)
  const r = await send(businessId, '/templates', {
    name: String(form.get('name')),
    kind: String(form.get('kind') || 'custom'),
    items: labels.map((label) => ({ label, required: true, photo_required: false })),
  })
  if (!r.ok) return r
  return { ok: true }
}

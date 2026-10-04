'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function send<T = unknown>(businessId: string, path: string, body: unknown): Promise<ActionResult<T>> {
  return sendJson<T>(`/v1/b/${businessId}/jobs${path}`, 'POST', body)
}

function optional(form: FormData, key: string) {
  return String(form.get(key) || '').trim() || null
}

export async function createJob(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const result = await send<{ id: string }>(businessId, '', {
    customer_contact_id: String(form.get('customer_contact_id')),
    title: String(form.get('title') || '').trim(),
    problem: optional(form, 'problem'),
    project_id: optional(form, 'project_id'),
    location_id: optional(form, 'location_id'),
    assigned_member_id: optional(form, 'assigned_member_id'),
    scheduled_at: optional(form, 'scheduled_at') ? new Date(`${String(form.get('scheduled_at'))}:00+05:30`).toISOString() : null,
    asset_description: optional(form, 'asset_description'),
    asset_serial: optional(form, 'asset_serial'),
    priority: String(form.get('priority') || 'normal'),
  })
  if (!result.ok) return result
  revalidatePath(`/b/${businessId}/jobs`)
  redirect(`/b/${businessId}/jobs/${result.data?.id ?? ''}`)
}

export async function assignJob(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const jobId = String(form.get('jobId'))
  const r = await send(businessId, `/${jobId}/assign`, { member_id: String(form.get('member_id')) })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/jobs/${jobId}`)
  return { ok: true }
}

export async function moveJob(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const jobId = String(form.get('jobId'))
  const r = await send(businessId, `/${jobId}/move`, {
    status: String(form.get('status')), version: Number(form.get('version')),
    work_performed: optional(form, 'work_performed'),
    completion_note: optional(form, 'completion_note'),
    approval_note: optional(form, 'approval_note'),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/jobs`)
  revalidatePath(`/b/${businessId}/jobs/${jobId}`)
  return { ok: true }
}

export async function consumePart(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const jobId = String(form.get('jobId'))
  const r = await send(businessId, `/${jobId}/parts`, {
    inventory_record_id: String(form.get('inventory_record_id')),
    quantity: Number(form.get('quantity')),
    serials: String(form.get('serials') || '').split(/[\n,]/).map((v) => v.trim()).filter(Boolean),
    idempotency_key: String(form.get('idempotency_key')),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/jobs/${jobId}`)
  return { ok: true }
}

export async function returnPart(form: FormData): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const jobId = String(form.get('jobId'))
  const r = await send(businessId, `/${jobId}/parts/${String(form.get('partId'))}/return`, {
    quantity: Number(form.get('quantity')),
    idempotency_key: String(form.get('idempotency_key')),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/jobs/${jobId}`)
  return { ok: true }
}

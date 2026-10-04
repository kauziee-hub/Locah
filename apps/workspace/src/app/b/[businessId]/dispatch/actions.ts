'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function post(path: string, body: Record<string, unknown>): Promise<ActionResult> {
  return sendJson(path, 'POST', body)
}

export async function createDispatchJob(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const dropoffLine = String(formData.get('dropoff') || '').trim()
  const r = await post(`/v1/b/${businessId}/dispatch/jobs`, {
    order_id: String(formData.get('orderId')),
    kind: String(formData.get('kind') || 'delivery'),
    planned_at: String(formData.get('plannedAt') || '') || null,
    dropoff: dropoffLine ? { line: dropoffLine } : null,
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/dispatch`)
  return { ok: true }
}

export async function assignDispatchJob(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const jobId = String(formData.get('jobId'))
  const r = await post(`/v1/b/${businessId}/dispatch/jobs/${jobId}/assign`, {
    member_id: String(formData.get('memberId')),
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/dispatch`)
  revalidatePath(`/b/${businessId}/dispatch/${jobId}`)
  revalidatePath(`/b/${businessId}/crew`)
  return { ok: true }
}

export async function advanceDispatchJob(formData: FormData): Promise<ActionResult> {
  const businessId = String(formData.get('businessId'))
  const jobId = String(formData.get('jobId'))
  const r = await post(`/v1/b/${businessId}/dispatch/jobs/${jobId}/status`, {
    status: String(formData.get('status')),
    proof_note: String(formData.get('proof') || '') || null,
    reason: String(formData.get('reason') || '') || null,
  })
  if (!r.ok) return r
  revalidatePath(`/b/${businessId}/dispatch`)
  revalidatePath(`/b/${businessId}/dispatch/${jobId}`)
  revalidatePath(`/b/${businessId}/crew`)
  return { ok: true }
}

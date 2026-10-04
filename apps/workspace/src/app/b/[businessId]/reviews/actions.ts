'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

async function act(form: FormData, suffix: string, method: string, body: unknown): Promise<ActionResult> {
  const businessId = String(form.get('businessId'))
  const reviewId = String(form.get('reviewId'))
  const r = await sendJson(`/v1/platform/businesses/${businessId}/reviews/${reviewId}/${suffix}`, method, body)
  if (r.ok) revalidatePath(`/b/${businessId}/reviews`)
  return r
}

export async function replyReview(form: FormData): Promise<ActionResult> {
  const r = await act(form, 'reply', 'PUT', { body: String(form.get('body') || '').trim() || null })

  if (!r.ok) return r
  return { ok: true }
}

export async function featureReview(form: FormData): Promise<ActionResult> {
  const r = await act(form, 'feature', 'PUT', { featured: form.get('featured') === 'true' })

  if (!r.ok) return r
  return { ok: true }
}

export async function reportReview(form: FormData): Promise<ActionResult> {
  const r = await act(form, 'report', 'POST', { reason: String(form.get('reason')), note: String(form.get('note') || '') || null })

  if (!r.ok) return r
  return { ok: true }
}
